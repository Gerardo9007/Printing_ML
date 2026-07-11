"""Initiative A runtime: OCR each known label line, string-diff, emit boxes + text.

For the SYNTHETIC reference/defective label the line layout (tag, y, size, text) is known
exactly from generate_labels.build_lines(), so we OCR a tight horizontal band per line in
both the reference image and the aligned/defective image, NFKC-normalize, and run
difflib.SequenceMatcher on the two line texts. A line is flagged different only when the
similarity ratio drops below OCR_SIMILARITY_THRESHOLD (suppresses OCR jitter). The changed
character span is mapped to a pixel bbox by PROPORTIONAL character position across the line's
rendered text extent (measured with the reference font metrics) — an approximation, not a
per-glyph measurement, chosen because the diff is computed on noisy OCR text whose glyph
positions don't line up with the crisp reference render.

NOTE: real-photo labels have no known build_lines() layout — they would need OCR's own line
detection (reader.readtext returns per-line boxes) to derive the crop bands. That is out of
scope for this pass; this module targets the synthetic demo contract.

Everything degrades gracefully: if EasyOCR import/inference fails or OCR is disabled, every
public function returns empty results and never raises.
"""

import os
import sys
import unicodedata
from difflib import SequenceMatcher

import numpy as np

_TASK1_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "docs", "dev", "task1-print-plate")
)
if _TASK1_DIR not in sys.path:
    sys.path.insert(0, _TASK1_DIR)

import diff_detect  # noqa: E402  _rects_close, _union
import generate_labels  # noqa: E402  build_lines(), _font(), WIDTH

OCR_SIMILARITY_THRESHOLD = 0.97  # lines with ratio >= this are treated as identical
_LINE_X_PAD = 20
_LINE_Y_PAD_TOP = 10
_LINE_Y_PAD_BOT = 16

_reader = None
_reader_failed = False


def _ocr_disabled():
    return os.environ.get("OCR_DISABLED", "").strip().lower() in ("1", "true", "yes")


def _get_reader():
    """Lazily build a single EasyOCR reader (ko+en, CPU). Returns None on any failure.

    First construction downloads model weights to the EasyOCR cache (~/.EasyOCR). For an
    offline box, pre-warm by running this once with network access, or ship the cache dir.
    """
    global _reader, _reader_failed
    if _reader is not None:
        return _reader
    if _reader_failed or _ocr_disabled():
        return None
    try:
        import easyocr  # heavy import; only when OCR actually runs

        _reader = easyocr.Reader(["ko", "en"], gpu=False, verbose=False)
        return _reader
    except Exception:
        _reader_failed = True
        return None


def _line_crop_region(line, img_w, img_h):
    """Pixel band (x0, y0, x1, y1) to OCR for one build_lines() entry, in reference coords."""
    y = int(line["y"])
    size = int(line["size"])
    x0 = max(0, 60 - _LINE_X_PAD)  # margin=60 in generate_labels
    y0 = max(0, y - _LINE_Y_PAD_TOP)
    x1 = min(img_w, generate_labels.WIDTH - 60 + _LINE_X_PAD)
    y1 = min(img_h, y + size + _LINE_Y_PAD_BOT)
    return x0, y0, x1, y1


def _text_extent(line):
    """Rendered (x0, y0, x1, y1) pixel extent of the reference line text via PIL font metrics."""
    from PIL import Image, ImageDraw

    scratch = Image.new("RGB", (10, 10))
    draw = ImageDraw.Draw(scratch)
    font = generate_labels._font(int(line["size"]), line.get("bold", False))
    return draw.textbbox((60, int(line["y"])), line["text"], font=font)


def _ocr_text(reader, crop_bgr):
    """OCR a crop and return concatenated text (spaces stripped by join), '' on empty."""
    try:
        results = reader.readtext(crop_bgr, detail=0, paragraph=True)
    except Exception:
        return ""
    return "".join(results) if results else ""


def _norm(s):
    return unicodedata.normalize("NFKC", s or "").strip()


def _changed_span(text_before, text_after):
    """Return (start, end) char index range in text_before that changed, or None if none."""
    sm = SequenceMatcher(None, text_before, text_after, autojunk=False)
    starts, ends = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        starts.append(i1)
        # for a pure insertion (i1==i2) keep a minimal 1-char footprint
        ends.append(max(i2, i1 + 1))
    if not starts:
        return None
    return min(starts), max(ends)


