import { describe, expect, it } from 'vitest';
import type { AnswerKey } from '../api/types';
import {
  accuracyVerdict,
  extractErrorsSample,
  extractOverall,
  extractTargetChecks,
  extractTiers,
  latencyVerdict,
  metricValue,
  targetsFrom,
} from './benchmark';
import { isAcceptedType, MAX_FILES, MAX_FILE_BYTES, mergeFiles } from './files';
import { fmtPct, toFraction } from './format';
import { gradeAnswers } from './grade';
import { queueNeighbours } from './queue';

describe('mergeFiles', () => {
  const f = (name: string, size = 100, type = '') => ({ name, size, type });

  it('accepts supported types by extension and MIME', () => {
    expect(isAcceptedType(f('a.JPG', 1, 'image/jpeg'))).toBe(true);
    expect(isAcceptedType(f('a.tiff', 1, ''))).toBe(true);
    expect(isAcceptedType(f('a.pdf', 1, 'application/pdf'))).toBe(true);
    expect(isAcceptedType(f('a.gif', 1, 'image/gif'))).toBe(false);
    expect(isAcceptedType(f('a.png', 1, 'text/html'))).toBe(false);
  });

  it('rejects bad type, oversize, empty and duplicates', () => {
    const res = mergeFiles([f('a.png')], [f('b.gif'), f('c.jpg', MAX_FILE_BYTES + 1), f('d.jpg', 0), f('a.png'), f('e.webp')]);
    expect(res.accepted.map((x) => x.name)).toEqual(['a.png', 'e.webp']);
    expect(res.rejected.map((x) => x.name)).toEqual(['b.gif', 'c.jpg', 'd.jpg', 'a.png']);
  });

  it('enforces the file count limit', () => {
    const many = Array.from({ length: MAX_FILES + 3 }, (_, i) => f(`s${i}.jpg`));
    const res = mergeFiles([], many);
    expect(res.accepted).toHaveLength(MAX_FILES);
    expect(res.rejected).toHaveLength(3);
  });
});

describe('queueNeighbours', () => {
  const items = [
    { id: 1, q: false },
    { id: 2, q: true },
    { id: 3, q: false },
    { id: 4, q: true },
    { id: 5, q: true },
  ];
  const inQ = (t: { q: boolean }) => t.q;

  it('finds prev / next in queue relative to the current item', () => {
    const n = queueNeighbours(items, '4', inQ);
    expect(n.prev?.id).toBe(2);
    expect(n.next?.id).toBe(5);
    expect(n.position).toBe(2);
    expect(n.total).toBe(3);
  });

  it('works when the current item is not in the queue', () => {
    const n = queueNeighbours(items, 3, inQ);
    expect(n.prev?.id).toBe(2);
    expect(n.next?.id).toBe(4);
    expect(n.position).toBe(0);
  });

  it('handles unknown ids', () => {
    expect(queueNeighbours(items, 'zzz', inQ).next?.id).toBe(2);
  });
});

describe('format', () => {
  it('treats >1 as percentages', () => {
    expect(toFraction(0.995)).toBe(0.995);
    expect(toFraction(99.5)).toBeCloseTo(0.995);
    expect(toFraction(1)).toBe(1);
    expect(fmtPct(undefined)).toBe('—');
    expect(fmtPct(0.9987, 2)).toBe('99.87%');
  });
});

