# OMR Scanner — Architecture & System Design (MVP)

Status: MVP. Target sheet: **80-question OMR sheet, v2** (`templates/sheet80_v2`).
The template is confidential customer material; it stays local and is never uploaded or published.

## 1. Goals

| Goal | MVP target |
|---|---|
| Read 80 MCQ answers (A–D), 10-digit roll no, paper set (A/B/C) | yes |
| Inputs: flatbed scans (JPG/PNG/TIFF), multi-page PDFs, phone photos | yes |
| Grade against per-paper-set answer keys, with +/− marking | yes |
| Flag blank / multiple / ambiguous marks for human review | yes |
| Web UI: upload batch, review overlay, correct, export CSV | yes |
| Reproducible benchmark with accuracy + speed scores | yes |
| Auth, multi-tenant, cloud deploy, GitHub push | **out of scope** (no push until tests and benchmark pass) |

**Accuracy targets** (question-level accuracy on the synthetic benchmark):
`clean ≥ 99.9%`, `scan ≥ 99.5%`, `photo ≥ 98%`, `hard`: reported only.
**Speed target:** p95 under 1.5 s per sheet on a laptop CPU.

## 2. Key facts about the sheet (measured from the PDF)

- US Letter, 612×792 pt. The canonical template space is **1700×2200 px (200 dpi)**.
- All print is **magenta** (OpenCV HSV hue ≈ 130–179, high saturation). Students mark with **blue/black ballpoint**.
  → **Colour dropout**: suppress magenta, keep dark or blue pixels. This is the main accuracy lever.
- **No corner fiducials.** Registration relies on the page outline plus the 7 magenta panel boxes (`anchors` in template.json).
- Bubbles: roll/set r≈14 px, answers r≈15 px (template px). Letters are printed *inside* the bubbles in magenta, and colour dropout removes them.
- Answer rows are not perfectly uniform (pitch 51–56 px). That is why `template.json` stores every bubble centre explicitly instead of using a grid formula.

## 3. High-level architecture

```
 ┌──────────────────────┐   /api (JSON, multipart)  ┌───────────────────────────────┐
 │ frontend/ (React+TS, │ ───────────────────────►  │ backend/app (FastAPI)          │
 │ Vite, port 5173)     │ ◄───────────────────────  │  routes · schemas · SQLite     │
 └──────────────────────┘   Vite dev proxy → :8000  │  file store (data/)            │
                                                    └──────────────┬────────────────┘
                                                                   │ pure function calls
                                                    ┌──────────────▼────────────────┐
                                                    │ backend/omr_engine (library)   │
                                                    │ io → page → register → ink →   │
                                                    │ bubbles → decide → grade       │
                                                    └──────────────▲────────────────┘
                                                                   │ same public API
                                                    ┌──────────────┴────────────────┐
                                                    │ benchmarks/ (synthetic data   │
                                                    │ generator + metrics runner)   │
                                                    └───────────────────────────────┘
```

The engine is a **pure library**: no web code, no DB, deterministic. The API and the benchmark call the same `scan_image()`, so benchmark scores reflect production behaviour.

## 4. Repository layout

