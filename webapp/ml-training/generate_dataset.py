"""Bootstrap training-dataset generator for the reliability classifier (Initiative B).

Emits ONE CSV row per detection box produced by running the REAL pipeline
(registration.align_to_reference -> diff_detect.compute_diff_mask) over many synthetic
(reference, defective) pairs with varied defect combinations and capture misalignment.

Contracts followed EXACTLY (webapp/ML-ARCHITECTURE.md):
  - §5 feature vector: features are produced ONLY by the shared reliability.extract_features
    (imported here via the sys.path bridge) so training/inference order can never drift.
  - §4 handoff format: CSV header + dataset_manifest.json exactly as specified.

Labeling (see LABEL DECISION below).
"""

import csv
import copy
import datetime
import json
import os
import random
import sys

import numpy as np
import cv2

# --- sys.path bridges -------------------------------------------------------
# 1) the frozen feature contract lives in the runtime backend's reliability.py
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
# 2) the prototype pipeline (registration/diff_detect) + synthetic generator
_TASK1_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "docs", "dev", "task1-print-plate")
)
if _TASK1_DIR not in sys.path:
    sys.path.insert(0, _TASK1_DIR)

from reliability import FEATURE_NAMES, FEATURE_SCHEMA_VERSION, extract_features  # noqa: E402
import registration  # noqa: E402
import diff_detect  # noqa: E402
import generate_labels as gl  # noqa: E402
from run_demo import _overlap_fraction  # noqa: E402
import ocr_diff  # noqa: E402  detect_text_diffs, merge_with_source (EasyOCR-backed)


DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CSV_PATH = os.path.join(DATA_DIR, "reliability_dataset.csv")
MANIFEST_PATH = os.path.join(DATA_DIR, "dataset_manifest.json")

CSV_HEADER = [
    "schema_version", "run_id", "box_index", "source",
    *FEATURE_NAMES,               # area_ratio .. diff_threshold_used  (§4: exactly FEATURE_NAMES)
    "gt_overlap_fraction", "label",
]

# ---------------------------------------------------------------------------
# LABEL DECISION (deviation from §4 literal wording, made to satisfy §4's OWN
# stated intent + the task's verification gate — documented in the manifest):
#
# §4 literally says label=1 iff _overlap_fraction(gt, box) > 0.05. That metric is
# inter/gt_area (recall-side): it answers "is a real defect under this box?". But a
# giant registration-residual box (QA 발견1) covers the whole label, so it ALSO covers
# any GT region -> literal rule would label it 1 (reliable), which is exactly the
# false positive the classifier must flag.
#
# Resolution: label=1 iff the box (a) covers a real defect (gt_overlap_fraction >
# GT_OVERLAP_MIN, the §4 recall metric, recorded verbatim) AND (b) is NOT oversized
# (area_ratio <= OVERSIZE_GUARD). This is EXACTLY run_demo.evaluate_recall's
# `reliable_detected` definition (hit AND not oversized), so the classifier is trained
# to predict the pipeline's own notion of a trustworthy localization. A 발견1 giant box
# fails (b) -> label 0. A signal-bearing but line-wide OCR box (e.g. the enlarged-period
# 점누락 catch, which spans the usage line) passes both -> label 1, and max_diff_intensity
# then separates it from a same-size clean-line OCR misread (which fails (a): no GT).
#
# (Earlier this used a precision-side box_defect_coverage>=0.15 gate; that wrongly
# downgraded diluted-but-real line-wide OCR catches to 0. The oversize guardrail is the
# pipeline's actual reliability boundary and does not have that failure mode.)
GT_OVERLAP_MIN = 0.05          # §4 recall-side threshold (== evaluate_recall's)
OVERSIZE_GUARD = 0.20          # area_ratio guardrail (== diff_detect oversize_area_ratio)

# robust_threshold k sweep. The prototype default is k=6.0 (well-localized boxes).
# LOWER k reproduces the OLD Otsu-like instability from QA 발견1 — the SAME real
# pipeline function, driven into its degenerate regime — surfacing large/giant
# registration-residual false positives so the classifier learns to flag them.
K_VALUES = [6.0, 4.0, 3.0, 2.0]

