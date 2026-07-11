"use client";

import type { DetectionItem, Metrics } from "@/lib/api";

const CRITICAL_TYPE = "성분표시오류";

const SOURCE_BADGE: Record<
  DetectionItem["source"],
  { classes: string; icon: string; label: string }
> = {
  pixel_diff: {
    classes:
      "inline-flex items-center gap-1 rounded-full border border-[var(--border-strong)] px-2 py-0.5 text-xs font-medium text-ink-secondary",
    icon: "▦",
    label: "픽셀",
  },
  ocr_diff: {
    classes:
      "inline-flex items-center gap-1 rounded-full border border-[var(--source-ocr)] px-2 py-0.5 text-xs font-medium text-ink-primary",
    icon: "🔤",
    label: "OCR",
  },
  both: {
    classes:
      "inline-flex items-center gap-1 rounded-full border border-accent bg-[var(--accent-tint)] px-2 py-0.5 text-xs font-semibold text-ink-primary",
    icon: "✓✓",
    label: "둘 다",
  },
};

function ReliabilityIndicator({ score }: { score: number | null }) {
  if (score == null) return null;
  if (score >= 0.5) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-ink-secondary">
        <span
          className="inline-block h-2 w-2 rounded-full bg-[var(--reliability-ok)]"
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

export default function DetectionList({
  detections,
  metrics,
  selectedIndex,
  onSelectDetection,
  onHoverDetection,
}: {
  detections: DetectionItem[];
  metrics: Metrics;
  selectedIndex: number | null;
  onSelectDetection: (index: number) => void;
  onHoverDetection: (index: number | null) => void;
}) {
  const hasGt = metrics.recall != null;

  return (
    <section className="space-y-6">
      {/* Detections table (always) */}
      <div>
        <h2 className="mb-2 text-lg font-semibold text-ink-primary">
          검출 목록
        </h2>
        <div className="overflow-x-auto rounded-lg border border-[var(--border-hairline)] bg-surface">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-[var(--border-hairline)] text-xs uppercase tracking-wide text-ink-muted">
                <th className="px-4 py-2">#</th>
                <th className="px-4 py-2">bbox (x,y,w,h)</th>
                <th className="px-4 py-2">area</th>
                <th className="px-4 py-2">ratio</th>
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
                    검출된 영역이 없습니다.
                  </td>
                </tr>
              )}
              {detections.map((d) => {
                const selected = d.index === selectedIndex;
                return (
                  <tr
                    key={d.index}
                    onClick={() => onSelectDetection(d.index)}
                    onMouseEnter={() => onHoverDetection(d.index)}
                    onMouseLeave={() => onHoverDetection(null)}
                    className={`cursor-pointer border-b border-[var(--border-hairline)] last:border-0 hover:bg-[var(--accent-tint)] ${
                      selected ? "bg-[var(--accent-tint-2)]" : ""
                    }`}
                  >
                    <td className="px-4 py-3 font-mono text-sm tabular-nums text-ink-secondary">
                      {d.index}
                    </td>
                    <td className="px-4 py-3 font-mono text-sm tabular-nums text-ink-secondary">
                      {d.bbox.x}, {d.bbox.y}, {d.bbox.w}, {d.bbox.h}
                    </td>
                    <td className="px-4 py-3 font-mono text-sm tabular-nums text-ink-secondary">
                      {d.area}
                    </td>
                    <td className="px-4 py-3 font-mono text-sm tabular-nums text-ink-secondary">
                      {(d.area_ratio * 100).toFixed(2)}%
                    </td>
                    <td className="px-4 py-3">
                      <ReliabilityIndicator score={d.reliability_score} />
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center gap-2">
                        <span className={SOURCE_BADGE[d.source].classes}>
                          <span aria-hidden>{SOURCE_BADGE[d.source].icon}</span>
                          {SOURCE_BADGE[d.source].label}
                        </span>
                        {d.oversized && (
                          <span className="inline-flex items-center gap-1 rounded-full border border-status-warning px-2 py-0.5 text-xs font-medium text-ink-primary">
                            <span aria-hidden>⚠</span> 오검출
                          </span>
                        )}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Per-defect table (GT only) */}
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
                  <th className="px-4 py-2">reliable</th>
                  <th className="px-4 py-2">overlap</th>
                  <th className="px-4 py-2">OCR diff</th>
                </tr>
              </thead>
              <tbody>
                {metrics.per_defect.map((p, i) => {
                  const critical =
                    p.type === CRITICAL_TYPE && !p.reliable_detected;
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
                      <td className="px-4 py-3 text-sm">
                        {p.reliable_detected ? (
                          <span className="text-ink-primary">
                            <span aria-hidden>✓</span> 예
                          </span>
                        ) : (
                          <span className="text-ink-muted">
                            <span aria-hidden>✕</span> 아니오
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 font-mono text-sm tabular-nums text-ink-secondary">
                        {p.overlap_score.toFixed(2)}
                      </td>
                      <td className="px-4 py-3">
                        {p.ocr_text_before != null && p.ocr_text_after != null && (
                          <>
                            <span className="font-mono text-xs text-ink-secondary">
                              {p.ocr_text_before}
                            </span>
                            <span className="mx-1 text-ink-muted" aria-hidden>
                              →
                            </span>
                            <span className="font-mono text-xs font-semibold text-ink-primary">
                              {p.ocr_text_after}
                            </span>
                          </>
                        )}
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
