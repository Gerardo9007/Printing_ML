"""
과제① 인쇄판 문안검사 - 정합 + 차분 파이프라인 데모 (End-to-End)

spec.md 1절 공통 파이프라인의 앞부분을 재현한다:
  [입력] -> [전처리] -> [정합(Registration)] -> [차분/이상탐지] -> [판정·시각화]

실행:
    python run_demo.py

이 스크립트는:
  1) generate_labels.py로 정답본/불량본(회전·이동 오차 포함) 합성 이미지를 생성하고
  2) registration.py로 불량본을 정답본 좌표계에 정합하고
  3) diff_detect.py로 정합 전/후 차분 결과를 비교해 정합의 효과를 보이고
  4) 검출된 불일치 후보 영역을 주입된 결함(GT)과 대조해 재현율(recall)을 계산한다
     (spec.md 6절: 치명 클래스 미검출 0이 최우선 지표이므로, 이 데모에서도
      "몇 건의 결함 중 몇 건을 실제로 검출했는가"를 최우선으로 보고한다.)
"""

import json
import os
import sys

import cv2
import numpy as np

import generate_labels
import registration
import diff_detect
from imgio import imread_unicode, imwrite_unicode

# Windows 콘솔(cp949) 환경에서도 한글 출력이 깨지지 않도록 stdout을 UTF-8로 강제한다.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")


def evaluate_recall(detected_boxes, ground_truth, oversized_flags=None):
    """
    주입된 결함마다 검출된 diff bbox 중 하나라도 겹치면 '검출'로 인정한다.

    버그 수정 이력 (QA 리포트 [발견 2]): 과거에는 항상 라인 단위 GT
    (`defect_line_boxes`)만 사용해서, 같은 줄(ingredient)에 3개 결함이 겹쳐 있으면
    하나만 diff에 걸려도 나머지 둘까지 "검출됨"으로 잘못 집계됐다. 이제
    `generate_labels.make_defective`가 결함 단위 GT(`injected_defects[i]["bbox"]`)를
    함께 제공하므로, 있으면 그것을 우선 사용하고 없을 때만 라인 단위 GT로 폴백한다.

    버그 수정 이력 (QA 리포트 [발견 1/3]): `oversized_flags`가 주어지면, "라인/이미지
    전체를 덮는 오검출 박스"(`diff_detect`의 면적 가드레일에 걸린 박스)로만 겹친
    경우는 `detected=True`이지만 `reliable_detected=False`로 별도 표시한다. 즉
    "찾긴 찾았지만 위치를 좁히지 못해 신뢰할 수 없는 검출"과 "정상적으로 국소화된
    검출"을 구분해서 보고한다. spec.md 6절의 "치명 클래스 미검출 0"은
    `reliable_detected` 기준으로 판정해야 의미가 있다.
    """
    line_boxes = ground_truth["defect_line_boxes"]
    defects = ground_truth["injected_defects"]
    oversized_flags = oversized_flags or [False] * len(detected_boxes)

    results = []
    for d in defects:
        tag = d["tag"]
        gt_bbox_xyxy = d.get("bbox")  # 결함 단위 GT (있으면 우선 사용, 발견 2 대응)
        used_line_level_gt = gt_bbox_xyxy is None
        if gt_bbox_xyxy is None:
            gt_bbox_xyxy = line_boxes[tag]  # 폴백: 라인 단위 GT (구버전 호환)
        gx0, gy0, gx1, gy1 = gt_bbox_xyxy
        gt_box_xywh = (gx0, gy0, gx1 - gx0, gy1 - gy0)

        hit = False
        hit_reliable = False
        best_iou = 0.0
        for db, oversized in zip(detected_boxes, oversized_flags):
            score = _overlap_fraction(gt_box_xywh, db)
            best_iou = max(best_iou, score)
            if score > 0.05:  # GT 영역의 5% 이상을 detected box가 덮으면 검출로 인정
                hit = True
                if not oversized:
                    hit_reliable = True

        results.append(
            dict(
                type=d["type"],
                tag=tag,
                note=d["note"],
                detected=hit,
                reliable_detected=hit_reliable,
                overlap_score=round(best_iou, 3),
                used_line_level_gt=used_line_level_gt,
            )
        )
    return results


def _overlap_fraction(gt_box, det_box):
    """GT box 면적 대비, 두 박스가 겹치는 면적의 비율 (recall 지향 지표)."""
    gx, gy, gw, gh = gt_box
    dx, dy, dw, dh = det_box[:4]

    ix0, iy0 = max(gx, dx), max(gy, dy)
    ix1, iy1 = min(gx + gw, dx + dw), min(gy + gh, dy + dh)
    iw, ih = max(0, ix1 - ix0), max(0, iy1 - iy0)
    inter = iw * ih
    if inter == 0 or gw * gh == 0:
        return 0.0
    return inter / (gw * gh)


