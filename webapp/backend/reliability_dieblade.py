"""Die-blade Initiative B runtime: false-positive / reliability classifier scoring.

Mirrors reliability.py (task1) exactly in spirit: FEATURE_NAMES + extract_features
here are the single source of truth both the training script and this runtime
import, so trained/inference feature order can never drift. Scoring is a plain-
numpy logistic regression loaded from committed JSON artifacts (backend/ml/
reliability_dieblade_model.json + _meta.json). No scikit-learn at runtime.

Why a SEPARATE classifier from task1's reliability.py: the detection shape is
completely different here — no bbox-vs-text pixel diff, but four heterogeneous
defect kinds (휨/끊김/마모/위치오차) each carrying mm-based deviation/arc-length
fields, plus global registration-residual/position-shift context. A single set
of features has to span all four kinds, so kind is one-hot encoded rather than
inferred from a `source` tag like task1's pixel/ocr/both.
"""

import json
import os

import numpy as np

FEATURE_SCHEMA_VERSION = 1
FEATURE_NAMES = [
    "area_ratio",               # per-box: bbox area / image area
    "aspect_ratio",             # per-box: w/h
    "max_deviation_mm",         # per-box
    "mean_deviation_mm",        # per-box (0 for non-마모 kinds)
    "arc_length_mm",            # per-box (0 for 위치오차)
    "n_nearby_defects",         # per-box: other detections within a small gap
    "registration_residual_mm", # global (same value on every box in a run)
    "position_shift_mm",        # global: ECC-absorbed shift, from classify_position_error
    "is_bend",                  # kind one-hot (복합 sets both is_bend and is_break)
    "is_break",
    "is_wear",
    "is_position",
]

_NEARBY_GAP = 20  # px; matches detect_defects' merge_kernel radius roughly (15,15) with margin

_MODEL_PATH = os.path.join(os.path.dirname(__file__), "ml", "reliability_dieblade_model.json")
_META_PATH = os.path.join(os.path.dirname(__file__), "ml", "reliability_dieblade_meta.json")


def _rects_close(a, b, gap: float) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (
        ax - gap > bx + bw or bx - gap > ax + aw or
        ay - gap > by + bh or by - gap > ay + ah
    )


def _kind_flags(kind: str) -> tuple[float, float, float, float]:
    is_bend = 1.0 if (kind == "휨" or kind.startswith("복합")) else 0.0
    is_break = 1.0 if (kind == "끊김" or kind.startswith("복합")) else 0.0
    is_wear = 1.0 if kind == "마모" else 0.0
    is_position = 1.0 if kind == "위치오차" else 0.0
    return is_bend, is_break, is_wear, is_position


def extract_features(detection: dict, all_detections: list, image_area: float,
                      registration_residual_mm: float, position_shift_mm: float) -> list:
    """Return a length-12 list[float] in FEATURE_NAMES order.

    ``detection``/``all_detections``: dicts shaped like pipeline_bridge_dieblade's
    ``detections[]`` entries (kind, bbox, max_deviation_mm, mean_deviation_mm,
    arc_length_mm). Never raises on a degenerate box.
    """
    bbox = detection["bbox"]
    w, h = int(bbox["w"]), int(bbox["h"])
    area_ratio = (w * h) / image_area if image_area else 0.0
    aspect_ratio = (w / h) if h > 0 else 0.0

    rect = (bbox["x"], bbox["y"], w, h)
    n_nearby = 0
    for other in all_detections:
        if other is detection:
            continue
        ob = other["bbox"]
        orect = (ob["x"], ob["y"], ob["w"], ob["h"])
        if orect == rect:
            continue
        if _rects_close(rect, orect, _NEARBY_GAP):
            n_nearby += 1

    is_bend, is_break, is_wear, is_position = _kind_flags(detection["kind"])

    return [
        float(area_ratio),
        float(aspect_ratio),
        float(detection["max_deviation_mm"]),
        float(detection["mean_deviation_mm"]),
        float(detection["arc_length_mm"]),
        float(n_nearby),
        float(registration_residual_mm),
        float(position_shift_mm),
        is_bend,
        is_break,
        is_wear,
        is_position,
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

        scale = np.where(scale == 0.0, 1.0, scale)

        self._coef = coef
        self._intercept = intercept
        self._mean = mean
        self._scale = scale
        self.available = True

    def score_one(self, features):
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


def score_boxes(detections: list, image_area: float, registration_residual_mm: float,
                position_shift_mm: float):
    """Score every detection's reliability.

    Returns list[float|None] (per-box None on compute error) if a model is
    available, else None for the whole list (progressive enhancement).
    """
    clf = _get_classifier()
    if not clf.available:
        return None

    scores = []
    for d in detections:
        try:
            feats = extract_features(d, detections, image_area, registration_residual_mm, position_shift_mm)
            scores.append(clf.score_one(feats))
        except Exception:
            scores.append(None)
    return scores
