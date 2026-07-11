"""Bridge to the existing task2-die-blade pipeline.

Same strategy as pipeline_bridge.py (task1): prepend the absolute task2 dir to
sys.path and import the prototype module directly (no copying, no subprocessing).
"""

import os
import sys

TASK1_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "docs", "dev", "task1-print-plate")
)
if TASK1_DIR not in sys.path:
    sys.path.insert(0, TASK1_DIR)  # for imgio.imread_unicode / imwrite_unicode (generic util)

TASK2_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "docs", "dev", "task2-die-blade")
)
if TASK2_DIR not in sys.path:
    sys.path.insert(0, TASK2_DIR)

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import die_blade_qc_demo as dbm  # noqa: E402
from imgio import imread_unicode, imwrite_unicode  # noqa: E402

import reliability_dieblade  # noqa: E402  score_boxes(...)

DEMO_DIR = os.path.join(TASK2_DIR, "output", "webapp_demo")
DEFAULT_REFERENCE_PATH = os.path.join(DEMO_DIR, "reference.png")
DEFAULT_ACTUAL_PATH = os.path.join(DEMO_DIR, "actual_captured.png")
DEFAULT_GT_PATH = os.path.join(DEMO_DIR, "ground_truth.json")

# 치명 클래스 (spec.md §6 "미검출 0" 최우선 대상): 휨·끊김. 마모/위치오차는 등급/사후판정 성격이라 제외.
CRITICAL_KINDS = ("휨", "끊김")


def default_reference_available() -> bool:
    return os.path.isfile(DEFAULT_REFERENCE_PATH)


def default_actual_available() -> bool:
    return os.path.isfile(DEFAULT_ACTUAL_PATH)


def default_gt_available() -> bool:
    return os.path.isfile(DEFAULT_GT_PATH)


def _binarize(gray: np.ndarray) -> np.ndarray:
    """Threshold an arbitrary grayscale upload to a 0/255 line mask.

    die_blade_qc_demo assumes backlight-silhouette capture (already binary). For
    uploads that aren't already clean binary, Otsu-threshold and pick the minority
    class as foreground (a thin die-line silhouette covers a small fraction of the
    canvas, unlike a filled shape).
    """
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if (mask > 0).mean() > 0.5:
        mask = 255 - mask
    return mask


def _to_mask(bgr_or_gray: np.ndarray) -> np.ndarray:
    if bgr_or_gray.ndim == 3:
        gray = cv2.cvtColor(bgr_or_gray, cv2.COLOR_BGR2GRAY)
    else:
        gray = bgr_or_gray
    return _binarize(gray)


def _bbox_overlaps(a, b) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw < bx or bx + bw < ax or ay + ah < by or by + bh < ay)


def _kind_matches(detected_kind: str, injected_kind: str) -> bool:
    if detected_kind == injected_kind:
        return True
    if detected_kind.startswith("복합") and injected_kind in ("휨", "끊김"):
        return True
    return False


def evaluate_recall(detected, ground_truth_injected):
    """Kind-count based recall (die_blade_qc_demo.py's own self-test logic, exposed here).

    There's no per-defect pixel bbox in the GT (defects are injected along the
    contour, not against a fixed image-space box), so matching is done per-kind by
    count rather than by IoU/overlap (unlike task1's text-diff GT). Each GT entry
    of a given kind is matched against detections of that kind (or a "복합" tag)
    in injection order; extra/missing counts fall out of a simple greedy count.
    """
    detected_count_by_kind: dict[str, int] = {}
    for d in detected:
        for kind in ("휨", "끊김", "마모", "위치오차"):
            if _kind_matches(d["kind"], kind):
                detected_count_by_kind[kind] = detected_count_by_kind.get(kind, 0) + 1

    injected_count_by_kind: dict[str, int] = {}
    per_defect = []
    for gt in ground_truth_injected:
        kind = gt["kind"]
        seen_so_far = injected_count_by_kind.get(kind, 0)
        injected_count_by_kind[kind] = seen_so_far + 1
        detected_so_far_for_kind = detected_count_by_kind.get(kind, 0)
        hit = detected_so_far_for_kind > seen_so_far
        per_defect.append({
            "type": kind,
            "note": gt.get("note", ""),
            "detected": bool(hit),
            "reliable_detected": bool(hit),
        })
    return per_defect, detected_count_by_kind


