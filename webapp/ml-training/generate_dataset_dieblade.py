"""Bootstrap training-dataset generator for the die-blade reliability classifier.

Mirrors generate_dataset.py (task1) in spirit: run the REAL pipeline
(pipeline_bridge_dieblade.analyze, run_dir=None so no PNGs are written) over many
synthetic (reference, actual) pairs with varied defect combinations + capture
misalignment, and emit one CSV row per detected box.

Contract: features come ONLY from reliability_dieblade.extract_features (imported
via the sys.path bridge below), so training/inference feature order can never drift.

Labeling (see LABEL DECISION below) mirrors task1's resolution of the same tension:
a registration artifact can look locally like it "covers" a GT region only when
the GT itself is huge (rare here) — but a large registration-residual false
positive covers a LARGE area with no real defect underneath, so an oversize
guard (on top of GT-overlap) keeps that regime correctly labeled 0.
"""

import csv
import datetime
import json
import math
import os
import sys

import numpy as np

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
_TASK2_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "docs", "dev", "task2-die-blade")
)
if _TASK2_DIR not in sys.path:
    sys.path.insert(0, _TASK2_DIR)

from reliability_dieblade import FEATURE_NAMES, FEATURE_SCHEMA_VERSION  # noqa: E402
import pipeline_bridge_dieblade as bridge  # noqa: E402
import die_blade_qc_demo as dbm  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CSV_PATH = os.path.join(DATA_DIR, "reliability_dieblade_dataset.csv")
MANIFEST_PATH = os.path.join(DATA_DIR, "dieblade_dataset_manifest.json")

CSV_HEADER = ["schema_version", "run_id", "box_index", "kind", *FEATURE_NAMES, "gt_overlap_fraction", "label"]

GT_OVERLAP_MIN = 0.05    # same threshold task1 uses (evaluate_recall / _overlap_fraction)
OVERSIZE_GUARD = 0.15    # area_ratio guard: a real single defect here never covers this much


def _overlap_fraction(gt_box, det_box) -> float:
    """intersection / gt_area (same semantic as task1's run_demo._overlap_fraction)."""
    gx, gy, gw, gh = gt_box
    dx, dy, dw, dh = det_box
    ix0, iy0 = max(gx, dx), max(gy, dy)
    ix1, iy1 = min(gx + gw, dx + dw), min(gy + gh, dy + dh)
    iw, ih = max(0, ix1 - ix0), max(0, iy1 - iy0)
    inter = iw * ih
    gt_area = gw * gh
    return (inter / gt_area) if gt_area else 0.0


def _gt_bbox_from_idx_range(points: np.ndarray, start_idx: int, end_idx: int, n_total: int):
    if start_idx <= end_idx:
        idx = np.arange(start_idx, end_idx + 1)
    else:
        idx = np.concatenate([np.arange(start_idx, n_total), np.arange(0, end_idx + 1)])
    pts = points[idx % n_total]
    x0, y0 = pts.min(axis=0)
    x1, y1 = pts.max(axis=0)
    pad = 10  # injected points define a centerline; pad to approximate the detected bbox
    return (float(x0 - pad), float(y0 - pad), float(x1 - x0 + 2 * pad), float(y1 - y0 + 2 * pad))


def build_pair(reference_points, defect_set, params, misalign, rng):
    """Build (reference_mask, actual_captured_mask, gt_records) for one combo.

    gt_records: list of {"kind", "bbox"(x,y,w,h) or None for 위치오차}.
    """
    n_total = len(reference_points)
    working_points = reference_points.copy()
    gt_records = []

    if "bend" in defect_set:
        p = params["bend"]
        working_points, gt = dbm.inject_bend(working_points, rng=rng, **p)
        bbox = _gt_bbox_from_idx_range(reference_points, gt.start_idx, gt.end_idx, n_total)
        gt_records.append({"kind": "휨", "bbox": bbox})

    if "wear" in defect_set:
        p = params["wear"]
        working_points, gt = dbm.inject_wear(working_points, rng=rng, **p)
        bbox = _gt_bbox_from_idx_range(reference_points, gt.start_idx, gt.end_idx, n_total)
        gt_records.append({"kind": "마모", "bbox": bbox})

    polylines = [dbm.Arc(points=working_points, orig_idx=np.arange(n_total), is_closed=True)]
    if "break" in defect_set:
        p = params["break"]
        target_idx = int(np.argmax([len(a.points) for a in polylines]))
        target = polylines.pop(target_idx)
        new_arcs, gt = dbm.inject_break(target, n_total=n_total, **p)
        polylines.extend(new_arcs)
        bbox = _gt_bbox_from_idx_range(reference_points, gt.start_idx, gt.end_idx, n_total)
        gt_records.append({"kind": "끊김", "bbox": bbox})

    if not ("break" in defect_set):
        actual_source = dbm.render_closed(working_points)
    else:
        actual_source = dbm.render_polylines([a.points for a in polylines])

    actual_captured = dbm.apply_camera_misalignment(actual_source, **misalign)

    injected_shift_mm = math.hypot(misalign.get("tx", 0.0), misalign.get("ty", 0.0)) * dbm.MM_PER_PX
    if "position" in defect_set and injected_shift_mm > dbm.POSITION_ERROR_TOL_MM:
        gt_records.append({"kind": "위치오차", "bbox": None})

    reference_mask = dbm.render_closed(reference_points)
    return reference_mask, actual_captured, gt_records


