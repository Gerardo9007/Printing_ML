# Print-Plate Defect Viewer — Architecture Spec

Contract for a local dev web service wrapping the existing `task1-print-plate` Python pipeline.
Two developers and two designers build against this doc without further coordination.

- Backend: FastAPI (Python), port **8000**
- Frontend: Next.js (App Router) + React, port **3000**
- No auth, no database. Results stored on the filesystem under a per-run id.
- Scope: `task1-print-plate` ONLY.

Absolute project root (contains Korean chars — always use `imgio` unicode helpers, never bare `cv2.imread`):
`C:\Users\amore\Desktop\26년 AP Claude Play Ground\08 Printing ML`

---

## 1. Directory layout

```
webapp/
  ARCHITECTURE.md                 # this file
  backend/
    main.py                       # FastAPI app: routes, CORS, static mount, uvicorn entry
    pipeline_bridge.py            # imports existing task1 modules; runs registration+diff; computes metrics
    schemas.py                    # pydantic response models (see §3)
    storage.py                    # per-run result dir mgmt under RESULTS_ROOT
    requirements.txt              # fastapi, uvicorn[standard], python-multipart, opencv-python, numpy
    results/                      # runtime output, one subdir per run id (gitignored)
      {id}/
        reference.png
        aligned.png
        diff_mask.png
        detections.png            # annotated image (draw_boxes output)
        result.json               # cached AnalyzeResponse
  frontend/
    package.json                  # next, react, react-dom
    next.config.js                # rewrites /api/* -> http://localhost:8000/api/* (see §5)
    app/
      layout.tsx                  # root layout, global providers
      page.tsx                    # "/"  upload page
      results/[id]/page.tsx       # "/results/:id" results view
      globals.css
    components/
      UploadForm.tsx              # file inputs + submit -> POST /api/analyze
      ResultView.tsx              # annotated image + metrics + detection list container
      AnnotatedImage.tsx          # renders detections.png (via image_urls.detections)
      DetectionList.tsx           # table/list of DetectionItem
      MetricsPanel.tsx            # summary metrics + oversized/critical warnings
    lib/
      api.ts                      # typed fetch wrappers + TS types mirroring §3 schemas
```

---

## 2. Reusing the existing pipeline

**Strategy: `sys.path` insertion in one bridge module. Do NOT copy or subprocess.**

`backend/pipeline_bridge.py` prepends the absolute task1 dir to `sys.path`, then imports the
prototype modules directly and calls them as a library. The prototype stays the single source of
truth (no drift from copying; no fragile stdout parsing from subprocessing `run_demo.py`).

```python
# pipeline_bridge.py
import os, sys
TASK1_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "docs", "dev", "task1-print-plate"
)
TASK1_DIR = os.path.abspath(TASK1_DIR)
if TASK1_DIR not in sys.path:
    sys.path.insert(0, TASK1_DIR)

import registration          # align_to_reference(reference, moving, min_matches=15)
import diff_detect           # compute_diff_mask(...), draw_boxes(img, boxes)
import run_demo              # evaluate_recall(...), compute_precision_proxy(...)
from imgio import imread_unicode, imwrite_unicode
```

Verified signatures the bridge depends on (do not guess — these are exact):

- `registration.align_to_reference(reference_bgr, moving_bgr, min_matches=15)`
  → `(aligned_bgr, method_str, info_dict)`. `method_str` ∈ {`"orb_homography"`, `"ecc_euclidean"`, `"none (registration failed, using raw image)"`}. `info_dict` may contain `n_inliers` (orb) or `warp_matrix` (ecc); may include `H` (drop before JSON).
- `diff_detect.compute_diff_mask(reference_bgr, aligned_bgr, min_area=40)`
  → `(mask_uint8, boxes, diff_uint8, info)`.
  - `boxes`: `list[(x, y, w, h, area)]` ints.
  - `info`: `{threshold: float, image_area: int, box_area_ratios: list[float], oversized_flags: list[bool], any_oversized: bool, oversize_area_ratio: float}` (indices align with `boxes`).
- `diff_detect.draw_boxes(img_bgr, boxes)` → annotated BGR image.
- `run_demo.evaluate_recall(detected_boxes, ground_truth, oversized_flags=...)`
  → `list[{type, tag, note, detected, reliable_detected, overlap_score, used_line_level_gt}]`.
