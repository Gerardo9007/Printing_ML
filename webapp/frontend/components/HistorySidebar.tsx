"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { getHistory, type HistoryItem } from "@/lib/api";

type State =
  | { status: "loading" }
  | { status: "ok"; items: HistoryItem[] }
  | { status: "error" };

// "2026-07-09T10:15:00+09:00" -> "07-09 10:15"; null/invalid -> "—"
function shortTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(
    d.getMinutes()
  )}`;
}

function StatusBadge({ item }: { item: HistoryItem }) {
  if (item.critical_missed === true) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-status-critical px-1.5 py-0.5 text-[10px] font-medium text-ink-primary">
        <span aria-hidden>⛔</span> 치명 미검출
      </span>
    );
  }
  if (item.any_oversized) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-status-warning px-1.5 py-0.5 text-[10px] font-medium text-ink-primary">
        <span aria-hidden>⚠</span> 오검출
      </span>
    );
  }
  if (item.recall != null) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-[var(--border-strong)] px-1.5 py-0.5 text-[10px] font-medium text-ink-primary">
        <span aria-hidden>✓</span> recall {(item.recall * 100).toFixed(0)}%
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-full border border-dashed border-[var(--border-strong)] px-1.5 py-0.5 text-[10px] font-medium text-ink-muted">
      GT 없음
    </span>
  );
}

export default function HistorySidebar() {
  const pathname = usePathname();
  const [state, setState] = useState<State>({ status: "loading" });
  const [open, setOpen] = useState(true);

  // Current results id, if on a results page, for highlighting.
  const match = pathname?.match(/^\/results\/([^/]+)/);
  const currentId = match ? decodeURIComponent(match[1]) : null;

  // Refetch on every route change so a just-created run appears.
  useEffect(() => {
    let alive = true;
    getHistory()
      .then((items) => {
        if (alive) setState({ status: "ok", items });
      })
      .catch(() => {
        if (alive) setState({ status: "error" });
      });
    return () => {
      alive = false;
    };
  }, [pathname]);

  return (
    <aside className="print:hidden border-r border-[var(--border-hairline)] bg-surface">
      <div className="flex items-center justify-between gap-2 px-4 py-3">
        <h2 className="text-sm font-semibold text-ink-primary">분석 이력</h2>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="text-xs text-ink-muted hover:text-ink-primary md:hidden"
          aria-expanded={open}
        >
          {open ? "접기" : "펼치기"}
        </button>
      </div>

      <div className={`${open ? "block" : "hidden"} md:block md:w-72`}>
        {state.status === "loading" && (
          <ul className="space-y-2 px-3 pb-4">
            {Array.from({ length: 3 }).map((_, i) => (
              <li
                key={i}
                className="h-16 animate-pulse rounded-md border border-[var(--border-hairline)] bg-[var(--accent-tint)]"
              />
            ))}
          </ul>
        )}

        {state.status === "error" && (
          <p className="px-4 pb-4 text-xs text-ink-muted">
            이력을 불러올 수 없습니다.
          </p>
        )}

        {state.status === "ok" && state.items.length === 0 && (
          <p className="px-4 pb-4 text-sm text-ink-muted">
            아직 분석 이력이 없습니다.
          </p>
        )}

        {state.status === "ok" && state.items.length > 0 && (
          <ul className="space-y-1 px-3 pb-4">
            {state.items.map((item) => {
              const active = item.id === currentId;
              return (
                <li key={item.id}>
                  <Link
                    href={`/results/${item.id}`}
                    className={`flex gap-3 rounded-md border p-2 transition-colors ${
                      active
                        ? "border-accent bg-[var(--accent-tint-2)]"
                        : "border-transparent hover:bg-[var(--accent-tint)]"
                    }`}
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={item.thumbnail_url}
                      alt=""
                      className="h-12 w-12 flex-shrink-0 rounded border border-[var(--border-hairline)] object-cover"
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-mono text-xs text-ink-secondary">
                          {shortTime(item.created_at)}
                        </span>
                        <span className="text-[10px] text-ink-muted">
                          검출 {item.n_detections}
                        </span>
                      </div>
                      <div className="mt-1 flex items-center gap-1">
                        <StatusBadge item={item} />
                      </div>
                    </div>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </aside>
  );
}