# k at which we run the FULL production pipeline (pixel diff + OCR diff + merge_with_source).
# Lower-k runs stay pixel-only: they exist only to harvest giant-residual negatives, and
# re-running the (slow, k-independent) OCR merge there would just duplicate OCR rows.
PRODUCTION_K = 6.0

# The 5 injectable defects (problem.md / spec.md). Each maps to a text edit or a
# local image op, plus the substring used to measure its per-defect GT bbox.
DEFECT_KEYS = ["typo", "missing_char", "ingredient_error", "dot", "bleed"]
_DEFECT_TYPE = {
    "typo": "오탈자",
    "missing_char": "문자누락",
    "ingredient_error": "성분표시오류",
    "dot": "점누락",
    "bleed": "번짐",
}
_INGREDIENT_SUBSTR = {
    "typo": "토너",
    "missing_char": "나이아신아마이드",
    "ingredient_error": ", 향료.",
}


def _pil_to_bgr(img):
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def build_pair(defect_set, misalign):
    """Build (reference_bgr, defective_bgr, gt) injecting ONLY the defects in defect_set.

    gt = {"injected_defects": [{type, tag, bbox:[x0,y0,x1,y1]}...],
          "image_size": [W,H]}. Reuses generate_labels' primitives so geometry/GT
    measurement is byte-identical to the prototype's established convention.
    """
    ref_lines = gl.build_lines()
    ref_img, _ref_boxes = gl.draw_label(ref_lines)

    lines = copy.deepcopy(ref_lines)
    ingredient_line = next(l for l in lines if l["tag"] == "ingredient")
    ingredient_char_boxes = gl._measure_substring_bboxes(
        margin=60,
        y=ingredient_line["y"],
        size=ingredient_line["size"],
        bold=ingredient_line.get("bold", False),
        text=ingredient_line["text"],
        substrings=_INGREDIENT_SUBSTR,
    )

    defects = []

    if "typo" in defect_set:
        for line in lines:
            if line["tag"] == "ingredient" and "토너" in line["text"]:
                line["text"] = line["text"].replace("토너", "토노")
        defects.append(dict(type=_DEFECT_TYPE["typo"], tag="ingredient",
                            bbox=ingredient_char_boxes.get("typo")))
    if "missing_char" in defect_set:
        for line in lines:
            if line["tag"] == "ingredient" and "나이아신아마이드" in line["text"]:
                line["text"] = line["text"].replace("나이아신아마이드", "나이신아마이드")
        defects.append(dict(type=_DEFECT_TYPE["missing_char"], tag="ingredient",
                            bbox=ingredient_char_boxes.get("missing_char")))
    if "ingredient_error" in defect_set:
        for line in lines:
            if line["tag"] == "ingredient" and "향료." in line["text"]:
                line["text"] = line["text"].replace(", 향료.", ".")
        defects.append(dict(type=_DEFECT_TYPE["ingredient_error"], tag="ingredient",
                            bbox=ingredient_char_boxes.get("ingredient_error")))
    if "dot" in defect_set:
        for line in lines:
            if line["tag"] == "usage" and line["text"].endswith("."):
                line["text"] = line["text"][:-1]
        # defect-unit GT = the enlarged-period region (now carries a real diff/OCR signal)
        defects.append(dict(type=_DEFECT_TYPE["dot"], tag="usage",
                            bbox=gl.usage_period_bbox(ref_lines)))

    defective_img, boxes = gl.draw_label(lines)

    # fill line-level GT for defects whose substring measurement was unavailable / None
    for d in defects:
        if d.get("bbox") is None and d["tag"] in boxes:
            d["bbox"] = list(boxes[d["tag"]])

    if "bleed" in defect_set:
        caution_box = boxes["caution"]
        defects.append(dict(type=_DEFECT_TYPE["bleed"], tag="caution",
                            bbox=list(caution_box)))
        defective_img = gl.apply_local_bleed(defective_img, caution_box, pad=10)

    # capture misalignment (varied per call; within spec ±1~2도, no flip)
    defective_img = gl.apply_capture_misalignment(
        defective_img,
        angle_deg=misalign["angle_deg"],
        tx=misalign["tx"],
        ty=misalign["ty"],
        scale=misalign["scale"],
    )

    gt = dict(
        injected_defects=defects,
        image_size=[gl.WIDTH, gl.HEIGHT],
    )
    return _pil_to_bgr(ref_img), _pil_to_bgr(defective_img), gt