- `run_demo.compute_precision_proxy(detected_boxes, ground_truth)`
  → `{precision_proxy: float, total_detected_area: int, gt_overlap_area: int}`.

**Ground-truth (recall/precision) is only available when a stored reference has an associated GT
JSON.** Arbitrary user uploads have no GT, so recall/precision are `null` in that case; the
diff-based metrics (threshold, oversized flags, detection count) are ALWAYS computed. See §3.

The bridge core function (developer 1 implements the body):

```python
def analyze(reference_bgr, defective_bgr, run_dir, ground_truth=None, min_area=40) -> dict:
    aligned, method, info = registration.align_to_reference(reference_bgr, defective_bgr)
    mask, boxes, diff, diff_info = diff_detect.compute_diff_mask(reference_bgr, aligned, min_area=min_area)
    vis = diff_detect.draw_boxes(aligned.copy(), boxes)
    # imwrite_unicode reference/aligned/diff_mask/detections into run_dir
    # build detections[] from boxes + diff_info (per-index oversized_flag, area_ratio)
    # metrics: always diff-based; recall/precision only if ground_truth is not None
    return { ... matches AnalyzeResponse ... }
```

A stored default reference lives at `docs/dev/task1-print-plate/output/01_reference.png` with GT at
`.../output/00_ground_truth.json` (produced by `generate_labels`). If those files are absent,
`GET /api/health` reports `default_reference_available: false` and the frontend hides the
"compare against stored reference" option. The backend must NOT run `generate_labels` on request.

---

## 3. REST API contract

Base URL `http://localhost:8000`. All JSON is UTF-8. All endpoints under `/api`.

### `GET /api/health`
200 →
```json
{
  "status": "ok",
  "default_reference_available": true
}
```

### `POST /api/analyze`
`multipart/form-data` fields:

| field       | type            | required | notes |
|-------------|-----------------|----------|-------|
| `defective` | file (image)    | yes      | the image to inspect |
| `reference` | file (image)    | no       | if omitted, use stored default reference (must exist per health) |
| `min_area`  | text (int)      | no       | default `40`; min connected-component area |

Behavior: if `reference` omitted and default reference has GT, recall/precision are computed;
otherwise (user-supplied reference, or no GT) they are `null`.

**200 response — `AnalyzeResponse`:**
```json
{
  "id": "a1b2c3d4",
  "registration": {
    "method": "orb_homography",
    "n_inliers": 312
  },
  "detections": [
    {
      "index": 0,
      "bbox": { "x": 120, "y": 240, "w": 60, "h": 28 },
      "area": 1680,
      "area_ratio": 0.0123,
      "oversized": false
    }
  ],
  "metrics": {
    "n_detections": 1,
    "diff_threshold": 64.4,
    "any_oversized": false,
    "oversize_area_ratio_guard": 0.20,
    "recall": 1.0,
    "reliable_recall": 1.0,
    "precision_proxy": 0.82,
    "n_defects_total": 3,
    "n_defects_detected": 3,
    "n_defects_reliably_detected": 3,
    "critical_missed": false,
    "per_defect": [
      {
        "type": "성분표시오류",
        "note": "…",
        "detected": true,
        "reliable_detected": true,
        "overlap_score": 0.41,
        "used_line_level_gt": false
      }
    ]
  },
  "image_urls": {
    "reference":  "/api/results/a1b2c3d4/reference.png",
    "aligned":    "/api/results/a1b2c3d4/aligned.png",
    "diff_mask":  "/api/results/a1b2c3d4/diff_mask.png",
    "detections": "/api/results/a1b2c3d4/detections.png"
  }
}
```

Field types / rules:
- `id`: string (8-char hex or uuid4 hex).
- `registration.method`: string; `registration.n_inliers`: int or `null` (present only for orb).
- `detections[]`: always present (empty list if none). `index` int, `bbox` ints, `area` int,
  `area_ratio` float (0–1), `oversized` bool. Order matches pipeline `boxes` order.
- `metrics.diff_threshold`, `any_oversized`, `oversize_area_ratio_guard`, `n_detections`: ALWAYS present.
- `metrics.recall`, `reliable_recall`, `precision_proxy`, `n_defects_*`, `critical_missed`,
  `per_defect`: `null` (recall/precision/counts) or `[]` (`per_defect`) when no GT is available.
  `critical_missed` = true if any `type == "성분표시오류"` defect is not `reliable_detected`.