def _iter_combos():
    kinds = ["bend", "break", "wear", "position"]
    yield "none", set()
    for k in kinds:
        yield f"single_{k}", {k}
    pairs = [("bend", "break"), ("break", "wear"), ("bend", "wear"),
             ("break", "position"), ("bend", "position"), ("wear", "position")]
    for a, b in pairs:
        yield f"pair_{a}_{b}", {a, b}
    yield "triple_bbw", {"bend", "break", "wear"}
    yield "all", set(kinds)


def _random_params(defect_set, rng):
    params = {}
    if "bend" in defect_set:
        params["bend"] = dict(
            start_frac=round(rng.uniform(0.0, 0.95), 3), span_frac=round(rng.uniform(0.06, 0.14), 3),
            magnitude_px=round(rng.uniform(18, 36), 1),
        )
    if "break" in defect_set:
        params["break"] = dict(
            start_frac=round(rng.uniform(0.0, 0.95), 3), span_frac=round(rng.uniform(0.02, 0.05), 3),
        )
    if "wear" in defect_set:
        params["wear"] = dict(
            start_frac=round(rng.uniform(0.0, 0.95), 3), span_frac=round(rng.uniform(0.08, 0.16), 3),
            depth_px=round(rng.uniform(2.0, 4.0), 1),
        )
    return params


def _iter_misalignments(defect_set, rng, n_per_combo):
    """Normal small-angle capture misalignment for most combos.

    "position" combos need a LARGE tx/ty (still small rotation) to exceed
    POSITION_ERROR_TOL_MM — that's a real signal, not a registration artifact.
    """
    if "position" in defect_set:
        for _ in range(n_per_combo):
            yield dict(angle_deg=round(rng.uniform(-1.8, 1.8), 3),
                       tx=rng.choice([1, -1]) * rng.integers(30, 55),
                       ty=rng.choice([1, -1]) * rng.integers(15, 35))
    else:
        for _ in range(n_per_combo):
            yield dict(angle_deg=round(rng.uniform(-1.8, 1.8), 3),
                       tx=rng.integers(-9, 9), ty=rng.integers(-9, 9))


def _iter_large_angle_misalignments(rng, n):
    """QA §2-B regime: large rotation -> ECC symmetric misconvergence -> false positives."""
    for _ in range(n):
        angle = rng.choice([30, 35, 40, 45, 60, 75, 90])
        yield dict(angle_deg=float(angle), tx=rng.integers(-5, 5), ty=rng.integers(-5, 5))


def _label_detection(det, gt_records, image_area) -> float:
    kind = det["kind"]

    # 위치오차's bbox is ALWAYS the whole reference shape's bounding box by design
    # (dbm.analyze() sets it to cv2.boundingRect of the full mask — it's a global
    # judgment, not a localized region), so the oversize-area guard (meant to catch
    # local-defect detections that spuriously ballooned) does not apply to it.
    if kind == "위치오차":
        matched = any(g["kind"] == "위치오차" for g in gt_records)
        return (1.0 if matched else 0.0), (1.0 if matched else 0.0)

    area_ratio = (det["bbox"]["w"] * det["bbox"]["h"]) / image_area if image_area else 0.0
    if area_ratio > OVERSIZE_GUARD:
        return 0.0, 0.0

    match_kinds = ("휨", "끊김") if kind.startswith("복합") else (kind,)
    det_box = (det["bbox"]["x"], det["bbox"]["y"], det["bbox"]["w"], det["bbox"]["h"])
    best = 0.0
    for g in gt_records:
        if g["kind"] not in match_kinds or g["bbox"] is None:
            continue
        best = max(best, _overlap_fraction(g["bbox"], det_box))
    label = 1.0 if best > GT_OVERLAP_MIN else 0.0
    return label, best