```
omr-scanner/
  ARCHITECTURE.md  README.md  .gitignore
  .venv/                         # shared Python 3.12 venv (not committed)
  templates/sheet80_v2/
    source.pdf  template_200dpi.png  template.json
  tools/template_calibration/    # scripts that produced template.json
  backend/
    requirements.txt  pyproject.toml (pytest config)
    omr_engine/
      __init__.py      # exports load_template, scan_image, scan_document, grade, render_overlay
      models.py        # pydantic models (ScanResult, FieldResult, GradeResult, AnswerKey, ...)
      template.py      # Template loading/validation, scaling helpers
      io.py            # bytes → list[np.ndarray BGR]; images + PDF via PyMuPDF; EXIF orientation
      page.py          # page/document quad detection, perspective normalisation, orientation (0/90/180/270)
      registration.py  # fine alignment to the template (feature + anchor-box based homography)
      ink.py           # magenta dropout → binary ink map
      bubbles.py       # per-bubble fill score
      decide.py        # per-field decision (blank/single/multiple/ambiguous) + confidence
      grading.py       # grade(ScanResult, AnswerKey) → GradeResult
      overlay.py       # debug/review overlay rendering
      config.py        # all thresholds in one dataclass (EngineConfig)
    app/
      main.py          # FastAPI app factory, CORS, static, lifespan
      config.py        # settings via env (OMR_DATA_DIR, OMR_MAX_UPLOAD_MB, ...)
      db.py            # sqlite3 (stdlib) repository layer, schema migrations
      schemas.py       # API request/response models
      routes/  health.py templates.py answer_keys.py scans.py batches.py benchmarks.py
    tests/  unit/ (engine)  api/ (FastAPI TestClient)  conftest.py
  benchmarks/
    synth/ generator.py  degrade.py  handwriting.py
    run_benchmark.py     # CLI: generate (seeded) → scan → metrics → reports/
    data/                # generated datasets (gitignored)
    reports/             # latest.json, latest.md, history/
  frontend/              # Vite + React 18 + TypeScript
  data/                  # runtime uploads + sqlite db (gitignored)
```

## 5. Engine pipeline

| # | Stage | Module | Technique | Output |
|---|---|---|---|---|
| 1 | Load | `io` | PIL/OpenCV decode, EXIF transpose, PyMuPDF renders PDF pages at 200 dpi. Max side clamp 4000 px. | list of BGR images |
| 2 | Page normalise | `page` | Downscale, find the largest 4-point contour (paper on background), perspective-warp to 1700×2200. If there is no clear page edge (flatbed scan, page fills the frame), use the full frame. Orientation is chosen by testing 0/90/180/270 against the magenta layout. | coarse-aligned image |
| 3 | Register | `registration` | Magenta mask of the input vs the template's magenta mask. (a) ECC (`MOTION_HOMOGRAPHY`) on blurred masks, coarse-to-fine; (b) fallback: ORB features + RANSAC homography; (c) refinement: detect the 7 anchor boxes and solve the homography from box corners. Quality = IoU of warped magenta mask vs template mask. | 1700×2200 aligned image + `registration.quality` |
| 4 | Ink map | `ink` | HSV: ink = (V low ∧ S low) [black/graphite] ∨ (hue in blue band ∧ S moderate) [blue pen]; magenta excluded; adaptive normalisation for uneven lighting (divide by a large-kernel background estimate). | binary ink mask |
| 5 | Bubble score | `bubbles` | For each bubble: ink fraction in a disc of radius 0.75·r, plus a local ±4 px search to absorb residual misalignment (take the max over small shifts). | score ∈ [0,1] per bubble |
| 6 | Decide | `decide` | Per-sheet adaptive threshold: Otsu / largest gap on all scores, clamped to `[cfg.min_thr, cfg.max_thr]`. Per field: 0 marked → `blank`, 1 → `single`, >1 → `multiple`; any score within `cfg.ambiguity_margin` of the threshold → `ambiguous` (needs review). Confidence = normalised distance from the threshold. | `FieldResult`s |
| 7 | Assemble | `__init__` | roll_no string (`?` = blank/ambiguous digit, `*` = multiple), paper_set, status: `ok`, `needs_review` (any flags or low registration quality), or `failed`. | `ScanResult` |
| 8 | Grade | `grading` | Answer key per paper set; marks_correct / marks_wrong (negative allowed) / marks_blank; multiple counts as wrong. | `GradeResult` |

All thresholds live in `EngineConfig` so the benchmark can sweep them.

## 6. Engine public API (contract, do not break)