- `image_urls.*`: relative URLs served by the endpoint below (frontend prefixes with backend origin
  via the rewrite in §5, so use them as-is).

**Errors** (see §5 error format): `400` missing `defective`, or `reference` omitted while no default
reference exists; `415` unreadable/undecodable image; `500` pipeline exception.

### `GET /api/results/{id}/{filename}`
Serves a stored PNG for a run. `filename` ∈ {`reference.png`, `aligned.png`, `diff_mask.png`,
`detections.png`}. Content-Type `image/png`. `404` if id or file unknown.
**Chosen over base64** to keep JSON small and let the browser cache/lazy-load images.
`filename` MUST be validated against the fixed allow-list above (no path traversal).

### `GET /api/results/{id}`
Returns the cached `AnalyzeResponse` for a prior run (frontend loads `/results/:id` directly).
`404` if unknown.

---

## 4. Frontend page structure

### Route `/` — Upload (`app/page.tsx` → `UploadForm.tsx`)
- Two file inputs: **Defective image** (required), **Reference image** (optional).
- If `health.default_reference_available`, show a toggle "Compare against stored reference"; when on,
  the reference input is hidden and `reference` is omitted from the request.
- Optional advanced field: `min_area` (number, default 40).
- Client-side image preview for selected files.
- Submit → `POST /api/analyze`. On 200, `router.push('/results/' + resp.id)` and stash the response
  (via sessionStorage or refetch through `GET /api/results/{id}`). On error, render the `error.message`.

### Route `/results/[id]` — Results (`app/results/[id]/page.tsx` → `ResultView.tsx`)
- On mount, if no stashed response, fetch `GET /api/results/{id}`.
- Layout: `MetricsPanel` (top), `AnnotatedImage` (main), `DetectionList` (side/below).
- **`MetricsPanel`**: shows `n_detections`, `diff_threshold`, registration `method`/`n_inliers`.
  If GT present: recall / reliable_recall / precision_proxy + `n_defects_*`. Prominent warning banner
  when `any_oversized` (unreliable/oversized detection) and a red banner when `critical_missed`.
  When metrics are `null`, show "No ground truth — detection-only mode".
- **`AnnotatedImage`**: `<img src={image_urls.detections}>`; provide tabs/toggle to also view
  `reference`, `aligned`, `diff_mask`.
- **`DetectionList`**: one row per `detections[]` item — index, bbox (x,y,w,h), area, area_ratio %,
  and an "oversized / unreliable" badge when `oversized`. If GT present, also list `per_defect` with
  detected / reliable_detected / overlap_score and highlight rows where `type == "성분표시오류"`.

`lib/api.ts` exposes `getHealth()`, `analyze(form)`, `getResult(id)` with TS types mirroring §3.

---

## 5. Shared conventions

- **Ports**: backend `8000`, frontend `3000`.
- **CORS**: backend enables `CORSMiddleware` with `allow_origins=["http://localhost:3000"]`,
  `allow_methods=["*"]`, `allow_headers=["*"]`. Additionally, `frontend/next.config.js` rewrites
  `/api/:path*` → `http://localhost:8000/api/:path*` so the browser calls same-origin `/api/...`
  (image URLs in responses work without hardcoding the backend host).
- **Error format** (all non-2xx JSON):
  ```json
  { "error": { "code": "BAD_REQUEST", "message": "human readable text" } }
  ```
  `code` ∈ {`BAD_REQUEST`, `UNSUPPORTED_MEDIA`, `NOT_FOUND`, `INTERNAL`}. HTTP status set
  accordingly (400/415/404/500). Implement via a FastAPI exception handler.
- **Image encoding**: read uploads with `imgio.imread_unicode`-style decode
  (`cv2.imdecode(np.frombuffer(bytes))`) and write results with `imwrite_unicode` — the repo path
  contains Korean characters, so bare `cv2.imread/imwrite` will fail.
- **Result lifecycle**: results persist on disk under `backend/results/{id}`; no TTL/cleanup for this
  demo. `backend/results/` is gitignored.
- **Content-Type**: JSON responses `application/json; charset=utf-8`; images `image/png`.
- **Run backend**: `uvicorn main:app --reload --port 8000` from `webapp/backend/`.
- **Run frontend**: `npm run dev` (Next on 3000) from `webapp/frontend/`.
