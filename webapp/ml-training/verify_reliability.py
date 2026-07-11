"""Verification harness for the retrained (schema v2, 10-feature) reliability classifier.

Scores boxes through the ACTUAL runtime path (reliability.score_boxes, pure numpy from
the committed JSON artifacts) on the three cases that define the OCR-fix regression gate:
  1) QA 발견1 giant residual pixel box (성분표시오류 alone, low-k)  -> must stay LOW
  2) real OCR/both catches (ingredient_error, bleed via OCR+pixel) -> should be HIGH
  3) OCR misread on clean text (no injected defect)                -> must stay LOW
  + the 점누락-alone case, reported honestly with its box features.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

import ocr_diff  # noqa: E402
import registration  # noqa: E402
import diff_detect  # noqa: E402
import reliability  # noqa: E402
import generate_dataset as g  # noqa: E402

MIS = dict(angle_deg=1.5, tx=6, ty=-4, scale=0.995)


def _score_scene(name, defect_set, k=6.0, ocr=True):
    ref, defc, gt = g.build_pair(defect_set, MIS)
    aligned, method, info = registration.align_to_reference(ref, defc)
    mask, pboxes, diff, di = diff_detect.compute_diff_mask(ref, aligned, min_area=40, k=k)
    if ocr:
        oboxes, _ = ocr_diff.detect_text_diffs(ref, aligned)
        merged = ocr_diff.merge_with_source(pboxes, oboxes)
    else:
        merged = [(x, y, w, h, a, "pixel_diff") for (x, y, w, h, a) in pboxes]
    scores = reliability.score_boxes(
        merged, diff, di["image_area"], info.get("n_inliers", 0), di["threshold"]
    )
    print(f"\n=== {name}  (k={k}, ocr={ocr}, thr={di['threshold']:.1f}) ===")
    rows = []
    for bi, b in enumerate(merged):
        f = reliability.extract_features(b, diff, merged, di["image_area"],
                                         info.get("n_inliers", 0), di["threshold"])
        ov = g._gt_overlap(b, gt)
        L = g._label(ov, f[0])
        src = b[5] if len(b) > 5 else "pixel_diff"
        s = scores[bi] if scores else None
        print(f"  {src:10s} L{L} wh=({b[2]},{b[3]}) ar={f[0]:.3f} "
              f"max={f[8]:.0f} pixfrac={f[9]:.3f} -> score={s:.4f}")
        rows.append((src, L, s, b))
    return rows


def main():
    clf = reliability._get_classifier()
    print("classifier available:", clf.available, "| reason:", clf.reason)

    # 1) QA 발견1 giant residual pixel box — 성분표시오류 alone driven to giant-box regime
    _score_scene("① QA 발견1 giant box (ing_error alone, k=2, pixel-only)",
                 {"ingredient_error"}, k=2.0, ocr=False)

    # 2) real OCR/both catches
    _score_scene("② ing_error alone (production k=6, OCR+pixel merged)",
                 {"ingredient_error"}, k=6.0, ocr=True)
    _score_scene("② bleed alone (production k=6, OCR+pixel merged)",
                 {"bleed"}, k=6.0, ocr=True)

    # 3) OCR misread on clean text (no injected defect)
    _score_scene("③ clean, no defect (OCR misreads only)", set(), k=6.0, ocr=True)

    # 점누락 alone — reported honestly
    _score_scene("△ 점누락 alone (production k=6, OCR+pixel merged)",
                 {"dot"}, k=6.0, ocr=True)


if __name__ == "__main__":
    main()
