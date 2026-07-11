"use client";

import type { DieBladeMetrics, DieBladeRegistration } from "@/lib/api";

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

export default function MetricsPanelDieBlade({
  registration,
  metrics,
}: {
  registration: DieBladeRegistration;
  metrics: DieBladeMetrics;
}) {
  const hasGt = metrics.recall != null;
  const pe = metrics.position_error;

  return (
    <section className="space-y-4">
      <h2 className="text-lg font-semibold text-ink-primary">지표</h2>

      {metrics.critical_missed === true && (
        <div className="flex items-center gap-2 rounded-md border border-status-critical bg-[color-mix(in_srgb,var(--status-critical)_12%,var(--surface-1))] px-4 py-2 font-semibold text-ink-primary">
          <span aria-hidden>⛔</span>
          <span>치명 결함(휨·끊김) 미검출!</span>
        </div>
      )}

      {!metrics.registration_reliable && (
        <div className="flex items-center gap-2 rounded-md border border-status-critical bg-[color-mix(in_srgb,var(--status-critical)_12%,var(--surface-1))] px-4 py-2 text-ink-primary">
          <span aria-hidden>⚠</span>
          <span>
            정합 신뢰 불가 — 대칭 오수렴 의심 (잔차 {metrics.registration_residual_mm}mm
            &gt; 허용 {metrics.registration_residual_tol_mm}mm). 사람이 재검해야 합니다.
          </span>
        </div>
      )}

      {pe.is_position_error && (
        <div className="flex items-center gap-2 rounded-md border border-status-warning bg-[color-mix(in_srgb,var(--status-warning)_12%,var(--surface-1))] px-4 py-2 text-ink-primary">
          <span aria-hidden>⚠</span>
          <span>
            위치오차 — 지그 안착 이동량 추정 {pe.estimated_shift_mm}mm (허용 {pe.tol_mm}mm 초과)
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
        <Tile label="검출 수" value={String(metrics.n_detections)} />
        <Tile
          label="정합 잔차"
          value={`${metrics.registration_residual_mm}mm`}
        />
        <div className="flex flex-col gap-1 rounded-lg border border-[var(--border-hairline)] bg-surface p-4">
          <span className="text-xs uppercase tracking-wide text-ink-secondary">
            정합 신뢰도
          </span>
          <span className="font-mono text-sm text-ink-primary">
            {metrics.registration_reliable ? "OK (신뢰 가능)" : "신뢰 불가"}
          </span>
        </div>
        <Tile
          label="위치오차 추정 이동량"
          value={`${pe.estimated_shift_mm}mm`}
        />

        <Tile
          label="Recall"
          value={pct(metrics.recall)}
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
        <Tile label="휨" value={String(metrics.detection_count_by_kind["휨"] ?? 0)} />
        <Tile label="끊김" value={String(metrics.detection_count_by_kind["끊김"] ?? 0)} />
        <Tile label="마모" value={String(metrics.detection_count_by_kind["마모"] ?? 0)} />
        <Tile label="위치오차" value={String(metrics.detection_count_by_kind["위치오차"] ?? 0)} />
      </div>
    </section>
  );
}
