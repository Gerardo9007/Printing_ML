"""Initiative B runtime: false-positive / reliability classifier scoring.

Single source of truth for FEATURE_NAMES + extract_features (ML-ARCHITECTURE.md §5).
The training scripts import FEATURE_NAMES / extract_features from HERE so the trained
feature order and the inference feature order can never drift.

Scoring uses a plain-numpy logistic regression loaded from committed JSON artifacts
(backend/ml/reliability_model.json + reliability_meta.json). No scikit-learn at runtime.
If the artifacts are absent or fail validation, scoring degrades to None gracefully.
"""

import json
import os
import sys

import numpy as np

# diff_detect provides the _rects_close geometry primitive used for n_nearby_boxes.
# Ensure the task1 prototype dir is importable both under the backend (via pipeline_bridge)
# and standalone (via ml-training's sys.path bridge).
_TASK1_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "docs", "dev", "task1-print-plate")
)
if _TASK1_DIR not in sys.path:
    sys.path.insert(0, _TASK1_DIR)

import diff_detect  # noqa: E402  _rects_close(a, b, gap)

try:
    import cv2  # noqa: E402
except Exception:  # pragma: no cover - cv2 is a hard backend dep, but never crash on import
    cv2 = None


FEATURE_SCHEMA_VERSION = 2
FEATURE_NAMES = [
    "area_ratio",             # per-box
    "aspect_ratio",           # per-box
    "mean_diff_intensity",    # per-box
    "std_diff_intensity",     # per-box
    "edge_density",           # per-box
    "n_nearby_boxes",         # per-box
    "registration_n_inliers", # global (same value on every box in a run)
    "diff_threshold_used",    # global
    # --- v2: dilution-resistant peak/fraction signals ---
    # The box-average mean/std collapse toward 0 for a small real change inside a large,
    # padded OCR-derived box (ocr_diff._changed_span widens thin spans + ±4px pad), making a
    # genuine ocr_diff catch (e.g. 점누락) indistinguishable from a pure OCR misread on
    # unchanged pixels. These two are peak/fraction-based, so a small localized real signal
    # still registers regardless of box size.
    "max_diff_intensity",     # per-box: peak absdiff pixel in the crop (0..255)
    "diff_pixel_fraction",    # per-box: fraction of crop pixels above DIFF_PIXEL_FLOOR
]

DIFF_PIXEL_FLOOR = 15  # intensity floor for diff_pixel_fraction; above ~registration noise

_MODEL_PATH = os.path.join(os.path.dirname(__file__), "ml", "reliability_model.json")
_META_PATH = os.path.join(os.path.dirname(__file__), "ml", "reliability_meta.json")

_NEARBY_GAP = 25  # matches merge_close_boxes max_gap: approximates neighbours that would merge


def extract_features(box, diff, all_boxes, image_area, registration_n_inliers, diff_threshold_used):
    """Return a length-8 list[float] in FEATURE_NAMES order.

    box = (x, y, w, h, area[, source]); all_boxes = full box list (for n_nearby_boxes).
    All values are raw units (the stored StandardScaler handles normalization) and coerced
    to Python float for JSON/CSV safety. Never raises on a degenerate crop.
    """
    x, y, w, h = int(box[0]), int(box[1]), int(box[2]), int(box[3])

    # 0: area_ratio
    area_ratio = (w * h) / image_area if image_area else 0.0

    # 1: aspect_ratio (h guaranteed >=1 for a connected-component bbox; guard anyway)
    aspect_ratio = (w / h) if h > 0 else 0.0

    # 2-4: crop-based stats on the aligned-coords uint8 absdiff
    crop = diff[y:y + h, x:x + w] if diff is not None else None
    if crop is None or crop.size == 0:
        mean_diff = 0.0
        std_diff = 0.0
        edge_density = 0.0
        max_diff = 0.0
        pixel_fraction = 0.0
    else:
        mean_diff = float(crop.mean())
        std_diff = float(crop.std())
        # Laplacian variance; needs at least a 2x2 region and cv2 available
        if cv2 is not None and crop.shape[0] >= 2 and crop.shape[1] >= 2:
            edge_density = float(cv2.Laplacian(crop, cv2.CV_64F).var())
        else:
            edge_density = 0.0
        max_diff = float(crop.max())
        pixel_fraction = float((crop > DIFF_PIXEL_FLOOR).mean())

    # 5: n_nearby_boxes — count OTHER boxes within _NEARBY_GAP px (edge-to-edge)
    rect = (x, y, x + w, y + h)
    n_nearby = 0
    for other in all_boxes:
        if other is box:
            continue
        ox, oy, ow, oh = int(other[0]), int(other[1]), int(other[2]), int(other[3])
        orect = (ox, oy, ox + ow, oy + oh)
        if orect == rect:
            # identical rect but distinct object (defensive): skip self-like duplicate
            continue
        if diff_detect._rects_close(rect, orect, _NEARBY_GAP):
            n_nearby += 1

    return [
        float(area_ratio),
        float(aspect_ratio),
        float(mean_diff),
        float(std_diff),
        float(edge_density),
        float(n_nearby),
        float(int(registration_n_inliers or 0)),
        float(diff_threshold_used),
        float(max_diff),
        float(pixel_fraction),
    ]


