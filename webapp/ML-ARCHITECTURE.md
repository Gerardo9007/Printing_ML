# Print-Plate ML Extension — Architecture Spec

Extension contract for the two ML initiatives from `docs/planning/task1-print-plate-ml-plan.md`:
- **Initiative A (P0)** — OCR line-level text diff → extra defect boxes (`ocr_diff.py`)
- **Initiative B (P1)** — false-positive / reliability classifier scoring each box (`reliability.py`)

This EXTENDS `webapp/ARCHITECTURE.md`; it does not replace it. Every field added here is
**optional and degrades gracefully**: OCR and the classifier are built incrementally by different
teammates, so the pipeline must produce a valid `AnalyzeResponse` whether or not either is present.
Read `webapp/ARCHITECTURE.md` §2–§3 first — the existing contract (detections[], metrics, per_defect,
image_urls) stays exactly as-is; we only ADD fields.

The data analyst (trains the classifier) and the developer (integrates OCR + inference) must both
conform to §4 (training-data contract) and §5 (feature vector) **exactly** — those two sections are
the load-bearing cross-team interface.

---

## 1. New modules and where they live

```
webapp/
  backend/
    ocr_diff.py          # NEW  Initiative A runtime: OCR each line, string-diff, emit boxes + text
    reliability.py       # NEW  Initiative B runtime: FEATURE_NAMES + extract_features + Classifier
    ml/                  # NEW  committed runtime inference artifacts (small, no training deps)
      reliability_model.json   # LogisticRegression weights+scaler exported to plain JSON
      reliability_meta.json    # feature_names order, model type, train date, decision threshold
    pipeline_bridge.py   # EXTEND analyze() call sequence (see §3)
    schemas.py           # EXTEND with 3 optional fields (see §2)
    requirements.txt     # ADD easyocr  (do NOT add scikit-learn/lightgbm — see below)
  ml-training/           # NEW  top-level, NOT part of the runtime backend package
    requirements.txt     # scikit-learn, lightgbm, easyocr, pandas  (heavy; training only)
    generate_dataset.py  # extends generate_labels to emit the training CSV (see §4)
    train_reliability.py # trains classifier, exports to backend/ml/*.json
    data/                # generated datasets (gitignored)
      reliability_dataset.csv
      dataset_manifest.json
```

### Runtime dependency decision (important)
- **The runtime backend DOES need `easyocr`** — OCR runs at inference time for every analyze call
  (Initiative A). Add it to `backend/requirements.txt`. First run downloads model weights to the
  EasyOCR cache; document offline pre-warm in the developer task.
- **The runtime backend does NOT need scikit-learn or lightgbm.** The Phase-1 classifier is a
  `LogisticRegression` whose fitted coefficients + `StandardScaler` mean/scale are exported to plain
  JSON (`ml/reliability_model.json`). `reliability.py` reloads them and scores with pure numpy
  (`1/(1+exp(-(x_scaled·w + b)))`). This keeps the runtime image light and matches the plan's
  "경량 의존성" philosophy.
- If Initiative B later graduates to LightGBM or a CNN (plan §4.4 stretch goal), the runtime WILL
  need that library. That is an explicit future decision — the JSON-export path is the committed
  Phase-1 contract. `reliability.py` branches on `reliability_meta.json["model_type"]`.

### Feature-extraction single source of truth
`extract_features()` and `FEATURE_NAMES` live in **`webapp/backend/reliability.py` only**. The
training script imports them via the same `sys.path` bridge the backend already uses:

```python
# ml-training/generate_dataset.py / train_reliability.py
import os, sys
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, BACKEND_DIR)
from reliability import FEATURE_NAMES, extract_features   # the ONE definition both sides use
```

This is what guarantees the trained feature order and the inference feature order can never drift.

---

## 2. Schema additions (`schemas.py`)

Three new optional fields. All default to a graceful "not-ready" value so a partial rollout stays valid.

```python
class DetectionItem(BaseModel):
    index: int
    bbox: BBox
    area: int
    area_ratio: float
    oversized: bool
    # --- NEW ---
    source: str = "pixel_diff"                 # "pixel_diff" | "ocr_diff" | "both"
    reliability_score: Optional[float] = None  # 0..1 from classifier; null if model absent

class PerDefect(BaseModel):
    type: str
    note: str
    detected: bool
    reliable_detected: bool
    overlap_score: float
    used_line_level_gt: bool
    # --- NEW ---
    ocr_text_before: Optional[str] = None      # reference line text; null if OCR not run/matched
    ocr_text_after:  Optional[str] = None       # defective line text; null if OCR not run/matched
```

