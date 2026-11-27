/**
 * Dev-only mock API (enabled with VITE_USE_MOCKS=true). Serves an in-memory batch of 3 scans
 * (one needs_review) so the UI can be exercised without the backend. The template geometry is a
 * generated approximation of the real layout, not a copy of template.json.
 */
import { ApiError } from './errors';
import type { ApiClient, ApiUrls, UploadProgress, UploadRequest } from './client';
import type {
  AnswerKey,
  AnswerKeyInput,
  BatchSummary,
  BenchmarkReport,
  FieldResult,
  Id,
  ScanPatch,
  ScanRecord,
  ScanResult,
  ScanStatus,
  TemplateField,
  TemplateGeometry,
  UploadResponse,
} from './types';
import { gradeAnswers } from '../lib/grade';

const TEMPLATE_ID = 'sheet80_v2';
const OPTS = ['A', 'B', 'C', 'D'];
const DIGITS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'];

function buildGeometry(): TemplateGeometry {
  const fields: TemplateField[] = [];
  for (let k = 1; k <= 10; k++) {
    fields.push({
      id: `roll_${k}`,
      group: 'roll_no',
      type: 'digit',
      bubbles: DIGITS.map((d, i) => ({ value: d, x: 164.5 + 40 * (k - 1), y: 181.5 + 40 * i, r: 13.5 })),
    });
  }
  fields.push({
    id: 'paper_set',
    group: 'paper_set',
    type: 'choice',
    bubbles: ['A', 'B', 'C'].map((v, i) => ({ value: v, x: 693.5, y: 181.5 + 40 * i, r: 13.5 })),
  });
  for (let q = 1; q <= 80; q++) {
    const col = Math.floor((q - 1) / 20);
    const row = (q - 1) % 20;
    fields.push({
      id: `q${q}`,
      group: 'answers',
      type: 'choice',
      question: q,
      bubbles: OPTS.map((v, i) => ({ value: v, x: 174.5 + 380 * col + 40 * i, y: 888.5 + row * 53.16, r: 14.5 })),
    });
  }
  return {
    id: TEMPLATE_ID,
    name: '80-question OMR sheet (v2) [mock]',
    version: 1,
    page: { width_px: 1700, height_px: 2200, dpi: 200, paper: 'letter' },
    anchors: {
      roll_box: [94, 46, 745, 529],
      details_box: [94, 581, 744, 203],
      instructions_box: [850, 203, 744, 581],
      answers_col_1: [94, 821, 367, 1107],
      answers_col_2: [474, 821, 367, 1107],
      answers_col_3: [854, 821, 367, 1107],
      answers_col_4: [1234, 821, 361, 1107],
    },
    num_questions: 80,
    options: OPTS,
    fields,
  };
}

/** Deterministic PRNG so fixtures are stable across reloads. */
function rng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 2 ** 32;
  };
}

function makeKeySet(seed: number): Record<string, string> {
  const r = rng(seed);
  const out: Record<string, string> = {};
  for (let q = 1; q <= 80; q++) out[String(q)] = OPTS[Math.floor(r() * 4)];
  return out;
}

