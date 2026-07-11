"""웹앱 기본 참조/실물 이미지 + GT를 생성한다 (task1의 run_demo.py 산출물과 같은 역할).

die_blade_qc_demo.run_scenario()가 내부에서 합성 생성부터 정합·검출까지 한 번에 하지만,
웹앱은 "정합~검출"만 실제 파이프라인으로 재사용하고 "합성 생성"은 이 스크립트가 미리 한 번
해서 결과물(이미지+GT)만 저장해 둔다. 그래야 웹앱 기본 데모가 매 요청마다 새로 합성하지 않고
task1처럼 고정된 참조/실물 쌍을 재사용할 수 있다.

산출물 (output/webapp_demo/):
  reference.png       # 기준 도면 마스크 (검정 배경, 흰색 라인)
  actual_captured.png # 촬영된(=결함 주입 + 촬영 정렬오차 적용된, 아직 정합 전) 실물 마스크
  ground_truth.json   # 주입된 결함 목록 (kind, note, magnitude_px 등)
"""

import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import die_blade_qc_demo as dbm

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "webapp_demo")


def build_demo_pair():
    """휨+끊김+마모 복합 결함 시나리오 하나를 생성한다 (위치오차는 별도 데모 이미지로 분리).

    case5(끊김2+휨1)와 case7(마모)을 합친 형태 — 웹앱 기본 데모에서 4개 결함 클래스 중
    3개(휨·끊김·마모)를 한 이미지에서 보여주기 위함. 위치오차는 촬영 정렬오차 자체를 크게
    벌려야 재현되므로(=등록 자체가 다른 스케일), 같은 이미지에 섞으면 오히려 이해하기 어려워
    별도 이미지(actual_position_error.png)로 분리한다.
    """
    scenario = dbm.Scenario(
        name="webapp_demo_main",
        title="웹앱 기본 데모: 끊김2 + 휨1 + 마모 복합",
        bend={"start_frac": 0.55, "span_frac": 0.08, "magnitude_px": 30},
        breaks=[
            {"start_frac": 0.05, "span_frac": 0.03},
            {"start_frac": 0.85, "span_frac": 0.03},
        ],
        wears=[{"start_frac": 0.30, "span_frac": 0.12, "depth_px": 3.0}],
    )
    return scenario


def build_position_error_scenario():
    return dbm.Scenario(
        name="webapp_demo_position",
        title="웹앱 기본 데모: 위치오차 단독",
        bend=None,
        breaks=[],
        misalign={"angle_deg": 1.4, "tx": 40, "ty": -20},
    )


def render_pair(scenario: dbm.Scenario, rng: np.random.Generator):
    """run_scenario()의 '합성 생성' 절반만 재현한다 (정합·검출은 웹앱이 담당)."""
    reference_points = dbm.generate_reference_contour()
    reference_mask = dbm.render_closed(reference_points)
    n_total = len(reference_points)

    ground_truth = []
    working_points = reference_points.copy()

    all_bends = ([scenario.bend] if scenario.bend else []) + list(scenario.bends)
    for bend_spec in all_bends:
        working_points, gt = dbm.inject_bend(working_points, rng=rng, **bend_spec)
        ground_truth.append(gt)

    for wear_spec in scenario.wears:
        working_points, gt = dbm.inject_wear(working_points, rng=rng, **wear_spec)
        ground_truth.append(gt)

    import math
    injected_shift_mm = math.hypot(scenario.misalign.get("tx", 0.0),
                                    scenario.misalign.get("ty", 0.0)) * dbm.MM_PER_PX
    if injected_shift_mm > dbm.POSITION_ERROR_TOL_MM:
        ground_truth.append(dbm.InjectedDefect(
            kind="위치오차", start_idx=0, end_idx=0, magnitude_px=injected_shift_mm / dbm.MM_PER_PX,
            note=f"지그 안착 이동량 약 {injected_shift_mm:.2f}mm (허용 {dbm.POSITION_ERROR_TOL_MM}mm 초과)",
        ))

    polylines = [dbm.Arc(points=working_points, orig_idx=np.arange(n_total), is_closed=True)]
    for b in scenario.breaks:
        target_idx = int(np.argmax([len(p.points) for p in polylines]))
        target = polylines.pop(target_idx)
        new_arcs, gt = dbm.inject_break(target, n_total=n_total, **b)
        polylines.extend(new_arcs)
        ground_truth.append(gt)

    if not scenario.breaks:
        actual_source = dbm.render_closed(working_points)
    else:
        actual_source = dbm.render_polylines([a.points for a in polylines])

    actual_captured = dbm.apply_camera_misalignment(actual_source, **scenario.misalign)
    return reference_mask, actual_captured, ground_truth


def _save_png(img, path):
    ok, buf = dbm.cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError(f"PNG 인코딩 실패: {path}")
    buf.tofile(path)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    rng = np.random.default_rng(42)

    reference_mask, actual_captured, ground_truth = render_pair(build_demo_pair(), rng)
    _save_png(reference_mask, os.path.join(OUT_DIR, "reference.png"))
    _save_png(actual_captured, os.path.join(OUT_DIR, "actual_captured.png"))

    _, actual_position, gt_position = render_pair(build_position_error_scenario(), rng)
    _save_png(actual_position, os.path.join(OUT_DIR, "actual_position_error.png"))

    gt_json = {
        "image_size": [dbm.CANVAS_SIZE, dbm.CANVAS_SIZE],
        "injected_defects": [gt.__dict__ for gt in ground_truth],
        "assumptions": {
            "mm_per_px": dbm.MM_PER_PX,
            "defect_tolerance_mm": dbm.DEFECT_TOL_MM,
            "min_defect_arc_mm": dbm.MIN_DEFECT_ARC_MM,
        },
    }
    with open(os.path.join(OUT_DIR, "ground_truth.json"), "w", encoding="utf-8") as f:
        json.dump(gt_json, f, ensure_ascii=False, indent=2)

    gt_position_json = {
        "image_size": [dbm.CANVAS_SIZE, dbm.CANVAS_SIZE],
        "injected_defects": [gt.__dict__ for gt in gt_position],
    }
    with open(os.path.join(OUT_DIR, "ground_truth_position.json"), "w", encoding="utf-8") as f:
        json.dump(gt_position_json, f, ensure_ascii=False, indent=2)

    print("생성 완료:")
    print(f"  {OUT_DIR}/reference.png")
    print(f"  {OUT_DIR}/actual_captured.png  (주입 결함: {[g.kind for g in ground_truth]})")
    print(f"  {OUT_DIR}/actual_position_error.png  (주입 결함: {[g.kind for g in gt_position]})")
    print(f"  {OUT_DIR}/ground_truth.json")
    print(f"  {OUT_DIR}/ground_truth_position.json")


if __name__ == "__main__":
    main()