Default / degradation rules:
- `source`: **`"pixel_diff"`** for every box produced by the existing diff path. `"ocr_diff"` for a
  box that came only from OCR. `"both"` when a pixel box and an OCR box merged into one (§3 merge).
  When OCR is not available, every box is `"pixel_diff"` — the field is always a valid string, never null.
- `reliability_score`: **`null`** whenever the classifier artifact is missing or fails to load, OR
  the model is present but a feature can't be computed for a box. Never raises. Frontend treats
  `null` as "score unavailable" (no badge), distinct from a low score.
- `ocr_text_before` / `ocr_text_after`: **`null`** when OCR did not run, or when no OCR line could be
  matched to that defect. Non-null only when both a before and after line text are available.
- `oversized` (existing) is UNCHANGED and stays the rule-based dual guardrail per plan §4.1 — the
  classifier does not replace it. A box can be `oversized=true` and also carry a `reliability_score`.

The frontend (designer) interpretation, documented for `visual-design-system.md`:
`reliability_score < 0.5` → amber "확인 필요" badge; `null` → no reliability badge; `oversized`
badge remains separate and independent.

---

## 3. `pipeline_bridge.analyze()` call sequence

Exact order (new steps marked ★):

1. `aligned, method, info = registration.align_to_reference(reference_bgr, defective_bgr)`
2. `mask, pixel_boxes, diff, diff_info = diff_detect.compute_diff_mask(reference_bgr, aligned, min_area=min_area)`
   — `pixel_boxes` are `(x,y,w,h,area)`; `diff` is the uint8 absdiff (needed for features in §5).
3. ★ **OCR branch (parallel data source):**
   `ocr_boxes, ocr_lines = ocr_diff.detect_text_diffs(reference_bgr, aligned)`
   - `ocr_boxes`: `list[(x,y,w,h,area)]` — same tuple shape as `pixel_boxes`, in aligned coords.
   - `ocr_lines`: `list[{"bbox_xyxy": [..], "text_before": str, "text_after": str}]` — the raw
     line-level diffs, used later to fill `per_defect.ocr_text_*`.
   - If EasyOCR import/inference fails or is disabled, return `([], [])`. Never raise.
4. ★ **Merge with provenance:**
   `merged = ocr_diff.merge_with_source(pixel_boxes, ocr_boxes, max_gap=25)`
   → `list[(x,y,w,h,area, source)]`. See merge semantics below.
5. ★ **Recompute area ratios + oversized flags on the merged list** (the box set changed, so
   `diff_info["oversized_flags"]` from step 2 no longer aligns). Reuse the exact same formula as
   `diff_detect.compute_diff_mask`:
   ```python
   image_area = diff_info["image_area"]
   guard = diff_info["oversize_area_ratio"]  # 0.20
   box_area_ratios = [(w*h)/image_area if image_area else 0.0 for (_,_,w,h,_,_) in merged]
   oversized_flags = [r > guard for r in box_area_ratios]
   ```
6. ★ **Reliability scoring:**
   `scores = reliability.score_boxes(merged, diff, image_area, n_inliers, diff_info["threshold"])`
   → `list[float] | None`. Returns `None` (whole list) if the model artifact is absent; otherwise one
   score per box. Per-box compute errors yield `None` for that box only.
7. **Assemble `detections[]`** from `merged` + `box_area_ratios` + `oversized_flags` + `scores`,
   adding `source` and `reliability_score` (null when `scores is None` or `scores[i] is None`).
8. **Metrics / per_defect** exactly as today, but evaluate on the merged boxes:
   `evaluate_recall(merged_xywha, ground_truth, oversized_flags=oversized_flags)` where
   `merged_xywha` strips the trailing `source` element back to `(x,y,w,h,area)`.
   Then fill `ocr_text_before/after` per defect (see below).
9. **Visualization + persistence** unchanged: `draw_boxes(aligned.copy(), merged_xywha)` → detections.png,
   plus reference/aligned/diff_mask as today.

