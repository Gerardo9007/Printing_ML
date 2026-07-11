"""
webapp 테스트용 샘플 이미지 생성기.

기존 docs/dev/task1-print-plate/generate_labels.py는 5개 결함을 한 이미지에
동시에 주입한 데모용 불량본 1장만 만든다. 여기서는 웹서비스 업로드 테스트를 위해
같은 화장품 라벨 레이아웃을 재사용하되, "결함 1건만 주입된" 불량본 5장을 각각
따로 만든다 (참조이미지 1장과 1:1로 비교 가능하도록).

결함 유형은 problem.md / generate_labels.py와 동일하게 유지한다:
  1. 오탈자      : "토너" -> "토노"
  2. 문자누락    : "나이아신아마이드" -> "나이신아마이드"
  3. 점누락      : 사용법 문장 끝 마침표 누락
  4. 성분표시오류 : "향료" 성분 누락 (최우선 치명 클래스)
  5. 번짐        : 사용상 주의사항 문구에 가우시안 블러+팽창
"""

import copy
import json
import os
import sys

TASK1_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "docs", "dev", "task1-print-plate")
)
sys.path.insert(0, TASK1_DIR)

import generate_labels as gl  # noqa: E402

OUTPUT_DIR = os.path.dirname(__file__)


def build_single_defect(ref_lines, defect_key):
    """ref_lines를 기반으로 defect_key 하나만 주입된 (img, defect_meta) 반환."""
    lines = copy.deepcopy(ref_lines)
    ingredient_line = next(l for l in lines if l["tag"] == "ingredient")
    char_boxes = gl._measure_substring_bboxes(
        margin=60,
        y=ingredient_line["y"],
        size=ingredient_line["size"],
        bold=ingredient_line.get("bold", False),
        text=ingredient_line["text"],
        substrings={
            "typo": "토너",
            "missing_char": "나이아신아마이드",
            "ingredient_error": ", 향료.",
        },
    )

    defect = None
    bleed_box = None

    if defect_key == "typo":
        for line in lines:
            if line["tag"] == "ingredient":
                line["text"] = line["text"].replace("토너", "토노")
        defect = dict(type="오탈자", tag="ingredient", note="토너->토노", bbox=char_boxes.get("typo"))

    elif defect_key == "missing_char":
        for line in lines:
            if line["tag"] == "ingredient":
                line["text"] = line["text"].replace("나이아신아마이드", "나이신아마이드")
        defect = dict(
            type="문자누락",
            tag="ingredient",
            note="나이아신아마이드->나이신아마이드",
            bbox=char_boxes.get("missing_char"),
        )

    elif defect_key == "missing_period":
        for line in lines:
            if line["tag"] == "usage":
                line["text"] = line["text"][:-1]
        defect = dict(type="점누락", tag="usage", note="문장 끝 마침표 누락", bbox=None)

    elif defect_key == "ingredient_error":
        for line in lines:
            if line["tag"] == "ingredient":
                line["text"] = line["text"].replace(", 향료.", ".")
        defect = dict(
            type="성분표시오류",
            tag="ingredient",
            note="'향료' 성분 누락",
            bbox=char_boxes.get("ingredient_error"),
        )

    elif defect_key == "bleed":
        defect = dict(type="번짐", tag="caution", note="가우시안 블러+팽창으로 인쇄 번짐 모사", bbox=None)

    else:
        raise ValueError(defect_key)

    img, boxes = gl.draw_label(lines)

    if defect["bbox"] is None:
        defect["bbox"] = list(boxes[defect["tag"]])

    if defect_key == "bleed":
        bleed_box = boxes["caution"]
        img = gl.apply_local_bleed(img, bleed_box, pad=10)

    return img, defect


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    ref_lines = gl.build_lines()
    ref_img, ref_boxes = gl.draw_label(ref_lines)
    ref_path = os.path.join(OUTPUT_DIR, "reference.png")
    ref_img.save(ref_path)
    print(f"[생성 완료] 참조이미지: {ref_path}")

    samples = [
        ("01_typo", "typo"),
        ("02_missing_char", "missing_char"),
        ("03_missing_period", "missing_period"),
        ("04_ingredient_error", "ingredient_error"),
        ("05_bleed", "bleed"),
    ]

    manifest = []
    for name, key in samples:
        img, defect = build_single_defect(ref_lines, key)
        img_misaligned = gl.apply_capture_misalignment(img)
        out_path = os.path.join(OUTPUT_DIR, f"defective_{name}.png")
        img_misaligned.save(out_path)
        manifest.append(dict(file=os.path.basename(out_path), defect=defect))
        print(f"[생성 완료] 결함이미지({defect['type']}): {out_path}")

    manifest_path = os.path.join(OUTPUT_DIR, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(
            dict(reference_image="reference.png", samples=manifest),
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"[생성 완료] 매니페스트: {manifest_path}")


if __name__ == "__main__":
    main()