class Classifier:
    """Plain-numpy logistic-regression scorer loaded from committed JSON artifacts.

    Load failure / schema mismatch => self.available is False and score() returns None.
    """

    def __init__(self, model_path=_MODEL_PATH, meta_path=_META_PATH):
        self.available = False
        self.reason = None
        self._coef = None
        self._intercept = None
        self._mean = None
        self._scale = None
        self._load(model_path, meta_path)

    def _load(self, model_path, meta_path):
        if not (os.path.isfile(model_path) and os.path.isfile(meta_path)):
            self.reason = "model artifact absent"
            return
        try:
            with open(model_path, encoding="utf-8") as f:
                model = json.load(f)
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
        except Exception as exc:
            self.reason = f"artifact load error: {exc}"
            return

        if meta.get("feature_names") != FEATURE_NAMES:
            self.reason = "feature_names mismatch vs FEATURE_NAMES"
            return
        if meta.get("schema_version") != FEATURE_SCHEMA_VERSION:
            self.reason = "schema_version mismatch"
            return
        if meta.get("model_type") != "logreg_json":
            self.reason = f"unsupported model_type: {meta.get('model_type')}"
            return

        try:
            coef = np.asarray(model["coef"], dtype=np.float64).reshape(-1)
            mean = np.asarray(model["scaler_mean"], dtype=np.float64).reshape(-1)
            scale = np.asarray(model["scaler_scale"], dtype=np.float64).reshape(-1)
            intercept = float(model["intercept"])
        except Exception as exc:
            self.reason = f"malformed weights: {exc}"
            return

        n = len(FEATURE_NAMES)
        if not (coef.shape[0] == mean.shape[0] == scale.shape[0] == n):
            self.reason = "weight/feature length mismatch"
            return

        # avoid division by zero in scaler
        scale = np.where(scale == 0.0, 1.0, scale)

        self._coef = coef
        self._intercept = intercept
        self._mean = mean
        self._scale = scale
        self.available = True

    def score_one(self, features):
        """features: length-8 sequence. Returns float 0..1, or None on error."""
        if not self.available:
            return None
        try:
            x = np.asarray(features, dtype=np.float64).reshape(-1)
            if x.shape[0] != self._coef.shape[0]:
                return None
            xs = (x - self._mean) / self._scale
            z = float(np.dot(xs, self._coef) + self._intercept)
            return float(1.0 / (1.0 + np.exp(-z)))
        except Exception:
            return None


_classifier = None


def _get_classifier():
    global _classifier
    if _classifier is None:
        _classifier = Classifier()
    return _classifier


def score_boxes(merged, diff, image_area, registration_n_inliers, diff_threshold_used):
    """Score every merged box's reliability.

    merged: list[(x,y,w,h,area[,source])]. Returns list[float|None] (per-box None on
    compute error) if a model is available, else None for the whole list.
    """
    clf = _get_classifier()
    if not clf.available:
        return None

    scores = []
    for box in merged:
        try:
            feats = extract_features(
                box, diff, merged, image_area, registration_n_inliers, diff_threshold_used
            )
            scores.append(clf.score_one(feats))
        except Exception:
            scores.append(None)
    return scores