```python
from omr_engine import load_template, scan_image, scan_document, grade, render_overlay, EngineConfig

tpl = load_template("templates/sheet80_v2")              # dir containing template.json
res = scan_image(img_bgr, tpl, config=EngineConfig())       # -> ScanResult (single page)
results = scan_document(file_bytes, filename, tpl)          # -> list[ScanResult] (pdf: one per page)
g = grade(res, answer_key)                                  # -> GradeResult
png = render_overlay(img_bgr, res, tpl)                     # -> np.ndarray BGR, aligned + coloured circles
```

`ScanResult` (pydantic v2, `.model_dump()` is the JSON form used by the API):
```jsonc
{
  "template_id": "sheet80_v2",
  "status": "ok" | "needs_review" | "failed",
  "error": null,
  "roll_no": "20240?1234",
  "paper_set": "A",                         // null if blank/ambiguous
  "answers": {"1": "A", "2": "", "3": "AC"}, // "" blank; >1 letter = multiple
  "fields": [{
      "id": "q3", "group": "answers", "question": 3,
      "state": "single" | "blank" | "multiple" | "ambiguous",
      "value": "AC", "confidence": 0.93,
      "scores": {"A": 0.71, "B": 0.02, "C": 0.64, "D": 0.03}
  }],
  "review_flags": ["q3:multiple", "roll_6:blank"],
  "registration": {"method": "ecc|orb|anchors|identity", "quality": 0.97, "homography": [[...],[...],[...]]},
  "threshold": 0.42,
  "aligned_size": [1700, 2200],
  "timings_ms": {"load": 12, "page": 30, "register": 180, "read": 20, "total": 250}
}
```
`AnswerKey`: `{ "id", "name", "template_id", "keys": {"A": {"1":"B",...}, "B": {...}, "C": {...}}, "marks_correct": 1, "marks_wrong": 0, "marks_blank": 0 }`
`GradeResult`: `{ "answer_key_id", "paper_set_used", "score", "max_score", "correct", "wrong", "blank", "multiple", "per_question": {"1": "correct|wrong|blank|multiple|no_key"} }`

## 7. REST API (FastAPI, prefix `/api`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness + engine version |
| GET | `/templates` · `/templates/{id}` · `/templates/{id}/image` | list, geometry (for client overlays), reference PNG |
| GET/POST | `/answer-keys` | list / create |
| GET/PUT/DELETE | `/answer-keys/{id}` | CRUD |
| POST | `/scans` | multipart `files[]`, `template_id`, optional `answer_key_id`. Creates a batch, runs synchronously (MVP), returns `{batch_id, scans:[ScanRecord]}` |
| GET | `/scans?batch_id=` · `/scans/{id}` | list / detail (`ScanRecord` = id, batch_id, filename, page, created_at, result: ScanResult, grade: GradeResult \| null, corrected: bool) |
| GET | `/scans/{id}/overlay.png` · `/scans/{id}/aligned.png` · `/scans/{id}/original` | images for review |
| PATCH | `/scans/{id}` | manual corrections `{roll_no?, paper_set?, answers?: {"12":"B"}}` → re-grade, sets corrected=true |
| POST | `/scans/{id}/regrade` | body `{answer_key_id}` |
| GET | `/batches` · `/batches/{id}` · `/batches/{id}/export.csv` | batch summary and CSV export |
| GET | `/benchmarks/latest` | contents of `benchmarks/reports/latest.json` (404 if not run yet) |

**Security & limits (MVP).** Files are validated by magic bytes (JPEG/PNG/TIFF/WebP/PDF). Each file is capped at 20 MB, a request at 50 files, and a PDF at 20 pages. Uploads are stored under UUID filenames inside `OMR_DATA_DIR`, and user-supplied paths are never used. CORS only allows `http://localhost:5173`. SQL is parameterised. There is **no authentication in the MVP**, so it must run only on localhost or a trusted LAN (flagged in the README).

## 8. Persistence

SQLite (stdlib `sqlite3`, WAL mode) at `data/omr.db`. Tables: `answer_keys`, `batches`, `scans` (result JSON + grade JSON columns), `schema_version`. Files are stored in `data/uploads/{scan_id}/` (original and aligned.png).

