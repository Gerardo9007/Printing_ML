"use client";

import type { Metrics, Registration } from "@/lib/api";

function pct(v: number | null): string {
  return v == null ? "—" : `${(v * 100).toFixed(1)}%`;
}

function Tile({
  label,
  value,
  na = false,
  suffix,
}: {
  label: string;
  value: string;
  na?: boolean;
  suffix?: string;
}) {
  return (
    <div
      className={`flex flex-col gap-1 rounded-lg border bg-surface p-4 ${
        na ? "border-dashed border-[var(--border-strong)]" : "border-[var(--border-hairline)]"
      }`}
    >
      <span className="text-xs uppercase tracking-wide text-ink-secondary">
        {label}
        {na && suffix && (
          <span className="ml-1 normal-case text-ink-muted">· {suffix}</span>
        )}
      </span>
      <span
        className={`text-3xl font-bold tabular-nums ${
          na ? "text-ink-muted" : "text-ink-primary"
        }`}
      >
        {value}
      </span>
    </div>
  );
}

export default function MetricsPanel({
  registration,
  metrics,
}: {
  registration: Registration;
  metrics: Metrics;
}) {
  const hasGt = metrics.recall != null;
  const methodValue =
    registration.method +
    (registration.n_inliers != null ? ` (${registration.n_inliers})` : "");

  return (
    <section className="space-y-4">
      <h2 className="text-lg font-semibold text-ink-primary">지표</h2>

      {metrics.critical_missed === true && (
        <div className="flex items-center gap-2 rounded-md border border-status-critical bg-[color-mix(in_srgb,var(--status-critical)_12%,var(--surface-1))] px-4 py-2 font-semibold text-ink-primary">
          <span aria-hidden>⛔</span>
          <span>치명 결함(성분표시오류) 미검출!</span>
        </div>
      )}

      {metrics.any_oversized && (
        <div className="flex items-center gap-2 rounded-md border border-status-warning bg-[color-mix(in_srgb,var(--status-warning)_12%,var(--surface-1))] px-4 py-2 text-ink-primary">
          <span aria-hidden>⚠</span>
          <span>
            오검출 가드레일 발동 — 검출 영역이 비정상적으로 큽니다
          </span>
        </div>
      )}

      {!hasGt && (
        <div className="flex items-center gap-2 rounded-md border border-[var(--border-strong)] bg-surface px-4 py-2 text-sm text-ink-secondary">
          <span aria-hidden>ℹ</span>
          <span>N/A — 참조 GT 없음 (탐지 전용 모드)</span>
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        {/* Always present */}
        <Tile label="검출 수" value={String(metrics.n_detections)} />
        <Tile
          label="Diff threshold"
          value={metrics.diff_threshold.toFixed(1)}
        />
        <div className="flex flex-col gap-1 rounded-lg border border-[var(--border-hairline)] bg-surface p-4">
          <span className="text-xs uppercase tracking-wide text-ink-secondary">
            정합 방법
          </span>
          <span className="font-mono text-sm text-ink-primary">
            {methodValue}
          </span>
        </div>

        {/* GT-dependent — always render slots to avoid layout jump */}
        <Tile
          label="Recall"
          value={pct(metrics.recall)}
          na={!hasGt}
          suffix="no ground truth"
        />
        <Tile
          label="Reliable recall"
          value={pct(metrics.reliable_recall)}
          na={!hasGt}
          suffix="no ground truth"
        />
        <Tile
          label="Precision (proxy)"
          value={pct(metrics.precision_proxy)}
          na={!hasGt}
          suffix="no ground truth"
        />
        <Tile
          label="결함 검출"
          value={
            hasGt
              ? `${metrics.n_defects_detected} / ${metrics.n_defects_total}`
              : "—"
          }
          na={!hasGt}
          suffix="no ground truth"
        />
      </div>
    </section>
  );
}
