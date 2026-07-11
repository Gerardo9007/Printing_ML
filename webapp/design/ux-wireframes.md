# UX Wireframes — Print-Plate Defect Viewer

Covers both routes from `ARCHITECTURE.md` §4, all states, using the exact component names from the
architecture doc so Developer 2 can map this directly onto the component tree:
`UploadForm`, `ResultView`, `AnnotatedImage`, `DetectionList`, `MetricsPanel`.

---

## Route `/` — Upload page (`app/page.tsx` → `UploadForm`)

### Layout (all states)

```
+--------------------------------------------------------------+
| Header: "인쇄판 문안검사 뷰어"                                    |
+--------------------------------------------------------------+
| UploadForm                                                    |
|  [Backend status dot]  (green="ok" / red="down", from health) |
|                                                                |
|  Defective image *        [Choose file]  <preview thumb>      |
|                                                                |
|  ( ) Compare against stored reference   <- only if            |
|        default_reference_available === true                  |
|  ( ) Upload my own reference image                             |
|      Reference image      [Choose file]  <preview thumb>      |
|      (hidden entirely if toggle above is on, or if no          |
|       default reference exists this option is forced-on       |
|       and the toggle is not shown at all)                      |
|                                                                |
|  > Advanced (collapsed by default)                             |
|      min_area [ 40 ]  (number input, default 40)               |
|                                                                |
|  [ Analyze ]  (primary button, right-aligned)                 |
|                                                                |
|  <inline error banner area, appears only on error state>       |
+--------------------------------------------------------------+
```

### States

1. **Empty / initial** — both file slots empty, previews hidden, `Analyze` button disabled
   (greyed, tooltip "Select a defective image"). Health check runs on mount; while pending, show
   status dot as neutral/grey pulsing.
2. **File-selected, not submitted** — defective preview thumbnail appears next to its input
   (object-fit contain, ~120px box). If reference was uploaded, same treatment. `Analyze` becomes
   enabled once `defective` is present (`reference` is optional per the API contract). No preview
   for the toggle-based default-reference option since nothing was uploaded for it.
3. **Uploading / processing** — `Analyze` button switches to a disabled loading state with a
   spinner and label "분석 중…"; all inputs and the toggle become disabled (prevent double-submit).
   Show a thin indeterminate progress bar under the form. No page navigation yet.
4. **Success** — on `200`, immediately `router.push('/results/' + id)`; stash the full
   `AnalyzeResponse` (e.g. `sessionStorage.setItem('result:' + id, JSON.stringify(resp))`) so
   `ResultView` can render instantly without a refetch, falling back to `GET /api/results/{id}`
   if the stash is missing (e.g. direct link visit).
