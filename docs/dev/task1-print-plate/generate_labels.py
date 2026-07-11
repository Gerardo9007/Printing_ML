"""
과제① 인쇄판 문안검사 - 합성 라벨 이미지 생성기

spec.md 3.2 절 "합성 결함 생성"에 근거하여, 정답본(디자인 원본에 해당)과
불량본(실제 인쇄물에 해당, 문안 결함이 주입됨)을 코드로 직접 생성한다.

주입하는 결함은 problem.md 1절 "과제① 구체적 실패 사례"에 명시된 유형을 그대로 사용한다:
  - 오탈자      : "토너" -> "토노"
  - 문자 누락   : "나이아신아마이드"에서 '아' 누락
  - 점 누락     : 문장 끝 마침표 누락
  - 번짐        : 잉크 확산으로 글자가 뭉개짐 (가우시안 블러 + 모폴로지 팽창, spec.md 3.2)
  - 성분표시오류 : 성분표 한 항목 누락 (spec.md 최우선 치명 클래스)

또한 실제 촬영/인쇄 공정에서 발생하는 "정합이 필요한 이유"를 재현하기 위해
불량본에는 약간의 회전/이동/스케일 오차를 추가로 부여한다
(spec.md 3.2: 과제①은 ±1~2도 이내의 소회전만 허용, 반전 금지 -> 준수).
"""

import json
import os

from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ----------------------------------------------------------------------------
# 설정
# ----------------------------------------------------------------------------

WIDTH, HEIGHT = 900, 1200
BG_COLOR = (255, 255, 255)
FG_COLOR = (20, 20, 20)
FONT_PATH_REGULAR = "C:/Windows/Fonts/malgun.ttf"
FONT_PATH_BOLD = "C:/Windows/Fonts/malgunbd.ttf"

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")

# 점누락(마침표) 결함이 실제 검출 가능한 diff/OCR 신호를 갖도록, 문장 끝 마침표만
# 본문 폰트 대비 이 배수로 크게(그리고 bold) 별도 렌더링한다. 본문 텍스트 자체는
# 그대로 두므로 다른 결함(오탈자/문자누락/성분표시오류/번짐)의 GT 좌표에는 영향 없음.
BIG_PERIOD_SCALE = 2.0


def _font(size, bold=False):
    path = FONT_PATH_BOLD if bold else FONT_PATH_REGULAR
    return ImageFont.truetype(path, size)


# ----------------------------------------------------------------------------
# 정답본(reference) 텍스트 레이아웃 정의
#
# 각 라인은 (텍스트, y좌표, 폰트크기, bold여부, 태그) 형태로 정의한다.
# 태그는 이후 결함 주입 시 어떤 라인을 건드릴지 지정하는 용도로만 쓰인다.
# ----------------------------------------------------------------------------

def build_lines():
    return [
        dict(tag="title", text="모이스처 리페어 크림", y=80, size=48, bold=True),
        dict(tag="volume", text="용량: 50 mL", y=150, size=28, bold=False),
        dict(tag="section_ingredient", text="전성분", y=260, size=30, bold=True),
        dict(
            tag="ingredient",
            text="정제수, 글리세린, 나이아신아마이드, 다이메티콘, 토너, 향료.",
            y=310,
            size=24,
            bold=False,
        ),
        dict(tag="section_usage", text="사용법", y=420, size=30, bold=True),
        dict(
            tag="usage",
            text="세안 후 적당량을 취해 얼굴에 고르게 발라주세요.",
            y=470,
            size=24,
            bold=False,
        ),
        dict(tag="section_caution", text="사용상 주의사항", y=580, size=30, bold=True),
        dict(
            tag="caution",
            text="상처가 있는 부위에는 사용을 자제해 주세요.",
            y=630,
            size=24,
            bold=False,
        ),
        dict(
            tag="legal",
            text="본 제품은 화장품법에 따라 표시되었습니다.",
            y=740,
            size=22,
            bold=False,
        ),
        dict(tag="lot", text="LOT NO. 24AP0917-A", y=1080, size=22, bold=False),
        dict(tag="madein", text="MADE IN KOREA", y=1120, size=22, bold=False),
    ]