def generate(n_misalign_per_combo=6, n_large_angle=10, seed=20260711, out_csv=CSV_PATH):
    rng = np.random.default_rng(seed)
    os.makedirs(DATA_DIR, exist_ok=True)

    reference_points = dbm.generate_reference_contour()
    image_area = float(dbm.CANVAS_SIZE * dbm.CANVAS_SIZE)

    rows = []
    n_pairs = 0

    for combo_name, defect_set in _iter_combos():
        for misalign in _iter_misalignments(defect_set, rng, n_misalign_per_combo):
            params = _random_params(defect_set, rng)
            reference_mask, actual_mask, gt_records = build_pair(
                reference_points, defect_set, params, misalign, rng
            )
            n_pairs += 1
            result = bridge.analyze(reference_mask, actual_mask, run_dir=None)
            residual_mm = result["metrics"]["registration_residual_mm"]
            position_shift_mm = result["metrics"]["position_error"]["estimated_shift_mm"]
            run_id = f"{combo_name}__a{misalign['angle_deg']}_t{misalign['tx']},{misalign['ty']}"
            for bi, det in enumerate(result["detections"]):
                label, overlap = _label_detection(det, gt_records, image_area)
                feats = _extract(det, result["detections"], image_area, residual_mm, position_shift_mm)
                rows.append(dict(
                    schema_version=FEATURE_SCHEMA_VERSION, run_id=run_id, box_index=bi, kind=det["kind"],
                    **{name: feats[j] for j, name in enumerate(FEATURE_NAMES)},
                    gt_overlap_fraction=round(overlap, 4), label=label,
                ))

    # Negative harvesting: large-angle registration-residual regime (QA §2-B), no defects injected.
    for misalign in _iter_large_angle_misalignments(rng, n_large_angle):
        reference_mask, actual_mask, gt_records = build_pair(
            reference_points, set(), {}, misalign, rng
        )
        n_pairs += 1
        result = bridge.analyze(reference_mask, actual_mask, run_dir=None)
        residual_mm = result["metrics"]["registration_residual_mm"]
        position_shift_mm = result["metrics"]["position_error"]["estimated_shift_mm"]
        run_id = f"large_angle_none__a{misalign['angle_deg']}"
        for bi, det in enumerate(result["detections"]):
            label, overlap = _label_detection(det, gt_records, image_area)
            feats = _extract(det, result["detections"], image_area, residual_mm, position_shift_mm)
            rows.append(dict(
                schema_version=FEATURE_SCHEMA_VERSION, run_id=run_id, box_index=bi, kind=det["kind"],
                **{name: feats[j] for j, name in enumerate(FEATURE_NAMES)},
                gt_overlap_fraction=round(overlap, 4), label=label,
            ))

    _write_csv(rows, out_csv)
    _write_manifest(rows, n_pairs, out_csv)
    return rows, n_pairs


def _extract(det, all_dets, image_area, residual_mm, position_shift_mm):
    import reliability_dieblade as rd
    return rd.extract_features(det, all_dets, image_area, residual_mm, position_shift_mm)


def _write_csv(rows, out_csv):
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def _write_manifest(rows, n_pairs, out_csv):
    n_pos = sum(1 for r in rows if r["label"] == 1.0)
    n_neg = len(rows) - n_pos

    def _kind_counts(kind_pred):
        sub = [r for r in rows if kind_pred(r["kind"])]
        return dict(rows=len(sub), positive=sum(1 for r in sub if r["label"] == 1.0),
                    negative=sum(1 for r in sub if r["label"] == 0.0))

    manifest = dict(
        schema_version=FEATURE_SCHEMA_VERSION,
        feature_names=list(FEATURE_NAMES),
        n_rows=len(rows), n_pairs=n_pairs,
        n_positive=n_pos, n_negative=n_neg,
        by_kind=dict(
            bend=_kind_counts(lambda k: k == "휨"),
            break_=_kind_counts(lambda k: k == "끊김"),
            composite=_kind_counts(lambda k: k.startswith("복합")),
            wear=_kind_counts(lambda k: k == "마모"),
            position=_kind_counts(lambda k: k == "위치오차"),
        ),
        generated_at=datetime.datetime.now().astimezone().isoformat(),
        generator="generate_dataset_dieblade.py",
        notes=(
            "auto-labeled: label=1 iff gt_overlap_fraction>%.2f (bend/break/wear, matched by kind; "
            "복합 matches either 휨 or 끊김 GT) AND area_ratio<=%.2f (not oversize); 위치오차 label=1 "
            "iff GT actually injected a 위치오차 (shift beyond POSITION_ERROR_TOL_MM). Negatives include "
            "a dedicated large-rotation-angle sweep (30-90deg, no injected defects) harvesting QA §2-B "
            "ECC symmetric-misconvergence false positives." % (GT_OVERLAP_MIN, OVERSIZE_GUARD)
        ),
    )
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    rows, n_pairs = generate()
    n_pos = sum(1 for r in rows if r["label"] == 1.0)
    print(f"pairs={n_pairs} rows={len(rows)} pos={n_pos} neg={len(rows) - n_pos}")
    print(f"CSV: {CSV_PATH}")
    print(f"manifest: {MANIFEST_PATH}")
