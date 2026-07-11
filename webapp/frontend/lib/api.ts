// Typed API client mirroring webapp/ARCHITECTURE.md §3.
// All requests go to same-origin /api/* which next.config.js rewrites to
// http://localhost:8000/api/*. image_urls in responses are already /api/... and
// are used verbatim.

export interface HealthResponse {
  status: string;
  default_reference_available: boolean;
}

export interface BBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

export type DetectionSource = "pixel_diff" | "ocr_diff" | "both";

export interface DetectionItem {
  index: number;
  bbox: BBox;
  area: number;
  area_ratio: number;
  oversized: boolean;
  source: DetectionSource;
  reliability_score: number | null;
}

export interface PerDefectItem {
  type: string;
  note: string;
  detected: boolean;
  reliable_detected: boolean;
  overlap_score: number;
  used_line_level_gt: boolean;
  ocr_text_before: string | null;
  ocr_text_after: string | null;
}

export interface Registration {
  method: string;
  n_inliers: number | null;
}

export interface Metrics {
  // Always present (diff-based).
  n_detections: number;
  diff_threshold: number;
  any_oversized: boolean;
  oversize_area_ratio_guard: number;
  // GT-dependent — null when no ground truth is available.
  recall: number | null;
  reliable_recall: number | null;
  precision_proxy: number | null;
  n_defects_total: number | null;
  n_defects_detected: number | null;
  n_defects_reliably_detected: number | null;
  critical_missed: boolean | null;
  per_defect: PerDefectItem[];
}

export interface ImageUrls {
  reference: string;
  aligned: string;
  diff_mask: string;
  detections: string;
}

export interface AnalyzeResponse {
  id: string;
  registration: Registration;
  detections: DetectionItem[];
  metrics: Metrics;
  image_urls: ImageUrls;
}

export type ReferenceMode = "stored_default" | "user_uploaded";

export interface HistoryItem {
  id: string;
  // Contract says always present, but backend may emit null for older runs.
  created_at: string | null;
  reference_mode: ReferenceMode | null;
  n_detections: number;
  recall: number | null;
  reliable_recall: number | null;
  critical_missed: boolean | null;
  any_oversized: boolean;
  thumbnail_url: string;
}

export interface HistoryResponse {
  history: HistoryItem[];
}

export type ApiErrorCode =
  | "BAD_REQUEST"
  | "UNSUPPORTED_MEDIA"
  | "NOT_FOUND"
  | "INTERNAL"
  | "NETWORK";

export class ApiError extends Error {
  code: ApiErrorCode;
  status: number | null;
  constructor(code: ApiErrorCode, message: string, status: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

async function parseError(res: Response): Promise<ApiError> {
  let code: ApiErrorCode = "INTERNAL";
  let message = `Request failed (${res.status})`;
  try {
    const body = await res.json();
    if (body && body.error) {
      if (body.error.code) code = body.error.code as ApiErrorCode;
      if (body.error.message) message = body.error.message;
    }
  } catch {
    // non-JSON error body; keep defaults
  }
  return new ApiError(code, message, res.status);
}

export async function getHealth(): Promise<HealthResponse> {
  let res: Response;
  try {
    res = await fetch("/api/health", { cache: "no-store" });
  } catch {
    throw new ApiError("NETWORK", "백엔드에 연결할 수 없습니다.");
  }
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export interface AnalyzeInput {
  defective: File;
  reference?: File | null;
  minArea?: number;
}

export async function analyze(input: AnalyzeInput): Promise<AnalyzeResponse> {
  const form = new FormData();
  form.append("defective", input.defective);
  if (input.reference) form.append("reference", input.reference);
  if (input.minArea != null) form.append("min_area", String(input.minArea));

  let res: Response;
  try {
    res = await fetch("/api/analyze", { method: "POST", body: form });
  } catch {
    throw new ApiError("NETWORK", "백엔드에 연결할 수 없습니다.");
  }
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function getResult(id: string): Promise<AnalyzeResponse> {
  let res: Response;
  try {
    res = await fetch(`/api/results/${encodeURIComponent(id)}`, { cache: "no-store" });
  } catch {
    throw new ApiError("NETWORK", "백엔드에 연결할 수 없습니다.");
  }
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function getHistory(): Promise<HistoryItem[]> {
  let res: Response;
  try {
    res = await fetch("/api/history", { cache: "no-store" });
  } catch {
    throw new ApiError("NETWORK", "백엔드에 연결할 수 없습니다.");
  }
  if (!res.ok) throw await parseError(res);
  const body = (await res.json()) as HistoryResponse;
  return body.history ?? [];
}

// Maps an ApiError to the user-facing Korean message per ux-wireframes.md §Error.
export function friendlyMessage(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case "BAD_REQUEST":
        return `요청 오류: ${err.message}`;
      case "UNSUPPORTED_MEDIA":
        return `이미지를 읽을 수 없습니다: ${err.message}`;
      case "INTERNAL":
        return `서버 오류가 발생했습니다: ${err.message}`;
      case "NOT_FOUND":
        return err.message;
      case "NETWORK":
        return "백엔드에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요.";
    }
  }
  return "알 수 없는 오류가 발생했습니다.";
}

// sessionStorage stash helpers so ResultView renders instantly after submit,
// falling back to GET /api/results/{id} on a direct link visit.
const stashKey = (id: string) => `result:${id}`;

export function stashResult(resp: AnalyzeResponse): void {
  try {
    sessionStorage.setItem(stashKey(resp.id), JSON.stringify(resp));
  } catch {
    // storage may be unavailable/full; refetch path covers it
  }
}

export function readStashedResult(id: string): AnalyzeResponse | null {
  try {
    const raw = sessionStorage.getItem(stashKey(id));
    return raw ? (JSON.parse(raw) as AnalyzeResponse) : null;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// 과제② 목형 칼날검사 (die-blade) — 별도 파이프라인/응답 모양, 별도 네임스페이스
// ---------------------------------------------------------------------------

export type DieBladeKind = "휨" | "끊김" | "마모" | "위치오차" | string; // "복합(휨+끊김 의심)" 등도 포함

export interface DieBladeDetectionItem {
  index: number;
  kind: DieBladeKind;
  bbox: BBox;
  area_px: number;
  max_deviation_mm: number;
  arc_length_mm: number;
  mean_deviation_mm: number; // 마모(G3)만 의미 있음; 그 외 0
  wear_grade: string; // "정상" | "주의" | "교체"; 마모 외에는 빈 문자열
  note: string;
  reliability_score: number | null; // 0..1 from classifier; null if model absent
}

export interface DieBladeRegistration {
  converged: boolean;
  residual_mm: number;
  reliable: boolean;
}

export interface DieBladePositionError {
  estimated_shift_px: number;
  estimated_shift_mm: number;
  estimated_angle_deg: number;
  tol_mm: number;
  is_position_error: boolean;
}

export interface DieBladePerDefectItem {
  type: DieBladeKind;
  note: string;
  detected: boolean;
  reliable_detected: boolean;
}

export interface DieBladeMetrics {
  n_detections: number;
  registration_converged: boolean;
  registration_residual_mm: number;
  registration_residual_tol_mm: number;
  registration_reliable: boolean;
  position_error: DieBladePositionError;
  detection_count_by_kind: Record<string, number>;
  recall: number | null;
  reliable_recall: number | null;
  n_defects_total: number | null;
  n_defects_detected: number | null;
  critical_missed: boolean | null;
  per_defect: DieBladePerDefectItem[];
}

export interface DieBladeImageUrls {
  reference: string;
  aligned: string;
  detections: string;
}

export interface DieBladeAnalyzeResponse {
  id: string;
  created_at: string | null;
  reference_mode: ReferenceMode | null;
  registration: DieBladeRegistration;
  detections: DieBladeDetectionItem[];
  metrics: DieBladeMetrics;
  image_urls: DieBladeImageUrls;
}

export interface DieBladeHistoryItem {
  id: string;
  created_at: string | null;
  reference_mode: ReferenceMode | null;
  n_detections: number;
  recall: number | null;
  critical_missed: boolean | null;
  registration_reliable: boolean | null;
  thumbnail_url: string;
}

export async function getDieBladeHealth(): Promise<HealthResponse> {
  let res: Response;
  try {
    res = await fetch("/api/die-blade/health", { cache: "no-store" });
  } catch {
    throw new ApiError("NETWORK", "백엔드에 연결할 수 없습니다.");
  }
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export interface DieBladeAnalyzeInput {
  actual: File;
  reference?: File | null;
}

export async function dieBladeAnalyze(
  input: DieBladeAnalyzeInput
): Promise<DieBladeAnalyzeResponse> {
  const form = new FormData();
  form.append("actual", input.actual);
  if (input.reference) form.append("reference", input.reference);

  let res: Response;
  try {
    res = await fetch("/api/die-blade/analyze", { method: "POST", body: form });
  } catch {
    throw new ApiError("NETWORK", "백엔드에 연결할 수 없습니다.");
  }
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function getDieBladeResult(id: string): Promise<DieBladeAnalyzeResponse> {
  let res: Response;
  try {
    res = await fetch(`/api/die-blade/results/${encodeURIComponent(id)}`, {
      cache: "no-store",
    });
  } catch {
    throw new ApiError("NETWORK", "백엔드에 연결할 수 없습니다.");
  }
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function getDieBladeHistory(): Promise<DieBladeHistoryItem[]> {
  let res: Response;
  try {
    res = await fetch("/api/die-blade/history", { cache: "no-store" });
  } catch {
    throw new ApiError("NETWORK", "백엔드에 연결할 수 없습니다.");
  }
  if (!res.ok) throw await parseError(res);
  const body = (await res.json()) as { history: DieBladeHistoryItem[] };
  return body.history ?? [];
}

const dieBladeStashKey = (id: string) => `dieblade-result:${id}`;

export function stashDieBladeResult(resp: DieBladeAnalyzeResponse): void {
  try {
    sessionStorage.setItem(dieBladeStashKey(resp.id), JSON.stringify(resp));
  } catch {
    // storage may be unavailable/full; refetch path covers it
  }
}

export function readStashedDieBladeResult(id: string): DieBladeAnalyzeResponse | null {
  try {
    const raw = sessionStorage.getItem(dieBladeStashKey(id));
    return raw ? (JSON.parse(raw) as DieBladeAnalyzeResponse) : null;
  } catch {
    return null;
  }
}