def draw_label(lines, margin=60):
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # 라벨 테두리 (인쇄판 외곽선 모사)
    draw.rectangle([20, 20, WIDTH - 20, HEIGHT - 20], outline=(0, 0, 0), width=4)

    boxes = {}
    for line in lines:
        font = _font(line["size"], line.get("bold", False))
        pos = (margin, line["y"])
        text = line["text"]
        # usage 라인의 문장 끝 마침표는 본문에서 분리해 크게/굵게 별도 렌더링한다.
        # 본문(마침표 제외)은 정답본/불량본이 동일하게 그려지고, 마침표 유무만
        # 국소적으로 달라지므로 점누락 결함이 그 위치에 뚜렷한 diff 신호를 만든다.
        if line.get("tag") == "usage" and text.endswith("."):
            body = text[:-1]
            draw.text(pos, body, fill=FG_COLOR, font=font)
            boxes[line["tag"]] = draw.textbbox(pos, body, font=font)
            period_x = margin + draw.textlength(body, font=font)
            big_font = _font(int(line["size"] * BIG_PERIOD_SCALE), bold=True)
            trial = draw.textbbox((period_x, line["y"]), ".", font=big_font)
            py = line["y"] + (boxes[line["tag"]][3] - trial[3])  # bottom-align w/ body text
            draw.text((period_x, py), ".", fill=FG_COLOR, font=big_font)
            boxes["usage_period"] = draw.textbbox((period_x, py), ".", font=big_font)
        else:
            draw.text(pos, text, fill=FG_COLOR, font=font)
            boxes[line["tag"]] = draw.textbbox(pos, text, font=font)

    return img, boxes


def make_reference():
    """정답본(디자인 원본) 생성."""
    lines = build_lines()
    img, boxes = draw_label(lines)
    return img, lines, boxes


def _measure_substring_bboxes(margin, y, size, bold, text, substrings):
    """
    (버그 수정 이력 - QA 리포트 [발견 2] 대응)
    같은 라인(예: ingredient) 안에 여러 결함이 함께 있으면 라인 전체를 GT로 쓰는
    기존 방식은 결함 유형별 독립 검증을 보장하지 못한다. 이 함수는 "결함이 주입되기
    전(정답본과 동일한) 원본 라인 텍스트" 안에서 각 결함이 차지하는 부분 문자열의
    x 범위를 폰트 메트릭으로 직접 측정해, 결함 유형별로 분리된 bbox를 만든다.

    측정 기준을 "정답본 텍스트"로 고정하는 이유: diff_detect의 차분은 항상 참조(정답본)
    이미지 좌표계에서 계산되므로(정합은 불량본을 정답본 좌표계로 맞추는 과정이다),
    결함 위치의 GT도 정답본 좌표계를 기준으로 잡아야 좌표가 일치한다.

    substrings: {defect_key: substring} 매핑. substring이 원본 텍스트에 없으면
    해당 defect_key는 결과에서 생략된다 (호출부에서 라인 전체 bbox로 폴백해야 함).
    """
    scratch = Image.new("RGB", (10, 10))
    draw = ImageDraw.Draw(scratch)
    font = _font(size, bold)

    full_bbox = draw.textbbox((margin, y), text, font=font)
    y0, y1 = full_bbox[1], full_bbox[3]

    result = {}
    for key, sub in substrings.items():
        idx = text.find(sub)
        if idx < 0:
            continue
        prefix = text[:idx]
        x0 = margin + draw.textlength(prefix, font=font)
        x1 = margin + draw.textlength(prefix + sub, font=font)
        result[key] = [x0, y0, x1, y1]
    return result


def usage_period_bbox(ref_lines, margin=60):
    """정답본 usage 라인의 '크게 그린 마침표' bbox(xyxy)를 폰트 메트릭으로 측정한다.

    draw_label의 마침표 렌더링과 동일한 산식을 사용하므로 좌표가 정확히 일치한다.
    점누락 결함의 결함 단위(defect-unit) GT로 쓰인다(QA [발견 2] 방향: 라인 단위 대신
    결함 단위 GT). usage 라인이 없거나 마침표로 끝나지 않으면 None.
    """
    usage = next((l for l in ref_lines if l["tag"] == "usage"), None)
    if usage is None or not usage["text"].endswith("."):
        return None
    scratch = Image.new("RGB", (10, 10))
    draw = ImageDraw.Draw(scratch)
    font = _font(usage["size"], usage.get("bold", False))
    body = usage["text"][:-1]
    body_bbox = draw.textbbox((margin, usage["y"]), body, font=font)
    period_x = margin + draw.textlength(body, font=font)
    big_font = _font(int(usage["size"] * BIG_PERIOD_SCALE), bold=True)
    trial = draw.textbbox((period_x, usage["y"]), ".", font=big_font)
    py = usage["y"] + (body_bbox[3] - trial[3])
    return list(draw.textbbox((period_x, py), ".", font=big_font))