def _gt_overlap(box, gt):
    """Max over injected defects of _overlap_fraction (inter/gt_area) — §4's recall metric."""
    x, y, w, h = int(box[0]), int(box[1]), int(box[2]), int(box[3])
    det = (x, y, w, h)
    best = 0.0
    for d in gt["injected_defects"]:
        bb = d.get("bbox")
        if not bb:
            continue
        gx0, gy0, gx1, gy1 = bb
        gt_box = (gx0, gy0, gx1 - gx0, gy1 - gy0)
        best = max(best, _overlap_fraction(gt_box, det))
    return best


def _label(gt_overlap, area_ratio):
    """== run_demo reliable_detected: overlaps a real defect AND not oversized."""
    return 1 if (gt_overlap > GT_OVERLAP_MIN and area_ratio <= OVERSIZE_GUARD) else 0


def _iter_defect_sets():
    """Yield (name, defect_set) combinations to cover the threshold regimes the
    classifier must generalize over."""
    # no defect at all (registration-residual only -> the pure false-positive regime)
    yield ("none", set())
    # every single defect alone — the QA 발견1 regime (esp. ingredient_error alone)
    for k in DEFECT_KEYS:
        yield (f"single_{k}", {k})
    # selected pairs (mix ingredient-line and cross-line)
    pairs = [
        ("typo", "missing_char"),
        ("typo", "ingredient_error"),
        ("missing_char", "ingredient_error"),
        ("ingredient_error", "dot"),
        ("ingredient_error", "bleed"),
        ("dot", "bleed"),
        ("typo", "bleed"),
    ]
    for a, b in pairs:
        yield (f"pair_{a}_{b}", {a, b})
    # three ingredient-line defects together (README demo regime -> high threshold)
    yield ("triple_ingredient", {"typo", "missing_char", "ingredient_error"})
    # all five
    yield ("all", set(DEFECT_KEYS))


def _iter_misalignments(rng, n_per_combo):
    """Yield n_per_combo varied capture misalignments (within spec ±1~2도, no flip)."""
    # always include the prototype's fixed demo value first for continuity
    yield dict(angle_deg=1.5, tx=6, ty=-4, scale=0.995)
    for _ in range(n_per_combo - 1):
        yield dict(
            angle_deg=round(rng.uniform(-1.8, 1.8), 3),
            tx=rng.randint(-9, 9),
            ty=rng.randint(-9, 9),
            scale=round(rng.uniform(0.99, 1.01), 4),
        )