### Merge semantics (`ocr_diff.merge_with_source`)
`diff_detect.merge_close_boxes(boxes, max_gap=25)` takes `list[(x,y,w,h,area)]`, greedily unions any
two rects within `max_gap` px, and returns merged `(x,y,w,h,area)` — it carries **no** source tag, so
it cannot be used directly for two provenance-tagged lists. Reuse its geometry primitives
(`diff_detect._rects_close`, `diff_detect._union`) but track source:

```
1. Tag inputs: pixel_boxes -> source "pixel_diff", ocr_boxes -> source "ocr_diff".
2. Greedy union (same loop as merge_close_boxes) over the combined list, using _rects_close(a,b,25).
3. When two boxes union: new source = "both" if the two sources differ, else the shared source.
   ("pixel"+"pixel"->"pixel", "ocr"+"ocr"->"ocr", "pixel"+"ocr"->"both", and "both" is absorbing.)
4. Recompute area = w*h for each unioned rect (same as merge_close_boxes).
Return list[(x,y,w,h,area, source)].
```
Rationale: an OCR-only box that never touches a pixel box stays `"ocr_diff"` (catches the point-missing
case pixel-diff structurally misses, plan G-01); a genuine defect flagged by both paths becomes
`"both"` and is the highest-confidence signal.

### Filling `per_defect.ocr_text_before/after`
For each `per_defect` entry (one per GT `injected_defect`), take the defect's GT bbox
(`d["bbox"]` else `defect_line_boxes[tag]`), find the `ocr_lines` entry whose `bbox_xyxy` overlaps it
most (reuse `run_demo._overlap_fraction` logic), and copy that line's `text_before`/`text_after`.
No `ocr_lines`, or best overlap `== 0` → leave both `null`.

---

## 4. Training-data bootstrap contract (the load-bearing interface)

The data analyst's `ml-training/generate_dataset.py` emits **one CSV row per detection box** produced
by running the pipeline over many synthetic defect/misalignment combinations (plan §4.3 Phase A).
Labels are auto-assigned: a box that overlaps any GT defect region (`run_demo._overlap_fraction > 0.05`,
the same threshold `evaluate_recall` uses) is `label=1` (reliable/real); a box overlapping no GT
region — i.e. a registration-residual / oversize false positive — is `label=0`.

### File: `ml-training/data/reliability_dataset.csv`
Header (exact column order):
```
schema_version,run_id,box_index,source,area_ratio,aspect_ratio,mean_diff_intensity,std_diff_intensity,edge_density,n_nearby_boxes,registration_n_inliers,diff_threshold_used,gt_overlap_fraction,label
```
- Columns `area_ratio … diff_threshold_used` are **exactly `FEATURE_NAMES` in order** (§5). They MUST
  be produced by calling the shared `extract_features()` — not recomputed independently — so training
  and inference are byte-for-byte identical.
- `schema_version`: integer, currently `1`. Bump if `FEATURE_NAMES` changes; training refuses to load
  a CSV whose version ≠ the code's `FEATURE_SCHEMA_VERSION`.
- `source`, `run_id`, `box_index`, `gt_overlap_fraction`: provenance/debug only, NOT fed to the model.
- `label`: 0 or 1.

### File: `ml-training/data/dataset_manifest.json`
```json
{
  "schema_version": 1,
  "feature_names": ["area_ratio","aspect_ratio","mean_diff_intensity","std_diff_intensity",
                    "edge_density","n_nearby_boxes","registration_n_inliers","diff_threshold_used"],
  "n_rows": 0, "n_positive": 0, "n_negative": 0,
  "generated_at": "ISO-8601", "generator": "generate_dataset.py",
  "notes": "auto-labeled via overlap_fraction>0.05 against GT"
}
```

### Trained artifact handoff — `backend/ml/reliability_model.json` + `reliability_meta.json`
`train_reliability.py` fits `StandardScaler` + `LogisticRegression`, then writes:
```json
// reliability_model.json
{ "coef": [w0..w7], "intercept": b, "scaler_mean": [..8..], "scaler_scale": [..8..] }
// reliability_meta.json
{ "model_type": "logreg_json", "schema_version": 1,
  "feature_names": [ ...same 8, same order... ],
  "decision_threshold": 0.5, "trained_at": "ISO-8601",
  "train_rows": 0, "val_precision": 0.0, "val_recall": 0.0 }
```
`reliability.py` on load **asserts `meta["feature_names"] == FEATURE_NAMES` and
`meta["schema_version"] == FEATURE_SCHEMA_VERSION`**; on mismatch it logs and disables scoring
(returns `None`) rather than producing silently-wrong scores.

