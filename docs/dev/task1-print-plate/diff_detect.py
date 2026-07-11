"""
과제① 인쇄판 문안검사 - 차분(Diff) 기반 불일치 검출 모듈

spec.md 1절: "핵심 기술 = 이미지 정합 + OCR + 픽셀 차분"
이 프로토타입은 실물 이미지/OCR 엔진(tesseract 등)이 없는 환경을 고려해
"정합 + 픽셀 차분" 부분만 실행 가능한 형태로 구현한다. OCR은 registration.py와
분리된 선택적 확장 지점으로 두었다 (README 참고).

파이프라인:
  1) 정합된 두 이미지를 그레이스케일 변환
  2) 절대차 (absdiff) 계산
  3) 강건한(robust) 고정 임계값으로 이진화 (버그 수정 이력: 과거 Otsu 자동 임계값의
     불안정성 문제. README "버그 수정 이력" 절 참고)
  4) 모폴로지 연산으로 정합 미세오차/노이즈에 의한 얇은 잡음 제거 + 결함 영역 뭉치기
  5) 연결요소(connected components)로 후보 영역 bbox 추출
  6) 최소 면적 이하 잡음 제거
  7) 병합 후 각 bbox가 이미지 면적 대비 지나치게 크면(oversize) "신뢰불가" 플래그를 붙임
"""

import cv2
import numpy as np


def robust_threshold(diff, k=6.0, fixed_min=30, fixed_max=200):
    """
    Otsu 자동 임계값 대신 사용하는 강건한(robust) 임계값 산출 함수.

    버그 배경 (QA 리포트 [발견 1]): `cv2.threshold(..., THRESH_OTSU)`는 diff 이미지
    전체 히스토그램을 이미지마다 자동으로 2분할하는데, 결함이 여러 개 겹쳐 강한 diff
    신호가 많을 때는 임계값이 높게(예: 69~71) 잡히지만, 결함이 하나거나 전혀 없을 때는
    같은 정합 잔차 노이즈만 있어도 임계값이 아주 낮게(9~14) 잡혀 노이즈 자체가 "결함"
    으로 병합되어 라벨 전체를 덮는 거대한 오검출 박스를 만든다.

    해결 방향: diff 값 0(완전 일치)인 배경 픽셀이 전체의 90% 이상을 차지하므로,
    0을 포함한 전체 히스토그램에 기반한 통계(예: 전체 median/MAD)는 항상 0으로
    붕괴해 쓸모가 없다. 대신 diff > 0인 픽셀(정합 잔차 노이즈 + 실제 결함 신호가
    섞여 있는 픽셀)만 모아 median + k*MAD(정규분포 근사를 위해 1.4826 스케일)를
    구하면, 이 값은 "결함이 몇 개 있는가"와 거의 무관하게 안정적으로 정합 잔차
    노이즈 수준 바로 위쪽에 자리잡는다.

    실측 근거 (본 합성 데이터, diff_detect 버그 수정 시 스윕 실측):
      - 결함 없음(정합오차만 존재)          : diff 최대값 52, otsu=9   (오검출 유발)
      - 성분표시오류만 단독 발생            : otsu=14  vs robust floor(k=6) = 64.4
      - 오탈자만 단독 발생                  : otsu=9   vs robust floor(k=6) = 54.5
      - 오탈자+문자누락+성분표시오류 동시   : otsu=69  vs robust floor(k=6) = 64.4
    즉 robust floor는 결함 조합과 거의 무관하게 54~64 범위에 안정적으로 위치하고,
    "결함 없음" 케이스의 최대 diff 값(52)보다 항상 높게 유지되어 전면 오검출을
    방지한다. `fixed_min`/`fixed_max`는 이 값이 극단적으로 무너지거나(예: diff가
    전부 0이라 median/MAD 계산 불가) 폭주하는 것을 막는 안전 하한/상한이다.

    Parameters
    ----------
    k : float
        median 위로 몇 MAD만큼 올릴지 (클수록 보수적/둔감, 작을수록 민감/오검출 위험)
    fixed_min, fixed_max : int
        robust 통계가 붕괴하거나 폭주할 때의 안전 하한/상한
    """
    nz = diff[diff > 0]
    if nz.size == 0:
        # 두 이미지가 완전히 동일 -> 어떤 임계값을 골라도 마스크가 비어 있으므로 안전한 상수 반환
        return float(fixed_min)

    nz = nz.astype(np.float64)
    med = float(np.median(nz))
    mad = float(np.median(np.abs(nz - med)))
    floor = med + k * 1.4826 * mad

    thr = max(float(fixed_min), floor)
    thr = min(thr, float(fixed_max))
    return thr


