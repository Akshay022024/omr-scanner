# External benchmark: tamaulipas (test)

- Generated: 2026-11-24T10:53:41Z
- Engine version: 0.1.0
- Data: Tamaulipas MCQ Exam Image Dataset, Universidad Politecnica de Victoria, Mendeley Data v2, doi:10.17632/djmynjwjpy.2, CC BY 4.0
- Schools: School006, School016, School026, School036

| Metric | Value |
|---|---:|
| Sheets | 84 |
| Questions | 7560 |
| Question accuracy (strict) | 99.92% |
| Question accuracy (lenient: ambiguous = review) | 99.99% |
| Strict, excluding suspected label errors | 99.93% |
| Silent error rate | 0.01% |
| Question review rate | 0.12% |
| Blank precision | 78.26% |
| Blank recall | 100.00% |
| Multiple precision | n/a |
| Multiple recall | n/a |
| Labelled blanks / multiples | 18 / 0 |
| ID exact match | 98.81% |
| Sheet exact match | 97.62% |
| Sheets needs_review | 4.76% |
| Failure rate | 0.00% |
| Latency p50 (ms) | 764 |
| Latency p95 (ms) | 805 |

## Errors by kind

- missed_fill: 5
- wrong_option: 1
- id:missed_fill: 1

Suspected label errors (counted above as errors): 1

## Per school

| School | Sheets | Strict | Silent | ID exact |
|---|---:|---:|---:|---:|
| School006 | 24 | 99.95% | 0.00% | 100.00% |
| School016 | 24 | 100.00% | 0.00% | 100.00% |
| School026 | 24 | 100.00% | 0.00% | 100.00% |
| School036 | 12 | 99.54% | 0.09% | 91.67% |

## Errors

| Sheet | Field | Expected | Got | State | Kind | Suspected label error |
|---|---|---|---|---|---|---|
| School006_Grade12_File0011 | q6 | D | B | ambiguous | wrong_option | yes |
| School036_Grade10_File0008 | id_2 | 1 |  | ambiguous | id:missed_fill |  |
| School036_Grade10_File0008 | q12 | B | (blank) | ambiguous | missed_fill |  |
| School036_Grade10_File0008 | q18 | A | (blank) | ambiguous | missed_fill |  |
| School036_Grade10_File0008 | q24 | C | (blank) | ambiguous | missed_fill |  |
| School036_Grade10_File0008 | q40 | B | (blank) | blank | missed_fill |  |
| School036_Grade10_File0008 | q48 | B | (blank) | ambiguous | missed_fill |  |
