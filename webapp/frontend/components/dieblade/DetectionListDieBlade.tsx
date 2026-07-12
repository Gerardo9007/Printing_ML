"use client";

import type { DieBladeDetectionItem, DieBladeMetrics } from "@/lib/api";

const CRITICAL_KINDS = ["휨", "끊김"];

function isCritical(kind: string): boolean {
  return CRITICAL_KINDS.includes(kind) || kind.startsWith("복합");
}

// 0.4, not 0.5 — matches reliability_dieblade_meta.json's decision_threshold
// (train_reliability_dieblade.py picked 0.4 as the precision==recall balance
// point; spec.md's "치명 결함 미검출 0" priority favors recall here).
const RELIABILITY_THRESHOLD = 0.4;

function ReliabilityIndicator({ score }: { score: number | null }) {
  if (score == null) return null;
  if (score >= RELIABILITY_THRESHOLD) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-ink-secondary">
        <span
          className="inline-block h-2 w-2 rounded-full bg-status-good"
          aria-hidden
        />
        {score.toFixed(2)}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-status-warning px-2 py-0.5 text-xs font-medium text-ink-primary">
      <span aria-hidden>⚠</span> 확인 필요 ({score.toFixed(2)})
    </span>
  );
}

export default function DetectionListDieBlade({
  detections,
  metrics,
  selectedIndex,
  onSelectDetection,
  onHoverDetection,
}: {
  detections: DieBladeDetectionItem[];
  metrics: DieBladeMetrics;
  selectedIndex: number | null;
  onSelectDetection: (index: number) => void;
  onHoverDetection: (index: number | null) => void;
}) {
  const hasGt = metrics.recall != null;

  return (
    <section className="space-y-6">
      <div>
        <h2 className="mb-2 text-lg font-semibold text-ink-primary">
          검출 목록
        </h2>
        <div className="overflow-x-auto rounded-lg border border-[var(--border-hairline)] bg-surface">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-[var(--border-hairline)] text-xs uppercase tracking-wide text-ink-muted">
                <th className="px-4 py-2">#</th>
                <th className="px-4 py-2">유형</th>
                <th className="px-4 py-2">bbox (x,y,w,h)</th>
                <th className="px-4 py-2">편차/길이</th>
                <th className="px-4 py-2">reliability</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {detections.length === 0 && (
                <tr>
                  <td
                    colSpan={6}
                    className="px-4 py-6 text-center text-sm text-ink-muted"
                  >
                    검출된 결함이 없습니다.
                  </td>
                </tr>
              )}
              {detections.map((d) => {
                const selected = d.index === selectedIndex;
                const critical = isCritical(d.kind);
                return (
                  <tr
                    key={d.index}
                    onClick={() => onSelectDetection(d.index)}
                    onMouseEnter={() => onHoverDetection(d.index)}
                    onMouseLeave={() => onHoverDetection(null)}
                    className={`cursor-pointer border-b border-[var(--border-hairline)] last:border-0 hover:bg-[var(--accent-tint)] ${
                      selected ? "bg-[var(--accent-tint-2)]" : ""
                    } ${
                      critical
                        ? "border-l-4 border-l-status-critical"
                        : ""
                    }`}
                  >
                    <td className="px-4 py-3 font-mono text-sm tabular-nums text-ink-secondary">
                      {d.index}
                    </td>
                    <td className="px-4 py-3 text-sm font-medium text-ink-primary">
                      {d.kind}
                      {d.wear_grade && (
                        <span className="ml-2 inline-flex items-center gap-1 rounded-full border border-[var(--border-strong)] px-2 py-0.5 text-xs font-medium text-ink-secondary">
                          {d.wear_grade}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 font-mono text-sm tabular-nums text-ink-secondary">
                      {d.bbox.x}, {d.bbox.y}, {d.bbox.w}, {d.bbox.h}
                    </td>
                    <td className="px-4 py-3 font-mono text-sm tabular-nums text-ink-secondary">
                      {d.mean_deviation_mm > 0
                        ? `평균 ${d.mean_deviation_mm}mm`
                        : `${d.max_deviation_mm}mm`}
                      {d.arc_length_mm > 0 && ` / ${d.arc_length_mm}mm`}
                    </td>
                    <td className="px-4 py-3">
                      <ReliabilityIndicator score={d.reliability_score} />
                    </td>
                    <td className="px-4 py-3 text-xs text-ink-muted">
                      {d.note}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {hasGt && metrics.per_defect.length > 0 && (
        <div>
          <h2 className="mb-2 text-lg font-semibold text-ink-primary">
            결함별 검출 현황
          </h2>
          <div className="overflow-x-auto rounded-lg border border-[var(--border-hairline)] bg-surface">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-[var(--border-hairline)] text-xs uppercase tracking-wide text-ink-muted">
                  <th className="px-4 py-2">type</th>
                  <th className="px-4 py-2">detected</th>
                  <th className="px-4 py-2">note</th>
                </tr>
              </thead>
              <tbody>
                {metrics.per_defect.map((p, i) => {
                  const critical = isCritical(p.type) && !p.detected;
                  return (
                    <tr
                      key={i}
                      className={`border-b border-[var(--border-hairline)] last:border-0 ${
                        critical
                          ? "border-l-4 border-l-status-critical bg-[color-mix(in_srgb,var(--status-critical)_8%,var(--surface-1))]"
                          : ""
                      }`}
                    >
                      <td className="px-4 py-3 text-sm text-ink-primary">
                        {p.type}
                        {critical && (
                          <span className="ml-2 inline-flex items-center gap-1 rounded-full border border-status-critical px-2 py-0.5 text-xs font-medium text-ink-primary">
                            <span aria-hidden>⛔</span> 미검출
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-sm">
                        {p.detected ? (
                          <span className="text-ink-primary">
                            <span aria-hidden>✓</span> 예
                          </span>
                        ) : (
                          <span className="text-ink-muted">
                            <span aria-hidden>✕</span> 아니오
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-xs text-ink-secondary">
                        {p.note}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
