"use client";

import { useRef, useState } from "react";
import type { DieBladeDetectionItem, DieBladeImageUrls } from "@/lib/api";

export type DieBladeImageTab = "detections" | "reference" | "aligned";

const TABS: { key: DieBladeImageTab; label: string }[] = [
  { key: "detections", label: "Detections" },
  { key: "reference", label: "Reference" },
  { key: "aligned", label: "Aligned" },
];

const OVERLAY_TABS: DieBladeImageTab[] = ["detections", "aligned"];

const KIND_COLOR: Record<string, string> = {
  "끊김": "var(--status-critical)",
  "휨": "var(--status-warning)",
  "마모": "#c800ff",
  "위치오차": "var(--accent)",
};

function colorForKind(kind: string): string {
  if (kind.startsWith("복합")) return "#c800c8";
  return KIND_COLOR[kind] ?? "var(--accent)";
}

export default function AnnotatedImageDieBlade({
  imageUrls,
  detections,
  activeTab,
  onTabChange,
  selectedIndex,
  hoverIndex,
}: {
  imageUrls: DieBladeImageUrls;
  detections: DieBladeDetectionItem[];
  activeTab: DieBladeImageTab;
  onTabChange: (t: DieBladeImageTab) => void;
  selectedIndex: number | null;
  hoverIndex: number | null;
}) {
  const imgRef = useRef<HTMLImageElement>(null);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);

  const showOverlay = OVERLAY_TABS.includes(activeTab);
  const activeIndex = selectedIndex ?? hoverIndex;
  const isPinned = selectedIndex != null;
  const target =
    activeIndex != null
      ? detections.find((d) => d.index === activeIndex)
      : undefined;

  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold text-ink-primary">주석 이미지</h2>

      <div
        className="inline-flex rounded-md border border-[var(--border-hairline)] p-0.5 print:hidden"
        role="tablist"
      >
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={activeTab === t.key}
            onClick={() => onTabChange(t.key)}
            className={`rounded px-3 py-1.5 text-sm transition-colors ${
              activeTab === t.key
                ? "bg-accent text-white"
                : "text-ink-secondary hover:bg-[var(--accent-tint)]"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="relative overflow-hidden rounded-lg border border-[var(--border-hairline)] bg-surface">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          ref={imgRef}
          src={imageUrls[activeTab]}
          alt={activeTab}
          className="block h-auto w-full"
          onLoad={(e) =>
            setNatural({
              w: e.currentTarget.naturalWidth,
              h: e.currentTarget.naturalHeight,
            })
          }
        />
        {showOverlay && target && natural && (
          <div
            className="pointer-events-none absolute rounded-[2px] ring-2 ring-offset-1"
            style={{
              left: `${(target.bbox.x / natural.w) * 100}%`,
              top: `${(target.bbox.y / natural.h) * 100}%`,
              width: `${(target.bbox.w / natural.w) * 100}%`,
              height: `${(target.bbox.h / natural.h) * 100}%`,
              borderStyle: "solid",
              borderWidth: 2,
              borderColor: colorForKind(target.kind),
              boxShadow: "0 0 0 2px var(--surface-1)",
              opacity: isPinned ? 1 : 0.55,
            }}
          >
            <span
              className="absolute left-0 top-0 -translate-y-full whitespace-nowrap rounded-t px-1 text-[10px] font-medium text-white"
              style={{ background: colorForKind(target.kind) }}
            >
              {target.kind}
              {target.wear_grade ? ` · ${target.wear_grade}` : ""}
            </span>
          </div>
        )}
      </div>
      {!showOverlay && (selectedIndex != null || hoverIndex != null) && (
        <p className="text-xs text-ink-muted">
          bbox 하이라이트는 Detections / Aligned 탭에서만 표시됩니다.
        </p>
      )}
    </section>
  );
}