def analyze(reference_bgr_or_gray, actual_bgr_or_gray, run_dir=None, ground_truth=None) -> dict:
    """Run registration + defect detection (휨/끊김/마모/위치오차), persist images, build response dict.

    ``run_dir=None`` skips writing reference/aligned/detections.png — used by the
    ML training script, which calls this hundreds of times and only needs the
    returned ``detections``/``metrics`` dicts, not the visualization files.
    """
    reference_mask = _to_mask(reference_bgr_or_gray)
    actual_mask = _to_mask(actual_bgr_or_gray)
    if actual_mask.shape != reference_mask.shape:
        actual_mask = cv2.resize(
            actual_mask, (reference_mask.shape[1], reference_mask.shape[0]),
            interpolation=cv2.INTER_NEAREST,
        )

    aligned_actual_mask, warp_matrix, reg_ok = dbm.register_actual_to_reference(
        reference_mask, actual_mask
    )
    residual_px = dbm.compute_registration_residual(reference_mask, aligned_actual_mask)
    residual_mm = residual_px * dbm.MM_PER_PX
    registration_reliable = bool(reg_ok) and residual_px <= dbm.REGISTRATION_RESIDUAL_TOL_PX

    detected = dbm.detect_defects(reference_mask, aligned_actual_mask)
    detected = dbm.resolve_bend_break_overlap(detected)

    wear_detected = dbm.detect_wear(reference_mask, aligned_actual_mask)
    single_event_bboxes = [
        d.bbox for d in detected if d.kind in ("휨", "끊김") or d.kind.startswith("복합")
    ]
    wear_detected = [
        w for w in wear_detected
        if not any(_bbox_overlaps(w.bbox, sb) for sb in single_event_bboxes)
    ]
    detected = detected + wear_detected

    position = dbm.classify_position_error(warp_matrix)
    if position["is_position_error"]:
        rx, ry, rw, rh = cv2.boundingRect((reference_mask > 0).astype(np.uint8))
        detected.append(dbm.DetectedDefect(
            kind="위치오차",
            bbox=(int(rx), int(ry), int(rw), int(rh)),
            centroid_px=(float(rx + rw / 2), float(ry + rh / 2)),
            max_deviation_mm=position["estimated_shift_mm"],
            arc_length_mm=0.0,
            area_px=0,
            note=(f"위치오차: 정합이 흡수한 추정 이동량 {position['estimated_shift_mm']}mm "
                  f"(허용 {position['tol_mm']}mm 초과, 추정 회전 {position['estimated_angle_deg']}°)"),
        ))

    if run_dir is not None:
        vis = dbm.visualize(
            reference_mask, aligned_actual_mask, detected, title="분석 결과",
            registration_reliable=registration_reliable, registration_residual_mm=residual_mm,
        )
        imwrite_unicode(os.path.join(run_dir, "reference.png"), reference_mask)
        imwrite_unicode(os.path.join(run_dir, "aligned.png"), aligned_actual_mask)
        imwrite_unicode(os.path.join(run_dir, "detections.png"), vis)

    image_area = float(reference_mask.shape[0] * reference_mask.shape[1])
    position_shift_mm = float(position["estimated_shift_mm"])

    detections = []
    for i, d in enumerate(detected):
        x, y, w, h = d.bbox
        detections.append({
            "index": i,
            "kind": d.kind,
            "bbox": {"x": int(x), "y": int(y), "w": int(w), "h": int(h)},
            "area_px": int(d.area_px),
            "max_deviation_mm": float(d.max_deviation_mm),
            "arc_length_mm": float(d.arc_length_mm),
            "mean_deviation_mm": float(d.mean_deviation_mm),
            "wear_grade": d.wear_grade,
            "note": d.note,
        })

    # ★ Reliability scoring (None whole-list if model artifact absent — graceful rollout).
    scores = reliability_dieblade.score_boxes(
        detections, image_area, residual_mm, position_shift_mm
    )
    for i, det in enumerate(detections):
        score = None
        if scores is not None and i < len(scores):
            score = None if scores[i] is None else float(scores[i])
        det["reliability_score"] = score

    detection_count_by_kind = {
        k: sum(1 for d in detected if d.kind == k or d.kind.startswith("복합"))
        for k in ("휨", "끊김", "마모", "위치오차")
    }

    metrics = {
        "n_detections": len(detected),
        "registration_converged": bool(reg_ok),
        "registration_residual_mm": round(residual_mm, 2),
        "registration_residual_tol_mm": dbm.REGISTRATION_RESIDUAL_TOL_MM,
        "registration_reliable": registration_reliable,
        "position_error": position,
        "detection_count_by_kind": detection_count_by_kind,
        "recall": None,
        "reliable_recall": None,
        "n_defects_total": None,
        "n_defects_detected": None,
        "critical_missed": None,
        "per_defect": [],
    }

    if ground_truth is not None:
        injected = ground_truth["injected_defects"]
        per_defect, _ = evaluate_recall(detections, injected)
        n_total = len(per_defect)
        n_hit = sum(1 for r in per_defect if r["detected"])
        critical_missed = any(
            r["type"] in CRITICAL_KINDS and not r["detected"] for r in per_defect
        )
        metrics.update({
            "recall": (n_hit / n_total) if n_total else 0.0,
            "reliable_recall": (n_hit / n_total) if n_total else 0.0,
            "n_defects_total": n_total,
            "n_defects_detected": n_hit,
            "critical_missed": critical_missed,
            "per_defect": per_defect,
        })

    return {
        "registration": {
            "converged": bool(reg_ok),
            "residual_mm": round(residual_mm, 2),
            "reliable": registration_reliable,
        },
        "detections": detections,
        "metrics": metrics,
    }