def compute_precision_proxy(detected_boxes, ground_truth):
    """
    (버그 수정 이력 - QA 리포트 [발견 3] 대응)
    run_demo.py는 과거 recall만 계산했고, 검출 박스가 얼마나 "과하게 큰가"에 대한
    지표가 전혀 없었다. GT bbox(gt) 대비 실측 픽셀 단위 Precision을 계산할 수는
    없으므로(실측 문자 단위 라벨이 없음), 대신 "검출된 박스 면적 중 실제 결함
    GT 영역과 겹치는 비율"을 Precision 근사 지표로 사용한다:

        precision_proxy = (검출 박스 ∩ 임의의 GT 영역 합) / (검출 박스 전체 면적)

    라벨 전체(93%)를 덮는 오검출 박스처럼 GT와 무관한 영역을 많이 포함할수록 이 값이
    낮아지므로, [발견 1] 같은 실패를 recall과 별도로 드러낼 수 있다.
    """
    defects = ground_truth["injected_defects"]
    gt_rects = []
    for d in defects:
        bbox = d.get("bbox") or ground_truth["defect_line_boxes"].get(d["tag"])
        if bbox is None:
            continue
        gx0, gy0, gx1, gy1 = bbox
        gt_rects.append((gx0, gy0, gx1 - gx0, gy1 - gy0))

    total_area = 0
    tp_area = 0
    for db in detected_boxes:
        dx, dy, dw, dh = db[:4]
        box_area = dw * dh
        total_area += box_area

        best_overlap = 0
        for gx, gy, gw, gh in gt_rects:
            ix0, iy0 = max(dx, gx), max(dy, gy)
            ix1, iy1 = min(dx + dw, gx + gw), min(dy + dh, gy + gh)
            iw, ih = max(0, ix1 - ix0), max(0, iy1 - iy0)
            best_overlap = max(best_overlap, iw * ih)
        tp_area += best_overlap

    precision = tp_area / total_area if total_area > 0 else 1.0
    return dict(precision_proxy=round(precision, 4), total_detected_area=total_area, gt_overlap_area=tp_area)


def run_pipeline_stage(ref_bgr, moving_bgr, label, min_area=40):
    """정합 -> 차분 -> bbox 검출까지 한 번에 수행하고 시각화 이미지를 저장한다."""
    aligned, method, info = registration.align_to_reference(ref_bgr, moving_bgr)
    mask, boxes, diff, diff_info = diff_detect.compute_diff_mask(ref_bgr, aligned, min_area=min_area)

    vis = diff_detect.draw_boxes(aligned.copy(), boxes)

    imwrite_unicode(os.path.join(OUTPUT_DIR, f"{label}_aligned.png"), aligned)
    imwrite_unicode(os.path.join(OUTPUT_DIR, f"{label}_diff_mask.png"), mask)
    imwrite_unicode(os.path.join(OUTPUT_DIR, f"{label}_detections.png"), vis)

    return dict(method=method, info=info, boxes=boxes, aligned=aligned, mask=mask, diff_info=diff_info)