def compute_diff_mask(
    reference,
    aligned,
    blur_ksize=3,
    morph_ksize=5,
    min_area=40,
    k=6.0,
    fixed_min=30,
    fixed_max=200,
    oversize_area_ratio=0.20,
):
    """
    Returns
    -------
    mask   : uint8 binary mask (255 = 차이 있음)
    boxes  : list of (x, y, w, h, area)  검출된 후보 영역 (병합 후 bbox 면적 기준)
    diff   : uint8 raw absdiff 이미지 (디버깅/분석용)
    info   : dict
        threshold        : 실제 사용된 이진화 임계값
        image_area        : 참조 이미지 전체 면적(픽셀)
        box_area_ratios   : boxes와 같은 순서의 리스트, 각 박스 면적/image_area
        oversized_flags   : boxes와 같은 순서의 리스트, box_area_ratio > oversize_area_ratio 이면 True
        any_oversized     : oversized_flags 중 하나라도 True인지 여부 (요약 경고용)

    버그 수정 이력: 과거에는 `cv2.threshold(..., THRESH_OTSU)`로 임계값을 자동
    산출했으나, 결함 조합에 따라 임계값이 9~71로 크게 흔들려(QA 리포트 [발견 1])
    결함이 1건뿐이거나 없을 때 라벨 전체(면적 약 93%)를 덮는 거대한 단일 오검출
    박스를 만드는 문제가 있었다. `robust_threshold()`로 대체했고, 병합된 각 박스가
    이미지 면적의 `oversize_area_ratio`(기본 20%)를 넘으면 `info['oversized_flags']`
    에 True로 표시해 "신뢰불가" 상태를 지표에서 드러낸다 (박스를 억제하지는 않음 —
    "이 결과를 믿을 수 없다"는 사실 자체를 숨기지 않는 것이 목적).
    """
    ref_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY) if reference.ndim == 3 else reference
    mov_gray = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY) if aligned.ndim == 3 else aligned

    ref_blur = cv2.GaussianBlur(ref_gray, (blur_ksize, blur_ksize), 0)
    mov_blur = cv2.GaussianBlur(mov_gray, (blur_ksize, blur_ksize), 0)

    diff = cv2.absdiff(ref_blur, mov_blur)

    threshold = robust_threshold(diff, k=k, fixed_min=fixed_min, fixed_max=fixed_max)
    _, mask = cv2.threshold(diff, threshold, 255, cv2.THRESH_BINARY)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (morph_ksize, morph_ksize))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

    n_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)

    boxes = []
    for i in range(1, n_labels):  # 0번은 배경
        x, y, w, h, area = stats[i]
        if area < min_area:
            continue
        boxes.append((int(x), int(y), int(w), int(h), int(area)))

    # 근접 bbox 병합 (같은 문구/단어 내 여러 조각으로 쪼개진 경우를 하나의 결함 영역으로 합침)
    boxes = merge_close_boxes(boxes, max_gap=25)

    image_area = int(ref_gray.shape[0] * ref_gray.shape[1])
    box_area_ratios = [
        (w * h) / image_area if image_area else 0.0 for (_, _, w, h, _) in boxes
    ]
    oversized_flags = [ratio > oversize_area_ratio for ratio in box_area_ratios]

    info = dict(
        threshold=threshold,
        image_area=image_area,
        box_area_ratios=[round(r, 4) for r in box_area_ratios],
        oversized_flags=oversized_flags,
        any_oversized=any(oversized_flags),
        oversize_area_ratio=oversize_area_ratio,
    )

    return mask, boxes, diff, info


def merge_close_boxes(boxes, max_gap=25):
    """x/y 방향으로 max_gap 이내에 있는 bbox들을 하나로 병합한다 (단순 그리디 방식)."""
    if not boxes:
        return boxes

    rects = [(x, y, x + w, y + h) for x, y, w, h, _ in boxes]
    merged = True
    while merged:
        merged = False
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                if _rects_close(rects[i], rects[j], max_gap):
                    rects[i] = _union(rects[i], rects[j])
                    del rects[j]
                    merged = True
                    break
            if merged:
                break

    result = []
    for x0, y0, x1, y1 in rects:
        result.append((x0, y0, x1 - x0, y1 - y0, (x1 - x0) * (y1 - y0)))
    return result


def _rects_close(a, b, gap):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    expanded_a = (ax0 - gap, ay0 - gap, ax1 + gap, ay1 + gap)
    return not (
        expanded_a[2] < bx0 or bx1 < expanded_a[0] or expanded_a[3] < by0 or by1 < expanded_a[1]
    )


def _union(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def draw_boxes(img, boxes, color=(0, 0, 255), thickness=3, labels=None):
    out = img.copy()
    for idx, (x, y, w, h, area) in enumerate(boxes):
        cv2.rectangle(out, (x, y), (x + w, y + h), color, thickness)
        text = labels[idx] if labels and idx < len(labels) else f"#{idx+1}"
        cv2.putText(
            out, text, (x, max(0, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA
        )
    return out


def iou(box_a, box_b):
    """box = (x, y, w, h). IoU 계산."""
    ax0, ay0, aw, ah = box_a
    ax1, ay1 = ax0 + aw, ay0 + ah
    bx0, by0, bw, bh = box_b
    bx1, by1 = bx0 + bw, by0 + bh

    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0, ix1 - ix0), max(0, iy1 - iy0)
    inter = iw * ih
    if inter == 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    return inter / union