---

## 5. Feature vector spec

**Resolution of the plan §4.2 "7 features" ambiguity:** the table lists 7 *rows*, but one row
(`mean_diff_intensity, std_diff_intensity`) names two scalars, so there are **8 scalar features** —
**6 per-box** + **2 global** (repeated onto every box's row). The canonical, frozen order is:

```python
# reliability.py
FEATURE_SCHEMA_VERSION = 1
FEATURE_NAMES = [
    "area_ratio",            # per-box
    "aspect_ratio",          # per-box
    "mean_diff_intensity",   # per-box
    "std_diff_intensity",    # per-box
    "edge_density",          # per-box
    "n_nearby_boxes",        # per-box
    "registration_n_inliers",# global (same value on every box in a run)
    "diff_threshold_used",   # global
]
```

Signature (single source of truth, imported by training):
```python
def extract_features(box, diff, all_boxes, image_area, registration_n_inliers, diff_threshold_used):
    # box = (x, y, w, h, area[, source]); all_boxes = full merged list (for n_nearby_boxes)
    # returns list[float] length 8 in FEATURE_NAMES order
```

Exact computation (all `cv2`/`numpy`, raw units — the stored `StandardScaler` handles normalization):

| # | feature | computation | notes |
|---|---------|-------------|-------|
| 0 | `area_ratio` | `(w*h) / image_area` | reuse diff_detect's `box_area_ratios` value; 0 if `image_area==0` |
| 1 | `aspect_ratio` | `w / h` | `h` guaranteed ≥1 (connected-component bbox); guard `h==0 → 0.0` |
| 2 | `mean_diff_intensity` | `float(crop.mean())` | `crop = diff[y:y+h, x:x+w]`, the uint8 absdiff from `compute_diff_mask`; 0..255 |
| 3 | `std_diff_intensity` | `float(crop.std())` | same crop; local uniform noise → low, real defect → high/localized |
| 4 | `edge_density` | `float(cv2.Laplacian(crop, cv2.CV_64F).var())` | Laplacian variance of the **diff crop** region; guard crops with <2px side → `0.0` |
| 5 | `n_nearby_boxes` | count of OTHER boxes in `all_boxes` within `nearby_gap=25` px (edge-to-edge, via `_rects_close`) | reproducible proxy for plan's "merge history"; `max_gap` matches merge's 25px so it approximates how many neighbors would have merged |
| 6 | `registration_n_inliers` | `int(info.get("n_inliers", 0))` | global; **0** for `ecc_euclidean` / `none` (no inliers reported) — document 0 as the "no-orb" sentinel |
| 7 | `diff_threshold_used` | `float(diff_info["threshold"])` | global; the robust threshold — low values are the QA [발견 1] root-cause signal |

Crop is always taken from the aligned-coords `diff` image (the same one returned by
`compute_diff_mask`). All values coerced to Python `float` for JSON/CSV safety.

---

## 6. Incremental-rollout invariants (what "degrades gracefully" means concretely)

| State | `detections[].source` | `reliability_score` | `per_defect.ocr_text_*` | Response valid? |
|-------|----------------------|---------------------|--------------------------|-----------------|
| Neither A nor B built yet | all `"pixel_diff"` | all `null` | all `null` | ✅ identical to today + defaulted fields |
| OCR (A) only | `pixel_diff`/`ocr_diff`/`both` | all `null` | populated when matched | ✅ |
| Classifier (B) only | all `"pixel_diff"` | 0..1 per box | all `null` | ✅ |
| Both A + B | full provenance | 0..1 per box | populated | ✅ |

`pipeline_bridge.analyze()` must never raise because OCR or the model is missing — both branches
catch import/load failure and fall back to empty/`None`. The regression set (QA [발견 1] single
성분표시오류 case + README 5-defect demo) stays the fixed acceptance gate after every change.