describe('benchmark report reader', () => {
  const report = {
    generated_at: '2026-11-24T10:00:00Z',
    overall: { question_accuracy: 0.99 },
    tiers: {
      photo: { metrics: { question_accuracy: 0.981, latency_ms: { p95: 1600 } } },
      clean: { question_accuracy: 0.9995, latency_p95_ms: 300, blank: { precision: 1 } },
    },
    errors_sample: [{ tier: 'photo', field: 'q1' }, 'junk'],
  };

  it('extracts and orders tiers', () => {
    expect(extractTiers(report).map((t) => t.name)).toEqual(['clean', 'photo']);
    expect(extractTiers({ tiers: [{ tier: 'scan', question_accuracy: 1 }] })[0].name).toBe('scan');
    expect(extractTiers(null)).toEqual([]);
  });

  it('reads metrics via aliases and nested paths', () => {
    const [clean, photo] = extractTiers(report);
    expect(metricValue(clean.data, 'question_accuracy')).toBe(0.9995);
    expect(metricValue(photo.data, 'question_accuracy')).toBe(0.981);
    expect(metricValue(photo.data, 'latency_p95')).toBe(1600);
    expect(metricValue(clean.data, 'blank_precision')).toBe(1);
    expect(metricValue(clean.data, 'multiple_recall')).toBeNull();
  });

  it('computes verdicts against MVP targets', () => {
    expect(accuracyVerdict('clean', 0.999)).toBe('pass');
    expect(accuracyVerdict('clean', 0.9989)).toBe('fail');
    expect(accuracyVerdict('scan', 99.6)).toBe('pass');
    expect(accuracyVerdict('photo', 0.979)).toBe('fail');
    expect(accuracyVerdict('hard', 0.5)).toBe('na');
    expect(accuracyVerdict('clean', null)).toBe('na');
    expect(latencyVerdict(1499)).toBe('pass');
    expect(latencyVerdict(1500)).toBe('fail');
    expect(latencyVerdict(null)).toBe('na');
  });

  it('reads the real runner shape (n_sheets, latency_ms.*, paper_set_accuracy, avg_flags_per_sheet)', () => {
    const tier = {
      n_sheets: 20,
      paper_set_accuracy: 1,
      review_rate: 0.75,
      avg_flags_per_sheet: 1.85,
      registration_failure_rate: 0,
      latency_ms: { p50: 196, p95: 220, mean: 200 },
      throughput_sheets_per_s: 4.98,
    };
    expect(metricValue(tier, 'n')).toBe(20);
    expect(metricValue(tier, 'set_accuracy')).toBe(1);
    expect(metricValue(tier, 'review_rate')).toBe(0.75);
    expect(metricValue(tier, 'flags_per_sheet')).toBe(1.85);
    expect(metricValue(tier, 'failure_rate')).toBe(0);
    expect(metricValue(tier, 'latency_p50')).toBe(196);
    expect(metricValue(tier, 'throughput')).toBe(4.98);
  });

  it('prefers targets embedded in the report and reads targets_check', () => {
    const r = {
      targets: { question_accuracy: { clean: 0.99, photo: 97 }, latency_p95_ms: 900 },
      targets_check: [{ name: 'clean', value: '99.7%', pass: true }, { name: 'x' }, 'junk'],
    };
    const t = targetsFrom(r);
    expect(t.accuracy.clean).toBe(0.99);
    expect(t.accuracy.photo).toBeCloseTo(0.97);
    expect(t.accuracy.scan).toBe(0.995); // default kept
    expect(t.p95Ms).toBe(900);
    expect(accuracyVerdict('clean', 0.995, t.accuracy)).toBe('pass');
    expect(latencyVerdict(1000, t.p95Ms)).toBe('fail');
    expect(extractTargetChecks(r)).toEqual([
      { name: 'clean', value: '99.7%', pass: true },
      { name: 'x', value: '', pass: null },
    ]);
    expect(targetsFrom({}).p95Ms).toBe(1500);
  });

  it('extracts overall and error samples', () => {
    expect(extractOverall(report)).toEqual({ question_accuracy: 0.99 });
    expect(extractErrorsSample(report)).toEqual([{ tier: 'photo', field: 'q1' }]);
  });
});

describe('gradeAnswers (mock grading mirror)', () => {
  const key: AnswerKey = {
    id: 'k',
    name: 'k',
    template_id: 't',
    keys: { A: { '1': 'A', '2': 'B', '3': 'C', '4': 'D' } },
    marks_correct: 4,
    marks_wrong: -1,
    marks_blank: 0,
  };
  it('applies negative marking and counts multiple as wrong', () => {
    const g = gradeAnswers({ '1': 'A', '2': 'C', '3': '', '4': 'AD' }, 'A', key, 5);
    expect(g).toMatchObject({ correct: 1, wrong: 1, blank: 1, multiple: 1, score: 2, max_score: 16, paper_set_used: 'A' });
    expect(g.per_question['5']).toBe('no_key');
  });
});
