# Print-Plate Defect Viewer — Frontend

Next.js (App Router) + TypeScript + Tailwind CSS UI for the print-plate defect
detection service. Implements the contract in `../ARCHITECTURE.md` and the
`../design/*.md` specs.

## Run

```bash
npm install
npm run dev
```

Frontend runs on **http://localhost:3000**. It expects the FastAPI backend on
**http://localhost:8000**. `next.config.js` rewrites `/api/:path*` →
`http://localhost:8000/api/:path*`, so the browser only ever calls same-origin
`/api/...` (this also makes the `image_urls` returned by the backend work
verbatim). Start the backend first:

```bash
cd ../backend && uvicorn main:app --reload --port 8000
```

## Scripts

- `npm run dev` — dev server on port 3000
- `npm run build` — production build (also full type-check)
- `npm run typecheck` — `tsc --noEmit`
- `npm run lint` — `next lint`

## Structure

- `app/page.tsx` — `/` upload page → `UploadForm`
- `app/results/[id]/page.tsx` — `/results/:id` → `ResultView`
- `components/` — `UploadForm`, `ResultView`, `AnnotatedImage`, `DetectionList`,
  `MetricsPanel`
- `lib/api.ts` — typed client (`getHealth`, `analyze`, `getResult`) mirroring the
  API contract, plus sessionStorage stash helpers and error→message mapping.

## Theming

Light/dark are driven by `prefers-color-scheme` via CSS custom properties in
`app/globals.css` (no manual toggle) — the OS/browser setting decides. Tailwind
color tokens (`surface`, `ink.*`, `accent`, `status.*`) map to those variables in
`tailwind.config.js`, so the whole UI swaps in one place.

## Notes / small decisions made

- The reference-source choice is rendered as two radio buttons ("저장된 참조
  이미지와 비교" / "참조 이미지 직접 업로드"). When `health.default_reference_available`
  is `false`, the stored-reference radio is not shown and the upload option is
  forced on and required (client-side validation mirrors the backend 400 rule).
- Detection→image highlight: hovering a `DetectionList` row shows the bbox overlay
  at low opacity; clicking pins it (click again to unpin). Overlay renders only on
  the Detections/Aligned tabs (shared coordinate space with `aligned.png`), per the
  wireframe.
- `null` GT metrics render muted `—` tiles with a "· no ground truth" suffix
  rather than being hidden, to avoid layout jump.
