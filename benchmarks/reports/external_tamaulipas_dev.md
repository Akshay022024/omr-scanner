# External benchmark: tamaulipas (dev)

- Generated: 2026-11-24T10:51:57Z
- Engine version: 0.1.0
- Data: Tamaulipas MCQ Exam Image Dataset, Universidad Politecnica de Victoria, Mendeley Data v2, doi:10.17632/djmynjwjpy.2, CC BY 4.0
- Schools: School001, School011, School021, School031

| Metric | Value |
|---|---:|
| Sheets | 96 |
| Questions | 8640 |
| Question accuracy (strict) | 99.90% |
| Question accuracy (lenient: ambiguous = review) | 99.97% |
| Strict, excluding suspected label errors | 99.90% |
| Silent error rate | 0.03% |
| Question review rate | 0.25% |
| Blank precision | 95.20% |
| Blank recall | 100.00% |
| Multiple precision | 66.67% |
| Multiple recall | 100.00% |
| Labelled blanks / multiples | 119 / 6 |
| ID exact match | 95.83% |
| Sheet exact match | 90.62% |
| Sheets needs_review | 23.96% |
| Failure rate | 0.00% |
| Latency p50 (ms) | 764 |
| Latency p95 (ms) | 811 |

## Errors by kind

- id:missed_fill: 7
- missed_fill: 6
- false_multiple: 3
- id:wrong_option: 1
- id:false_multiple: 1

Suspected label errors (counted above as errors): 1

## Per school

| School | Sheets | Strict | Silent | ID exact |
|---|---:|---:|---:|---:|
| School001 | 24 | 99.91% | 0.05% | 95.83% |
| School011 | 24 | 100.00% | 0.00% | 100.00% |
| School021 | 24 | 100.00% | 0.00% | 100.00% |
| School031 | 24 | 99.68% | 0.09% | 87.50% |

## Errors

| Sheet | Field | Expected | Got | State | Kind | Suspected label error |
|---|---|---|---|---|---|---|
| School001_Grade10_File0002 | id_2 | 2 |  | blank | id:missed_fill |  |
| School001_Grade10_File0002 | id_4 | 1 |  | ambiguous | id:missed_fill |  |
| School001_Grade12_File0011 | q79 | A | (blank) | blank | missed_fill |  |
| School001_Grade12_File0012 | q86 | B | (blank) | ambiguous | missed_fill |  |
| School031_Grade10_File0001 | q62 | D | (blank) | ambiguous | missed_fill |  |
| School031_Grade10_File0002 | id_2 | 6 |  | ambiguous | id:missed_fill |  |
| School031_Grade10_File0002 | id_3 | 8 |  | blank | id:missed_fill |  |
| School031_Grade10_File0002 | id_4 | 8 |  | blank | id:missed_fill |  |
| School031_Grade10_File0002 | q21 | B | (blank) | ambiguous | missed_fill |  |
| School031_Grade10_File0002 | q23 | A | (blank) | ambiguous | missed_fill |  |
| School031_Grade10_File0002 | q39 | A | (blank) | ambiguous | missed_fill |  |
| School031_Grade10_File0003 | q78 | A | AB | multiple | false_multiple |  |
| School031_Grade10_File0010 | id_1 | 1 | 1 | ambiguous | id:wrong_option |  |
| School031_Grade10_File0010 | id_2 | 7 | 67 | multiple | id:false_multiple | yes |
| School031_Grade10_File0010 | q28 | C | BC | ambiguous | false_multiple |  |
| School031_Grade10_File0011 | id_2 | 6 |  | ambiguous | id:missed_fill |  |
| School031_Grade10_File0011 | id_4 | 8 |  | blank | id:missed_fill |  |
| School031_Grade12_File0003 | q18 | A | AD | multiple | false_multiple |  |
