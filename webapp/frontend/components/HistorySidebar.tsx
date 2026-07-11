"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  getHistory,
  getDieBladeHistory,
  type HistoryItem,
  type DieBladeHistoryItem,
} from "@/lib/api";

type State =
  | { status: "loading" }
  | { status: "ok"; items: HistoryItem[] }
  | { status: "error" };

type DieBladeState =
  | { status: "loading" }
  | { status: "ok"; items: DieBladeHistoryItem[] }
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

function DieBladeStatusBadge({ item }: { item: DieBladeHistoryItem }) {
  if (item.critical_missed === true) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-status-critical px-1.5 py-0.5 text-[10px] font-medium text-ink-primary">
        <span aria-hidden>⛔</span> 치명 미검출
      </span>
    );
  }
  if (item.registration_reliable === false) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-status-critical px-1.5 py-0.5 text-[10px] font-medium text-ink-primary">
        <span aria-hidden>⚠</span> 정합 신뢰 불가
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
  const isDieBlade = pathname?.startsWith("/die-blade") ?? false;

  const [state, setState] = useState<State>({ status: "loading" });
  const [dieBladeState, setDieBladeState] = useState<DieBladeState>({
    status: "loading",
  });
  const [open, setOpen] = useState(true);

  const match = pathname?.match(/^\/results\/([^/]+)/);
  const currentId = match ? decodeURIComponent(match[1]) : null;
  const dieBladeMatch = pathname?.match(/^\/die-blade\/results\/([^/]+)/);
  const currentDieBladeId = dieBladeMatch
    ? decodeURIComponent(dieBladeMatch[1])
    : null;

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

  useEffect(() => {
    let alive = true;
    getDieBladeHistory()
      .then((items) => {
        if (alive) setDieBladeState({ status: "ok", items });
      })
      .catch(() => {
        if (alive) setDieBladeState({ status: "error" });
      });
    return () => {
      alive = false;
    };
  }, [pathname]);

  return (
    <aside className="print:hidden border-r border-[var(--border-hairline)] bg-surface">
      <div className="flex items-center justify-between gap-2 border-b border-[var(--border-hairline)] px-4 py-3">
        <div className="flex gap-1 rounded-md border border-[var(--border-hairline)] p-0.5">
          <Link
            href="/"
            className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
              !isDieBlade
                ? "bg-accent text-white"
                : "text-ink-secondary hover:bg-[var(--accent-tint)]"
            }`}
          >
            인쇄판 검사
          </Link>
          <Link
            href="/die-blade"
            className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
              isDieBlade
                ? "bg-accent text-white"
                : "text-ink-secondary hover:bg-[var(--accent-tint)]"
            }`}
          >
            목형칼날 검사
          </Link>
        </div>
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
        <h2 className="px-4 pt-3 text-sm font-semibold text-ink-primary">
          분석 이력
        </h2>

        {!isDieBlade && (
          <>
            {state.status === "loading" && (
              <ul className="space-y-2 px-3 pb-4 pt-2">
                {Array.from({ length: 3 }).map((_, i) => (
                  <li
                    key={i}
                    className="h-16 animate-pulse rounded-md border border-[var(--border-hairline)] bg-[var(--accent-tint)]"
                  />
                ))}
              </ul>
            )}

            {state.status === "error" && (
              <p className="px-4 py-4 text-xs text-ink-muted">
                이력을 불러올 수 없습니다.
              </p>
            )}

            {state.status === "ok" && state.items.length === 0 && (
              <p className="px-4 py-4 text-sm text-ink-muted">
                아직 분석 이력이 없습니다.
              </p>
            )}

            {state.status === "ok" && state.items.length > 0 && (
              <ul className="space-y-1 px-3 py-2">
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
          </>
        )}

        {isDieBlade && (
          <>
            {dieBladeState.status === "loading" && (
              <ul className="space-y-2 px-3 pb-4 pt-2">
                {Array.from({ length: 3 }).map((_, i) => (
                  <li
                    key={i}
                    className="h-16 animate-pulse rounded-md border border-[var(--border-hairline)] bg-[var(--accent-tint)]"
                  />
                ))}
              </ul>
            )}

            {dieBladeState.status === "error" && (
              <p className="px-4 py-4 text-xs text-ink-muted">
                이력을 불러올 수 없습니다.
              </p>
            )}

            {dieBladeState.status === "ok" && dieBladeState.items.length === 0 && (
              <p className="px-4 py-4 text-sm text-ink-muted">
                아직 분석 이력이 없습니다.
              </p>
            )}

            {dieBladeState.status === "ok" && dieBladeState.items.length > 0 && (
              <ul className="space-y-1 px-3 py-2">
                {dieBladeState.items.map((item) => {
                  const active = item.id === currentDieBladeId;
                  return (
                    <li key={item.id}>
                      <Link
                        href={`/die-blade/results/${item.id}`}
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
                            <DieBladeStatusBadge item={item} />
                          </div>
                        </div>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            )}
          </>
        )}
      </div>
    </aside>
  );
}
