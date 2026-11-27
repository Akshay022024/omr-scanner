# OMR scanner backend

`omr_engine/` is the pure scanning library and `app/` is the FastAPI + SQLite API. The binding contract is in
`../ARCHITECTURE.md`.

> **Security:** the MVP has **no authentication**. Run it only on localhost or a trusted LAN.

## Run

From the project root (Windows PowerShell):

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt   # once
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --port 8000
```

- Health check: `http://127.0.0.1:8000/api/health`. Interactive docs: `http://127.0.0.1:8000/docs`.
- To upload, send `multipart/form-data` to `POST /api/scans` with `files` (or `files[]`), `template_id`, and an optional `answer_key_id`.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest backend -q
```

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `OMR_DATA_DIR` | `<project>/data` | SQLite DB (`omr.db`) and uploads (`uploads/{scan_id}/`) |
| `OMR_TEMPLATES_DIR` | `<project>/templates` | One sub-directory per template (`template.json` + reference PNG) |
| `OMR_BENCHMARK_REPORTS_DIR` | `<project>/benchmarks/reports` | `GET /api/benchmarks/latest` serves `latest.json` from here |
| `OMR_MAX_UPLOAD_MB` | `20` | Per-file size limit |
| `OMR_MAX_FILES` | `50` | Files per request |
| `OMR_MAX_PDF_PAGES` | `20` | Pages per PDF |
| `OMR_CORS_ORIGINS` | `http://localhost:5173` | Comma-separated allowed origins |
| `OMR_FRONTEND_DIST` | unset | If set to a built frontend directory, it is served at `/` |

## Engine pipeline

1. **Page:** candidate transforms from the paper quad (at several brightness cuts plus edges), the magenta content box, and the full frame, each in 4 orientations, are scored against the template's magenta layout. The best one is kept.
2. **Register:** coarse-to-fine ECC homography on blurred magenta masks, with an ORB + RANSAC fallback. This is refined by an affine fit to the 7 panel-box edges. Quality is the mask IoU.
3. **Verify:** a geometric check independent of the IoU:
   - the dark template print (question numbers and labels, with bubbles masked out) must correlate best at zero offset rather than one bubble pitch away;
   - re-detected panel edges must have a small residual.

   A failed check flags `registration:geometry` and sets the status to `needs_review`. It fails the scan only if the IoU or the print correlation is also very low.
4. **Ink:** red-channel dropout on the background-normalised image. Magenta print reflects red, while blue and black ballpoint absorb it, including light grey strokes. A small closing followed by an opening suppresses ticks and crosses.
5. **Bubbles:** mean ink in a 0.75·r disc, taking the maximum over ±4 px shifts.
6. **Decide:** per-sheet threshold set at the largest score gap, clamped to [0.30, 0.50], with an ambiguity margin. Each field is `blank`, `single`, `multiple` or `ambiguous`.

All thresholds are in `omr_engine.config.EngineConfig`. A template can override some of them through
`engine_overrides` in its `template.json`. For example, `tamaulipas_90` is filled in pencil, so it uses more
sensitive ink settings.

## Templates and print colours

| Template | Print colour | Anchors | Notes |
|---|---|---|---|
| `sheet80_v2` | magenta | magenta panel boxes | Customer sheet (confidential); ballpoint pen |
| `tamaulipas_90` | orange | black frames (`anchor_source: "dark"`) | Public dataset sheet; pencil; 90 questions, 4-digit ID |

`print_color` selects a profile in `omr_engine/printcolor.py`. The profile sets the hue range, saturation and value
floors, and the soft strength map: magenta uses `min(R,B) − G`, orange uses `R − B`. The ink map uses
red-channel dropout and works for both colours.

The `tamaulipas_90` reference image was synthesised from filled DEV-split sheets (aligned, per-pixel
median, with bubble interiors taken from an upper percentile so the reference stays blank) by
`tools/template_calibration/tamaulipas/build_template.py`.

### External real-sheet benchmark

```powershell
.\.venv\Scripts\python.exe benchmarks\run_external.py --dataset tamaulipas --split test   # dev | test | all
```

Data: *Tamaulipas MCQ Exam Image Dataset*, Universidad Politécnica de Victoria, Mendeley Data, v2,
doi:[10.17632/djmynjwjpy.2](https://doi.org/10.17632/djmynjwjpy.2), licensed CC BY 4.0. The images live under
`benchmarks/data/external/tamaulipas/` (gitignored) and are never committed. The split by school is fixed in
`benchmarks/external_splits/tamaulipas.json`; calibration and tuning used DEV only.