def generate(n_misalign_per_combo=6, seed=20260710, min_area=40):
    rng = random.Random(seed)
    os.makedirs(DATA_DIR, exist_ok=True)

    rows = []
    n_pairs = 0
    n_runs = 0
    for combo_name, defect_set in _iter_defect_sets():
        for misalign in _iter_misalignments(rng, n_misalign_per_combo):
            ref_bgr, def_bgr, gt = build_pair(defect_set, misalign)
            n_pairs += 1
            # registration + OCR are both k-independent, so run each once per pair.
            aligned, method, info = registration.align_to_reference(ref_bgr, def_bgr)
            n_inliers = int(info.get("n_inliers", 0))
            ocr_boxes, _ocr_lines = ocr_diff.detect_text_diffs(ref_bgr, aligned)

            for k in K_VALUES:
                run_id = (f"{combo_name}__a{misalign['angle_deg']}_t{misalign['tx']},"
                          f"{misalign['ty']}_s{misalign['scale']}_k{k}")
                mask, pixel_boxes, diff, diff_info = diff_detect.compute_diff_mask(
                    ref_bgr, aligned, min_area=min_area, k=k
                )
                n_runs += 1
                threshold = float(diff_info["threshold"])
                image_area = int(diff_info["image_area"])

                # Full production pipeline (pixel + OCR + merge) only at PRODUCTION_K;
                # lower-k runs are pixel-only (giant-residual negative harvesting).
                if k == PRODUCTION_K:
                    boxes = ocr_diff.merge_with_source(pixel_boxes, ocr_boxes)
                else:
                    boxes = [(x, y, w, h, area, "pixel_diff")
                             for (x, y, w, h, area) in pixel_boxes]

                for bi, box in enumerate(boxes):
                    feats = extract_features(
                        box, diff, boxes, image_area, n_inliers, threshold
                    )
                    gt_overlap = _gt_overlap(box, gt)
                    label = _label(gt_overlap, feats[0])  # feats[0] == area_ratio
                    box_source = box[5] if len(box) > 5 else "pixel_diff"
                    rows.append(dict(
                        schema_version=FEATURE_SCHEMA_VERSION,
                        run_id=run_id,
                        box_index=bi,
                        source=box_source,
                        **{name: feats[j] for j, name in enumerate(FEATURE_NAMES)},
                        gt_overlap_fraction=round(gt_overlap, 4),
                        label=label,
                    ))

    _write_csv(rows)
    _write_manifest(rows, n_pairs, n_runs)
    return rows, n_pairs, n_runs


def _write_csv(rows):
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def _write_manifest(rows, n_pairs, n_runs):
    n_pos = sum(1 for r in rows if r["label"] == 1)
    n_neg = len(rows) - n_pos

    def _src_counts(src):
        sub = [r for r in rows if r["source"] == src]
        return dict(rows=len(sub),
                    positive=sum(1 for r in sub if r["label"] == 1),
                    negative=sum(1 for r in sub if r["label"] == 0))

    manifest = dict(
        schema_version=FEATURE_SCHEMA_VERSION,
        feature_names=list(FEATURE_NAMES),
        n_rows=len(rows),
        n_images=n_pairs,
        n_pipeline_runs=n_runs,
        k_values=K_VALUES,
        production_k=PRODUCTION_K,
        n_positive=n_pos,
        n_negative=n_neg,
        by_source=dict(
            pixel_diff=_src_counts("pixel_diff"),
            ocr_diff=_src_counts("ocr_diff"),
            both=_src_counts("both"),
        ),
        generated_at=datetime.datetime.now().astimezone().isoformat(),
        generator="generate_dataset.py",
        notes=(
            "schema v2 (10 features incl. max_diff_intensity, diff_pixel_fraction). "
            "Boxes come from the FULL merged pipeline: pixel_diff + ocr_diff (EasyOCR) "
            "merged via ocr_diff.merge_with_source at production_k; lower-k runs are "
            "pixel-only to harvest QA 발견1 giant-residual negatives. "
            "auto-labeled == run_demo reliable_detected: label=1 iff gt_overlap_fraction>%.2f "
            "(recall, §4) AND area_ratio<=%.2f (not oversized). gt_overlap_fraction column is "
            "the §4 inter/gt_area metric, recorded verbatim. usage-line period is rendered "
            "enlarged/bold so 점누락 carries a real diff/OCR signal (BIG_PERIOD_SCALE in "
            "generate_labels)." % (GT_OVERLAP_MIN, OVERSIZE_GUARD)
        ),
    )
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    rows, n_pairs, n_runs = generate()
    n_pos = sum(1 for r in rows if r["label"] == 1)
    print(f"pairs={n_pairs} runs={n_runs} rows={len(rows)} pos={n_pos} neg={len(rows) - n_pos}")
    print(f"CSV: {CSV_PATH}")
    print(f"manifest: {MANIFEST_PATH}")
