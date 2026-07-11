# Visual Design System — Print-Plate Defect Viewer

Built on the `dataviz` skill's validated palette (`references/palette.md`) and color-formula
(`references/color-formula.md`). All categorical/status hex values below are taken verbatim from
that reference instance — do not invent new hues. Tailwind CSS project: values are expressed as
CSS custom properties (so light/dark swap in one place) plus suggested Tailwind utility patterns.

## 1. Color palette

Define once in `globals.css`, consume via Tailwind arbitrary values `bg-[var(--surface-1)]` or by
extending `tailwind.config` (`colors.surface.DEFAULT: 'var(--surface-1)'`, etc.).

```css
:root {
  /* base */
  --page:            #f9f9f7;
  --surface-1:       #fcfcfb;   /* cards, panels, dropzone, stat tiles */
  --text-primary:    #0b0b0b;
  --text-secondary:  #52514e;
  --text-muted:      #898781;   /* N/A values, disabled, placeholder */
  --border-hairline: #e1e0d9;
  --border-strong:   #c3c2b7;   /* dropzone idle border, axis-like dividers */
  --ring:            rgba(11,11,11,0.10);

  /* accent — primary actions, links, focus ring, "normal" bbox stroke */
  --accent:          #2a78d6;
  --accent-tint:     rgba(42,120,214,0.08);   /* hover wash */
  --accent-tint-2:   rgba(42,120,214,0.14);   /* active/dragging wash */

  /* status (fixed — never re-themed; always icon + label, never color alone) */
  --status-good:     #0ca30c;
  --status-warning:  #fab219;   /* "oversized / unreliable" detections */
  --status-serious:  #ec835a;
  --status-critical: #d03b3b;   /* critical_missed (성분표시오류 not reliably detected) */
}

@media (prefers-color-scheme: dark) {
  :root {
    --page:            #0d0d0d;
    --surface-1:       #1a1a19;
    --text-primary:    #ffffff;
    --text-secondary:  #c3c2b7;
    --text-muted:      #898781;
    --border-hairline: #2c2c2a;
    --border-strong:   #383835;
    --ring:            rgba(255,255,255,0.10);

    --accent:          #3987e5;
    --accent-tint:     rgba(57,135,229,0.10);
    --accent-tint-2:   rgba(57,135,229,0.16);

    --status-good:     #0ca30c;
    --status-warning:  #fab219;
    --status-serious:  #ec835a;
    --status-critical: #d03b3b;
  }
}
```

**Contrast note (relief rule):** `--status-warning` and `--status-serious` sit below 3:1 on the
light surface by design (per the palette spec). Never use them as a fill with text on top or as
the sole signal — always pair with an icon **and** a text label, and prefer them for *strokes/borders*
(checked against the accessible mitigation) over body text. On dark surface both clear 3:1 safely.

Tailwind class shorthand for the values above (add to `tailwind.config.js theme.extend.colors`):

```js
colors: {
  page: 'var(--page)',
  surface: 'var(--surface-1)',
  ink: { primary: 'var(--text-primary)', secondary: 'var(--text-secondary)', muted: 'var(--text-muted)' },
  accent: 'var(--accent)',
  status: { good: 'var(--status-good)', warning: 'var(--status-warning)', serious: 'var(--status-serious)', critical: 'var(--status-critical)' },
}
```

## 2. Typography

Single system sans everywhere (per palette spec — no display/serif face):

```
font-sans: system-ui, -apple-system, "Segoe UI", sans-serif
font-mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace
```

| Element | Tailwind | Notes |
|---|---|---|
| Page title (`h1`, e.g. "Print-Plate Defect Viewer") | `text-2xl md:text-3xl font-bold text-ink-primary` | |
| Section heading (`MetricsPanel`, `DetectionList` titles) | `text-lg font-semibold text-ink-primary` | |
| Body / labels | `text-sm text-ink-secondary` | |
| Metric numbers (stat tile values) | `text-3xl font-bold tabular-nums text-ink-primary` | `font-variant-numeric: tabular-nums` |
| Table numeric cells (bbox, area, ratios) | `font-mono text-sm tabular-nums text-ink-secondary` | |
| JSON-ish / raw values (registration info, ids) | `font-mono text-xs text-ink-muted` | |
| Muted/N/A metric value | `text-3xl font-bold text-ink-muted` + literal `"—"` glyph, not `"N/A"` in accent color | |

## 3. Spacing & component styles

Base scale: Tailwind default (`4px` steps). Panels use `p-4`/`p-6`, page gutter `px-6 py-8`,
gap between stacked sections `space-y-6`, gap between tiles/cards `gap-4`.

### Upload dropzone (`UploadForm`)

| State | Classes |
|---|---|
| Idle | `border-2 border-dashed border-[var(--border-strong)] bg-surface rounded-xl p-10 text-center` |
| Hover | `border-accent bg-[var(--accent-tint)]` (transition `transition-colors duration-150`) |
| Dragging | `border-accent border-solid bg-[var(--accent-tint-2)] ring-2 ring-accent ring-offset-2` |

