# OMR Scanner (MVP)

Reads the **80-question OMR sheet** (80 MCQs A–D, 10-digit roll no, paper set A/B/C) from scans, PDFs or phone photos. It grades the answers against per-set answer keys and sends doubtful marks to a review UI.

- Design: [ARCHITECTURE.md](ARCHITECTURE.md)
- Details per part: [backend/README.md](backend/README.md) · [frontend/README.md](frontend/README.md) · [benchmarks/README.md](benchmarks/README.md)

> **Security:** there is no authentication in the MVP. Run it on localhost or a trusted LAN only.
> **Sheet artwork:** the 80-question sheet's source PDF and reference PNG are third-party artwork and are not in this repo. `templates/sheet80_v2/template.json` (bubble geometry) is included. To use that template, put the PDF at `templates/sheet80_v2/source.pdf` and run `python tools/template_calibration/render.py templates/sheet80_v2/source.pdf templates/sheet80_v2/template_200dpi.png`. Without it, `tamaulipas_90` works out of the box, and tests that need sheet80 are skipped.

## Prerequisites (Windows)
- Python 3.12, with the venv at `.venv`. To recreate it: `py -3.12 -m venv .venv; .\.venv\Scripts\pip install -r backend\requirements.txt`
- Node 26 LTS, then `cd frontend; npm ci`

## Run
```powershell
# terminal 1 — API on :8000
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
# terminal 2 — UI on :5173 (proxies /api to :8000)
cd frontend; npm run dev
```
Open http://localhost:5173. Create an answer key, upload sheets, then review and export a CSV.

## Test & benchmark
```powershell
.\.venv\Scripts\python.exe -m pytest backend benchmarks -q          # 108 tests
cd frontend; npx vitest run; npm run build                         # 65 tests + type-check
.\.venv\Scripts\python.exe benchmarks\run_benchmark.py --n 50 --tiers clean,scan,photo,hard --seed 2026 --check-targets
```

## Results so far (synthetic benchmark, seed 2026, 50 sheets per tier, not used for tuning)

| Tier | Question acc. | Roll no exact | Sheet exact | p95 latency |
|---|---|---|---|---|
| clean | 99.95% (target ≥ 99.9) | 100% | 98% | 263 ms |
| scan | 99.95% (target ≥ 99.5) | 100% | 98% | 306 ms |
| photo | 100.00% (target ≥ 98) | 100% | 100% | 335 ms |
| hard | 99.98% | 100% | 98% | 375 ms |

5 of 16,000 answers were wrong, all of them sparse scribble fills. 3 of those were flagged for review. Throughput is about 3.5 sheets/s on one CPU core.
These are **synthetic** results. Validate on 20–50 real printed, hand-filled sheets (see `benchmarks/data/real/` in the benchmarks README) before production use.

## Real-world evaluation (real student sheets)

Dataset: [Tamaulipas MCQ Exam Image Dataset](https://data.mendeley.com/datasets/djmynjwjpy) (Universidad Politécnica de Victoria, DOI 10.17632/djmynjwjpy.2, CC BY 4.0).
The sample is 180 real pencil-filled, flatbed-scanned sheets from 8 schools (16,200 labelled answers), read with template `tamaulipas_90`.
The split is by school and was fixed before tuning: calibration and tuning used DEV schools only, and TEST was scored once with frozen settings.

| Split | Question acc. (strict) | Silent errors | 4-digit ID exact | Sheet exact | Sheets sent to review |
|---|---|---|---|---|---|
| **TEST** (84 sheets, held out) | **99.92%** | 0.01% | 98.8% | 97.6% | 4.8% |
| DEV (96 sheets) | 99.90% | 0.03% | 95.8% | 90.6% | 24.0% |

Most remaining errors are very light or outline-only pencil marks. On TEST, 6 of 7 come from one student, and most were flagged for review. There are 2 suspected label errors (`benchmarks/external_splits/tamaulipas_label_notes.json`).
To reproduce:
1. `python -I tools/external_data/fetch_tamaulipas.py --out benchmarks/data/external/tamaulipas/sheets --schools 8 --per-folder 12`
2. `python benchmarks/run_external.py --dataset tamaulipas --split test`

Latency note: the most recent runs were on battery, with the CPU capped at 1.5 GHz. Sheet80 p95 was then 1.04 s, against about 0.35 s on mains power.

## Repository layout
`backend/omr_engine` (pure CV library) · `backend/app` (FastAPI + SQLite) · `frontend` (React + TS + Vite) · `benchmarks` (synthetic generator + metrics) · `templates/sheet80_v2` (sheet geometry) · `tools/template_calibration` (scripts that produced the geometry).
