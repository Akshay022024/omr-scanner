# OMR benchmark report

- Generated: 2026-11-24T11:29:18Z
- Engine version: 0.1.0
- Seed: 2026, sheets per synthetic tier: 50, tiers: clean, scan, photo, hard

| Metric | clean | scan | photo | hard | overall |
|---|---:|---:|---:|---:|---:|
| Sheets | 50 | 50 | 50 | 50 | 200 |
| Question accuracy (strict) | 99.95% | 99.95% | 100.00% | 99.98% | 99.97% |
| Question accuracy (lenient) | 99.95% | 100.00% | 100.00% | 100.00% | 99.99% |
| Silent error rate | 0.050% | 0.000% | 0.000% | 0.000% | 0.013% |
| Bubble accuracy | 99.991% | 99.991% | 100.000% | 99.995% | 99.994% |
| Roll no exact | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% |
| Paper set accuracy | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% |
| Sheet exact match | 98.00% | 98.00% | 100.00% | 98.00% | 98.50% |
| Blank precision | 99.03% | 99.03% | 100.00% | 100.00% | 99.51% |
| Blank recall | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% |
| Multiple precision | 100.00% | 100.00% | 100.00% | 98.78% | 99.69% |
| Multiple recall | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% |
| Distractor false-fill | 0.00% | 0.00% | 0.00% | 1.49% | 0.37% |
| Distractor flagged | 0.00% | 1.49% | 0.00% | 4.48% | 1.49% |
| Question review rate | 0.00% | 0.05% | 0.00% | 0.07% | 0.03% |
| Sheets needs_review | 86.00% | 86.00% | 86.00% | 88.00% | 86.50% |
| Avg flags / sheet | 1.62 | 1.66 | 1.62 | 1.68 | 1.65 |
| Registration failures | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% |
| Registration quality (mean) | 0.885 | 0.753 | 0.666 | 0.320 | 0.656 |
| Latency p50 (ms) | 750 | 813 | 807 | 1002 | 816 |
| Latency p95 (ms) | 876 | 963 | 1010 | 1176 | 1040 |
| Latency mean (ms) | 764 | 839 | 830 | 1020 | 863 |
| Throughput (sheets/s) | 1.31 | 1.19 | 1.21 | 0.98 | 1.16 |

## Targets

| Target | Value | Status |
|---|---:|---|
| clean question accuracy >= 99.9% | 99.950% | PASS |
| scan question accuracy >= 99.5% | 99.950% | PASS |
| photo question accuracy >= 98.0% | 100.000% | PASS |
| latency p95 < 1500 ms | 1040 ms | PASS |

## Top error patterns

- **clean**: missed_fill x2
- **scan**: missed_fill x2
- **hard**: false_multiple:cross x1
- **overall**: missed_fill x4, false_multiple:cross x1

## Fill recall by mark style (overall)

| Style | Count | Recall |
|---|---:|---:|
| heavy | 2680 | 100.00% |
| overshoot | 888 | 100.00% |
| partial | 2576 | 100.00% |
| scribble | 2472 | 99.84% |
| solid | 8936 | 100.00% |

## Distractors (GT = not filled)

| Type | Count | Read as filled | Flagged |
|---|---:|---:|---:|
| cross | 112 | 0.89% | 2.68% |
| smudge | 60 | 0.00% | 0.00% |
| tick | 96 | 0.00% | 1.04% |

## Sample misreads

| Tier | Sample | Field | Expected | Got | Kind | State | Style |
|---|---|---|---|---|---|---|---|
| clean | clean_0025 | q9 | D | (blank) | missed_fill | blank | scribble |
| hard | hard_0006 | q12 | B | BC | false_multiple:cross | ambiguous | scribble |
| scan | scan_0025 | q9 | D | (blank) | missed_fill | ambiguous | scribble |
| clean | clean_0025 | q21 | B | (blank) | missed_fill | blank | scribble |
| scan | scan_0025 | q21 | B | (blank) | missed_fill | ambiguous | scribble |