## 9. Frontend (React 18 + TypeScript + Vite)

Pages: **Scan** (drag-drop batch upload, choose template + answer key, progress) · **Batch results** (table: file, roll no, set, score, status chips, CSV export) · **Review** (aligned image with SVG overlay drawn from template geometry plus result: green = marked, red = multiple, amber = ambiguous; click a question to correct it; next/prev in the needs_review queue) · **Answer keys** (80-question grid editor per paper set, marking scheme, paste "ABCD..." string) · **Benchmarks** (latest scores per tier, confusion stats, latency).
No UI framework dependency beyond React + react-router; plain CSS modules. API calls are typed in `src/api/`.

## 10. Benchmark design

**Why synthetic.** Random OMR photos from the web use different layouts and have no ground truth, so they cannot measure accuracy for *this* template. Instead `benchmarks/synth` renders the real template and simulates students:
- Fill styles: solid ballpoint (blue/black), heavy, light/partial (60–85% coverage), scribbly strokes, slight overshoot outside the circle, small tick/cross marks (should count as *not* filled, or flagged ambiguous), erased-but-visible smudges.
- Answer patterns: random answers with configurable blank rate (~5%) and multiple-mark rate (~2%); random roll no and paper set.
- **Degradation tiers** (seeded, reproducible):
  - `clean`: digital render, no noise.
  - `scan`: ±2° rotation, 0.97–1.03 scale, 150–300 dpi resample, gaussian noise, JPEG q60–90, slight blur, faint grey background.
  - `photo`: perspective warp (as from a phone), page placed on a textured/dark desk background, uneven illumination and shadow gradient, colour cast, blur, JPEG.
  - `hard`: strong perspective + shadows + low resolution + motion blur.
- Optional `benchmarks/data/real/`: drop in real photos plus `*.json` ground truth and they are scored the same way.

**Metrics** (`reports/latest.json`, per tier and overall):
bubble accuracy · question accuracy · roll-no exact-match rate · paper-set accuracy · sheet-level exact match · blank detection P/R · multiple-mark detection P/R · review rate (flags/sheet) · registration failure rate · latency p50/p95/mean · throughput (sheets/s).
`run_benchmark.py --n 50 --tiers clean,scan,photo,hard --seed 42` produces `latest.json`, `latest.md` and a history snapshot.

## 11. Testing strategy

- **Unit (engine)**: template loading/validation, ink dropout (magenta removed, blue/black kept), bubble scoring on drawn fills, decision logic edge cases (blank/multi/ambiguous), grading arithmetic incl. negative marking, registration recovers known rotations/perspective.
- **API**: FastAPI TestClient: health, answer-key CRUD, scan upload (PNG + PDF), bad file type rejected, size limit, PATCH correction re-grades, CSV export.
- **Frontend**: Vitest unit tests for API client + answer-string parser; `npm run build` must type-check cleanly.
- **Benchmark** is the accuracy regression gate.

## 12. Tech stack & dependencies (all newly introduced)

Python 3.12: `opencv-python-headless`, `numpy`, `pymupdf` (AGPL licence: fine for internal MVP, **review before commercial distribution**), `pillow`, `fastapi`, `uvicorn`, `python-multipart`, `pydantic` v2, `pytest`, `httpx`.
Node 26 LTS: `react`, `react-dom`, `react-router-dom`, `vite`, `typescript`, `vitest`.

## 13. Risks

- No fiducials → registration is the weakest link on phone photos; mitigated by layered ECC→ORB→anchor refinement and a quality gate that routes low-quality scans to review.
- Pink/red pens or pencil would break colour dropout; the instructions require blue/black ballpoint.
- PyMuPDF is AGPL (see above).
- Synthetic benchmarks overestimate real-world accuracy, so validate on 20–50 real printed and filled sheets before production use.