def detect_text_diffs(reference_bgr, aligned_bgr):
    """OCR line-level text diff.

    Returns (ocr_boxes, ocr_lines):
      ocr_boxes: list[(x, y, w, h, area)] in aligned coords, same tuple shape as pixel_boxes.
      ocr_lines: list[{"bbox_xyxy": [x0,y0,x1,y1], "text_before": str, "text_after": str}].
    On any failure or when OCR is disabled/unavailable, returns ([], []). Never raises.
    """
    try:
        reader = _get_reader()
        if reader is None:
            return [], []

        img_h, img_w = reference_bgr.shape[:2]
        ocr_boxes = []
        ocr_lines = []

        for line in generate_labels.build_lines():
            cx0, cy0, cx1, cy1 = _line_crop_region(line, img_w, img_h)
            if cx1 <= cx0 or cy1 <= cy0:
                continue
            ref_crop = reference_bgr[cy0:cy1, cx0:cx1]
            mov_crop = aligned_bgr[cy0:cy1, cx0:cx1]

            text_before = _norm(_ocr_text(reader, ref_crop))
            text_after = _norm(_ocr_text(reader, mov_crop))

            if not text_before and not text_after:
                continue

            ratio = SequenceMatcher(None, text_before, text_after, autojunk=False).ratio()
            if ratio >= OCR_SIMILARITY_THRESHOLD and text_before == text_after:
                continue
            if ratio >= OCR_SIMILARITY_THRESHOLD:
                # near-identical but not exact: treat as OCR noise, skip
                continue

            tx0, ty0, tx1, ty1 = _text_extent(line)
            span = _changed_span(text_before, text_after)
            L = max(1, len(text_before))
            if span is not None:
                s, e = span
                frac0 = min(1.0, s / L)
                frac1 = min(1.0, e / L)
                bx0 = int(tx0 + frac0 * (tx1 - tx0))
                bx1 = int(tx0 + frac1 * (tx1 - tx0))
                if bx1 - bx0 < 6:  # widen a too-thin span (e.g. single missing period)
                    bx1 = bx0 + 6
            else:
                bx0, bx1 = int(tx0), int(tx1)

            bx0 = max(0, bx0 - 4)
            bx1 = min(img_w, bx1 + 4)
            by0 = max(0, int(ty0) - 4)
            by1 = min(img_h, int(ty1) + 4)
            w, h = bx1 - bx0, by1 - by0
            if w <= 0 or h <= 0:
                continue

            ocr_boxes.append((int(bx0), int(by0), int(w), int(h), int(w * h)))
            ocr_lines.append(
                {
                    "bbox_xyxy": [int(bx0), int(by0), int(bx1), int(by1)],
                    "text_before": text_before,
                    "text_after": text_after,
                }
            )

        return ocr_boxes, ocr_lines
    except Exception:
        return [], []


def merge_with_source(pixel_boxes, ocr_boxes, max_gap=25):
    """Greedy-union pixel and OCR boxes while tracking provenance.

    Reuses diff_detect's geometry primitives (_rects_close, _union). Source rules:
    pixel+pixel -> "pixel_diff", ocr+ocr -> "ocr_diff", differing -> "both" (absorbing).
    Returns list[(x, y, w, h, area, source)].
    """
    tagged = []  # (x0, y0, x1, y1, source)
    for (x, y, w, h, _area) in pixel_boxes:
        tagged.append((x, y, x + w, y + h, "pixel_diff"))
    for (x, y, w, h, _area) in ocr_boxes:
        tagged.append((x, y, x + w, y + h, "ocr_diff"))

    if not tagged:
        return []

    rects = [t[:4] for t in tagged]
    sources = [t[4] for t in tagged]

    merged = True
    while merged:
        merged = False
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                if diff_detect._rects_close(rects[i], rects[j], max_gap):
                    rects[i] = diff_detect._union(rects[i], rects[j])
                    sources[i] = _combine_source(sources[i], sources[j])
                    del rects[j]
                    del sources[j]
                    merged = True
                    break
            if merged:
                break

    result = []
    for (x0, y0, x1, y1), src in zip(rects, sources):
        w, h = x1 - x0, y1 - y0
        result.append((int(x0), int(y0), int(w), int(h), int(w * h), src))
    return result


def _combine_source(a, b):
    if a == b:
        return a
    return "both"
