"""FastAPI app for the print-plate defect viewer.

Run from webapp/backend/:
    uvicorn main:app --reload --port 8000
"""

import json
from datetime import datetime

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

import pipeline_bridge
import storage

app = FastAPI(title="Print-Plate Defect Viewer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    return JSONResponse(
        status_code=exc.status,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    detail = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(p) for p in detail.get("loc", [])[1:]) or "요청"
    return JSONResponse(
        status_code=400,
        content={"error": {"code": "BAD_REQUEST", "message": f"필수 입력값 누락 또는 형식 오류: {field}"}},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL", "message": str(exc)}},
    )


def _decode_upload(data: bytes) -> np.ndarray:
    """Decode uploaded image bytes to a BGR array (unicode-path safe: never touches disk)."""
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ApiError(415, "UNSUPPORTED_MEDIA", "이미지를 디코딩할 수 없습니다 (지원하지 않는 형식).")
    return img


def _image_urls(run_id: str) -> dict:
    base = f"/api/results/{run_id}"
    return {
        "reference": f"{base}/reference.png",
        "aligned": f"{base}/aligned.png",
        "diff_mask": f"{base}/diff_mask.png",
        "detections": f"{base}/detections.png",
    }


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "default_reference_available": pipeline_bridge.default_reference_available(),
    }


@app.get("/api/history")
async def history():
    return {"history": storage.list_runs()}


@app.post("/api/analyze")
async def analyze(
    defective: UploadFile = File(...),
    reference: UploadFile | None = File(None),
    min_area: str | None = Form(None),
):
    defective_bytes = await defective.read()
    if not defective_bytes:
        raise ApiError(400, "BAD_REQUEST", "'defective' 이미지가 비어 있습니다.")
    defective_bgr = _decode_upload(defective_bytes)

    try:
        min_area_val = int(min_area) if min_area not in (None, "") else 40
    except ValueError:
        raise ApiError(400, "BAD_REQUEST", "'min_area'는 정수여야 합니다.")

    ground_truth = None
    reference_mode = "user_uploaded" if reference is not None else "stored_default"
    if reference is not None:
        reference_bytes = await reference.read()
        if not reference_bytes:
            raise ApiError(400, "BAD_REQUEST", "'reference' 이미지가 비어 있습니다.")
        reference_bgr = _decode_upload(reference_bytes)
    else:
        if not pipeline_bridge.default_reference_available():
            raise ApiError(
                400,
                "BAD_REQUEST",
                "'reference'가 없고 저장된 기본 참조 이미지도 존재하지 않습니다.",
            )
        reference_bgr = pipeline_bridge.imread_unicode(pipeline_bridge.DEFAULT_REFERENCE_PATH)
        if reference_bgr is None:
            raise ApiError(500, "INTERNAL", "기본 참조 이미지를 읽지 못했습니다.")
        if pipeline_bridge.default_gt_available():
            with open(pipeline_bridge.DEFAULT_GT_PATH, encoding="utf-8") as f:
                ground_truth = json.load(f)

    run_id, run_path = storage.create_run_dir()
    try:
        result = pipeline_bridge.analyze(
            reference_bgr, defective_bgr, run_path, ground_truth=ground_truth, min_area=min_area_val
        )
    except Exception as exc:
        raise ApiError(500, "INTERNAL", f"파이프라인 처리 중 오류: {exc}")

    response = {
        "id": run_id,
        "created_at": datetime.now().astimezone().isoformat(),
        "reference_mode": reference_mode,
        "registration": result["registration"],
        "detections": result["detections"],
        "metrics": result["metrics"],
        "image_urls": _image_urls(run_id),
    }
    storage.save_result_json(run_id, response)
    return response


@app.get("/api/results/{run_id}")
async def get_result(run_id: str):
    response = storage.load_result_json(run_id)
    if response is None:
        raise ApiError(404, "NOT_FOUND", f"결과를 찾을 수 없습니다: {run_id}")
    return response


@app.get("/api/results/{run_id}/{filename}")
async def get_result_image(run_id: str, filename: str):
    path = storage.result_image_path(run_id, filename)
    if path is None:
        raise ApiError(404, "NOT_FOUND", f"이미지를 찾을 수 없습니다: {run_id}/{filename}")
    return FileResponse(path, media_type="image/png")
