"""Pydantic response models mirroring ARCHITECTURE.md §3."""

from typing import List, Optional

from pydantic import BaseModel


class BBox(BaseModel):
    x: int
    y: int
    w: int
    h: int


class DetectionItem(BaseModel):
    index: int
    bbox: BBox
    area: int
    area_ratio: float
    oversized: bool
    source: str = "pixel_diff"                  # "pixel_diff" | "ocr_diff" | "both"
    reliability_score: Optional[float] = None   # 0..1 from classifier; null if model absent


class RegistrationInfo(BaseModel):
    method: str
    n_inliers: Optional[int] = None


class PerDefect(BaseModel):
    type: str
    note: str
    detected: bool
    reliable_detected: bool
    overlap_score: float
    used_line_level_gt: bool
    ocr_text_before: Optional[str] = None   # reference line text; null if OCR not run/matched
    ocr_text_after: Optional[str] = None    # defective line text; null if OCR not run/matched


class Metrics(BaseModel):
    # Always present (diff-based)
    n_detections: int
    diff_threshold: float
    any_oversized: bool
    oversize_area_ratio_guard: float
    # GT-based; null / [] when no ground truth
    recall: Optional[float] = None
    reliable_recall: Optional[float] = None
    precision_proxy: Optional[float] = None
    n_defects_total: Optional[int] = None
    n_defects_detected: Optional[int] = None
    n_defects_reliably_detected: Optional[int] = None
    critical_missed: Optional[bool] = None
    per_defect: List[PerDefect] = []


class ImageUrls(BaseModel):
    reference: str
    aligned: str
    diff_mask: str
    detections: str


class AnalyzeResponse(BaseModel):
    id: str
    registration: RegistrationInfo
    detections: List[DetectionItem]
    metrics: Metrics
    image_urls: ImageUrls


class HealthResponse(BaseModel):
    status: str
    default_reference_available: bool


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody
