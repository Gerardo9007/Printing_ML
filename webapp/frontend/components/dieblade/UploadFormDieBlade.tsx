"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  dieBladeAnalyze,
  getDieBladeHealth,
  friendlyMessage,
  stashDieBladeResult,
  type HealthResponse,
} from "@/lib/api";

type HealthState =
  | { status: "pending" }
  | { status: "ok"; data: HealthResponse }
  | { status: "down" };

function FilePreview({ file }: { file: File }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    const objectUrl = URL.createObjectURL(file);
    setUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [file]);
  if (!url) return null;
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={url}
      alt={file.name}
      className="h-32 w-32 rounded-md border border-[var(--border-hairline)] object-cover"
    />
  );
}

export default function UploadFormDieBlade() {
  const router = useRouter();
  const [health, setHealth] = useState<HealthState>({ status: "pending" });

  const [actualFile, setActualFile] = useState<File | null>(null);
  const [referenceFile, setReferenceFile] = useState<File | null>(null);
  const [useStoredReference, setUseStoredReference] = useState(true);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  const actualInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let alive = true;
    getDieBladeHealth()
      .then((data) => {
        if (!alive) return;
        setHealth({ status: "ok", data });
        if (!data.default_reference_available) setUseStoredReference(false);
      })
      .catch(() => {
        if (alive) setHealth({ status: "down" });
      });
    return () => {
      alive = false;
    };
  }, []);

  const defaultRefAvailable =
    health.status === "ok" && health.data.default_reference_available;
  const referenceRequired = health.status === "ok" && !defaultRefAvailable;
  const needsUploadedReference = !useStoredReference || referenceRequired;

  const canSubmit =
    !!actualFile &&
    !submitting &&
    (!needsUploadedReference || !!referenceFile);

  function pickActual(file: File | null) {
    setActualFile(file);
    setError(null);
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) pickActual(file);
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!actualFile) {
      setError("요청 오류: 검사할 목형 이미지를 선택하세요.");
      return;
    }
    if (needsUploadedReference && !referenceFile) {
      setError(
        "요청 오류: 저장된 참조 도면이 없어 참조 도면을 직접 업로드해야 합니다."
      );
      return;
    }
    setSubmitting(true);
    try {
      const resp = await dieBladeAnalyze({
        actual: actualFile,
        reference: needsUploadedReference ? referenceFile : null,
      });
      stashDieBladeResult(resp);
      router.push(`/die-blade/results/${resp.id}`);
    } catch (err) {
      setError(friendlyMessage(err));
      setSubmitting(false);
    }
  }

  const statusDot =
    health.status === "ok"
      ? "bg-status-good"
      : health.status === "down"
      ? "bg-status-critical"
      : "bg-ink-muted animate-pulse";
  const statusLabel =
    health.status === "ok"
      ? "백엔드 연결됨"
      : health.status === "down"
      ? "백엔드 연결 안 됨"
      : "백엔드 확인 중…";

  return (
    <form
      onSubmit={onSubmit}
      className="space-y-6 rounded-xl border border-[var(--border-hairline)] bg-surface p-6"
    >
      <div className="flex items-center gap-2 text-sm text-ink-secondary">
        <span
          className={`inline-block h-2.5 w-2.5 rounded-full ${statusDot}`}
          aria-hidden
        />
        <span>{statusLabel}</span>
      </div>

      {/* Actual (captured) image — required — dropzone */}
      <div>
        <label className="mb-2 block text-sm font-medium text-ink-primary">
          촬영된 목형 이미지 <span className="text-status-critical">*</span>
        </label>
        <p className="mb-2 text-xs text-ink-muted">
          백라이트 실루엣 촬영을 가정합니다 (선/배경 이진 이미지). 컬러 사진을 올려도
          자동으로 이진화합니다.
        </p>
        <div className="flex items-start gap-4">
          <div
            role="button"
            tabIndex={0}
            onClick={() => !submitting && actualInputRef.current?.click()}
            onKeyDown={(e) => {
              if ((e.key === "Enter" || e.key === " ") && !submitting) {
                e.preventDefault();
                actualInputRef.current?.click();
              }
            }}
            onDragOver={(e) => {
              e.preventDefault();
              if (!submitting) setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={`flex-1 cursor-pointer rounded-xl border-2 border-dashed p-10 text-center transition-colors duration-150 ${
              dragging
                ? "border-accent border-solid bg-[var(--accent-tint-2)] ring-2 ring-accent ring-offset-2"
                : "border-[var(--border-strong)] bg-surface hover:border-accent hover:bg-[var(--accent-tint)]"
            } ${submitting ? "pointer-events-none opacity-60" : ""}`}
          >
            <p className="text-sm text-ink-secondary">
              {actualFile
                ? actualFile.name
                : "클릭하거나 이미지를 여기로 끌어다 놓으세요"}
            </p>
            <input
              ref={actualInputRef}
              type="file"
              accept="image/*"
              className="hidden"
              disabled={submitting}
              onChange={(e) => pickActual(e.target.files?.[0] ?? null)}
            />
          </div>
          {actualFile && <FilePreview file={actualFile} />}
        </div>
      </div>

      {/* Reference source */}
      <fieldset className="space-y-2" disabled={submitting}>
        {defaultRefAvailable && (
          <label className="flex items-center gap-2 text-sm text-ink-secondary">
            <input
              type="radio"
              name="refsource-dieblade"
              checked={useStoredReference}
              onChange={() => setUseStoredReference(true)}
            />
            저장된 기준 도면과 비교
          </label>
        )}
        <label className="flex items-center gap-2 text-sm text-ink-secondary">
          <input
            type="radio"
            name="refsource-dieblade"
            checked={needsUploadedReference}
            disabled={referenceRequired}
            onChange={() => setUseStoredReference(false)}
          />
          기준 도면 직접 업로드
        </label>

        {referenceRequired && (
          <p className="text-xs text-ink-muted">
            저장된 기준 도면이 없어 도면을 직접 업로드해야 합니다.
          </p>
        )}

        {needsUploadedReference && (
          <div className="flex items-start gap-4 pt-1">
            <label className="flex-1">
              <span className="sr-only">기준 도면</span>
              <input
                type="file"
                accept="image/*"
                className="block w-full text-sm text-ink-secondary file:mr-3 file:rounded-md file:border file:border-[var(--border-hairline)] file:bg-surface file:px-3 file:py-1.5 file:text-sm file:text-ink-primary"
                onChange={(e) => setReferenceFile(e.target.files?.[0] ?? null)}
              />
            </label>
            {referenceFile && <FilePreview file={referenceFile} />}
          </div>
        )}
      </fieldset>

      {/* Advanced (assumptions, read-only info) */}
      <div className="border-t border-[var(--border-hairline)] pt-4">
        <button
          type="button"
          onClick={() => setAdvancedOpen((v) => !v)}
          className="text-sm text-ink-secondary hover:text-ink-primary"
        >
          {advancedOpen ? "▾" : "▸"} 가정값 확인
        </button>
        {advancedOpen && (
          <ul className="mt-3 space-y-1 text-xs text-ink-muted">
            <li>1px = 0.2mm 촬영 스케일 캘리브레이션 (가정값)</li>
            <li>결함 판정 허용 오차 1.0mm, 정합 신뢰도 잔차 허용치 2.0mm</li>
            <li>마모 등급 경계: 정상&lt;0.3mm, 주의&lt;0.8mm, 교체≥0.8mm (가정값)</li>
            <li>위치오차 허용치 5.0mm — 초과 시 지그 안착 자체를 불량으로 판정</li>
          </ul>
        )}
      </div>

      {error && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-md border border-status-critical bg-[color-mix(in_srgb,var(--status-critical)_8%,var(--surface-1))] px-4 py-3 text-sm text-ink-primary"
        >
          <span aria-hidden>⚠</span>
          <span>{error}</span>
        </div>
      )}

      {submitting && (
        <div
          className="progress-indeterminate relative h-1 w-full overflow-hidden rounded bg-[var(--accent-tint)]"
          role="progressbar"
          aria-label="분석 중"
        />
      )}

      <div className="flex justify-end">
        <button
          type="submit"
          disabled={!canSubmit}
          title={!actualFile ? "목형 이미지를 선택하세요" : undefined}
          className="inline-flex items-center gap-2 rounded-md bg-accent px-5 py-2.5 text-sm font-semibold text-white transition-opacity disabled:cursor-not-allowed disabled:opacity-50"
        >
          {submitting && (
            <span
              className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent"
              aria-hidden
            />
          )}
          {submitting ? "분석 중…" : "분석"}
        </button>
      </div>
    </form>
  );
}
