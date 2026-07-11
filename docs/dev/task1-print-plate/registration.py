"""
과제① 인쇄판 문안검사 - 정합(Registration) 모듈

spec.md 3.3절: "정합(Registration): 특징점·호모그래피(①) ... 로 정밀 정렬 후 차분
— 정렬 오차로 인한 오검출 제거의 핵심"

이 모듈은 ORB 특징점 기반 호모그래피 정합을 1순위로 시도하고,
특징점이 부족해 호모그래피 추정이 실패하는 경우(예: 텍스트가 희소해 매칭점이 모자란
저해상도/저텍스처 이미지) ECC(Enhanced Correlation Coefficient) 기반 유사변환 정합을
대체 수단으로 사용한다. 두 방법 모두 실패하면 원본을 그대로 반환한다(정렬 안 함).
"""

import cv2
import numpy as np


def _to_gray(img):
    if img.ndim == 3:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img


def register_orb_homography(reference, moving, min_matches=15, good_ratio=0.75):
    """
    ORB 특징점 + BFMatcher + RANSAC 호모그래피로 moving 이미지를 reference 좌표계에 정렬한다.

    Returns
    -------
    aligned : np.ndarray or None   정렬된 moving 이미지 (실패 시 None)
    H       : np.ndarray or None   추정된 3x3 호모그래피 행렬
    n_inliers : int                RANSAC inlier 매칭 개수 (신뢰도 참고용)
    """
    ref_gray = _to_gray(reference)
    mov_gray = _to_gray(moving)

    orb = cv2.ORB_create(nfeatures=4000)
    kp1, des1 = orb.detectAndCompute(ref_gray, None)
    kp2, des2 = orb.detectAndCompute(mov_gray, None)

    if des1 is None or des2 is None or len(kp1) < 4 or len(kp2) < 4:
        return None, None, 0

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    raw_matches = matcher.knnMatch(des1, des2, k=2)

    good = []
    for m_n in raw_matches:
        if len(m_n) != 2:
            continue
        m, n = m_n
        if m.distance < good_ratio * n.distance:
            good.append(m)

    if len(good) < min_matches:
        return None, None, len(good)

    src_pts = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst_pts = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)

    H, mask = cv2.findHomography(dst_pts, src_pts, cv2.RANSAC, 4.0)
    if H is None:
        return None, None, len(good)

    n_inliers = int(mask.sum()) if mask is not None else 0
    h, w = ref_gray.shape[:2]
    aligned = cv2.warpPerspective(
        moving, H, (w, h), borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255)
    )
    return aligned, H, n_inliers


def register_ecc(reference, moving, warp_mode=cv2.MOTION_EUCLIDEAN, n_iter=200, eps=1e-6):
    """
    ECC 기반 정합 (특징점 매칭이 부족할 때의 대체 수단).
    MOTION_EUCLIDEAN: 회전+이동만 추정 (스케일/전단 없음) -> 인쇄판처럼 텍스트 위주 이미지에 안정적.
    """
    ref_gray = _to_gray(reference).astype(np.float32)
    mov_gray = _to_gray(moving).astype(np.float32)

    warp_matrix = np.eye(2, 3, dtype=np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, n_iter, eps)

    try:
        _, warp_matrix = cv2.findTransformECC(
            ref_gray, mov_gray, warp_matrix, warp_mode, criteria
        )
    except cv2.error:
        return None, None

    h, w = ref_gray.shape[:2]
    aligned = cv2.warpAffine(
        moving,
        warp_matrix,
        (w, h),
        flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )
    return aligned, warp_matrix


def align_to_reference(reference, moving, min_matches=15):
    """
    통합 정합 함수: ORB 호모그래피 -> 실패 시 ECC 유사변환 -> 실패 시 원본 그대로.
    Returns (aligned_image, method_used, info_dict)
    """
    aligned, H, n_inliers = register_orb_homography(reference, moving, min_matches=min_matches)
    if aligned is not None and n_inliers >= min_matches:
        return aligned, "orb_homography", dict(n_inliers=n_inliers, H=H.tolist())

    aligned, warp_matrix = register_ecc(reference, moving)
    if aligned is not None:
        return aligned, "ecc_euclidean", dict(warp_matrix=warp_matrix.tolist())

    return moving, "none (registration failed, using raw image)", dict()
