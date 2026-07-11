"""Per-run result directory management under RESULTS_ROOT."""

import json
import os
import uuid
from datetime import datetime

RESULTS_ROOT = os.path.join(os.path.dirname(__file__), "results")

ALLOWED_FILENAMES = {"reference.png", "aligned.png", "diff_mask.png", "detections.png"}


def new_run_id() -> str:
    return uuid.uuid4().hex[:8]


def run_dir(run_id: str) -> str:
    return os.path.join(RESULTS_ROOT, run_id)


def create_run_dir() -> tuple[str, str]:
    run_id = new_run_id()
    path = run_dir(run_id)
    os.makedirs(path, exist_ok=True)
    return run_id, path


def save_result_json(run_id: str, response: dict) -> None:
    path = os.path.join(run_dir(run_id), "result.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(response, f, ensure_ascii=False, indent=2)


def load_result_json(run_id: str) -> dict | None:
    path = os.path.join(run_dir(run_id), "result.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def list_runs() -> list[dict]:
    """Summarize all stored runs for the history endpoint, newest-first.

    Skips run dirs with missing/corrupt result.json rather than erroring the whole
    endpoint. Sorts by created_at when present, else by the run dir mtime, so legacy
    runs (pre-created_at) still appear and interleave sanely.
    """
    if not os.path.isdir(RESULTS_ROOT):
        return []

    runs = []
    for run_id in os.listdir(RESULTS_ROOT):
        path = run_dir(run_id)
        if not os.path.isdir(path):
            continue
        try:
            data = load_result_json(run_id)
        except (json.JSONDecodeError, OSError):
            data = None
        if not data:
            continue

        metrics = data.get("metrics", {})
        created_at = data.get("created_at")
        try:
            sort_key = (
                datetime.fromisoformat(created_at).timestamp()
                if created_at
                else os.path.getmtime(path)
            )
        except (ValueError, OSError):
            sort_key = os.path.getmtime(path)

        runs.append(
            (
                sort_key,
                {
                    "id": data.get("id", run_id),
                    "created_at": created_at,
                    "reference_mode": data.get("reference_mode"),
                    "n_detections": metrics.get("n_detections"),
                    "recall": metrics.get("recall"),
                    "reliable_recall": metrics.get("reliable_recall"),
                    "critical_missed": metrics.get("critical_missed"),
                    "any_oversized": metrics.get("any_oversized"),
                    "thumbnail_url": f"/api/results/{data.get('id', run_id)}/detections.png",
                },
            )
        )

    runs.sort(key=lambda r: r[0], reverse=True)
    return [summary for _, summary in runs]


def result_image_path(run_id: str, filename: str) -> str | None:
    """Return the on-disk path for a run image, or None if invalid/missing.

    ``filename`` is validated against a fixed allow-list to prevent path traversal.
    """
    if filename not in ALLOWED_FILENAMES:
        return None
    path = os.path.join(run_dir(run_id), filename)
    if not os.path.isfile(path):
        return None
    return path
