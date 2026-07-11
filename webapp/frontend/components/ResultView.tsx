"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  getResult,
  getHistory,
  readStashedResult,
  friendlyMessage,
  ApiError,
  type AnalyzeResponse,
  type HistoryItem,
} from "@/lib/api";
import MetricsPanel from "@/components/MetricsPanel";
import AnnotatedImage, { type ImageTab } from "@/components/AnnotatedImage";
import DetectionList from "@/components/DetectionList";

type LoadState =
  | { status: "loading" }
  | { status: "ok"; data: AnalyzeResponse }
  | { status: "notfound" }
  | { status: "error"; message: string };

export default function ResultView({ id }: { id: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [reloadKey, setReloadKey] = useState(0);

  // Lifted UI state shared by AnnotatedImage + DetectionList.
  const [activeTab, setActiveTab] = useState<ImageTab>("detections");
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  // History for the print-only appendix (best-effort; absent on failure).
  const [history, setHistory] = useState<HistoryItem[]>([]);

  useEffect(() => {
    let alive = true;
    getHistory()
      .then((items) => {
        if (alive) setHistory(items);
      })
      .catch(() => {
        if (alive) setHistory([]);
      });
    return () => {
      alive = false;
    };
  }, [id]);

  useEffect(() => {
    const stashed = readStashedResult(id);
    if (stashed) {
      setState({ status: "ok", data: stashed });
      return;
    }
    let alive = true;
    setState({ status: "loading" });
    getResult(id)
      .then((data) => {
        if (alive) setState({ status: "ok", data });
      })
      .catch((err) => {
        if (!alive) return;
        if (err instanceof ApiError && err.code === "NOT_FOUND") {
          setState({ status: "notfound" });
        } else {
          setState({ status: "error", message: friendlyMessage(err) });
        }
      });
    return () => {
      alive = false;
    };
  }, [id, reloadKey]);

  if (state.status === "loading") return <LoadingSkeleton id={id} />;

  if (state.status === "notfound") {
    return (
      <CenteredMessage title={`결과를 찾을 수 없습니다 (id: ${id})`}>
        <Link
          href="/"
          className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-white"
        >
          업로드로 돌아가기
        </Link>
      </CenteredMessage>
    );
  }

  if (state.status === "error") {
    return (
      <CenteredMessage title={state.message}>
        <div className="flex gap-3">
          <button
            onClick={() => setReloadKey((k) => k + 1)}
            className="rounded-md border border-[var(--border-strong)] px-4 py-2 text-sm text-ink-primary"
          >
            다시 시도
          </button>
          <Link
            href="/"
            className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-white"
          >
            업로드로 돌아가기
          </Link>
        </div>
      </CenteredMessage>
    );
  }

  const data = state.data;

  return (
    <main className="mx-auto max-w-6xl px-6 py-8">
      <header className="mb-6 flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-ink-primary md:text-3xl">
            분석 결과
          </h1>
          <p className="mt-1 font-mono text-xs text-ink-muted">id: {data.id}</p>
        </div>
        <div className="flex gap-2 print:hidden">
          <button
            type="button"
            onClick={() => window.print()}
            className="rounded-md border border-[var(--border-strong)] px-4 py-2 text-sm text-ink-primary hover:bg-[var(--accent-tint)]"
          >
            인쇄
          </button>
          <Link
            href="/"
            className="rounded-md border border-[var(--border-strong)] px-4 py-2 text-sm text-ink-primary hover:bg-[var(--accent-tint)]"
          >
            새 분석
          </Link>
        </div>
      </header>

      <div className="space-y-6">
        <MetricsPanel
          registration={data.registration}
          metrics={data.metrics}
        />

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <AnnotatedImage
            imageUrls={data.image_urls}
            detections={data.detections}
            activeTab={activeTab}
            onTabChange={setActiveTab}
            selectedIndex={selectedIndex}
            hoverIndex={hoverIndex}
          />
          <DetectionList
            detections={data.detections}
            metrics={data.metrics}
            selectedIndex={selectedIndex}
            onSelectDetection={(i) =>
              setSelectedIndex((cur) => (cur === i ? null : i))
            }
            onHoverDetection={setHoverIndex}
          />
        </div>
      </div>

      <PrintHistoryAppendix history={history} currentId={data.id} />
    </main>
  );
}

// Rendered into the DOM always but only visible in print output.
function PrintHistoryAppendix({
  history,
  currentId,
}: {
  history: HistoryItem[];
  currentId: string;
}) {
  return (
    <section className="mt-10 hidden print:block">
      <h2 className="mb-2 text-base font-semibold">분석 이력 (Analysis history)</h2>
      {history.length === 0 ? (
        <p className="text-sm">이력이 없습니다.</p>
      ) : (
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr>
              <th className="border border-black px-2 py-1 text-left">id</th>
              <th className="border border-black px-2 py-1 text-left">created_at</th>
              <th className="border border-black px-2 py-1 text-right">검출 수</th>
              <th className="border border-black px-2 py-1 text-right">recall</th>
              <th className="border border-black px-2 py-1 text-left">치명 미검출</th>
            </tr>
          </thead>
          <tbody>
            {history.map((h) => (
              <tr key={h.id} className={h.id === currentId ? "font-bold" : ""}>
                <td className="border border-black px-2 py-1 font-mono">
                  {h.id}
                  {h.id === currentId ? " (현재)" : ""}
                </td>
                <td className="border border-black px-2 py-1">
                  {h.created_at ?? "—"}
                </td>
                <td className="border border-black px-2 py-1 text-right">
                  {h.n_detections}
                </td>
                <td className="border border-black px-2 py-1 text-right">
                  {h.recall != null ? `${(h.recall * 100).toFixed(0)}%` : "N/A"}
                </td>
                <td className="border border-black px-2 py-1">
                  {h.critical_missed === true
                    ? "예"
                    : h.critical_missed === false
                    ? "아니오"
                    : "N/A"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function CenteredMessage({
  title,
  children,
}: {
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col items-center justify-center gap-6 px-6 text-center">
      <p className="text-lg font-semibold text-ink-primary">{title}</p>
      {children}
    </main>
  );
}

function LoadingSkeleton({ id }: { id: string }) {
  return (
    <main className="mx-auto max-w-6xl px-6 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-bold text-ink-primary md:text-3xl">
          분석 결과
        </h1>
        <p className="mt-1 font-mono text-xs text-ink-muted">id: {id}</p>
      </header>
      <div className="space-y-6">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div
              key={i}
              className="h-24 animate-pulse rounded-lg border border-[var(--border-hairline)] bg-surface"
            />
          ))}
        </div>
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <div className="aspect-[4/3] animate-pulse rounded-lg border border-[var(--border-hairline)] bg-surface" />
          <div className="space-y-2 rounded-lg border border-[var(--border-hairline)] bg-surface p-4">
            {Array.from({ length: 3 }).map((_, i) => (
              <div
                key={i}
                className="h-10 animate-pulse rounded bg-[var(--accent-tint)]"
              />
            ))}
          </div>
        </div>
      </div>
    </main>
  );
}
