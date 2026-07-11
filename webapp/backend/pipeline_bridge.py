"""Bridge to the existing task1-print-plate pipeline.

Strategy per ARCHITECTURE.md §2: prepend the absolute task1 dir to sys.path and
import the prototype modules directly. The prototype stays the single source of
truth (no copying, no subprocessing run_demo.py).
"""

import os
import sys

TASK1_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "docs", "dev", "task1-print-plate")
)
if TASK1_DIR not in sys.path:
    sys.path.insert(0, TASK1_DIR)

import registration  # noqa: E402  align_to_reference(reference, moving, min_matches=15)
import diff_detect  # noqa: E402  compute_diff_mask(...), draw_boxes(img, boxes)
import run_demo  # noqa: E402  evaluate_recall(...), compute_precision_proxy(...)
from imgio import imread_unicode, imwrite_unicode  # noqa: E402

import ocr_diff  # noqa: E402  detect_text_diffs(...), merge_with_source(...)
import reliability  # noqa: E402  score_boxes(...)

DEFAULT_REFERENCE_PATH = os.path.join(TASK1_DIR, "output", "01_reference.png")
DEFAULT_GT_PATH = os.path.join(TASK1_DIR, "output", "00_ground_truth.json")

CRITICAL_TYPE = "성분표시오류"


def default_reference_available() -> bool:
    return os.path.isfile(DEFAULT_REFERENCE_PATH)


def default_gt_available() -> bool:
    return os.path.isfile(DEFAULT_GT_PATH)


def _match_ocr_texts(eval_results, ground_truth, ocr_lines):
    """For each per_defect entry, find the OCR line whose bbox overlaps the defect GT most.

    Returns list of (text_before, text_after) tuples aligned to eval_results; (None, None)
    when there are no OCR lines or the best overlap is 0. eval_results are 1:1 with
    ground_truth["injected_defects"] (evaluate_recall iterates defects in order).
    """
    defects = ground_truth["injected_defects"]
    line_boxes = ground_truth["defect_line_boxes"]
    out = []
    for idx in range(len(eval_results)):
        before = after = None
        if ocr_lines and idx < len(defects):
            d = defects[idx]
            gt_xyxy = d.get("bbox") or line_boxes.get(d["tag"])
            if gt_xyxy is not None:
                gx0, gy0, gx1, gy1 = gt_xyxy
                gt_xywh = (gx0, gy0, gx1 - gx0, gy1 - gy0)
                best = 0.0
                best_line = None
                for ln in ocr_lines:
                    lx0, ly0, lx1, ly1 = ln["bbox_xyxy"]
                    frac = run_demo._overlap_fraction(gt_xywh, (lx0, ly0, lx1 - lx0, ly1 - ly0))
                    if frac > best:
                        best = frac
                        best_line = ln
                if best_line is not None and best > 0:
                    before = best_line["text_before"]
                    after = best_line["text_after"]
        out.append((before, after))
    return out