def main():
    print("=" * 70)
    print("STEP 1. 합성 라벨 이미지 생성 (정답본 / 불량본)")
    print("=" * 70)
    generate_labels.main()

    print()
    print("=" * 70)
    print("STEP 2. 이미지 로드")
    print("=" * 70)
    ref_path = os.path.join(OUTPUT_DIR, "01_reference.png")
    defect_path = os.path.join(OUTPUT_DIR, "02_defective_misaligned.png")
    gt_path = os.path.join(OUTPUT_DIR, "00_ground_truth.json")

    ref_bgr = imread_unicode(ref_path)
    defect_bgr = imread_unicode(defect_path)
    with open(gt_path, encoding="utf-8") as f:
        ground_truth = json.load(f)

    print(f"정답본: {ref_bgr.shape}, 불량본(정합오차 포함): {defect_bgr.shape}")

    print()
    print("=" * 70)
    print("STEP 3. [대조군] 정합 없이 바로 차분 -> 정렬 오차로 인한 오검출 확인")
    print("=" * 70)
    mask_naive, boxes_naive, _, naive_diff_info = diff_detect.compute_diff_mask(ref_bgr, defect_bgr, min_area=40)
    vis_naive = diff_detect.draw_boxes(defect_bgr.copy(), boxes_naive)
    imwrite_unicode(os.path.join(OUTPUT_DIR, "10_naive_nodiff_aligned.png"), defect_bgr)
    imwrite_unicode(os.path.join(OUTPUT_DIR, "10_naive_diff_mask.png"), mask_naive)
    imwrite_unicode(os.path.join(OUTPUT_DIR, "10_naive_detections.png"), vis_naive)
    print(f"정합 없이 검출된 후보 영역 수: {len(boxes_naive)} (텍스트 전체 라인이 오탐지될 가능성 높음)")

    print()
    print("=" * 70)
    print("STEP 4. [본 파이프라인] 정합(Registration) 수행")
    print("=" * 70)
    result = run_pipeline_stage(ref_bgr, defect_bgr, label="20_pipeline", min_area=40)
    print(f"정합 방법: {result['method']}")
    if "n_inliers" in result["info"]:
        print(f"  RANSAC inlier 매칭 수: {result['info']['n_inliers']}")
    diff_info = result["diff_info"]
    print(f"차분 이진화 임계값(robust threshold): {diff_info['threshold']:.1f}  (구버전 Otsu 자동임계값 대체, 버그 수정 이력 참고)")
    print(f"정합 후 검출된 후보 영역 수: {len(result['boxes'])}")
    for i, (x, y, w, h, area) in enumerate(result["boxes"]):
        ratio = diff_info["box_area_ratios"][i]
        flag = " [!! 오검출 가드레일: 이미지 면적의 {:.1%} 차지 -> 신뢰불가 !!]".format(ratio) if diff_info["oversized_flags"][i] else ""
        print(f"  #{i+1}: bbox=({x},{y},{w},{h}) area={area} area_ratio={ratio:.1%}{flag}")
    if diff_info["any_oversized"]:
        print(f"!! 경고: 검출 박스 중 하나 이상이 이미지 면적의 {diff_info['oversize_area_ratio']:.0%}를 초과 -> 위치를 좁히지 못한 신뢰불가 검출 !!")

    print()
    print("=" * 70)
    print("STEP 5. 결함 검출 재현율(Recall)/정밀도(Precision) 평가 — spec.md 6절: 미검출 0이 최우선 지표")
    print("=" * 70)
    eval_results = evaluate_recall(result["boxes"], ground_truth, oversized_flags=diff_info["oversized_flags"])
    n_total = len(eval_results)
    n_hit = sum(1 for r in eval_results if r["detected"])
    n_hit_reliable = sum(1 for r in eval_results if r["reliable_detected"])
    for r in eval_results:
        if r["reliable_detected"]:
            status = "검출 O"
        elif r["detected"]:
            status = "검출(신뢰불가 - 오검출 가드레일에 걸린 박스로만 겹침)"
        else:
            status = "!! 미검출 !!"
        gt_note = "" if not r["used_line_level_gt"] else " [라인단위 GT 폴백]"
        print(f"  [{r['type']:10s}] {r['note']:30s} -> {status} (overlap={r['overlap_score']}){gt_note}")

    recall = n_hit / n_total if n_total else 0.0
    reliable_recall = n_hit_reliable / n_total if n_total else 0.0
    print(f"\n총 주입 결함 {n_total}건 중 {n_hit}건 검출(단순 overlap 기준) -> Recall = {recall:.1%}")
    print(f"오검출 가드레일을 통과한(신뢰 가능한) 검출 -> {n_hit_reliable}건 -> Reliable Recall = {reliable_recall:.1%}")

    precision_info = compute_precision_proxy(result["boxes"], ground_truth)
    print(
        f"Precision 근사 지표(검출 박스 면적 중 실제 GT와 겹치는 비율) = "
        f"{precision_info['precision_proxy']:.1%}  "
        f"(검출 총면적={precision_info['total_detected_area']}, GT와 겹친 면적={precision_info['gt_overlap_area']})"
    )

    critical_missed = [
        r for r in eval_results if r["type"] == "성분표시오류" and not r["reliable_detected"]
    ]
    if critical_missed:
        print("!! 경고: 최우선 치명 클래스(성분표시오류)가 신뢰 가능하게 검출되지 않음"
              " (미검출 또는 오검출 가드레일에 걸린 박스로만 겹침) !!")
    else:
        print("최우선 치명 클래스(성분표시오류)는 모두 신뢰 가능하게 검출됨 (spec.md 목표 충족)")

    summary = dict(
        naive_no_registration_boxes=len(boxes_naive),
        naive_diff_threshold=naive_diff_info["threshold"],
        registration_method=result["method"],
        registration_info={k: v for k, v in result["info"].items() if k != "H"},
        pipeline_detected_boxes=len(result["boxes"]),
        diff_threshold=diff_info["threshold"],
        box_area_ratios=diff_info["box_area_ratios"],
        any_oversized_box=diff_info["any_oversized"],
        oversize_area_ratio_guard=diff_info["oversize_area_ratio"],
        recall=recall,
        reliable_recall=reliable_recall,
        precision_proxy=precision_info["precision_proxy"],
        n_defects_total=n_total,
        n_defects_detected=n_hit,
        n_defects_reliably_detected=n_hit_reliable,
        per_defect=eval_results,
    )
    summary_path = os.path.join(OUTPUT_DIR, "99_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print()
    print("=" * 70)
    print(f"완료. 요약 결과: {summary_path}")
    print(f"시각화 이미지: {OUTPUT_DIR} 폴더 (20_pipeline_detections.png 확인 권장)")
    print("=" * 70)


if __name__ == "__main__":
    main()
