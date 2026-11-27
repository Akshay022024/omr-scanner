# OMR benchmark

This is a reproducible accuracy and speed benchmark for `backend/omr_engine`. It renders the real template
(`templates/sheet80_v2`) and simulates how students fill it in. It then degrades each sheet the way a scanner
or phone camera would, runs `omr_engine.scan_image()` on it (the same function the API uses), and scores the
result against the exact ground truth.

Everything runs locally. The template is confidential customer material, so this suite never uploads anything.

## Running it

From the project root (Windows PowerShell):

```powershell
# full benchmark (writes benchmarks/reports/latest.json, latest.md, history/<timestamp>.json)
.\.venv\Scripts\python.exe benchmarks\run_benchmark.py --n 50 --tiers clean,scan,photo,hard --seed 42

# also save the first 5 samples of each tier (jpg + json) to benchmarks/data/<tier>/
.\.venv\Scripts\python.exe benchmarks\run_benchmark.py --n 20 --save-samples 5

# only generate samples, no engine needed
.\.venv\Scripts\python.exe benchmarks\run_benchmark.py --n 5 --save-samples 5 --generate-only

# use as a CI gate: exit code 1 if an MVP target is missed
.\.venv\Scripts\python.exe benchmarks\run_benchmark.py --n 50 --check-targets

# unit tests for the generator, degrader and metrics (no engine required)
.\.venv\Scripts\python.exe -m pytest benchmarks -q
```

Other options: `--out DIR`, `--data-dir DIR`, `--template DIR`, `--real-dir DIR`, `--no-real`, `--blank-rate`,
`--multiple-rate`, `--distractor-rate`, `-q`.

If `omr_engine` cannot be imported, the runner prints the reason and exits with code 2.

**Reproducibility.** Sheet *i* is generated with `default_rng([seed, i])` and degraded with
`default_rng([seed, i, crc32(tier)])`. Every tier therefore sees the same filled sheets, and a given seed
always produces identical pixels. Sheets are generated in memory. Latency is measured with a wall clock around
`scan_image` only. One warm-up scan runs first and is excluded from the latency figures.

No new dependencies are needed. The suite uses only what is already in the venv: numpy, opencv-python-headless
and pytest.

## Layout

| Path | What it does |
|---|---|
| `synth/handwriting.py` | Ballpoint marks: `solid`, `heavy`, `partial` (60–85 % coverage), `scribble`, `overshoot`. Distractors: `tick`, `cross`, `smudge`. Also handwriting text, signatures and stray strokes. Marks are supersampled and multiply-blended, with pressure variation and slight blur. |
| `synth/generator.py` | `generate_sheet(rng, template, style_mix) -> (bgr 1700x2200, ground_truth)`. `StyleMix` sets the fill-style weights, blank rate (5 %), multiple rate (2 %) and distractor rate (2 %), plus the probabilities for handwriting, signature and stray marks. |
| `synth/degrade.py` | `degrade(img, tier, rng) -> (img, meta)` for the tiers `clean`, `scan`, `photo`, `hard`. |
| `metrics.py` | Engine-independent scoring (`normalize_prediction`, `score_sheet`, `aggregate`). |
| `run_benchmark.py` | The command-line runner. |
| `tests/test_synth.py` | Unit tests. |
| `data/` | Saved samples and real photos. This folder is gitignored. |
| `reports/` | `latest.json` (shown by the frontend Benchmarks page), `latest.md` and `history/`. |

### Degradation tiers

| Tier | Simulates |
|---|---|
| `clean` | A digital render with no noise, at 1700x2200. |
| `scan` | A flatbed scan: ±2° rotation, 0.97–1.03 scale, small shift, resampled to 150–300 dpi (output 1275x1650 … 2550x3300), grey scanner-lid border, cream paper tone, blur, gaussian noise, JPEG q60–90. |
| `photo` | A phone photo. The page fills 60–88 % of the frame height on a wood, dark-fabric or grey-table background, in frames from 1200x1600 to 3000x4000. Also: perspective/keystone ≤7 %, ±6° rotation, slight paper bend (≤3 template px), drop shadow, illumination gradient, vignette, optional shadow band, white-balance error (warm or cool), defocus blur, sensor noise, JPEG q70–92. |
| `hard` | A hard photo: strong perspective (6–14 %), ±12° rotation, paper bend of 2–8 px, dark shadow bands, frames of 1080x1440 to 1536x2048, motion blur (3–7 px), more noise, JPEG q50–75. This tier is reported only and has no target. |

## Metrics

All metrics are reported per tier and overall. `overall` covers the synthetic tiers only. The `real` tier is
reported separately.