def analyze(reference_bgr, defective_bgr, run_dir, ground_truth=None, min_area=40) -> dict:
    """Run registration + diff detection, persist images, and build the AnalyzeResponse dict.

    recall/precision metrics are computed only when ``ground_truth`` is provided;
    otherwise those fields are null / empty, while diff-based metrics are always present.
    """
    aligned, method, info = registration.align_to_reference(reference_bgr, defective_bgr)
    mask, pixel_boxes, diff, diff_info = diff_detect.compute_diff_mask(
        reference_bgr, aligned, min_area=min_area
    )

    # ★ OCR branch (parallel data source). Returns ([], []) if OCR unavailable/disabled.
    ocr_boxes, ocr_lines = ocr_diff.detect_text_diffs(reference_bgr, aligned)

    # ★ Merge pixel-diff + ocr-diff boxes with provenance -> (x,y,w,h,area,source).
    merged = ocr_diff.merge_with_source(pixel_boxes, ocr_boxes, max_gap=25)

    # ★ Recompute area ratios + oversized flags on the MERGED set (box set changed).
    image_area = diff_info["image_area"]
    guard = diff_info["oversize_area_ratio"]
    box_area_ratios = [
        (w * h) / image_area if image_area else 0.0 for (_, _, w, h, _, _) in merged
    ]
    oversized_flags = [r > guard for r in box_area_ratios]

    # merged boxes stripped back to (x,y,w,h,area) for the geometry-only consumers.
    merged_xywha = [(x, y, w, h, area) for (x, y, w, h, area, _src) in merged]

    # ★ Reliability scoring (None whole-list if model artifact absent).
    n_inliers = int(info["n_inliers"]) if "n_inliers" in info else 0
    scores = reliability.score_boxes(
        merged, diff, image_area, n_inliers, float(diff_info["threshold"])
    )

    vis = diff_detect.draw_boxes(aligned.copy(), merged_xywha)

    imwrite_unicode(os.path.join(run_dir, "reference.png"), reference_bgr)
    imwrite_unicode(os.path.join(run_dir, "aligned.png"), aligned)
    imwrite_unicode(os.path.join(run_dir, "diff_mask.png"), mask)
    imwrite_unicode(os.path.join(run_dir, "detections.png"), vis)

    detections = []
    for i, (x, y, w, h, area, source) in enumerate(merged):
        score = None
        if scores is not None and i < len(scores):
            score = None if scores[i] is None else float(scores[i])
        detections.append(
            {
                "index": i,
                "bbox": {"x": int(x), "y": int(y), "w": int(w), "h": int(h)},
                "area": int(area),
                "area_ratio": float(box_area_ratios[i]),
                "oversized": bool(oversized_flags[i]),
                "source": source,
                "reliability_score": score,
            }
        )

    metrics = {
        "n_detections": len(merged),
        "diff_threshold": float(diff_info["threshold"]),
        "any_oversized": bool(any(oversized_flags)),
        "oversize_area_ratio_guard": float(diff_info["oversize_area_ratio"]),
        "recall": None,
        "reliable_recall": None,
        "precision_proxy": None,
        "n_defects_total": None,
        "n_defects_detected": None,
        "n_defects_reliably_detected": None,
        "critical_missed": None,
        "per_defect": [],
    }

    if ground_truth is not None:
        eval_results = run_demo.evaluate_recall(
            merged_xywha, ground_truth, oversized_flags=oversized_flags
        )
        n_total = len(eval_results)
        n_hit = sum(1 for r in eval_results if r["detected"])
        n_hit_reliable = sum(1 for r in eval_results if r["reliable_detected"])
        precision_info = run_demo.compute_precision_proxy(merged_xywha, ground_truth)
        critical_missed = any(
            r["type"] == CRITICAL_TYPE and not r["reliable_detected"] for r in eval_results
        )

        ocr_texts = _match_ocr_texts(eval_results, ground_truth, ocr_lines)

        metrics.update(
            {
                "recall": (n_hit / n_total) if n_total else 0.0,
                "reliable_recall": (n_hit_reliable / n_total) if n_total else 0.0,
                "precision_proxy": float(precision_info["precision_proxy"]),
                "n_defects_total": n_total,
                "n_defects_detected": n_hit,
                "n_defects_reliably_detected": n_hit_reliable,
                "critical_missed": critical_missed,
                "per_defect": [
                    {
                        "type": r["type"],
                        "note": r["note"],
                        "detected": bool(r["detected"]),
                        "reliable_detected": bool(r["reliable_detected"]),
                        "overlap_score": float(r["overlap_score"]),
                        "used_line_level_gt": bool(r["used_line_level_gt"]),
                        "ocr_text_before": ocr_texts[i][0],
                        "ocr_text_after": ocr_texts[i][1],
                    }
                    for i, r in enumerate(eval_results)
                ],
            }
        )

    registration_out = {"method": method, "n_inliers": None}
    if "n_inliers" in info:
        registration_out["n_inliers"] = int(info["n_inliers"])

    return {
        "registration": registration_out,
        "detections": detections,
        "metrics": metrics,
    }