def make_defective(ref_lines):
    """
    정답본 텍스트 레이아웃을 기반으로 결함을 주입한 불량본(실제 인쇄물)을 생성한다.
    반환값에는 주입한 결함의 GT(ground truth) bbox 목록이 포함된다 (recall 평가용).

    버그 수정 이력 (QA 리포트 [발견 2]): ingredient 라인에는 오탈자/문자누락/
    성분표시오류 3개 결함이 동시에 존재하는데, 과거에는 이 라인 전체를 하나의 GT
    bbox로만 취급해 셋 중 하나만 검출돼도 나머지 둘까지 "검출됨"으로 잘못 집계될
    수 있었다. 이제 `_measure_substring_bboxes`로 각 결함의 개별 x범위를 측정해
    `defects[i]["bbox"]`에 결함 단위 GT를 함께 기록한다 (라인 전체 bbox는
    `defect_line_boxes`에 하위호환용으로 계속 남겨둔다).
    """
    import copy

    lines = copy.deepcopy(ref_lines)

    # ingredient 라인의 결함 3개(오탈자/문자누락/성분표시오류)는 같은 줄에 겹쳐 있으므로,
    # "결함 주입 전" 원본 텍스트를 기준으로 부분문자열 x범위를 먼저 측정해 둔다.
    ingredient_line = next(l for l in lines if l["tag"] == "ingredient")
    ingredient_char_boxes = _measure_substring_bboxes(
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

    defects = []  # 각 항목: {type, tag, note, bbox(optional, 결함 단위 GT)}

    # 1) 오탈자: "토너" -> "토노"  (problem.md 예시 그대로)
    for line in lines:
        if line["tag"] == "ingredient":
            assert "토너" in line["text"]
            line["text"] = line["text"].replace("토너", "토노")
            defects.append(
                dict(
                    type="오탈자",
                    tag="ingredient",
                    note="토너->토노",
                    bbox=ingredient_char_boxes.get("typo"),
                )
            )

    # 2) 문자 누락: "나이아신아마이드"에서 '아' 누락 -> "나이신아마이드"
    for line in lines:
        if line["tag"] == "ingredient":
            assert "나이아신아마이드" in line["text"]
            line["text"] = line["text"].replace("나이아신아마이드", "나이신아마이드")
            defects.append(
                dict(
                    type="문자누락",
                    tag="ingredient",
                    note="나이아신아마이드->나이신아마이드",
                    bbox=ingredient_char_boxes.get("missing_char"),
                )
            )

    # 3) 점 누락: 사용법 문장 끝 마침표 누락.
    #    마침표는 draw_label에서 크게/굵게 별도 렌더링되므로, GT도 그 확대된 마침표
    #    영역(결함 단위)으로 잡는다. 이제 실제 diff/OCR 신호가 이 영역에 뚜렷이 남는다.
    period_gt = usage_period_bbox(ref_lines)
    for line in lines:
        if line["tag"] == "usage":
            assert line["text"].endswith(".")
            line["text"] = line["text"][:-1]
            defects.append(dict(type="점누락", tag="usage", note="문장 끝 마침표 누락", bbox=period_gt))

    # 4) 성분표시오류(최우선 치명 클래스): 성분 항목 중 "향료." 누락 (표시사항 결손)
    for line in lines:
        if line["tag"] == "ingredient":
            assert "향료." in line["text"]
            line["text"] = line["text"].replace(", 향료.", ".")
            defects.append(
                dict(
                    type="성분표시오류",
                    tag="ingredient",
                    note="'향료' 성분 누락",
                    bbox=ingredient_char_boxes.get("ingredient_error"),
                )
            )

    img, boxes = draw_label(lines)

    # bbox=None으로 남겨둔 결함(예: 점누락 - usage 라인엔 결함이 이것 하나뿐)은
    # 해당 라인의 bbox를 그대로 결함 단위 GT로 사용한다 (라인=결함 1:1이라 근사 손실 없음).
    for d in defects:
        if d.get("bbox") is None and d["tag"] in boxes:
            d["bbox"] = list(boxes[d["tag"]])

    # 5) 번짐: 사용상 주의사항 문구 영역에 국소 블러 + 팽창을 적용해 잉크 확산을 모사
    #    (spec.md 3.2: 가우시안 블러, 모폴로지 팽창)
    caution_box = boxes["caution"]
    defects.append(
        dict(
            type="번짐",
            tag="caution",
            note="가우시안 블러+팽창으로 인쇄 번짐 모사",
            bbox=list(caution_box),
        )
    )
    img = apply_local_bleed(img, caution_box, pad=10)

    return img, defects, boxes


def apply_local_bleed(img, bbox, pad=10):
    """bbox 영역에 가우시안 블러 + 최소값 필터(어두운 색 팽창)를 적용해 잉크 번짐을 모사한다."""
    import numpy as np
    import cv2

    x0, y0, x1, y1 = [int(v) for v in bbox]
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(img.width, x1 + pad), min(img.height, y1 + pad)

    arr = np.array(img)
    patch = arr[y0:y1, x0:x1]

    # 모폴로지 팽창: 어두운 글자 획이 굵어지는 효과 (erode on light bg = dilate on dark text)
    kernel = np.ones((3, 3), np.uint8)
    patch = cv2.erode(patch, kernel, iterations=2)
    # 가우시안 블러: 잉크가 퍼져 경계가 흐려지는 효과
    patch = cv2.GaussianBlur(patch, (7, 7), 0)

    arr[y0:y1, x0:x1] = patch
    return Image.fromarray(arr)


def apply_capture_misalignment(img, angle_deg=1.5, tx=6, ty=-4, scale=0.995):
    """
    실제 촬영/인쇄 공정에서 발생하는 미세한 회전·이동·스케일 오차를 시뮬레이션한다.
    spec.md 3.2 준수: 과제①은 ±1~2도 이내 소회전만 허용, 반전 금지.
    """
    import numpy as np
    import cv2

    arr = np.array(img)
    h, w = arr.shape[:2]
    center = (w / 2, h / 2)

    M = cv2.getRotationMatrix2D(center, angle_deg, scale)
    M[0, 2] += tx
    M[1, 2] += ty

    warped = cv2.warpAffine(
        arr, M, (w, h), borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255)
    )
    return Image.fromarray(warped)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    ref_img, ref_lines, ref_boxes = make_reference()
    defect_img, defects, defect_boxes = make_defective(ref_lines)

    # 불량본에 촬영/인쇄 미세 오차(회전/이동/스케일)를 추가로 부여
    # -> 정합(Registration) 단계가 실제로 필요함을 보이기 위함
    defect_img_misaligned = apply_capture_misalignment(defect_img)

    ref_path = os.path.join(OUTPUT_DIR, "01_reference.png")
    defect_path = os.path.join(OUTPUT_DIR, "02_defective_misaligned.png")
    defect_aligned_path = os.path.join(OUTPUT_DIR, "02b_defective_no_misalign.png")

    ref_img.save(ref_path)
    defect_img_misaligned.save(defect_path)
    defect_img.save(defect_aligned_path)  # 정합 단계 효과 비교용 (오차 없는 버전)

    meta = dict(
        reference_image=os.path.basename(ref_path),
        defective_image=os.path.basename(defect_path),
        image_size=[WIDTH, HEIGHT],
        capture_misalignment=dict(angle_deg=1.5, tx=6, ty=-4, scale=0.995),
        injected_defects=defects,
        defect_line_boxes={k: list(v) for k, v in defect_boxes.items()},
    )
    meta_path = os.path.join(OUTPUT_DIR, "00_ground_truth.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"[생성 완료] 정답본: {ref_path}")
    print(f"[생성 완료] 불량본(정합오차 포함): {defect_path}")
    print(f"[생성 완료] 불량본(정합오차 없음, 비교용): {defect_aligned_path}")
    print(f"[생성 완료] GT 메타데이터: {meta_path}")
    print(f"\n주입된 결함 {len(defects)}건:")
    for d in defects:
        print(f"  - [{d['type']}] {d['note']} (라인: {d['tag']})")


if __name__ == "__main__":
    main()
