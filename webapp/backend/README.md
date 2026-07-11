# Print-Plate Defect Viewer — Backend

FastAPI service wrapping the existing `task1-print-plate` registration + diff pipeline.
Implements the contract in `../ARCHITECTURE.md`.

## Setup

From `webapp/backend/`:

```bash
pip install -r requirements.txt
```

## Run

```bash
uvicorn main:app --reload --port 8000
```

Server listens on `http://localhost:8000`. CORS is open to `http://localhost:3000`.

## Endpoints

- `GET  /api/health` → `{ "status": "ok", "default_reference_available": bool }`
- `POST /api/analyze` (multipart) — fields: `defective` (file, required),
  `reference` (file, optional), `min_area` (int text, optional, default 40).
  Returns `AnalyzeResponse` (see ARCHITECTURE.md §3).
- `GET  /api/results/{id}` → cached `AnalyzeResponse`.
- `GET  /api/results/{id}/{filename}` → PNG, `filename` ∈
  {`reference.png`, `aligned.png`, `diff_mask.png`, `detections.png`}.

## Pipeline reuse

`pipeline_bridge.py` prepends the absolute `docs/dev/task1-print-plate` dir to
`sys.path` and imports `registration`, `diff_detect`, `run_demo`, and `imgio`
directly — no copying, no subprocess. Uploads are decoded in-memory with
`cv2.imdecode` and results written with `imgio.imwrite_unicode` (the repo path
contains Korean characters, so bare `cv2.imread/imwrite` would fail).

## Ground-truth metrics

recall / precision / per-defect metrics are computed **only** when the analysis
runs against the stored default reference (`output/01_reference.png`) that has an
associated GT (`output/00_ground_truth.json`). For user-supplied references (no
GT), those fields are `null` / `[]`; the diff-based metrics (threshold,
detection count, oversized flags) are always present.

## Results

Stored under `results/{id}/` (gitignored). No TTL/cleanup for this demo.
