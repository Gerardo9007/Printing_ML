"""
과제② 목형 칼날검사 — 파이프라인 원리 검증용 프로토타입

spec.md 1절 공통 파이프라인을 목형 칼날검사에 좁혀 재현한다.

    [입력: 목형 이미지 / CAD 도면] -> [전처리·정규화] -> [정합(Registration)]
        -> [차분/이상탐지] -> [판정·시각화] -> [결과 기록]

실제 목형 사진이나 CAD 파일이 없으므로, 이 스크립트가 직접:
  1. "설계 기준 형상(CAD 도면)"에 해당하는 합성 사각형(모서리 라운드) 칼날 윤곽을 생성하고
  2. 그 위에 spec.md 2절에서 정의한 결함 클래스 중 최우선 치명 클래스인
     "휨"과 "끊김"을 프로그램으로 주입해 "실제 촬영된 목형"에 해당하는 버전을 만든 뒤
     (spec.md 3.2 "합성 결함 삽입"에 해당)
  3. 촬영 시 발생하는 미세한 위치/각도 어긋남(카메라 정렬 오차)을 추가로 흉내내고
  4. 기준 도면과 실물을 정합(Registration)한 뒤 형상 diff로 결함 위치를 자동 검출한다.

가정(assumptions) — problem.md/spec.md에 명시되지 않아 데모 구현을 위해 임의로 정한 값들:
  - 가정: 1px = 0.2mm 로 픽셀-실측 환산 스케일을 고정한다 (실제로는 지그·캘리브레이션으로 결정되어야 함, spec.md 3.1 "촬영 표준화" 참고).
  - 가정: 정합 오차 허용치(정상/결함 판정 임계값)는 1.0mm(=5px)로 둔다. 실제 값은 목형 공차 스펙에 따라 조정되어야 한다.
  - 가정: 칼날은 백라이트 실루엣 촬영을 통해 이미 이진(선/배경) 이미지로 얻어졌다고 가정한다 (spec.md 3.1 "촬영 표준화 - 백라이트(실루엣)" 참고). 즉 이 데모는 촬영 이후 단계(정합~판정)만 다룬다.
  - 마모(연속량)·위치오차 클래스도 spec.md 3.2 "합성 결함 삽입" 기법으로 합성 주입·검출을 구현했다(Gap G3/G4).
    마모는 미세·들쭉날쭉한 국소 침식으로 주입해 평균 편차(mm)로 등급화(정상/주의/교체)하고, 위치오차는
    정합이 흡수한 ECC 추정 이동량을 사후 검사해 판정한다. 단 모두 "완전 합성 데이터 한정" 검증이며,
    특히 교체 등급의 심한 마모는 휨과 형상적으로 구분되지 않는 한계가 있다(상세·한계는 README 참고).

실행: `python die_blade_qc_demo.py` (표준 라이브러리 외 numpy, opencv-python 필요 — requirements.txt 참고)
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# cv2.putText()는 Hershey 폰트를 사용해 한글을 그리지 못하므로(물음표로 깨짐),
# 한글 라벨은 PIL + 시스템 한글 폰트(맑은 고딕)로 렌더링한다.
_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\malgun.ttf",
    r"C:\Windows\Fonts\malgunbd.ttf",
]


def _load_korean_font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def put_korean_text(img_bgr: np.ndarray, text: str, org: tuple[int, int], color_bgr: tuple[int, int, int],
                     size: int = 20) -> np.ndarray:
    """OpenCV BGR 이미지 위에 한글 텍스트를 그려 반환한다."""
    pil_img = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)
    font = _load_korean_font(size)
    color_rgb = (color_bgr[2], color_bgr[1], color_bgr[0])
    draw.text(org, text, font=font, fill=color_rgb)
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

# ---------------------------------------------------------------------------
# 전역 설정 (가정 명시)
# ---------------------------------------------------------------------------

CANVAS_SIZE = 900              # px, 정사각 캔버스
MM_PER_PX = 0.2                 # 가정: 1px = 0.2mm 촬영 스케일 캘리브레이션
DEFECT_TOL_MM = 1.0             # 가정: 결함 판정 허용 오차 (정합 잔차 포함)
DEFECT_TOL_PX = DEFECT_TOL_MM / MM_PER_PX   # = 5px
MIN_DEFECT_ARC_MM = 2.0         # 가정: 이 길이 미만의 미세 편차는 노이즈로 간주(과검출 억제용 최소 크기)
LINE_THICKNESS = 3              # 칼날 라인 두께(px)

# QA 리포트 §2-B 가드레일: ECC(findTransformECC)는 "수렴했으나 틀린 답"(대칭 형상에서의 오수렴)도
# converged=True로 보고하므로, 그 값만으로 정합 품질을 신뢰할 수 없다. 정합 후 기준 도면과 정합된
# 실물 두 마스크 간 "대칭 평균 최근접거리"(chamfer distance, compute_registration_residual() 참고)를
# 별도로 계산해 정합이 실제로 잘 맞았는지 검증한다.
#
# 임계치 근거(실측, QA §2-B 재현 시나리오 — 끊김 1개 주입 + 회전 오차 1.4/35/45/90도로 재현):
#   회전  1.4°: 잔차 ≈  1.26px (0.25mm) -> 정상 정합, 검출 1건(정상)
#   회전   35°: 잔차 ≈  1.27px (0.25mm) -> 정상 정합, 검출 1건(정상) — 대각도에 가까워도 정확히 수렴
#   회전   45°: 잔차 ≈ 49.4px (9.9mm)  -> 대칭 오수렴(전혀 다른 위치/각도에 정렬), 오검출 17건
#   회전   90°: 잔차 ≈ 69.3px (13.9mm) -> 대칭 오수렴, 오검출 9건
# (실측 스크립트: test_rotation_angles.py, 본 저장소 밖 검증용 스크래치 스크립트)
# 즉 "정상 정합"(~1.3px)과 "대칭 오수렴"(~49px 이상) 사이에는 약 40배 차이의 명확한 간극이 있다.
# 정상 구간(35° 이하 관측값 ~1.3px)에 충분한 여유를 두면서, 오수렴 구간(45° 이상 관측값 최소
# ~49px)보다는 확실히 낮은 REGISTRATION_RESIDUAL_TOL_PX = 10px(=2.0mm)를 선택했다.
REGISTRATION_RESIDUAL_TOL_PX = 10.0
REGISTRATION_RESIDUAL_TOL_MM = REGISTRATION_RESIDUAL_TOL_PX * MM_PER_PX

# ---------------------------------------------------------------------------
# 마모(Gap G3)·위치오차(Gap G4) 검출 파라미터 — 모두 가정값, 실제 목형 공차 스펙 확인 필요
# ---------------------------------------------------------------------------
# [마모(Wear)] 마모는 "단일 사건(끊김/휨)"이 아니라 칼날 엣지가 국소적으로 조금씩 침식되는
# "누적 편차"이므로, 개별 건수가 아니라 침식 구간의 "평균 편차(mm)"로 등급화한다(classify_wear_grade).
# 편차 측정은 기존 distanceTransform(실물→기준 최근접거리)을 재사용하되, 다음 두 경계로 대역을 좁힌다.
#   - WEAR_NOISE_FLOOR_MM: 이 값 이하 편차는 AA 렌더링/정합 잔차 노이즈로 간주(정상 케이스 실측 최대
#     편차 ~0.44mm를 관측해, 그보다 위인 0.5mm를 바닥값으로 둠). 이 바닥값 미만은 마모 대역에서 제외.
#   - WEAR_CEIL_MM: 이 값 초과 편차는 국소 "휨/끊김"(단일 사건, 변위가 큼)으로 간주해 마모 대상에서
#     제외한다(그 주변 램프까지 팽창 배제). 마모는 미세·들쭉날쭉·저변위라는 형상적 특징으로 구분.
WEAR_NOISE_FLOOR_MM = 0.5       # 가정: AA/정합 잔차 노이즈 바닥값(정상 케이스 실측 최대 ~0.44mm 근거)
WEAR_NOISE_FLOOR_PX = WEAR_NOISE_FLOOR_MM / MM_PER_PX
WEAR_CEIL_MM = 3.0              # 가정: 이 초과 편차는 단일 사건(휨/끊김)으로 간주해 마모에서 제외
WEAR_CEIL_PX = WEAR_CEIL_MM / MM_PER_PX
MIN_WEAR_ARC_MM = 3.0           # 가정: 마모로 인정할 최소 침식 구간 길이(이 미만은 국소 노이즈로 간주)
# 등급 경계값(가정값 — 실제 목형 공차 스펙 확인 필요): 평균 편차 기준
#   정상 < 0.3mm, 0.3mm ≤ 주의 < 0.8mm, 교체 ≥ 0.8mm
WEAR_GRADE_CAUTION_MM = 0.3     # 가정: 정상/주의 경계
WEAR_GRADE_REPLACE_MM = 0.8     # 가정: 주의/교체 경계

# [위치오차(Position Error)] 정합(Registration)은 촬영 정렬오차를 흡수해버리므로, "목형이 지그에
# 실제로 잘못 놓인 것"과 "단순 촬영 정렬오차"를 diff 단계에서는 구분하지 못한다(설계상 근본 이슈).
# 대신 정합이 흡수한 변환량(ECC 추정 이동량)을 사후 검사해, 그 이동량이 "정상 촬영 정렬오차" 전제
# (작은 이동, 수 px)를 벗어나면 "지그 안착 자체가 불량"인 위치오차로 별도 분류한다.
# 근거(실측): 정상 촬영 정렬오차(tx=6,ty=-4 등)의 ECC 추정 이동량은 ~1.7mm, 무오차(0,0)에서도
# 정합/팽창 기하로 인한 추정 편향이 ~3.1mm까지 관측됨. 실제 위치오차(inj 8.9mm)는 ~6.1mm로 추정됨.
# 이 사이(≈3.1mm 노이즈 상한 ~ 6.1mm 신호)에 임계치 5.0mm를 둔다. (마진이 크지 않음 — 한계는 README 참고)
POSITION_ERROR_TOL_MM = 5.0     # 가정: 추정 이동량이 이 값을 초과하면 위치오차로 판정

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


# ---------------------------------------------------------------------------
# 1. 기준 도면(CAD) 형상 생성 — 라운드 사각 다이라인
# ---------------------------------------------------------------------------

def generate_reference_contour(
    center=(CANVAS_SIZE // 2, CANVAS_SIZE // 2),
    width=560,
    height=380,
    corner_radius=60,
    points_per_edge=140,
    points_per_arc=60,
) -> np.ndarray:
    """다이커팅 목형에서 흔한 '모서리가 둥근 사각 칼선'을 조밀한 점열로 생성한다.

    반환값: (N, 2) float64 배열, 시계방향 폐곡선, 등간격에 가깝게 샘플링됨.
    """
    cx, cy = center
    w, h = width / 2, height / 2
    r = corner_radius

    def arc(cx_, cy_, r_, a0, a1, n):
        angles = np.linspace(a0, a1, n, endpoint=False)
        return np.stack([cx_ + r_ * np.cos(angles), cy_ + r_ * np.sin(angles)], axis=1)

    def edge(p0, p1, n):
        t = np.linspace(0, 1, n, endpoint=False)[:, None]
        return p0 + (p1 - p0) * t

    # 네 변 + 네 모서리 호를 순서대로 이어붙여 시계방향 폐곡선을 만든다.
    top_right_arc_c = (cx + w - r, cy - h + r)
    bottom_right_arc_c = (cx + w - r, cy + h - r)
    bottom_left_arc_c = (cx - w + r, cy + h - r)
    top_left_arc_c = (cx - w + r, cy - h + r)

    segs = [
        edge(np.array([cx - w + r, cy - h]), np.array([cx + w - r, cy - h]), points_per_edge),   # top edge
        arc(*top_right_arc_c, r, -math.pi / 2, 0, points_per_arc),                                # top-right corner
        edge(np.array([cx + w, cy - h + r]), np.array([cx + w, cy + h - r]), points_per_edge),    # right edge
        arc(*bottom_right_arc_c, r, 0, math.pi / 2, points_per_arc),                              # bottom-right corner
        edge(np.array([cx + w - r, cy + h]), np.array([cx - w + r, cy + h]), points_per_edge),    # bottom edge
        arc(*bottom_left_arc_c, r, math.pi / 2, math.pi, points_per_arc),                         # bottom-left corner
        edge(np.array([cx - w, cy + h - r]), np.array([cx - w, cy - h + r]), points_per_edge),    # left edge
        arc(*top_left_arc_c, r, math.pi, 3 * math.pi / 2, points_per_arc),                        # top-left corner
    ]
    contour = np.concatenate(segs, axis=0)
    return contour


# ---------------------------------------------------------------------------
# 2. 결함 주입 (spec.md 3.2 "합성 결함 삽입": 국소 끊김·휨)
# ---------------------------------------------------------------------------

@dataclass
class InjectedDefect:
    kind: str                 # "휨" | "끊김" | "마모" | "위치오차"
    start_idx: int
    end_idx: int
    magnitude_px: float = 0.0
    note: str = ""


def _local_normals(points: np.ndarray) -> np.ndarray:
    """폐곡선 각 점에서 바깥 방향(진행방향 기준 우측 법선)을 근사 계산."""
    nxt = np.roll(points, -1, axis=0)
    prv = np.roll(points, 1, axis=0)
    tangent = nxt - prv
    normal = np.stack([tangent[:, 1], -tangent[:, 0]], axis=1)
    norm = np.linalg.norm(normal, axis=1, keepdims=True)
    norm[norm == 0] = 1.0
    return normal / norm


def inject_bend(points: np.ndarray, start_frac: float, span_frac: float, magnitude_px: float,
                 rng: np.random.Generator) -> tuple[np.ndarray, InjectedDefect]:
    """폐곡선 일부 구간을 바깥/안쪽으로 부드럽게 밀어내 '휨' 결함을 만든다."""
    n = len(points)
    start = int(start_frac * n)
    span = max(6, int(span_frac * n))
    idx = (np.arange(start, start + span)) % n

    normals = _local_normals(points)
    # 중앙이 가장 크게 휘고 양끝은 0으로 수렴하는 Hann 창(부드러운 굴곡)
    window = np.hanning(span)
    jitter = rng.normal(0, 0.05, size=span)  # 완전 매끈한 곡선이 아니게 약간의 자연스러움 부여

    bent = points.copy()
    for k, i in enumerate(idx):
        disp = magnitude_px * (window[k] + jitter[k])
        bent[i] = points[i] + normals[i] * disp

    defect = InjectedDefect(
        kind="휨",
        start_idx=int(idx[0]),
        end_idx=int(idx[-1]),
        magnitude_px=float(magnitude_px),
        note=f"바깥 방향 최대 변위 {magnitude_px * MM_PER_PX:.2f}mm",
    )
    return bent, defect


def inject_wear(points: np.ndarray, start_frac: float, span_frac: float, depth_px: float,
                 rng: np.random.Generator, jag: float = 0.6) -> tuple[np.ndarray, InjectedDefect]:
    """폐곡선 일부 구간을 '안쪽(칼날 바깥 법선의 반대)'으로 미세하게, 들쭉날쭉하게 침식시켜 '마모'
    결함을 만든다.

    휨(inject_bend)과의 형상적 구분(왜 이렇게 설계했는지는 README "마모/위치오차" 절 참고):
      (a) 저변위: depth_px는 휨(magnitude_px ~26~34px)보다 훨씬 작은 2~4px(0.4~0.8mm) 수준으로 둔다.
      (b) 들쭉날쭉(국소 랜덤 지터): 휨은 Hann 창으로 '부드럽게' 한 방향으로 밀어내지만, 마모는 각 점의
          침식 깊이에 큰 비율(jag)의 독립 균등난수를 곱해 이웃 점끼리 깊이가 크게 요동치는 거친 엣지를
          만든다. 이 '거칠고 얕은' 특징이 합성 데이터 상에서 휨(매끈·큰 변위)과 시각/수치적으로 구분된다.
      (c) 방향: 침식이므로 항상 안쪽(-normal). 휨은 바깥(+normal)으로 밀어낸다.

    depth_px는 '평균 침식 깊이의 기준값'이며, Hann 창(구간 중앙이 깊고 양끝은 얕음)과 지터가 곱해져
    실제 점별 깊이는 0~약 2*depth_px 사이에서 요동친다.
    """
    n = len(points)
    start = int(start_frac * n)
    span = max(6, int(span_frac * n))
    idx = (np.arange(start, start + span)) % n

    normals = _local_normals(points)
    window = np.hanning(span)

    worn = points.copy()
    depths: list[float] = []
    for k, i in enumerate(idx):
        base = depth_px * (0.5 + 0.5 * window[k])          # 구간 중앙이 더 깊게 침식
        depth = base * (1.0 + jag * rng.uniform(-1.0, 1.0))  # 들쭉날쭉(국소 랜덤 지터)
        depth = max(0.0, depth)
        worn[i] = points[i] - normals[i] * depth            # 안쪽 방향(-normal)으로 침식
        depths.append(depth)

    mean_depth_px = float(np.mean(depths)) if depths else 0.0
    defect = InjectedDefect(
        kind="마모",
        start_idx=int(idx[0]),
        end_idx=int(idx[-1]),
        magnitude_px=mean_depth_px,
        note=f"안쪽 평균 침식 깊이 약 {mean_depth_px * MM_PER_PX:.2f}mm (들쭉날쭉한 국소 침식)",
    )
    return worn, defect


@dataclass
class Arc:
    """끊김 주입 도중 다루는 하나의 연속 구간(호).

    points: 이 호를 구성하는 점 좌표
    orig_idx: 각 점이 "원본 폐곡선(생성 직후, 어떤 컷도 적용하기 전)"에서 가지던 인덱스.
              끊김을 여러 번 적용해 조각이 잘려나가도, 위치(start_frac) 해석은 항상
              이 원본 인덱스 기준으로 일관되게 이뤄지도록 하기 위한 것.
    is_closed: 이 호가 "아직 어떤 컷도 적용되지 않은, 원본 그대로의 폐곡선"인지 여부.
               폐곡선 랩어라운드(처음/끝 run 병합) 로직은 True일 때(=이 곡선에 대한 최초 컷)만
               적용해야 한다. 한 번이라도 컷이 적용되면 그 결과물은 항상 "열린 호"이므로
               이후로는 False로 유지된다.
    """
    points: np.ndarray
    orig_idx: np.ndarray
    is_closed: bool


def inject_break(arc: Arc, start_frac: float, span_frac: float, n_total: int) -> tuple[list[Arc], InjectedDefect]:
    """폐곡선(또는 그 일부인 열린 호) 일부 구간의 점을 아예 제거해 '끊김'(절단 불량)을 만든다.

    start_frac/span_frac은 항상 "원본 전체 폐곡선(n_total개 점)" 기준으로 해석한다 — 조각이
    이미 잘려나가 있어도 호출자가 의도한 위치가 그대로 유지되도록 하기 위함.

    폐곡선의 처음/끝 run을 하나로 잇는 랩어라운드 병합은, 이 호가 아직 컷이 한 번도 적용되지
    않은 원본 폐곡선(arc.is_closed == True)일 때만 수행한다. 이미 열린 호(부분 구간)에는
    로컬 인덱스 양끝이 우연히 0/len-1이더라도 실제로는 이어져 있지 않으므로 병합해서는 안 된다.

    반환값: 그릴 수 있는 연속 구간(run)들을 Arc 리스트로 반환 (끊긴 지점에서 분리된 열린 호들)
    """
    start = int(start_frac * n_total) % n_total
    span = max(4, int(span_frac * n_total))
    remove_idx = set((np.arange(start, start + span) % n_total).tolist())

    n_local = len(arc.points)
    keep_mask = np.array([oi not in remove_idx for oi in arc.orig_idx])
    # 로컬 인덱스를 순서대로 순회하며 연속 구간(run)으로 분리
    runs: list[list[int]] = []
    current: list[int] = []
    for i in range(n_local):
        if keep_mask[i]:
            current.append(i)
        else:
            if current:
                runs.append(current)
                current = []
    if current:
        runs.append(current)

    # 폐곡선 랩어라운드 병합: 이 호가 "아직 어떤 컷도 적용되지 않은 원본 폐곡선"일 때만 수행.
    # (이미 열린 호라면 로컬 인덱스 0/len-1은 실제 폐곡선상 인접점이 아니라 진짜 끝점이므로 병합 금지)
    if (
        arc.is_closed
        and len(runs) >= 2
        and runs[0][0] == 0
        and runs[-1][-1] == n_local - 1
        and (arc.orig_idx[0] not in remove_idx)
        and (arc.orig_idx[-1] not in remove_idx)
    ):
        runs[0] = runs[-1] + runs[0]
        runs.pop()

    new_arcs = [
        Arc(points=arc.points[r], orig_idx=arc.orig_idx[r], is_closed=False)
        for r in runs
    ]

    # 제거된 점들을 (원본 인덱스 순서 기준) 이었을 때의 누적 거리로 끊김 길이를 근사한다.
    removed_local = [i for i in range(n_local) if not keep_mask[i]]
    gap_len_px = 0.0
    for a, b in zip(removed_local[:-1], removed_local[1:]):
        gap_len_px += np.linalg.norm(arc.points[a] - arc.points[b])

    defect = InjectedDefect(
        kind="끊김",
        start_idx=start,
        end_idx=(start + span) % n_total,
        magnitude_px=float(gap_len_px),
        note=f"끊김 길이 약 {gap_len_px * MM_PER_PX:.2f}mm",
    )
    return new_arcs, defect


# ---------------------------------------------------------------------------
# 3. 렌더링 + 촬영 정렬오차 시뮬레이션
# ---------------------------------------------------------------------------

def render_polylines(polylines: list[np.ndarray], size=CANVAS_SIZE, thickness=LINE_THICKNESS) -> np.ndarray:
    img = np.zeros((size, size), dtype=np.uint8)
    for pts in polylines:
        if len(pts) < 2:
            continue
        cv2.polylines(img, [pts.astype(np.int32)], isClosed=False, color=255, thickness=thickness,
                       lineType=cv2.LINE_AA)
    return img


def render_closed(points: np.ndarray, size=CANVAS_SIZE, thickness=LINE_THICKNESS) -> np.ndarray:
    img = np.zeros((size, size), dtype=np.uint8)
    cv2.polylines(img, [points.astype(np.int32)], isClosed=True, color=255, thickness=thickness,
                   lineType=cv2.LINE_AA)
    return img


def apply_camera_misalignment(img: np.ndarray, angle_deg: float, tx: float, ty: float) -> np.ndarray:
    """촬영 시 목형이 지그에 완벽히 놓이지 않아 생기는 미세 회전/이동을 흉내낸다."""
    size = img.shape[0]
    center = (size / 2, size / 2)
    m = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    m[0, 2] += tx
    m[1, 2] += ty
    return cv2.warpAffine(img, m, (size, size), flags=cv2.INTER_LINEAR, borderValue=0)


# ---------------------------------------------------------------------------
# 4. 정합(Registration)
# ---------------------------------------------------------------------------

def register_actual_to_reference(reference_mask: np.ndarray, actual_mask: np.ndarray) -> tuple[np.ndarray, np.ndarray, bool]:
    """실물(actual) 이진 마스크를 기준 도면(reference) 좌표계로 정합한다.

    얇은 선 이미지는 ECC의 그래디언트 신호가 약해 수렴이 불안정하므로,
    두 마스크를 두껍게 팽창(dilate)한 버전으로 변환(회전+이동)을 추정한 뒤
    그 변환을 원본 얇은 실물 마스크에 적용한다 (spec.md 3.1 '정합' 원리를 단순화 구현).

    반환값: (정합된 actual 마스크, 2x3 변환행렬, 성공여부)
    """
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))
    ref_d = cv2.dilate(reference_mask, kernel).astype(np.float32) / 255.0
    act_d = cv2.dilate(actual_mask, kernel).astype(np.float32) / 255.0

    warp_matrix = np.eye(2, 3, dtype=np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-6)
    try:
        _, warp_matrix = cv2.findTransformECC(
            ref_d, act_d, warp_matrix, motionType=cv2.MOTION_EUCLIDEAN, criteria=criteria
        )
        success = True
    except cv2.error:
        success = False
        warp_matrix = np.eye(2, 3, dtype=np.float32)

    aligned = cv2.warpAffine(
        actual_mask, warp_matrix, (reference_mask.shape[1], reference_mask.shape[0]),
        flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP, borderValue=0,
    )
    _, aligned = cv2.threshold(aligned, 60, 255, cv2.THRESH_BINARY)
    return aligned, warp_matrix, success


def compute_registration_residual(reference_mask: np.ndarray, aligned_actual_mask: np.ndarray) -> float:
    """정합 후 두 마스크가 실제로 얼마나 겹치는지(정합 신뢰도)를 별도로 측정한다 (QA §2-B 가드레일).

    `cv2.findTransformECC`의 `converged=True`는 "수치적으로 어떤 지역해에 수렴했다"는 뜻일 뿐,
    그 해가 실제로 맞는 정렬인지는 보장하지 않는다(180° 근사대칭 형상에서는 반대편에 잘못
    정렬돼도 수렴은 성공으로 보고됨). 따라서 정합 결과물(정합된 실물 마스크)과 기준 도면
    마스크 사이의 "대칭 평균 최근접거리"(symmetric mean chamfer distance)를 전체 라인 픽셀에
    대해 직접 계산해, 정합이 실제로 두 형상을 겹쳐놓았는지를 독립적으로 검증한다.

    (참고: detect_defects()의 distanceTransform은 "결함 후보 개별 영역"의 국소적 최대 편차를
    보기 위한 것이고, 여기서는 "정합 전체 품질"을 보기 위해 전체 라인 픽셀의 평균 거리를 본다 —
    개별 결함 때문이 아니라 정합 자체가 전반적으로 어긋났는지를 구분해서 보기 위함.)

    반환값: 대칭 평균 최근접거리(px). 값이 작을수록 두 마스크가 잘 겹쳐진 것(정합 신뢰 가능),
    값이 크면 정합이 완전히 다른 위치/각도에 오수렴했음을 의미한다.
    """
    dist_to_actual = cv2.distanceTransform(255 - aligned_actual_mask, cv2.DIST_L2, 5)
    dist_to_reference = cv2.distanceTransform(255 - reference_mask, cv2.DIST_L2, 5)

    ref_pixels = reference_mask > 0
    act_pixels = aligned_actual_mask > 0
    if not ref_pixels.any() or not act_pixels.any():
        return float("inf")

    mean_ref_to_act = float(dist_to_actual[ref_pixels].mean())
    mean_act_to_ref = float(dist_to_reference[act_pixels].mean())
    return (mean_ref_to_act + mean_act_to_ref) / 2.0


# ---------------------------------------------------------------------------
# 5. 차분(diff) 기반 결함 검출
# ---------------------------------------------------------------------------

@dataclass
class DetectedDefect:
    kind: str
    bbox: tuple[int, int, int, int]     # x, y, w, h (px, reference 좌표계)
    centroid_px: tuple[float, float]
    max_deviation_mm: float
    arc_length_mm: float
    area_px: int
    note: str = ""            # Gap G5 후처리(복합 태깅) 등 부가 설명용
    mean_deviation_mm: float = 0.0   # 마모(G3): 침식 구간 평균 편차(등급화 근거). 휨/끊김은 0.
    wear_grade: str = ""             # 마모(G3): "정상"|"주의"|"교체". 마모 외 결함은 빈 문자열.


def detect_defects(reference_mask: np.ndarray, aligned_actual_mask: np.ndarray,
                    min_defect_arc_mm: float = MIN_DEFECT_ARC_MM) -> list[DetectedDefect]:
    """정합된 실물과 기준 도면을 비교해 '끊김'(도면엔 있으나 실물에 없음)과
    '휨'(실물이 도면 라인에서 허용치 이상 벗어남)을 각각 검출한다.

    min_defect_arc_mm: 과검출 억제용 최소 결함 길이 필터(QA §2-C). 기본값은 전역 상수
    MIN_DEFECT_ARC_MM이며, sweep_min_defect_arc_threshold()가 근거 스윕 테스트를 위해
    이 값을 바꿔가며 호출할 수 있도록 매개변수로 분리했다.
    """
    # 각 참조 라인 픽셀에서 가장 가까운 실물 라인 픽셀까지 거리
    dist_to_actual = cv2.distanceTransform(255 - aligned_actual_mask, cv2.DIST_L2, 5)
    # 각 실물 라인 픽셀에서 가장 가까운 참조 라인 픽셀까지 거리
    dist_to_reference = cv2.distanceTransform(255 - reference_mask, cv2.DIST_L2, 5)

    gap_mask = ((reference_mask > 0) & (dist_to_actual > DEFECT_TOL_PX)).astype(np.uint8) * 255
    bend_mask = ((aligned_actual_mask > 0) & (dist_to_reference > DEFECT_TOL_PX)).astype(np.uint8) * 255

    # 인접한 결함 픽셀들을 하나의 결함 영역으로 묶기 위한 팽창 후 연결요소 분석
    merge_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))

    defects: list[DetectedDefect] = []
    for kind, mask, ref_dist_field in (
        ("끊김", gap_mask, dist_to_actual),
        ("휨", bend_mask, dist_to_reference),
    ):
        merged = cv2.dilate(mask, merge_kernel)
        n_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(merged, connectivity=8)
        for label in range(1, n_labels):
            x, y, w, h, area = stats[label]
            component_pixels = mask[labels == label]
            if component_pixels.size == 0:
                continue
            raw_area = int((component_pixels > 0).sum())
            arc_length_px = max(w, h)  # 결함 영역의 긴 변을 대략적인 호 길이로 근사
            arc_length_mm = arc_length_px * MM_PER_PX
            if arc_length_mm < min_defect_arc_mm:
                continue  # 과검출 억제: 최소 길이 미만은 노이즈로 간주
            region_vals = ref_dist_field[y:y + h, x:x + w]
            max_dev_px = float(region_vals.max()) if region_vals.size else 0.0
            defects.append(DetectedDefect(
                kind=kind,
                bbox=(int(x), int(y), int(w), int(h)),
                centroid_px=(float(centroids[label][0]), float(centroids[label][1])),
                max_deviation_mm=round(max_dev_px * MM_PER_PX, 2),
                arc_length_mm=round(arc_length_mm, 2),
                area_px=raw_area,
            ))
    return defects


def classify_wear_grade(mean_deviation_mm: float) -> str:
    """마모(Gap G3) 등급화: 침식 구간의 '평균 편차(mm)'를 정상/주의/교체 3등급으로 분류한다.

    마모는 끊김/휨 같은 '단일 사건'이 아니라 칼날 엣지의 누적 침식이므로, 결함 개별 건수가 아니라
    침식 정도(평균 편차)를 연속량으로 보고 등급화하는 것이 spec.md 4절("마모는 회귀 또는 등급 라벨링
    (정상/주의/교체)으로 이진 분류 한계 보완") 취지에 부합한다.

    등급 경계값(WEAR_GRADE_CAUTION_MM=0.3mm, WEAR_GRADE_REPLACE_MM=0.8mm)은 **가정값이며 실제
    목형 공차 스펙 확인이 필요**하다(전역 상수 정의부 주석 참고).
    """
    if mean_deviation_mm < WEAR_GRADE_CAUTION_MM:
        return "정상"
    if mean_deviation_mm < WEAR_GRADE_REPLACE_MM:
        return "주의"
    return "교체"


def detect_wear(reference_mask: np.ndarray, aligned_actual_mask: np.ndarray,
                 min_wear_arc_mm: float = MIN_WEAR_ARC_MM) -> list[DetectedDefect]:
    """정합된 실물과 기준 도면을 비교해 '마모'(국소 미세 침식) 구간을 검출하고 등급화한다(Gap G3).

    기존 detect_defects()의 distanceTransform(실물→기준 최근접거리)을 그대로 재사용하되, 다음이 다르다.
      - 대역(band) 제한: 편차가 WEAR_NOISE_FLOOR_PX 초과 ~ WEAR_CEIL_PX 이하인 픽셀만 마모 후보로 본다.
        바닥값(0.5mm)은 AA 렌더링/정합 잔차 노이즈(정상 케이스 실측 최대 ~0.44mm)를 걷어내기 위한 것이고,
        천장값(3.0mm) 초과는 단일 사건(휨/끊김)으로 간주해 제외한다.
      - 단일 사건 배제: WEAR_CEIL_PX를 초과하는 강한 편차 픽셀(=휨/끊김 코어)을 크게 팽창시킨 영역은
        마모 후보에서 제외한다(휨의 램프 어깨가 마모로 오검출되는 것을 억제). 그래도 남는 겹침은
        run_scenario에서 휨/끊김 bbox와 겹치는 마모를 사후 제거해 최종 정리한다.
      - 등급화: 개별 건수가 아니라 침식 구간의 '평균 편차(mm)'를 계산해 classify_wear_grade로 등급화한다.
        등급이 '정상'인(=평균 편차가 경계 미만인) 구간은 결함으로 보고하지 않는다.
    """
    dist_to_reference = cv2.distanceTransform(255 - reference_mask, cv2.DIST_L2, 5)
    actual_pixels = aligned_actual_mask > 0
    deviation = np.where(actual_pixels, dist_to_reference, 0.0)

    # 단일 사건(휨/끊김) 코어를 크게 팽창시켜 마모 후보에서 배제(램프 어깨 오검출 억제)
    strong = ((aligned_actual_mask > 0) & (dist_to_reference > WEAR_CEIL_PX)).astype(np.uint8) * 255
    exclusion = cv2.dilate(strong, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (41, 41)))

    band = (
        (aligned_actual_mask > 0)
        & (dist_to_reference > WEAR_NOISE_FLOOR_PX)
        & (dist_to_reference <= WEAR_CEIL_PX)
        & (exclusion == 0)
    ).astype(np.uint8) * 255

    merge_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    merged = cv2.dilate(band, merge_kernel)
    n_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(merged, connectivity=8)

    defects: list[DetectedDefect] = []
    for label in range(1, n_labels):
        x, y, w, h, area = stats[label]
        arc_length_px = max(w, h)
        arc_length_mm = arc_length_px * MM_PER_PX
        if arc_length_mm < min_wear_arc_mm:
            continue
        component_band = (labels == label) & (band > 0)
        vals = deviation[component_band]
        if vals.size == 0:
            continue
        mean_dev_mm = float(vals.mean()) * MM_PER_PX
        max_dev_mm = float(vals.max()) * MM_PER_PX
        grade = classify_wear_grade(mean_dev_mm)
        if grade == "정상":
            continue  # 평균 편차가 등급 경계 미만이면 결함으로 보고하지 않음
        defects.append(DetectedDefect(
            kind="마모",
            bbox=(int(x), int(y), int(w), int(h)),
            centroid_px=(float(centroids[label][0]), float(centroids[label][1])),
            max_deviation_mm=round(max_dev_mm, 2),
            arc_length_mm=round(arc_length_mm, 2),
            area_px=int((component_band).sum()),
            mean_deviation_mm=round(mean_dev_mm, 2),
            wear_grade=grade,
            note=f"침식 구간 평균 편차 {mean_dev_mm:.2f}mm -> 등급 '{grade}' "
                 f"(경계 가정값: 정상<{WEAR_GRADE_CAUTION_MM}, 주의<{WEAR_GRADE_REPLACE_MM}, 교체≥{WEAR_GRADE_REPLACE_MM}mm)",
        ))
    return defects


def classify_position_error(estimated_transform: np.ndarray,
                             tol_mm: float = POSITION_ERROR_TOL_MM) -> dict:
    """위치오차(Gap G4) 판정: 정합(ECC)이 흡수한 변환량(이동량)을 사후 검사해 판정한다.

    설계상 근본 이슈: 정합(Registration)은 촬영 정렬오차를 제거하려고 실물을 기준 도면에 맞춰 이동/회전
    시키므로, "목형이 지그에 실제로 잘못 놓인 것(위치오차)"과 "단순 촬영 정렬오차"를 diff 단계에서는
    구분할 수 없다(둘 다 정합이 흡수해버림). 대신 정합이 흡수한 이동량 자체를 검사한다 — 정상 촬영
    정렬오차는 '작은 이동(수 px)'이라는 전제가 있으므로, 추정 이동량이 허용범위(tol_mm)를 넘으면
    "이 정도로 어긋난 채 실물이 지그에 놓였다면 그 자체가 불량"이라고 판정한다.

    한계(README에 상술): 이 방법으로도 "큰 촬영 정렬오차"와 "진짜 위치오차"를 완벽히 구분하지는
    못한다(둘 다 큰 이동량으로 나타남). 또 정합/팽창 기하로 인한 추정 편향(무오차에서도 ~3mm)이 있어
    임계치 마진이 크지 않다.

    반환값: 추정 이동량(mm)·회전각(deg)·위치오차 여부(bool)·허용치를 담은 dict.
    """
    tx = float(estimated_transform[0, 2])
    ty = float(estimated_transform[1, 2])
    shift_px = math.hypot(tx, ty)
    shift_mm = shift_px * MM_PER_PX
    angle_deg = math.degrees(math.atan2(float(estimated_transform[1, 0]), float(estimated_transform[0, 0])))
    is_position_error = shift_mm > tol_mm
    return {
        "estimated_shift_px": round(shift_px, 2),
        "estimated_shift_mm": round(shift_mm, 2),
        "estimated_angle_deg": round(angle_deg, 2),
        "tol_mm": tol_mm,
        "is_position_error": is_position_error,
    }


def _inject_calibrated_gap(reference_points: np.ndarray, start_frac: float,
                            target_gap_px: float) -> tuple[np.ndarray, float]:
    """스윕 테스트 전용: `inject_break()`와 달리 "최소 4점 제거" 하한을 두지 않고,
    목표 물리적 길이(target_gap_px)에 최대한 가깝게 점을 제거해 정밀한 끊김 길이를 만든다.

    `inject_break()`가 실제 운영 코드에서 `max(4, ...)` 하한을 두는 이유는 데모 취지상
    타당하지만(너무 짧은 인위적 끊김은 렌더링 두께에 묻혀 무의미), 그 하한 때문에 0.5~1.5mm대
    끊김이 전부 동일한(~1.8mm) 실제 길이로 뭉개져 임계값 스윕이 무의미해진다. 스윕은 필터
    자체의 경계 거동을 보려는 목적이므로, 이 헬퍼는 하한 없이 목표 길이에 맞춰 정밀하게
    제거한다.

    반환값: (제거 후 남은 점들을 원 둘레 순서대로 재배열한 열린 호 배열, 실제 제거된 길이(px))
    """
    n = len(reference_points)
    start = int(start_frac * n) % n
    removed = [start]
    cum = 0.0
    idx = start
    while cum < target_gap_px and len(removed) < n:
        nxt = (idx + 1) % n
        cum += float(np.linalg.norm(reference_points[nxt] - reference_points[idx]))
        removed.append(nxt)
        idx = nxt
    last_removed = idx
    # 제거된 구간 바로 다음 점부터 시작해, start 직전 점까지 원 둘레 순서대로 걸어가며
    # 남은 점들을 모은다. 이렇게 해야 배열이 실제로 연결된 하나의 열린 호가 되어
    # render_polylines()가 끊긴 자리를 직선으로 잘못 잇는(bridging) 일이 없다.
    ordered: list[int] = []
    i = (last_removed + 1) % n
    while i != start:
        ordered.append(i)
        i = (i + 1) % n
    return reference_points[ordered], cum


def sweep_min_defect_arc_threshold(
    threshold_candidates_mm: tuple[float, ...] = (0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 10.0),
) -> tuple[list[dict], list[float]]:
    """QA §2-C 근거 보강: 최소 결함 길이 필터(MIN_DEFECT_ARC_MM) 임계값 후보별 성능 스윕.

    목적: `MIN_DEFECT_ARC_MM = 2.0mm`가 "근거 없는 가정값"으로 남지 않도록, 후보 임계값들
    (1.0mm~3.0mm)에서 두 가지를 실측한다.
      1. 과검출(false positive): 결함이 전혀 없는 정상 케이스(촬영 정렬오차만 존재, case0과
         동일 조건)에서 임계값을 낮출수록 정합/렌더링 잔여 노이즈가 결함으로 새로 검출되는지.
      2. 미검출(false negative): 다양한 길이(0.5mm~4.0mm)의 인위적 끊김을 주입했을 때, 각
         임계값에서 실제로 검출되는지.
    이 결과는 값 자체를 바꾸기 위함이 아니라(값은 2.0mm로 유지), "왜 2.0mm를 선택했는지"에
    대한 실측 트레이드오프 근거를 README에 남기기 위한 것이다.
    """
    reference_points = generate_reference_contour()
    reference_mask = render_closed(reference_points)
    n_total = len(reference_points)
    contour_length_px = float(
        np.sum(np.linalg.norm(np.roll(reference_points, -1, axis=0) - reference_points, axis=1))
    )

    # 과검출 측정: 결함 없는 정상 케이스(case0과 동일한 촬영 정렬오차 조건)
    normal_misaligned = apply_camera_misalignment(reference_mask, angle_deg=1.4, tx=6, ty=-4)
    aligned_normal, _, _ = register_actual_to_reference(reference_mask, normal_misaligned)

    # 미검출 측정: 목표 끊김 길이(mm)별로 실제 끊김을 주입해 정합까지 미리 계산해 둔다.
    # (하한 없는 _inject_calibrated_gap()을 사용해 0.5mm 미만의 미세한 목표값도 뭉개지지 않게 한다.)
    target_gap_mms = [0.1, 0.3, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0]
    gap_cases: list[tuple[float, float, np.ndarray]] = []
    for nominal_gap_mm in target_gap_mms:
        target_gap_px = nominal_gap_mm / MM_PER_PX
        open_points, actual_gap_px = _inject_calibrated_gap(reference_points, start_frac=0.5,
                                                              target_gap_px=target_gap_px)
        actual_source = render_polylines([open_points])
        actual_misaligned = apply_camera_misalignment(actual_source, angle_deg=1.4, tx=6, ty=-4)
        aligned_actual, _, _ = register_actual_to_reference(reference_mask, actual_misaligned)
        actual_gap_mm = actual_gap_px * MM_PER_PX  # 이산화로 인해 목표값과 약간 다를 수 있음
        gap_cases.append((nominal_gap_mm, actual_gap_mm, aligned_actual))

    results: list[dict] = []
    for thr_mm in threshold_candidates_mm:
        fp_count = len(detect_defects(reference_mask, aligned_normal, min_defect_arc_mm=thr_mm))

        detected_by_gap: dict[float, dict] = {}
        for nominal_gap_mm, actual_gap_mm, aligned_actual in gap_cases:
            detected = detect_defects(reference_mask, aligned_actual, min_defect_arc_mm=thr_mm)
            found = any(d.kind == "끊김" for d in detected)
            detected_by_gap[nominal_gap_mm] = {"actual_gap_mm": round(actual_gap_mm, 2), "detected": found}

        results.append({
            "threshold_mm": thr_mm,
            "false_positive_count_on_normal": fp_count,
            "detected_by_target_gap_mm": detected_by_gap,
        })
    return results, target_gap_mms


def resolve_bend_break_overlap(defects: list[DetectedDefect]) -> list[DetectedDefect]:
    """Gap 목록 G5 대응: 같은 위치에서 휨과 끊김이 동시 검출되면 유형을 정리한다.

    README "알아둘 점"에 기록된 관찰(휨 결함이 부수적으로 같은 위치에서 끊김으로도 동시
    검출되는 경향)은 미검출 방지에는 유리하지만, 결함 유형 통계·재검 우선순위 판단에는
    혼선을 준다. 두 결함의 bbox가 실제로 겹치는 경우(=물리적으로 같은 위치)에 한해:
      - 편차(max_deviation_mm)가 더 큰 쪽을 대표 결함으로 삼고
      - 그 kind를 "복합(휨+끊김 의심)"으로 명시적으로 재태깅하며
      - note에 원래 두 후보의 수치를 함께 남긴다.
    검출 결과 자체(결함 존재 여부)는 삭제하지 않는다 — spec.md 6절 "미검출 0" 목표를
    해치지 않기 위해 유형 표기만 정리하는 것이 목적이다. bbox가 겹치지 않는 휨/끊김
    (예: case3처럼 서로 다른 위치에서 각각 발생한 진짜 별개의 결함)은 그대로 둔다.
    """

    def bbox_overlaps(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        return not (ax + aw < bx or bx + bw < ax or ay + ah < by or by + bh < ay)

    bends = [d for d in defects if d.kind == "휨"]
    breaks = [d for d in defects if d.kind == "끊김"]
    others = [d for d in defects if d.kind not in ("휨", "끊김")]

    consumed_break_indices: set[int] = set()
    resolved: list[DetectedDefect] = []
    for bend in bends:
        overlapped = [
            (i, brk) for i, brk in enumerate(breaks)
            if i not in consumed_break_indices and bbox_overlaps(bend.bbox, brk.bbox)
        ]
        if not overlapped:
            resolved.append(bend)
            continue
        i, brk = max(overlapped, key=lambda pair: pair[1].max_deviation_mm)
        consumed_break_indices.add(i)
        if bend.max_deviation_mm >= brk.max_deviation_mm:
            winner, loser = bend, brk
        else:
            winner, loser = brk, bend
        winner.kind = "복합(휨+끊김 의심)"
        winner.note = (
            f"같은 위치에서 휨(편차 {bend.max_deviation_mm}mm)과 끊김(편차 {brk.max_deviation_mm}mm)이 "
            f"동시 검출되어 편차가 더 큰 쪽({'휨' if winner is bend else '끊김'})을 대표값으로 병합함 (Gap G5)"
        )
        resolved.append(winner)

    for i, brk in enumerate(breaks):
        if i not in consumed_break_indices:
            resolved.append(brk)

    resolved.extend(others)
    return resolved


# ---------------------------------------------------------------------------
# 6. 시각화 (spec.md 7절 "설명 가능성": 비전문가도 이해 가능한 근거 시각화)
# ---------------------------------------------------------------------------

def visualize(reference_mask: np.ndarray, aligned_actual_mask: np.ndarray,
              defects: list[DetectedDefect], title: str,
              registration_reliable: bool = True, registration_residual_mm: float = 0.0) -> np.ndarray:
    canvas = np.zeros((*reference_mask.shape, 3), dtype=np.uint8)
    canvas[reference_mask > 0] = (90, 90, 90)      # 기준 도면: 회색
    canvas[aligned_actual_mask > 0] = (0, 200, 0)  # 실물(정합후): 녹색
    overlap = (reference_mask > 0) & (aligned_actual_mask > 0)
    canvas[overlap] = (200, 160, 0)                # 겹치는 부분(정상 일치): 청록/황색 계열

    # 마모=자홍(핑크), 위치오차=노랑(BGR) — UI 설계 근거(마모는 등급 게이지, 위치오차는 노란색 mm 콜아웃).
    color_map = {"끊김": (0, 0, 255), "휨": (0, 140, 255), "복합(휨+끊김 의심)": (200, 0, 200),
                 "마모": (200, 0, 255), "위치오차": (0, 220, 255)}
    for d in defects:
        x, y, w, h = d.bbox
        pad = 12
        color = color_map.get(d.kind, (255, 0, 255))
        cv2.rectangle(canvas, (x - pad, y - pad), (x + w + pad, y + h + pad), color, 3)
        if d.kind == "마모":
            # UI 4.3 게이지(등급) 위젯 취지: mm 오차보다 '등급'을 앞세워 표기(평균 편차 병기)
            label = f"마모 [{d.wear_grade}] (평균 {d.mean_deviation_mm}mm)"
        elif d.kind == "위치오차":
            label = d.note  # "위치오차: 추정 이동량 ..mm" (노란색 mm 콜아웃)
        else:
            label = f"{d.kind} ({d.max_deviation_mm}mm / {d.arc_length_mm}mm)"
        text_y = max(0, y - pad - 26)
        canvas = put_korean_text(canvas, label, (max(0, x - pad), text_y), color, size=18)

    canvas = put_korean_text(canvas, title, (20, 12), (255, 255, 255), size=22)

    # QA §2-B 가드레일: 정합이 converged=True를 반환했더라도 잔차 지표상 신뢰할 수 없으면
    # (대칭 오수렴 의심), 사람이 눈에 띄게 알 수 있도록 경고 배너를 시각화에도 노출한다.
    if not registration_reliable:
        cv2.rectangle(canvas, (0, 40), (canvas.shape[1], 78), (0, 0, 200), -1)
        warn_text = (f"[경고] 정합 신뢰 불가 (registration_reliable=False, 잔차 "
                     f"{registration_residual_mm:.1f}mm > 허용 {REGISTRATION_RESIDUAL_TOL_MM:.1f}mm) "
                     f"— 대칭 오수렴 의심, 재검 필요")
        canvas = put_korean_text(canvas, warn_text, (20, 46), (255, 255, 255), size=18)

    legend_y = canvas.shape[0] - 148
    legend = [
        ("기준 도면", (90, 90, 90)),
        ("실물(정합 후)", (0, 200, 0)),
        ("끊김 결함", (0, 0, 255)),
        ("휨 결함", (0, 140, 255)),
        ("마모(등급)", (200, 0, 255)),
        ("위치오차(mm)", (0, 220, 255)),
    ]
    for i, (text, color) in enumerate(legend):
        y = legend_y + i * 24
        cv2.rectangle(canvas, (20, y - 12), (40, y + 4), color, -1)
        canvas = put_korean_text(canvas, text, (48, y - 12), (255, 255, 255), size=16)
    return canvas


# ---------------------------------------------------------------------------
# 7. 시나리오 실행
# ---------------------------------------------------------------------------

@dataclass
class Scenario:
    name: str
    title: str
    bend: dict | None = None     # {"start_frac":.., "span_frac":.., "magnitude_px":..} (단일 휨, 하위호환용)
    bends: list[dict] = field(default_factory=list)  # 휨 2개 이상 동시 발생 시 사용
    breaks: list[dict] = field(default_factory=list)
    wears: list[dict] = field(default_factory=list)  # 마모(G3): {"start_frac":.., "span_frac":.., "depth_px":..}
    misalign: dict = field(default_factory=lambda: {"angle_deg": 1.4, "tx": 6, "ty": -4})


def run_scenario(scenario: Scenario, rng: np.random.Generator) -> dict:
    reference_points = generate_reference_contour()
    reference_mask = render_closed(reference_points)
    n_total = len(reference_points)  # 끊김 위치(start_frac) 해석의 항상-고정된 기준 길이

    ground_truth: list[InjectedDefect] = []
    working_points = reference_points.copy()

    # 단일 휨(bend)과 다중 휨(bends)을 모두 지원: 점 개수를 바꾸지 않으므로 순서대로 누적 적용 가능.
    all_bends = ([scenario.bend] if scenario.bend else []) + list(scenario.bends)
    for bend_spec in all_bends:
        working_points, gt = inject_bend(working_points, rng=rng, **bend_spec)
        ground_truth.append(gt)

    # 마모(Gap G3) 주입 — 휨과 마찬가지로 점 개수를 바꾸지 않으므로 끊김 적용 전에 순서대로 누적 적용.
    for wear_spec in scenario.wears:
        working_points, gt = inject_wear(working_points, rng=rng, **wear_spec)
        ground_truth.append(gt)

    # 위치오차(Gap G4) ground truth — "실물이 지그에 실제로 얼마나 어긋나 놓였는가"는 주입한
    # 촬영 정렬오차(misalign)의 이동량으로 정의한다. 그 이동량이 허용범위를 넘으면 위치오차를 주입한 것.
    injected_shift_mm = math.hypot(scenario.misalign.get("tx", 0.0),
                                    scenario.misalign.get("ty", 0.0)) * MM_PER_PX
    if injected_shift_mm > POSITION_ERROR_TOL_MM:
        ground_truth.append(InjectedDefect(
            kind="위치오차", start_idx=0, end_idx=0, magnitude_px=injected_shift_mm / MM_PER_PX,
            note=f"지그 안착 이동량 약 {injected_shift_mm:.2f}mm (허용 {POSITION_ERROR_TOL_MM}mm 초과)",
        ))

    # 시작은 "아직 컷이 적용되지 않은" 원본 폐곡선 하나 (휨은 점 개수를 바꾸지 않으므로 orig_idx는 그대로 0..n_total-1)
    polylines = [Arc(points=working_points, orig_idx=np.arange(n_total), is_closed=True)]
    for b in scenario.breaks:
        # 가장 긴 조각에 대해서만 끊김 적용(데모 단순화)
        target_idx = int(np.argmax([len(p.points) for p in polylines]))
        target = polylines.pop(target_idx)
        new_arcs, gt = inject_break(target, n_total=n_total, **b)
        polylines.extend(new_arcs)
        ground_truth.append(gt)

    if not scenario.breaks:
        actual_mask_unaligned_source = render_closed(working_points)
    else:
        actual_mask_unaligned_source = render_polylines([a.points for a in polylines])

    actual_mask_misaligned = apply_camera_misalignment(actual_mask_unaligned_source, **scenario.misalign)

    aligned_actual_mask, warp_matrix, reg_ok = register_actual_to_reference(reference_mask, actual_mask_misaligned)

    # QA §2-B 가드레일: ECC의 converged=True만으로는 정합 품질을 신뢰할 수 없으므로
    # (대칭 형상에서 대각도 오정렬 시 잘못된 지점에 오수렴해도 converged=True가 나옴),
    # 독립적인 잔차 지표(대칭 평균 최근접거리)를 별도로 계산해 정합 신뢰도를 판단한다.
    registration_residual_px = compute_registration_residual(reference_mask, aligned_actual_mask)
    registration_residual_mm = registration_residual_px * MM_PER_PX
    registration_reliable = bool(reg_ok) and registration_residual_px <= REGISTRATION_RESIDUAL_TOL_PX

    detected = detect_defects(reference_mask, aligned_actual_mask)
    # Gap G5 후처리: 같은 위치에서 휨/끊김이 동시 검출되면 유형을 "복합(휨+끊김 의심)"으로 정리한다.
    detected = resolve_bend_break_overlap(detected)

    # 마모(Gap G3) 검출 — 미세·저변위 침식 구간을 평균 편차로 등급화해 kind="마모"로 검출한다.
    wear_detected = detect_wear(reference_mask, aligned_actual_mask)
    # 단일 사건(휨/끊김/복합)과 bbox가 겹치는 마모 후보는 그 단일 사건의 램프 어깨가 마모로 새어들어온
    # 것이므로 제거(재귀속)한다. 심한 마모(교체 등급)가 휨과 형상적으로 겹치는 한계는 README에 명시.
    def _bbox_overlaps(a, b) -> bool:
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        return not (ax + aw < bx or bx + bw < ax or ay + ah < by or by + bh < ay)
    single_event_bboxes = [d.bbox for d in detected if d.kind in ("휨", "끊김", "복합(휨+끊김 의심)")]
    wear_detected = [
        w for w in wear_detected
        if not any(_bbox_overlaps(w.bbox, sb) for sb in single_event_bboxes)
    ]
    detected = detected + wear_detected

    # 위치오차(Gap G4) 검출 — 정합이 흡수한 ECC 추정 이동량을 사후 검사해 판정한다.
    position = classify_position_error(warp_matrix)
    if position["is_position_error"]:
        rx, ry, rw, rh = cv2.boundingRect((reference_mask > 0).astype(np.uint8))
        detected.append(DetectedDefect(
            kind="위치오차",
            bbox=(int(rx), int(ry), int(rw), int(rh)),
            centroid_px=(float(rx + rw / 2), float(ry + rh / 2)),
            max_deviation_mm=position["estimated_shift_mm"],
            arc_length_mm=0.0,
            area_px=0,
            note=(f"위치오차: 정합이 흡수한 추정 이동량 {position['estimated_shift_mm']}mm "
                  f"(허용 {position['tol_mm']}mm 초과, 추정 회전 {position['estimated_angle_deg']}°)"),
        ))

    vis = visualize(reference_mask, aligned_actual_mask, detected, title=scenario.title,
                     registration_reliable=registration_reliable,
                     registration_residual_mm=registration_residual_mm)

    os.makedirs(OUT_DIR, exist_ok=True)
    img_path = os.path.join(OUT_DIR, f"{scenario.name}.png")
    # 주의: 이 프로젝트 경로에 한글이 포함되어 있어 cv2.imwrite()는 실패(무음 실패)할 수 있다.
    # imencode + ndarray.tofile 조합으로 유니코드 경로에서도 안전하게 저장한다.
    ok, buf = cv2.imencode(".png", vis)
    if not ok:
        raise RuntimeError(f"PNG 인코딩 실패: {scenario.name}")
    buf.tofile(img_path)

    report = {
        "scenario": scenario.name,
        "title": scenario.title,
        "registration_converged": bool(reg_ok),
        # QA §2-B 가드레일: ECC의 converged=True와 별개로, 정합된 두 마스크가 실제로 겹쳤는지를
        # 나타내는 독립 지표. registration_reliable=False면 "정합이 converged=True를 반환했더라도
        # 대칭 오수렴 등으로 실제로는 신뢰할 수 없으니 사람이 재검해야 한다"는 뜻이며, 이 경우에도
        # 아래 detected_defects는 삭제/억제하지 않고 그대로 보고한다(재검용 근거 보존).
        "registration_residual_px": round(registration_residual_px, 2),
        "registration_residual_mm": round(registration_residual_mm, 2),
        "registration_residual_tol_mm": REGISTRATION_RESIDUAL_TOL_MM,
        "registration_reliable": registration_reliable,
        "warp_matrix": warp_matrix.tolist(),
        "assumptions": {
            "mm_per_px": MM_PER_PX,
            "defect_tolerance_mm": DEFECT_TOL_MM,
            "min_defect_arc_mm": MIN_DEFECT_ARC_MM,
            "registration_residual_tol_mm": REGISTRATION_RESIDUAL_TOL_MM,
            # 마모(G3)·위치오차(G4) 등급/판정 경계값(모두 가정값, 실제 목형 공차 스펙 확인 필요)
            "wear_grade_caution_mm": WEAR_GRADE_CAUTION_MM,
            "wear_grade_replace_mm": WEAR_GRADE_REPLACE_MM,
            "min_wear_arc_mm": MIN_WEAR_ARC_MM,
            "position_error_tol_mm": POSITION_ERROR_TOL_MM,
        },
        # 위치오차(G4): 정합이 흡수한 ECC 추정 이동량 사후 검사 결과(판정 근거)
        "position_error": position,
        "ground_truth_injected": [gt.__dict__ for gt in ground_truth],
        "detected_defects": [d.__dict__ for d in detected],
        # Gap G5 후처리로 병합된 "복합(휨+끊김 의심)" 태그는 원래 휨/끊김 양쪽 다중결함 개수
        # 검증에 계속 반영되어야 하므로(예: case6처럼 휨 2개가 모두 복합으로 재태깅되는 경우),
        # 복합 태그도 두 kind 모두의 카운트에 포함시킨다.
        "detection_count_by_kind": {
            k: sum(1 for d in detected if d.kind == k or d.kind.startswith("복합")) for k in ("휨", "끊김")
        },
        "polyline_count": len(polylines),  # 렌더링에 쓰인 분리된 열린 호(=연결요소가 되어야 할) 개수
        "image": os.path.basename(img_path),
    }
    report_path = os.path.join(OUT_DIR, f"{scenario.name}.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return report


def main():
    rng = np.random.default_rng(42)

    scenarios = [
        Scenario(
            name="case0_normal",
            title="Case 0: 정상 목형 (결함 없음, 촬영 정렬오차만 존재)",
            bend=None,
            breaks=[],
        ),
        Scenario(
            name="case1_bend_only",
            title="Case 1: 휨 결함 단독",
            bend={"start_frac": 0.06, "span_frac": 0.10, "magnitude_px": 34},
            breaks=[],
        ),
        Scenario(
            name="case2_break_only",
            title="Case 2: 끊김 결함 단독",
            bend=None,
            breaks=[{"start_frac": 0.55, "span_frac": 0.05}],
        ),
        Scenario(
            name="case3_bend_and_break",
            title="Case 3: 휨 + 끊김 복합 결함",
            bend={"start_frac": 0.30, "span_frac": 0.09, "magnitude_px": 26},
            breaks=[{"start_frac": 0.72, "span_frac": 0.04}],
        ),
        # QA 리포트 §2-A 버그 재현/회귀 테스트: 동일 폐곡선에 끊김 3개를 동시에 주입.
        # 수정 전에는 랩어라운드 병합 버그로 인해 열린 호들이 다시 이어붙여져(bridging)
        # len(polylines)가 1로 유지되고 검출도 1건뿐이었다. 수정 후에는 3개 모두 분리된
        # 열린 호(polyline_count == 3)로 남아야 하고, 3건 모두 검출되어야 한다.
        Scenario(
            name="case4_multi_break",
            title="Case 4: 끊김 결함 3개 동시 발생 (QA §2-A 회귀 테스트)",
            bend=None,
            breaks=[
                {"start_frac": 0.10, "span_frac": 0.03},
                {"start_frac": 0.40, "span_frac": 0.03},
                {"start_frac": 0.75, "span_frac": 0.03},
            ],
        ),
        # 보너스 검증: 끊김 2개 + 휨 1개 조합에서도 각각 정확한 위치에 주입/검출되는지 확인.
        Scenario(
            name="case5_multi_break_and_bend",
            title="Case 5: 끊김 2개 + 휨 1개 복합 결함",
            bend={"start_frac": 0.55, "span_frac": 0.08, "magnitude_px": 30},
            breaks=[
                {"start_frac": 0.05, "span_frac": 0.03},
                {"start_frac": 0.85, "span_frac": 0.03},
            ],
        ),
        # 보너스 검증: 휨 2개가 동시에 발생해도 각각 독립적으로 검출되는지 확인.
        Scenario(
            name="case6_multi_bend",
            title="Case 6: 휨 결함 2개 동시 발생",
            bend=None,
            breaks=[],
            bends=[
                {"start_frac": 0.15, "span_frac": 0.08, "magnitude_px": 32},
                {"start_frac": 0.62, "span_frac": 0.08, "magnitude_px": 28},
            ],
        ),
        # Gap G3 회귀 테스트: 마모 단독. 미세·들쭉날쭉 침식(depth 3px)을 주입 → 평균 편차 등급화("주의") 검출.
        # depth_px는 휨(magnitude_px 26~34)의 1/10 수준으로 두어, 휨/끊김 단일사건 검출을 건드리지 않는 저변위.
        Scenario(
            name="case7_wear_only",
            title="Case 7: 마모(국소 미세 침식) 단독 — 등급화 검출(Gap G3)",
            bend=None,
            breaks=[],
            wears=[{"start_frac": 0.30, "span_frac": 0.12, "depth_px": 3.0}],
        ),
        # Gap G4 회귀 테스트: 위치오차 단독. 형상 결함은 없고, 목형이 지그에 크게 어긋나 놓인 상황을
        # 큰 이동량(tx=40, ty=-20 → 약 8.9mm > 허용 5mm)으로 흉내낸다. 정합이 흡수한 추정 이동량을
        # 사후 검사해 "위치오차"로 판정한다(정합 자체는 여전히 성공/신뢰 가능 상태여야 함).
        Scenario(
            name="case8_position_error_only",
            title="Case 8: 위치오차(지그 안착 오차) 단독 — 정합 흡수량 사후검사(Gap G4)",
            bend=None,
            breaks=[],
            misalign={"angle_deg": 1.4, "tx": 40, "ty": -20},
        ),
        # 복합 회귀 테스트: 마모 + 위치오차 동시. 두 신규 클래스가 서로 간섭 없이 함께 검출되는지 확인.
        Scenario(
            name="case9_wear_and_position",
            title="Case 9: 마모 + 위치오차 복합(Gap G3+G4)",
            bend=None,
            breaks=[],
            wears=[{"start_frac": 0.30, "span_frac": 0.12, "depth_px": 3.0}],
            misalign={"angle_deg": 1.4, "tx": 40, "ty": -20},
        ),
    ]

    all_reports = []
    print("=" * 70)
    print("과제② 목형 칼날검사 — 정합+diff 파이프라인 프로토타입 실행")
    print(f"가정: 1px = {MM_PER_PX}mm, 결함 판정 허용오차 = {DEFECT_TOL_MM}mm({DEFECT_TOL_PX:.1f}px), "
          f"최소 결함 길이 = {MIN_DEFECT_ARC_MM}mm")
    print("=" * 70)

    for sc in scenarios:
        report = run_scenario(sc, rng)
        all_reports.append(report)
        print(f"\n[{report['scenario']}] {report['title']}")
        print(f"  정합 수렴 여부(ECC): {report['registration_converged']}")
        reliability_tag = "OK" if report["registration_reliable"] else "*** 신뢰 불가(재검 필요) ***"
        print(f"  정합 신뢰도(잔차 기반, QA §2-B 가드레일): {reliability_tag} "
              f"(잔차={report['registration_residual_mm']}mm, 허용={report['registration_residual_tol_mm']}mm)")
        print(f"  주입한 결함(ground truth): "
              + (", ".join(f"{g['kind']}({g['note']})" for g in report['ground_truth_injected']) or "없음"))
        def _fmt_detected(d: dict) -> str:
            if d["kind"] == "마모":
                return f"마모[{d['wear_grade']}] @bbox={d['bbox']} 평균편차={d['mean_deviation_mm']}mm 길이={d['arc_length_mm']}mm"
            if d["kind"] == "위치오차":
                return f"위치오차 추정이동량={d['max_deviation_mm']}mm (허용 {POSITION_ERROR_TOL_MM}mm 초과)"
            return f"{d['kind']} @bbox={d['bbox']} 편차={d['max_deviation_mm']}mm 길이={d['arc_length_mm']}mm"
        print(f"  검출된 결함: "
              + (", ".join(_fmt_detected(d) for d in report['detected_defects']) or "없음"))
        pe = report["position_error"]
        print(f"  위치오차 사후검사(G4): 추정 이동량={pe['estimated_shift_mm']}mm "
              f"(허용={pe['tol_mm']}mm) -> {'위치오차' if pe['is_position_error'] else '정상범위'}")
        print(f"  분리된 열린 호 개수(polyline_count): {report['polyline_count']}")
        print(f"  결과 이미지: output/{report['image']}")

    summary_path = os.path.join(OUT_DIR, "summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(all_reports, f, ensure_ascii=False, indent=2)

    # ---- 검증(자체 회귀 테스트에 준하는 요약): 주입한 결함 종류가 검출 결과에 나타나는지 확인 ----
    print("\n" + "=" * 70)
    print("자체 검증 요약 (주입 결함 유형이 실제로 검출되었는가)")
    print("=" * 70)
    def _kind_matches(detected_kind: str, injected_kind: str) -> bool:
        # Gap G5 후처리로 같은 위치의 휨+끊김이 "복합(휨+끊김 의심)"으로 병합될 수 있으므로,
        # 복합 태그는 원래 두 유형(휨/끊김) 중 어느 쪽이 주입되었어도 매칭된 것으로 본다.
        if detected_kind == injected_kind:
            return True
        if detected_kind.startswith("복합") and injected_kind in ("휨", "끊김"):
            return True
        return False

    all_ok = True
    for report in all_reports:
        injected_kinds = sorted({g["kind"] for g in report["ground_truth_injected"]})
        detected_kinds = sorted({d["kind"] for d in report["detected_defects"]})
        ok = all(any(_kind_matches(dk, ik) for dk in detected_kinds) for ik in injected_kinds)
        # case0(정상)은 검출이 없어야 함(과검출 없음)도 함께 확인
        if not injected_kinds:
            ok = ok and len(report["detected_defects"]) == 0
        # 동일 종류 결함이 2개 이상 주입된 경우(QA §2-A 회귀 검증): 검출 개수가 주입 개수 이상이어야 한다.
        # (bend는 부수적으로 끊김도 함께 잡히는 경향이 있어 '이상'으로 비교, '같음'으로는 비교하지 않음)
        injected_count_by_kind: dict[str, int] = {}
        for g in report["ground_truth_injected"]:
            injected_count_by_kind[g["kind"]] = injected_count_by_kind.get(g["kind"], 0) + 1
        multi_kind_ok = True
        for kind, n_injected in injected_count_by_kind.items():
            if n_injected >= 2:
                n_detected = report["detection_count_by_kind"].get(kind, 0)
                multi_kind_ok = multi_kind_ok and (n_detected >= n_injected)
        ok = ok and multi_kind_ok
        all_ok = all_ok and ok
        extra = f" (다중결함 개수검증: {'PASS' if multi_kind_ok else 'FAIL'})" if any(v >= 2 for v in injected_count_by_kind.values()) else ""
        print(f"  {report['scenario']}: 주입={injected_kinds or '없음'} 검출={detected_kinds or '없음'} "
              f"-> {'PASS' if ok else 'FAIL'}{extra}")
    print(f"\n전체 결과: {'PASS' if all_ok else 'FAIL'}")
    print(f"\n요약 리포트: {summary_path}")

    # ---- QA §2-C 근거 보강: 최소 결함 길이 필터(MIN_DEFECT_ARC_MM) 임계값 스윕 테스트 ----
    print("\n" + "=" * 70)
    print("QA §2-C 근거 보강: 최소 결함 길이 필터(MIN_DEFECT_ARC_MM) 임계값 스윕")
    print("=" * 70)
    sweep_results, target_gap_mms = sweep_min_defect_arc_threshold()
    for r in sweep_results:
        detected_str = ", ".join(
            f"{g}mm(실측{r['detected_by_target_gap_mm'][g]['actual_gap_mm']}mm)="
            f"{'검출' if r['detected_by_target_gap_mm'][g]['detected'] else '미검출'}"
            for g in target_gap_mms
        )
        print(f"  임계값 {r['threshold_mm']}mm: 정상케이스 과검출={r['false_positive_count_on_normal']}건 | {detected_str}")
    sweep_path = os.path.join(OUT_DIR, "min_defect_arc_sweep.json")
    with open(sweep_path, "w", encoding="utf-8") as f:
        json.dump(sweep_results, f, ensure_ascii=False, indent=2)
    print(f"\n스윕 결과 리포트: {sweep_path}")


if __name__ == "__main__":
    main()