/** All mock state lives in this closure so that nothing runs (or ships) unless mock mode is enabled. */
export function createMockClient(): ApiClient {
  const geometry = buildGeometry();

  let keys: AnswerKey[] = [
    {
      id: 'key-demo',
      name: 'Midterm 2026 (demo)',
      template_id: TEMPLATE_ID,
      keys: { A: makeKeySet(1), B: makeKeySet(2), C: makeKeySet(3) },
      marks_correct: 4,
      marks_wrong: -1,
      marks_blank: 0,
    },
    {
      id: 'key-plain',
      name: 'Plain +1 (set A only)',
      template_id: TEMPLATE_ID,
      keys: { A: makeKeySet(1) },
      marks_correct: 1,
      marks_wrong: 0,
      marks_blank: 0,
    },
  ];

  interface SheetSpec {
    roll: string; // '?' = blank digit
    set: string;
    answers: Record<string, string>;
    ambiguous: string[]; // field ids flagged ambiguous
  }

  function makeSheet(seed: number, keySet: Record<string, string>, roll: string, set: string, tweak: (a: Record<string, string>) => void, ambiguous: string[] = []): SheetSpec {
    const r = rng(seed);
    const answers: Record<string, string> = {};
    for (let q = 1; q <= 80; q++) {
      const x = r();
      answers[String(q)] = x < 0.78 ? keySet[String(q)] : x < 0.95 ? OPTS[Math.floor(r() * 4)] : '';
    }
    tweak(answers);
    return { roll, set, answers, ambiguous };
  }

  function buildResult(spec: SheetSpec, quality: number): ScanResult {
    const fields: FieldResult[] = [];
    const flags: string[] = [];
    const scoreFor = (marked: boolean, amb: boolean) => (amb ? 0.4 : marked ? 0.72 + Math.random() * 0.2 : 0.02 + Math.random() * 0.05);
    for (let k = 1; k <= 10; k++) {
      const id = `roll_${k}`;
      const ch = spec.roll.charAt(k - 1);
      const value = /\d/.test(ch) ? ch : '';
      const state = value ? 'single' : 'blank';
      if (!value) flags.push(`${id}:blank`);
      fields.push({
        id,
        group: 'roll_no',
        state,
        value,
        confidence: value ? 0.9 : 0.8,
        scores: Object.fromEntries(DIGITS.map((d) => [d, scoreFor(d === value, false)])),
      });
    }
    fields.push({
      id: 'paper_set',
      group: 'paper_set',
      state: spec.set ? 'single' : 'blank',
      value: spec.set,
      confidence: 0.95,
      scores: Object.fromEntries(['A', 'B', 'C'].map((s) => [s, scoreFor(s === spec.set, false)])),
    });
    for (let q = 1; q <= 80; q++) {
      const id = `q${q}`;
      const value = spec.answers[String(q)] ?? '';
      const amb = spec.ambiguous.includes(id);
      const state = amb ? 'ambiguous' : value === '' ? 'blank' : value.length > 1 ? 'multiple' : 'single';
      if (state === 'multiple' || state === 'ambiguous') flags.push(`${id}:${state}`);
      fields.push({
        id,
        group: 'answers',
        question: q,
        state,
        value,
        confidence: amb ? 0.08 : 0.85,
        scores: Object.fromEntries(OPTS.map((o) => [o, scoreFor(value.includes(o), amb && value.includes(o))])),
      });
    }
    const status: ScanStatus = flags.length || quality < 0.6 ? 'needs_review' : 'ok';
    return {
      template_id: TEMPLATE_ID,
      status,
      error: null,
      roll_no: spec.roll,
      paper_set: spec.set || null,
      answers: Object.fromEntries(Object.entries(spec.answers)),
      fields,
      review_flags: flags,
      registration: { method: 'ecc', quality, homography: [[1, 0, 0], [0, 1, 0], [0, 0, 1]] },
      threshold: 0.42,
      aligned_size: [1700, 2200],
      timings_ms: { load: 14, page: 38, register: 210, read: 22, total: 284 },
    };
  }

  const sheets: Record<string, SheetSpec> = {};

  function svgSheet(spec: SheetSpec | undefined, rotateDeg = 0): string {
    const parts: string[] = [];
    parts.push(`<rect width="1700" height="2200" fill="#fbfbf8"/>`);
    for (const [x, y, w, h] of Object.values(geometry.anchors ?? {})) {
      parts.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="none" stroke="#e05ab4" stroke-width="3"/>`);
    }
    parts.push(`<text x="850" y="2080" font-family="sans-serif" font-size="40" fill="#e05ab4" text-anchor="middle">MOCK SHEET</text>`);
    for (const f of geometry.fields) {
      let marked = '';
      if (spec) {
        if (f.group === 'answers') marked = spec.answers[String(f.question)] ?? '';
        else if (f.group === 'paper_set') marked = spec.set;
        else {
          const ch = spec.roll.charAt(Number(f.id.slice(5)) - 1);
          marked = /\d/.test(ch) ? ch : '';
        }
      }
      const amb = spec?.ambiguous.includes(f.id);
      for (const b of f.bubbles) {
        parts.push(`<circle cx="${b.x}" cy="${b.y}" r="${b.r}" fill="none" stroke="#f2a6d6" stroke-width="2"/>`);
        if (marked.includes(b.value)) {
          parts.push(`<circle cx="${b.x + 1}" cy="${b.y - 1}" r="${b.r * (amb ? 0.55 : 0.85)}" fill="#1e2a78" opacity="${amb ? 0.5 : 0.9}"/>`);
        }
      }
    }
    const body = rotateDeg ? `<g transform="rotate(${rotateDeg} 850 1100)">${parts.join('')}</g>` : parts.join('');
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1700 2200" width="1700" height="2200">${rotateDeg ? '<rect width="1700" height="2200" fill="#5b5148"/>' : ''}${body}</svg>`;
    return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  }

  let scans: ScanRecord[] = [];
  let batches: BatchSummary[] = [];
  let nextId = 100;

  function addBatch(files: { name: string; page?: number }[], answerKeyId: Id | null | undefined): { batch: BatchSummary; scans: ScanRecord[] } {
    const batchId = `batch-${nextId++}`;
    const key = keys.find((k) => String(k.id) === String(answerKeyId));
    const keyA = keys[0].keys.A ?? {};
    const created: ScanRecord[] = files.map((f, i) => {
      const id = `scan-${nextId++}`;
      let spec: SheetSpec;
      if (i % 3 === 1) {
        spec = makeSheet(nextId, keyA, '20241?7703', 'A', (a) => {
          a['7'] = 'AC';
          a['23'] = 'B';
        }, ['q23']);
      } else if (i % 3 === 2) {
        spec = makeSheet(nextId, keys[0].keys.B ?? keyA, '2024108815', 'B', () => undefined);
      } else {
        spec = makeSheet(nextId, keyA, '2024104412', 'A', () => undefined);
      }
      sheets[id] = spec;
      const result = buildResult(spec, i % 3 === 1 ? 0.71 : 0.96);
      return {
        id,
        batch_id: batchId,
        filename: f.name,
        page: f.page ?? 1,
        created_at: new Date().toISOString(),
        result,
        grade: key ? gradeAnswers(result.answers, result.paper_set, key) : null,
        corrected: false,
      };
    });
    const batch: BatchSummary = {
      id: batchId,
      created_at: new Date().toISOString(),
      template_id: TEMPLATE_ID,
      answer_key_id: key ? key.id : null,
      scan_count: created.length,
    };
    scans = [...scans, ...created];
    batches = [batch, ...batches];
    return { batch, scans: created };
  }

  addBatch([{ name: 'class-7A_0001.jpg' }, { name: 'class-7A_0002.jpg' }, { name: 'class-7A_0003.pdf', page: 1 }], 'key-demo');

  function batchSummary(b: BatchSummary): BatchSummary {
    const own = scans.filter((s) => String(s.batch_id) === String(b.id));
    const graded = own.filter((s) => s.grade);
    return {
      ...b,
      scan_count: own.length,
      needs_review: own.filter((s) => s.result.status === 'needs_review').length,
      failed: own.filter((s) => s.result.status === 'failed').length,
      mean_score: graded.length ? graded.reduce((a, s) => a + (s.grade?.score ?? 0), 0) / graded.length : null,
      status_counts: {
        ok: own.filter((s) => s.result.status === 'ok').length,
        needs_review: own.filter((s) => s.result.status === 'needs_review').length,
        failed: own.filter((s) => s.result.status === 'failed').length,
      },
      corrected_count: own.filter((s) => s.corrected).length,
    };
  }

  const delay = <T,>(v: T, ms = 180) => new Promise<T>((res) => setTimeout(() => res(structuredClone(v)), ms));

  function findScan(id: Id): ScanRecord {
    const s = scans.find((x) => String(x.id) === String(id));
    if (!s) throw new ApiError(404, `Scan ${id} not found`);
    return s;
  }

  function findKey(id: Id): AnswerKey {
    const k = keys.find((x) => String(x.id) === String(id));
    if (!k) throw new ApiError(404, `Answer key ${id} not found`);
    return k;
  }

  const mockBenchmark: BenchmarkReport = {
    generated_at: new Date(Date.now() - 3600_000).toISOString(),
    config: { n: 50, seed: 42, tiers: ['clean', 'scan', 'photo', 'hard'] },
    overall: { n: 200, question_accuracy: 0.9963, bubble_accuracy: 0.9989, latency_p50_ms: 310, latency_p95_ms: 690, throughput_sheets_per_s: 3.1 },
    tiers: {
      clean: { n: 50, question_accuracy: 0.9998, bubble_accuracy: 0.99995, roll_exact: 1, set_accuracy: 1, sheet_exact: 0.98, blank_precision: 1, blank_recall: 0.997, multiple_precision: 1, multiple_recall: 0.99, review_rate: 0.3, avg_flags_per_sheet: 0.4, failure_rate: 0, latency_p50_ms: 240, latency_p95_ms: 310, throughput_sheets_per_s: 4.0 },
      scan: { n: 50, question_accuracy: 0.9971, bubble_accuracy: 0.9992, roll_exact: 0.98, set_accuracy: 1, sheet_exact: 0.84, blank_precision: 0.99, blank_recall: 0.985, multiple_precision: 0.97, multiple_recall: 0.96, review_rate: 0.45, avg_flags_per_sheet: 0.9, failure_rate: 0, latency_p50_ms: 300, latency_p95_ms: 520, throughput_sheets_per_s: 3.2 },
      photo: { n: 50, question_accuracy: 0.9846, bubble_accuracy: 0.9951, roll_exact: 0.92, set_accuracy: 0.98, sheet_exact: 0.5, blank_precision: 0.95, blank_recall: 0.94, multiple_precision: 0.9, review_rate: 0.8, avg_flags_per_sheet: 2.4, failure_rate: 0.02, latency_p50_ms: 420, latency_p95_ms: 980, throughput_sheets_per_s: 2.2 },
      hard: { n: 50, question_accuracy: 0.931, bubble_accuracy: 0.97, roll_exact: 0.7, set_accuracy: 0.9, sheet_exact: 0.1, review_rate: 1, avg_flags_per_sheet: 6.1, failure_rate: 0.12, latency_p50_ms: 610, latency_p95_ms: 1720, throughput_sheets_per_s: 1.5 },
    },
    targets: { question_accuracy: { clean: 0.999, scan: 0.995, photo: 0.98 }, latency_p95_ms: 1500 },
    targets_check: [
      { name: 'clean question accuracy >= 99.9%', value: '99.980%', pass: true },
      { name: 'scan question accuracy >= 99.5%', value: '99.710%', pass: true },
      { name: 'photo question accuracy >= 98.0%', value: '98.460%', pass: true },
      { name: 'latency p95 < 1500 ms', value: '690 ms', pass: true },
    ],
    errors_sample: [
      { tier: 'photo', sheet: 'photo_0012', field: 'q41', expected: 'B', got: '', reason: 'light fill below threshold' },
      { tier: 'hard', sheet: 'hard_0007', field: 'roll_3', expected: '4', got: '*', reason: 'shadow edge' },
    ],
  };

  const urls: ApiUrls = {
    aligned: (id) => svgSheet(sheets[String(id)]),
    original: (id) => svgSheet(sheets[String(id)], 2.5),
    overlay: (id) => svgSheet(sheets[String(id)]),
    exportCsv: (id) => {
      const rows = [['filename', 'page', 'roll_no', 'paper_set', 'score', 'max_score', 'status']];
      for (const s of scans.filter((x) => String(x.batch_id) === String(id))) {
        rows.push([s.filename, String(s.page ?? ''), s.result.roll_no ?? '', s.result.paper_set ?? '', String(s.grade?.score ?? ''), String(s.grade?.max_score ?? ''), s.result.status]);
      }
      return `data:text/csv;charset=utf-8,${encodeURIComponent(rows.map((r) => r.join(',')).join('\n'))}`;
    },
    templateImage: () => svgSheet(undefined),
  };

  const regrade = (s: ScanRecord, keyId: Id | null | undefined) => {
    if (keyId === null || keyId === undefined || keyId === '') {
      s.grade = null;
      return;
    }
    s.grade = gradeAnswers(s.result.answers, s.result.paper_set, findKey(keyId));
  };

  return {
    mode: 'mock',
    urls,
    health: () => delay({ status: 'ok', engine_version: 'mock' }, 60),
    listTemplates: () => delay([{ id: TEMPLATE_ID, name: geometry.name, num_questions: 80 }]),
    getTemplate: async (id) => {
      if (id !== TEMPLATE_ID) throw new ApiError(404, `Template ${id} not found`);
      return delay(geometry);
    },
    listAnswerKeys: () => delay(keys),
    getAnswerKey: async (id) => delay(findKey(id)),
    createAnswerKey: async (input: AnswerKeyInput) => {
      if (!input.name.trim()) throw new ApiError(422, 'name: Field required');
      const k: AnswerKey = { ...structuredClone(input), id: `key-${nextId++}` };
      keys = [...keys, k];
      return delay(k);
    },
    updateAnswerKey: async (id, input) => {
      findKey(id);
      const k: AnswerKey = { ...structuredClone(input), id };
      keys = keys.map((x) => (String(x.id) === String(id) ? k : x));
      return delay(k);
    },
    deleteAnswerKey: async (id) => {
      findKey(id);
      keys = keys.filter((x) => String(x.id) !== String(id));
      await delay(null);
    },
    uploadScans: (req: UploadRequest, onProgress?: (p: UploadProgress) => void, signal?: AbortSignal) =>
      new Promise<UploadResponse>((resolve, reject) => {
        if (!req.files.length) {
          reject(new ApiError(422, 'files: at least one file is required'));
          return;
        }
        const total = req.files.reduce((a, f) => a + f.size, 0) || 1;
        let loaded = 0;
        signal?.addEventListener('abort', () => {
          clearInterval(timer);
          reject(new ApiError(0, 'Upload cancelled'));
        });
        const timer = setInterval(() => {
          loaded = Math.min(total, loaded + total / 8);
          onProgress?.({ loaded, total, fraction: loaded / total });
          if (loaded >= total) {
            clearInterval(timer);
            const { batch, scans: created } = addBatch(req.files.map((f) => ({ name: f.name })), req.answerKeyId);
            setTimeout(() => resolve(structuredClone({ batch_id: batch.id, scans: created })), 400);
          }
        }, 120);
      }),
    listScans: (batchId) => delay(batchId === undefined ? scans : scans.filter((s) => String(s.batch_id) === String(batchId))),
    getScan: async (id) => delay(findScan(id)),
    patchScan: async (id, patch: ScanPatch) => {
      const s = findScan(id);
      const r = s.result;
      if (patch.roll_no !== undefined) r.roll_no = patch.roll_no;
      if (patch.paper_set !== undefined) r.paper_set = patch.paper_set || null;
      if (patch.answers) {
        for (const [q, v] of Object.entries(patch.answers)) {
          r.answers[q] = v;
          const f = r.fields.find((x) => x.id === `q${q}`);
          if (f) {
            f.value = v;
            f.state = v === '' ? 'blank' : v.length > 1 ? 'multiple' : 'single';
          }
        }
      }
      r.review_flags = [];
      r.status = 'ok';
      s.corrected = true;
      regrade(s, s.grade?.answer_key_id ?? batches.find((b) => String(b.id) === String(s.batch_id))?.answer_key_id);
      return delay(s);
    },
    regradeScan: async (id, answerKeyId) => {
      const s = findScan(id);
      regrade(s, answerKeyId);
      return delay(s, 80);
    },
    listBatches: () => delay(batches.map(batchSummary)),
    getBatch: async (id) => {
      const b = batches.find((x) => String(x.id) === String(id));
      if (!b) throw new ApiError(404, `Batch ${id} not found`);
      return delay(batchSummary(b));
    },
    latestBenchmark: () => delay(mockBenchmark),
  };
}
