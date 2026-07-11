"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  analyze,
  getHealth,
  friendlyMessage,
  stashResult,
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

export default function UploadForm() {
  const router = useRouter();
  const [health, setHealth] = useState<HealthState>({ status: "pending" });

  const [defectiveFile, setDefectiveFile] = useState<File | null>(null);
  const [referenceFile, setReferenceFile] = useState<File | null>(null);
  // true => compare against the stored default reference (hide the upload input)
  const [useStoredReference, setUseStoredReference] = useState(true);
  const [minArea, setMinArea] = useState(40);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  const defectiveInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let alive = true;
    getHealth()
      .then((data) => {
        if (!alive) return;
        setHealth({ status: "ok", data });
        // No stored reference => force user-supplied reference, hide the toggle.
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
  // When no stored reference exists, the reference upload is required.
  const referenceRequired = health.status === "ok" && !defaultRefAvailable;
  const needsUploadedReference = !useStoredReference || referenceRequired;

  const canSubmit =
    !!defectiveFile &&
    !submitting &&
    (!needsUploadedReference || !!referenceFile);

  function pickDefective(file: File | null) {
    setDefectiveFile(file);
    setError(null);
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) pickDefective(file);
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!defectiveFile) {
      setError("요청 오류: 검사할 결함 이미지를 선택하세요.");
      return;
    }
    if (needsUploadedReference && !referenceFile) {
      setError(
        "요청 오류: 저장된 참조 이미지가 없어 참조 이미지를 직접 업로드해야 합니다."
      );
      return;
    }
    setSubmitting(true);
    try {
      const resp = await analyze({
        defective: defectiveFile,
        reference: needsUploadedReference ? referenceFile : null,
        minArea,
      });
      stashResult(resp);
      router.push(`/results/${resp.id}`);
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

      {/* Defective image (required) — dropzone */}
      <div>
        <label className="mb-2 block text-sm font-medium text-ink-primary">
          결함 이미지 <span className="text-status-critical">*</span>
        </label>
        <div className="flex items-start gap-4">
          <div
            role="button"
            tabIndex={0}
            onClick={() => !submitting && defectiveInputRef.current?.click()}
            onKeyDown={(e) => {
              if ((e.key === "Enter" || e.key === " ") && !submitting) {
                e.preventDefault();
                defectiveInputRef.current?.click();
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
              {defectiveFile
                ? defectiveFile.name
                : "클릭하거나 이미지를 여기로 끌어다 놓으세요"}
            </p>
            <input
              ref={defectiveInputRef}
              type="file"
              accept="image/*"
              className="hidden"
              disabled={submitting}
              onChange={(e) => pickDefective(e.target.files?.[0] ?? null)}
            />
          </div>
          {defectiveFile && <FilePreview file={defectiveFile} />}
        </div>
      </div>

      {/* Reference source */}
      <fieldset className="space-y-2" disabled={submitting}>
        {defaultRefAvailable && (
          <label className="flex items-center gap-2 text-sm text-ink-secondary">
            <input
              type="radio"
              name="refsource"
              checked={useStoredReference}
              onChange={() => setUseStoredReference(true)}
            />
            저장된 참조 이미지와 비교
          </label>
        )}
        <label className="flex items-center gap-2 text-sm text-ink-secondary">
          <input
            type="radio"
            name="refsource"
            checked={needsUploadedReference}
            disabled={referenceRequired}
            onChange={() => setUseStoredReference(false)}
          />
          참조 이미지 직접 업로드
        </label>

        {referenceRequired && (
          <p className="text-xs text-ink-muted">
            저장된 참조 이미지가 없어 참조 이미지를 직접 업로드해야 합니다.
          </p>
        )}

        {needsUploadedReference && (
          <div className="flex items-start gap-4 pt-1">
            <label className="flex-1">
              <span className="sr-only">참조 이미지</span>
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

      {/* Advanced */}
      <div className="border-t border-[var(--border-hairline)] pt-4">
        <button
          type="button"
          onClick={() => setAdvancedOpen((v) => !v)}
          className="text-sm text-ink-secondary hover:text-ink-primary"
        >
          {advancedOpen ? "▾" : "▸"} 고급 설정
        </button>
        {advancedOpen && (
          <div className="mt-3 flex items-center gap-2">
            <label htmlFor="minArea" className="text-sm text-ink-secondary">
              min_area
            </label>
            <input
              id="minArea"
              type="number"
              min={1}
              value={minArea}
              disabled={submitting}
              onChange={(e) => setMinArea(Number(e.target.value) || 40)}
              className="w-24 rounded-md border border-[var(--border-hairline)] bg-surface px-2 py-1 text-sm text-ink-primary tabular-nums"
            />
          </div>
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
          title={!defectiveFile ? "결함 이미지를 선택하세요" : undefined}
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