Preview thumbnails: `rounded-md border border-[var(--border-hairline)]`, `w-32 h-32 object-cover`.

### Annotated image viewer (bbox overlays on `detections.png` / SVG overlay)

Stroke rules — thin marks, per the skill's mark spec (2px lines, no thick fills):

| Box kind | Stroke | Width | Fill | Extra |
|---|---|---|---|---|
| Normal detection | `--accent` | 2px solid | none | rounded 2px corners |
| Oversized / unreliable (`oversized: true`) | `--status-warning` | 3px **dashed** (8/4) | `--status-warning` at 8% | small warning icon chip at top-left corner, label "oversized" — required (relief rule) |
| Critical missed defect (GT-only, `type == 성분표시오류` & not `reliable_detected`) | `--status-critical` | 3px solid | `--status-critical` at 10% | icon + "critical" label |
| Selected / hovered (linked from `DetectionList` row) | add `ring` | outer 2px surface-color ring (offset gap) around existing stroke | — | never remove the underlying identity stroke |

Toggle tabs (reference / aligned / diff_mask / detections): standard segmented control,
active tab `bg-accent text-white`, inactive `text-ink-secondary hover:bg-[var(--accent-tint)]`.

### Detection list (table/rows)

- Container: `bg-surface rounded-lg border border-[var(--border-hairline)]`
- Header row: `text-xs uppercase tracking-wide text-ink-muted border-b border-[var(--border-hairline)] px-4 py-2`
- Data row: `px-4 py-3 border-b border-[var(--border-hairline)] last:border-0 hover:bg-[var(--accent-tint)]`
- Oversized badge: `inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full border border-status-warning text-ink-primary` + warning icon (never the raw warning hex as text color — text stays ink, the color is carried by icon + border, satisfying the relief rule)
- Critical row highlight (성분표시오류 & not reliable): `bg-[color-mix(in_srgb,var(--status-critical)_8%,var(--surface-1))]` with a left `border-l-4 border-status-critical`

### Metric stat tiles (`MetricsPanel`)

- Tile: `bg-surface rounded-lg border border-[var(--border-hairline)] p-4 flex flex-col gap-1`
- Label: `text-xs uppercase tracking-wide text-ink-secondary`
- Value: `text-3xl font-bold tabular-nums text-ink-primary`
- **N/A state** (recall/precision/etc. `null`): tile gets `border-dashed`, value renders `—` in
  `text-ink-muted` (not bold-colored), label stays but suffix "· no ground truth" in
  `text-xs text-ink-muted`. Never gray-out via opacity alone — keep text legible.
- `any_oversized` banner: `bg-[color-mix(in_srgb,var(--status-warning)_12%,var(--surface-1))] border border-status-warning text-ink-primary rounded-md px-4 py-2 flex items-center gap-2` + warning icon + label text (icon/label mandatory per relief rule).
- `critical_missed` banner: same pattern with `border-status-critical` and critical icon, higher visual weight (`font-semibold`, placed above the warning banner if both present).

## 7. ML extension — source badge, reliability indicator, OCR text diff

Extends §1/§3 for the three new optional fields in `ML-ARCHITECTURE.md` §2
(`detections[].source`, `detections[].reliability_score`, `per_defect[].ocr_text_before/after`).
No existing token is redefined; only new variables and one new categorical hue are added.

### 7.1 New tokens

```css
:root {
  /* --- ML extension: OCR source hue (extends the categorical family, doesn't replace accent) --- */
  --source-ocr:       #1a8a72;   /* teal — second categorical hue in the dataviz palette family */
  --source-ocr-tint:  rgba(26,138,114,0.10);

  /* reliability dot — reuses existing status tokens, no new hue */
  --reliability-ok:   var(--status-good);
  --reliability-low:  var(--status-warning);
}

@media (prefers-color-scheme: dark) {
  :root {
    --source-ocr:      #2fb897;
    --source-ocr-tint: rgba(47,184,151,0.14);
  }
}
```

`--source-ocr` is a teal pulled from the same categorical family the palette already validates
elsewhere in the app (distinct hue bucket from `--accent` blue and all `--status-*` reds/ambers/
greens, so it never collides under simulated color-blindness checks) — not an invented one-off hex.

### 7.2 Source badge (`DetectionList` row, detections table)

Add a badge next to (left of) the existing `오검출`/oversized badge in the row's last `<td>`.
Icon + label always, per the relief rule already in effect for `--status-*` — same rule now applies
to `--source-ocr` even though it's a non-status hue, for consistency.

| `source` value | Classes | Icon | Label |
|---|---|---|---|
| `"pixel_diff"` | `inline-flex items-center gap-1 rounded-full border border-[var(--border-strong)] px-2 py-0.5 text-xs font-medium text-ink-secondary` | `▦` | `픽셀` |
| `"ocr_diff"` | `inline-flex items-center gap-1 rounded-full border border-[var(--source-ocr)] px-2 py-0.5 text-xs font-medium text-ink-primary` | `🔤` | `OCR` |
| `"both"` | `inline-flex items-center gap-1 rounded-full border border-accent bg-[var(--accent-tint)] px-2 py-0.5 text-xs font-semibold text-ink-primary` | `✓✓` | `둘 다` |

