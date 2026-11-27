# OMR Scanner: frontend

React 18, TypeScript, Vite and react-router. The UI calls the FastAPI backend under `/api` (see `../ARCHITECTURE.md` §6, §7 and §9).
There is no UI component library: the styling is one hand-written stylesheet (`src/styles.css`) with CSS variables for light and dark themes.

## Requirements

- Node 20.19+ or 22.12+ (developed on Node 26.13.1 / npm 11.20.0)
- For real data: the backend running on `http://localhost:8000`

On this machine Node is not on PATH by default:

```powershell
$env:Path = "C:\Users\akshay.nandigam\AppData\Local\Programs\nodejs-portable\node-v26.13.1-win-x64;" + $env:Path
```

## Install

```powershell
cd frontend
npm install
```

## Develop

```powershell
npm run dev          # http://localhost:5173, proxies /api -> http://localhost:8000
```

### Mock mode (no backend needed)

```powershell
npm run dev:mock     # same as: vite --mode mock  (loads .env.mock -> VITE_USE_MOCKS=true)
```

You can also set `VITE_USE_MOCKS=true` in `.env.local`. In mock mode the API client serves in-memory fixtures:

- a batch of 3 scans, one of which needs review
- two answer keys
- a sample benchmark report
- generated SVG sheet images

Uploads, corrections, regrading and answer-key CRUD all work against this in-memory state, which resets on page reload. A "Mock data" badge shows in the top bar.
The real backend is the default, and the mock code is tree-shaken out of production builds.

## Build, test, preview

```powershell
npm run build        # tsc type-check (app + vite config) then vite build -> dist/
npx vitest run       # unit tests (or: npm test)
npm run preview      # serve dist/ on :5173 with the same /api proxy
```

## Pages

| Route | Purpose |
|---|---|
| `/` | Scan: drag-drop or pick files (JPG/PNG/TIFF/WebP/PDF, at most 20 MB each, at most 50 files), choose a template and an optional answer key, upload with progress |
| `/batches`, `/batches/:id` | Batch list. Batch detail has summary cards, a status filter, the scans table, CSV export and "Re-grade all" with another key |
| `/scans/:id` | Review: aligned image with an SVG overlay (zoom/pan), review flags, an 80-question answer grid and roll no / paper-set editing. Save sends `PATCH`. Shortcuts: `J`/`K` or arrows for next/prev flagged sheet, `1-4`/`A-D` to set an answer, `0`/`Del` for blank, `Ctrl+S` to save, `O` for the original image, `V` to toggle the overlay |
| `/keys`, `/keys/new`, `/keys/:id` | Answer keys: marking scheme (negative allowed), an A/B/C tab per paper set with a question grid, and a paste box (`ABCD…`, `1-A,2-B`, or one per line) |
| `/benchmarks` | Latest `benchmarks/reports/latest.json`: headline numbers, target checks, accuracy chart, per-tier table with pass/fail and the error sample. Shows an empty state if the report has not been generated |

## Code layout

```
src/
  api/         types.ts (mirrors §6/§7), client.ts (fetch + XHR upload), errors.ts, mock.ts, index.ts (picks real or mock)
  components/  ScanViewer (zoom/pan), ReviewOverlay (SVG bubbles), AnswerGrid, KeyGrid, AnswerKeyEditor,
               AccuracyChart, Dropzone, Toasts, HealthIndicator, States
  lib/         answerString (paste parser), overlay (bubble/cell state colours, flags), benchmark (report reader),
               files (upload checks), queue (review navigation), grade (mock-only grading mirror), format, hooks
  pages/       ScanPage, BatchesPage, BatchPage, ReviewPage, KeysPage, BenchmarksPage
```

## Notes

- The backend's `GradeResult` is authoritative. `lib/grade.ts` only powers the mock.
- There is no authentication (MVP). Run this only on localhost or a trusted LAN, as stated in ARCHITECTURE.md §7.