5. **Error** — request rejects or backend returns non-2xx. Render a red inline banner above the
   `Analyze` button with `error.message` from the `{error:{code,message}}` payload (§5 error
   format). Map codes to friendlier prefixes for the user:
   - `BAD_REQUEST` → "요청 오류: {message}" (e.g. missing defective file, or reference omitted
     with no default reference — surface this distinctly since the fix is "upload a reference or
     enable the toggle")
   - `UNSUPPORTED_MEDIA` (415) → "이미지를 읽을 수 없습니다: {message}"
   - `INTERNAL` (500) → "서버 오류가 발생했습니다: {message}"
   - Network/fetch failure (backend down) → "백엔드에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요."
   Form re-enables; previously selected files remain so the user can just retry `Analyze` without
   re-picking files.

### Interaction notes
- Health check (`GET /api/health`) fires once on page mount; `default_reference_available`
  gates whether the toggle row is shown at all. If `false`, only "Upload my own reference" is
  available and it is **required** (client-side validation before submit, mirroring the backend's
  400 rule) — show inline hint "저장된 참조 이미지가 없어 참조 이미지를 직접 업로드해야 합니다."
- Clicking either file input's thumbnail opens a larger preview (lightbox) — optional nice-to-have,
  not required for MVP.
- Advanced section is collapsed by default to keep the form uncluttered for the common case.

---

## Route `/results/[id]` — Results page (`app/results/[id]/page.tsx` → `ResultView`)

### Layout (success state, GT present)

```
+--------------------------------------------------------------+
| Header: "분석 결과"  [id: a1b2c3d4]      [ New analysis ]      |
+--------------------------------------------------------------+
| MetricsPanel                                                   |
|  [ any_oversized ? amber banner: "오검출 가드레일 발동 — 검출 영역이|
|     비정상적으로 큽니다" : nothing ]                              |
|  [ critical_missed ? red banner: "치명 결함(성분표시오류) 미검출!" :  |
|     nothing ]                                                  |
|  Row of stat tiles:                                            |
|   [검출 수: n_detections] [Diff threshold: diff_threshold]      |
|   [정합 방법: method (+ n_inliers if orb)]                      |
|   [Recall: recall%] [Reliable recall: reliable_recall%]         |
|   [Precision(proxy): precision_proxy%]                         |
|   [결함: n_defects_detected / n_defects_total]                 |
+--------------------------------------------------------------+
| AnnotatedImage                  | DetectionList                |
|  Tabs: [Detections*] [Reference]|  Table, one row per           |
|        [Aligned] [Diff mask]    |  detections[]:                |
|  <img src={image_urls[tab]}>    |   idx | bbox | area | ratio%  |
|  (default tab = "detections")   |   | [오검출] badge if oversized|
|                                  |                                |
|                                  |  If GT present, second table   |
|                                  |  "결함별 검출 현황" from        |
|                                  |  per_defect[]:                 |
|                                  |   type | detected | reliable   |
|                                  |   | overlap_score | ocr diff*  |
|                                  |   row background = red tint if |
|                                  |   type === "성분표시오류" &&    |
|                                  |   !reliable_detected            |
+--------------------------------------------------------------+
```
`*` ocr diff column only renders content on rows where `ocr_text_before`/`_after` are both non-null
(see §7 below); other rows leave the cell blank.

Each detections-table row also gets, in its trailing cell (alongside the existing `오검출` badge):
a **source badge** (`pixel_diff`/`ocr_diff`/`both`) and, only when present, a **reliability dot/badge**.
See `visual-design-system.md` §7 for the exact markup/tokens — this file only fixes where they sit.

### States

1. **Loading** — on mount, if no stashed response for `id`, fetch `GET /api/results/{id}`; show
   skeleton placeholders for `MetricsPanel` tiles, `AnnotatedImage` (grey box, same aspect ratio as
   final image), and `DetectionList` rows (3 shimmer rows).
2. **Success, GT present** — full layout above; both stat rows and both `DetectionList` tables
   render.
3. **Success, no GT** (`reference` was user-supplied, or default reference has no GT) —
   `metrics.recall`/`reliable_recall`/`precision_proxy`/`n_defects_*`/`critical_missed` are `null`,
   `per_defect` is `[]`. `MetricsPanel` shows only the always-present tiles (`n_detections`,
   `diff_threshold`, registration method/inliers) plus a neutral info tile/banner reading
   **"N/A — 참조 GT 없음 (탐지 전용 모드)"** in place of the recall/precision tiles — do not hide
   the tiles' slots outright (avoids layout jump), just render them as muted "N/A" values. No
   `critical_missed` banner is shown (since it's `null`, not `false`); no second `DetectionList`
   table (per_defect table is simply omitted, not shown empty).
4. **Error — id not found (404)** — replace the whole content area with a centered message: "결과를
   찾을 수 없습니다 (id: {id})" + `[ Back to upload ]` button linking to `/`.
5. **Error — backend down / network failure** — same centered pattern: "백엔드에 연결할 수 없습니다"
   + `[ Retry ]` button (re-fetch) + `[ Back to upload ]`.

### Interaction notes
- **Row-to-bbox highlight**: clicking a row in `DetectionList` highlights that detection's bbox on
  `AnnotatedImage` — draw an overlay rectangle (absolute-positioned `div` scaled to the rendered
  image's displayed size, using `bbox.x/y/w/h` against the image's natural dimensions) in an accent
  color distinct from the red boxes already burned into `detections.png`. Hovering a row shows the
  same overlay at lower opacity; clicking pins it (click again or click another row to switch).
  This overlay only makes sense on the "Detections" and "Aligned" tabs (same coordinate space as
  `aligned.png`); switching to "Reference" or "Diff mask" clears/hides the overlay since those may
  differ in framing conceptually (same pixel grid, but keep it simple — only show overlay on
  Detections/Aligned tabs).
- Clicking a `per_defect` row (when present) scrolls/pans `AnnotatedImage` is out of scope for MVP;
  simply visually flag critical rows (성분표시오류 + not reliably detected) with a red-tinted row
  background and a small "미검출" badge — no bbox for these since GT per-defect entries don't carry
  a bbox in the API contract, only `type/note/detected/reliable_detected/overlap_score/
  used_line_level_gt`.
- Image tab switch is a simple client-side state toggle, no refetch (all four URLs are already in
  `image_urls`).
- `[ New analysis ]` in the header always links back to `/`.

---

## Shared component responsibilities (for Developer 2)

- **`UploadForm`**: owns all form state (files, toggle, min_area), health check, submit/error/
  loading states described above. No knowledge of results rendering.
- **`ResultView`**: top-level container for `/results/[id]`; owns fetch/stash resolution, loading/
  error states, and the "selected detection index" + "active image tab" UI state that
  `AnnotatedImage` and `DetectionList` both read from (lift this state to `ResultView`, pass down
  as props, so the two components can stay in sync without their own coupling).
- **`AnnotatedImage`**: pure display — image + tab switcher + overlay rectangle for the currently
  selected detection index (prop from `ResultView`).
- **`DetectionList`**: pure display — two tables (detections always; per_defect only if
  `metrics.recall !== null`), emits `onSelectDetection(index)` up to `ResultView`. Detections table
  rows also render the `source` badge and, when non-null, the `reliability_score` dot/badge; the
  per_defect table renders the OCR before/after text diff when both fields are non-null (§7 of
  `visual-design-system.md`).
- **`MetricsPanel`**: pure display — renders tiles/banners; treats `null` metric fields as "N/A",
  never as `0` or falsy-hide.