`"both"` uses the primary `--accent` (not `--source-ocr` or a status color) because it is the
highest-confidence provenance (agreement between two independent detectors) — reusing the existing
"most trusted" hue in the palette (already used for the normal-detection bbox stroke) communicates
that ranking for free, instead of introducing a third competing hue.
`"pixel_diff"` is deliberately the quietest (neutral border, `--border-strong`, muted-tier text) since
it is the default/majority case today — it should read as "baseline," not draw the eye.

### 7.3 Reliability score indicator

Compact dot, placed in its own small column (or inline after the `ratio` cell) in the detections
table — only rendered when `reliability_score != null` (progressive enhancement; renders **nothing**,
not a `—`, when `null`, since most rows will lack it during rollout and a dash-per-row would be noise
the N/A rule was never meant to produce outside `MetricsPanel`'s fixed stat tiles).

| Condition | Markup |
|---|---|
| `reliability_score >= 0.5` | `<span class="inline-flex items-center gap-1 text-xs text-ink-secondary"><span class="inline-block h-2 w-2 rounded-full bg-[var(--reliability-ok)]" aria-hidden></span>{score.toFixed(2)}</span>` |
| `reliability_score < 0.5` | `<span class="inline-flex items-center gap-1 rounded-full border border-status-warning px-2 py-0.5 text-xs font-medium text-ink-primary"><span aria-hidden>⚠</span> 확인 필요 ({score.toFixed(2)})</span>` |
| `null` | render nothing |

**Decision — kept separate from `oversized`, not merged, despite sharing the amber hue:**
`reliability_score < 0.5` reuses the *exact same* `--status-warning` amber and icon (⚠) that
`oversized` already uses, so on a quick glance both read as "the same severity of concern." But they
render as two independent badges that can both appear on one row, because they are answers to two
different QA questions — `oversized` is "did the deterministic guardrail reject this box's size"
and `확인 필요` is "did the classifier think this is a false positive" — and `ML-ARCHITECTURE.md` §2
explicitly requires the two stay independent (a box can be `oversized=true` and separately carry a
`reliability_score`). Collapsing them into one badge would hide *which* system flagged the box,
which is exactly the debugging signal a QA reviewer needs when the classifier and the guardrail
disagree. Sharing the color instead of inventing a third warning hue keeps the "amber = needs a
second look" mental model intact without adding a color the relief rule would need new coverage for.

### 7.4 OCR text diff (`per_defect` table)

Only for rows where both `ocr_text_before` and `ocr_text_after` are non-null. Insert as a new cell
appended to the existing `type / detected / reliable / overlap` row (or, on narrow layouts, as a
second line under the `type` cell) — monospace per the existing typography scale (§2, "Table numeric
cells" row), since this is exact string content a QA reviewer must compare character-by-character:

```
<span class="font-mono text-xs text-ink-secondary">{before}</span>
<span class="mx-1 text-ink-muted" aria-hidden>→</span>
<span class="font-mono text-xs font-semibold text-ink-primary">{after}</span>
```

Example rendering: `토너 → 토노`. The "before" side stays `text-ink-secondary` (reference, expected
text) and "after" is `text-ink-primary font-semibold` (what actually printed — the side the reviewer
is validating) so the diff reads left-to-right as "expected → actual" without needing a legend. Rows
with `null` text keep the cell empty (no placeholder), consistent with §7.3's no-dash-spam rule.

## Summary of key decisions

Adopted the dataviz skill's validated palette as-is (surfaces `#fcfcfb`/`#1a1a19`, ink `#0b0b0b`/`#ffffff`). Accent blue `#2a78d6`/`#3987e5` marks normal bbox strokes, links, and focus states. Reused the *status* scale (never re-themed) for severity: warning `#fab219` (dashed 3px stroke) for oversized/unreliable boxes, critical `#d03b3b` (solid 3px, left-border row highlight) for missed 성분표시오류 defects. N/A metrics render a muted `—` (`#898781`) rather than colored placeholder text. Because warning/serious fall below 3:1 contrast on light surfaces by the palette's own design, every warning/critical usage is paired with an icon + text label (never color alone), satisfying the skill's relief rule. Typography stays single system-sans with `font-mono`/`tabular-nums` reserved for bbox coordinates, ids, and table numerics.

**ML extension (§7):** added one new categorical hue, teal `--source-ocr`, for the `ocr_diff` source
badge — kept distinct from `--accent` and all `--status-*` so it never collides with them under
color-blindness simulation. `"both"`-source detections reuse `--accent` (not a new hue) since
agreement-between-detectors maps naturally onto the palette's existing "most trusted" color.
`reliability_score < 0.5` reuses `--status-warning` (same amber, same icon as `oversized`) but stays a
**separate badge**, not merged — they answer different QA questions (guardrail vs. classifier) and
`ML-ARCHITECTURE.md` requires them independent; merging would hide which system fired. `null`
reliability renders nothing (progressive enhancement, not an N/A dash). OCR before/after text diffs
use `font-mono text-xs` with a plain `→` separator, no legend needed.