| Metric | Meaning |
|---|---|
| `question_accuracy` | **Primary metric.** The predicted answer string equals the ground-truth string exactly. A blank must be read as blank, and a multiple mark must match letter for letter. |
| `question_accuracy_lenient` | (correct + wrong-but-flagged-`ambiguous`) / total. An ambiguous read goes to human review, so it counts as review rather than error. A failed sheet also counts as review. |
| `silent_error_rate` | The share of answers that are wrong **and** not flagged. These are the errors a human reviewer would never see. |
| `question_review_rate` | The share of questions in the `ambiguous` state. |
| `bubble_accuracy` | Per bubble, whether filled / not filled matches the ground truth (roll + set + answers). |
| `roll_exact`, `paper_set_accuracy` | The 10-digit roll number matches exactly; the paper set matches. |
| `sheet_exact` | All 80 answers, the roll number and the paper set are all correct. |
| `blank_precision` / `blank_recall` | A positive is a question left blank in the ground truth. A predicted positive is a predicted answer of `""`. |
| `multiple_precision` / `multiple_recall` | A positive is a ground-truth answer with more than one letter. A predicted positive is a prediction with more than one letter. |
| `distractor_false_fill_rate` | The share of tick, cross and smudge bubbles (ground truth: *not filled*) that were read as filled. The rate is also broken down by type, alongside `flagged_rate` (the question was flagged ambiguous). |
| `fill_recall_by_style` | For each fill style, the share of filled bubbles that were detected. This shows which pen styles the engine misses. |
| `review_rate`, `avg_flags_per_sheet` | The fraction of sheets with `status == needs_review`, and the mean number of `review_flags`. |
| `registration_failure_rate` | The fraction of sheets with `status == failed`, or where the engine raised an exception. Every question on a failed sheet counts as wrong in the strict metrics. |
| `latency_ms` p50/p95/mean/max, `throughput_sheets_per_s` | Wall-clock time of `scan_image`, and sheets per second of scan time. `engine_stage_ms_mean` averages the engine's own `timings_ms`. |
| `error_breakdown` | Error counts by kind: `missed_fill`, `false_fill`, `wrong_option`, `missed_multiple`, `false_multiple`, `multiple_mismatch`, `roll:*`, `set:*`, `registration_failed`. A `:tick`, `:cross` or `:smudge` suffix means a distractor was read as a fill. |
| `errors_sample` | Up to 20 misreads, spread across tiers and error kinds, each with tier, sample, field, expected, got, state, style and scores. |

### MVP targets

| Target | Value |
|---|---|
| `clean` question accuracy | ≥ 99.9 % |
| `scan` question accuracy | ≥ 99.5 % |
| `photo` question accuracy | ≥ 98 % |
| `hard` | reported only |
| Latency p95 | < 1.5 s per sheet (laptop CPU) |

`latest.json` includes `targets_check`, which lists each target with PASS or FAIL.

## Real sheets (`real` tier)

Filled OMR pictures from the web can't be used. They use other layouts and have no ground truth, so they can't
score this template. To check real-world accuracy, print **this** sheet (`templates/sheet80_v2/source.pdf`),
have people fill it in with blue or black ballpoint, then scan or photograph it.

For each sheet, put two files with the same stem into `benchmarks/data/real/`:

```
benchmarks/data/real/
  s001_phone.jpg      # or .png / .jpeg / .tif / .webp
  s001_phone.json     # ground truth
```

The runner scores them automatically as tier `real`. Use `--no-real` to skip them. The ground-truth JSON uses
the same schema as the generator, and only these three keys are required:

```json
{
  "roll_no": "2024001234",
  "paper_set": "B",
  "answers": {"1": "A", "2": "", "3": "BD", "4": "C", "...": "...", "80": "D"}
}
```

Labelling rules:

- Include all 80 questions, keyed `"1"` … `"80"`.
- `""` = blank. Several letters = a multiple mark, written in option order (`"AC"`, not `"CA"`).
- A tick, cross, dot or erased smudge does **not** count as filled. If you want those tracked as distractors, add
  `"flags": {"7": {"distractor": "tick", "distractor_option": "B"}}`.
- `roll_no` is the 10 digits as **bubbled**, not as handwritten in the boxes. Use `"?"` for a column with no
  bubble filled.
- `paper_set` is `"A"`, `"B"`, `"C"`, or `""` if left blank.
- Label from the paper itself, not from the scanner's output, and get a second person to check the labels.
- Aim for 20–50 sheets: a mix of flatbed scans and phone photos, different lighting, and both pen colours.
- Real student sheets are personal data. Keep them on local or trusted storage only. `benchmarks/data/` is
  gitignored.

## Limitations

- Synthetic data overestimates real-world accuracy. Real pens, paper, printers and cameras vary more than the
  simulation does. Treat the synthetic numbers as a regression gate, and use the `real` tier for go/no-go
  decisions.
- The distractor marks (tick, cross, smudge) are a judgement call. The ground truth says *not filled*, and the
  engine may flag them ambiguous instead. Look at `distractor_flagged_rate` together with
  `distractor_false_fill_rate`.
- The simulated handwriting uses Hershey script fonts and looks fairly neat. It tests robustness to dark strokes
  outside the bubbles, not handwriting recognition.
