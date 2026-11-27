import { describe, expect, it, vi } from 'vitest';
import { asArray, buildScanFormData, buildUrl, createHttpClient, makeUrls, type FetchLike } from './client';
import { ApiError, messageFromBody } from './errors';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function mockFetch(...responses: Response[]) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fn = vi.fn<FetchLike>(async (url, init) => {
    calls.push({ url, init });
    const r = responses.shift();
    if (!r) throw new Error('unexpected fetch');
    return r;
  });
  return { fn, calls };
}

describe('buildUrl', () => {
  it('joins base and path and encodes query params', () => {
    expect(buildUrl('/api', '/scans', { batch_id: 'a b&c' })).toBe('/api/scans?batch_id=a%20b%26c');
    expect(buildUrl('/api/', 'health')).toBe('/api/health');
  });
  it('drops empty query params', () => {
    expect(buildUrl('/api', '/scans', { batch_id: undefined, x: null, y: '' })).toBe('/api/scans');
    expect(buildUrl('/api', '/scans', { batch_id: 7 })).toBe('/api/scans?batch_id=7');
  });
});

describe('makeUrls', () => {
  const u = makeUrls('/api');
  it('builds image and export URLs', () => {
    expect(u.aligned('s1')).toBe('/api/scans/s1/aligned.png');
    expect(u.original(42)).toBe('/api/scans/42/original');
    expect(u.overlay('s/1')).toBe('/api/scans/s%2F1/overlay.png');
    expect(u.exportCsv('b1')).toBe('/api/batches/b1/export.csv');
    expect(u.templateImage('sheet80_v2')).toBe('/api/templates/sheet80_v2/image');
  });
});

describe('buildScanFormData', () => {
  it('repeats the files field and adds template / answer key', () => {
    const f1 = new File(['a'], 'one.jpg', { type: 'image/jpeg' });
    const f2 = new File(['b'], 'two.pdf', { type: 'application/pdf' });
    const fd = buildScanFormData({ files: [f1, f2], templateId: 'sheet80_v2', answerKeyId: 'k1' });
    const files = fd.getAll('files') as File[];
    expect(files.map((f) => f.name)).toEqual(['one.jpg', 'two.pdf']);
    expect(fd.get('template_id')).toBe('sheet80_v2');
    expect(fd.get('answer_key_id')).toBe('k1');
  });
  it('omits answer_key_id when not chosen', () => {
    const fd = buildScanFormData({ files: [], templateId: 't', answerKeyId: null });
    expect(fd.has('answer_key_id')).toBe(false);
  });
});

describe('asArray', () => {
  it('accepts arrays and common wrappers', () => {
    expect(asArray([1, 2])).toEqual([1, 2]);
    expect(asArray({ scans: [1] }, 'scans')).toEqual([1]);
    expect(asArray({ items: [3] })).toEqual([3]);
    expect(asArray(null)).toEqual([]);
  });
});

describe('createHttpClient', () => {
  it('GETs list endpoints and unwraps arrays', async () => {
    const { fn, calls } = mockFetch(jsonResponse([{ id: 's1' }]));
    const api = createHttpClient({ fetchImpl: fn });
    const scans = await api.listScans('b 1');
    expect(scans).toEqual([{ id: 's1' }]);
    expect(calls[0].url).toBe('/api/scans?batch_id=b%201');
    expect(calls[0].init?.method).toBe('GET');
    expect(calls[0].init?.body).toBeUndefined();
  });

  it('normalises a template list of plain ids', async () => {
    const { fn } = mockFetch(jsonResponse({ templates: ['sheet80_v2'] }));
    const api = createHttpClient({ fetchImpl: fn });
    expect(await api.listTemplates()).toEqual([{ id: 'sheet80_v2', name: 'sheet80_v2' }]);
  });

  it('sends JSON bodies for create / update / patch / regrade', async () => {
    const scan = { id: 's1', batch_id: 'b1', filename: 'x.jpg', result: { answers: {} } };
    const { fn, calls } = mockFetch(
      jsonResponse({ id: 'k1', name: 'K' }, 201),
      jsonResponse({ id: 'k1', name: 'K2' }),
      jsonResponse(scan),
      jsonResponse(scan),
      jsonResponse(undefined, 204),
    );
    const api = createHttpClient({ fetchImpl: fn });
    const input = { name: 'K', template_id: 't', keys: { A: { '1': 'B' } }, marks_correct: 4, marks_wrong: -1, marks_blank: 0 };
    await api.createAnswerKey(input);
    await api.updateAnswerKey('k1', { ...input, name: 'K2' });
    await api.patchScan('s1', { answers: { '12': 'B' }, roll_no: '2024100001', paper_set: 'A' });
    await api.regradeScan('s1', 'k1');
    await api.deleteAnswerKey('k1');

    expect(calls.map((c) => `${c.init?.method} ${c.url}`)).toEqual([
      'POST /api/answer-keys',
      'PUT /api/answer-keys/k1',
      'PATCH /api/scans/s1',
      'POST /api/scans/s1/regrade',
      'DELETE /api/answer-keys/k1',
    ]);
    expect(JSON.parse(String(calls[0].init?.body))).toEqual(input);
    expect(JSON.parse(String(calls[2].init?.body))).toEqual({ answers: { '12': 'B' }, roll_no: '2024100001', paper_set: 'A' });
    expect(JSON.parse(String(calls[3].init?.body))).toEqual({ answer_key_id: 'k1' });
    expect((calls[0].init?.headers as Record<string, string>)['Content-Type']).toBe('application/json');
  });

  it('refetches the scan when PATCH does not return a ScanRecord', async () => {
    const scan = { id: 's1', batch_id: 'b1', filename: 'x.jpg', result: { answers: {} } };
    const { fn, calls } = mockFetch(jsonResponse({ ok: true }), jsonResponse(scan));
    const api = createHttpClient({ fetchImpl: fn });
    const rec = await api.patchScan('s1', { answers: { '1': '' } });
    expect(rec).toEqual(scan);
    expect(calls[1].url).toBe('/api/scans/s1');
  });

  it('throws ApiError with the FastAPI detail message', async () => {
    const { fn } = mockFetch(jsonResponse({ detail: 'Scan not found' }, 404));
    const api = createHttpClient({ fetchImpl: fn });
    await expect(api.getScan('nope')).rejects.toMatchObject({ name: 'ApiError', status: 404, message: 'Scan not found' });
  });

  it('maps a network failure to status 0', async () => {
    const api = createHttpClient({
      fetchImpl: async () => {
        throw new TypeError('Failed to fetch');
      },
    });
    const err = await api.health().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(0);
  });

  it('returns null for a 404 benchmark report', async () => {
    const { fn } = mockFetch(jsonResponse({ detail: 'not run yet' }, 404));
    const api = createHttpClient({ fetchImpl: fn });
    expect(await api.latestBenchmark()).toBeNull();
  });

  it('propagates non-404 benchmark errors', async () => {
    const { fn } = mockFetch(jsonResponse({ detail: 'boom' }, 500));
    const api = createHttpClient({ fetchImpl: fn });
    await expect(api.latestBenchmark()).rejects.toMatchObject({ status: 500 });
  });

  it('uploads via XHR with progress and parses the response', async () => {
    const sent: { method?: string; url?: string; body?: unknown } = {};
    class FakeXhr {
      status = 0;
      responseText = '';
      upload: { onprogress: ((e: ProgressEvent) => void) | null } = { onprogress: null };
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      onabort: (() => void) | null = null;
      open(method: string, url: string) {
        sent.method = method;
        sent.url = url;
      }
      setRequestHeader() {}
      abort() {
        this.onabort?.();
      }
      send(body: unknown) {
        sent.body = body;
        this.upload.onprogress?.({ loaded: 50, total: 100, lengthComputable: true } as ProgressEvent);
        this.status = 200;
        this.responseText = JSON.stringify({ batch_id: 'b9', scans: [] });
        this.onload?.();
      }
    }
    const api = createHttpClient({ xhrFactory: () => new FakeXhr() as unknown as XMLHttpRequest });
    const progress: (number | null)[] = [];
    const res = await api.uploadScans(
      { files: [new File(['x'], 'a.png', { type: 'image/png' })], templateId: 'sheet80_v2' },
      (p) => progress.push(p.fraction),
    );
    expect(res.batch_id).toBe('b9');
    expect(sent.method).toBe('POST');
    expect(sent.url).toBe('/api/scans');
    expect(sent.body).toBeInstanceOf(FormData);
    expect((sent.body as FormData).get('template_id')).toBe('sheet80_v2');
    expect(progress).toEqual([0.5]);
  });

  it('rejects an upload with the server error detail', async () => {
    class FailXhr {
      status = 0;
      responseText = '';
      upload = { onprogress: null };
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      onabort: (() => void) | null = null;
      open() {}
      setRequestHeader() {}
      abort() {}
      send() {
        this.status = 413;
        this.responseText = JSON.stringify({ detail: 'File too large' });
        this.onload?.();
      }
    }
    const api = createHttpClient({ xhrFactory: () => new FailXhr() as unknown as XMLHttpRequest });
    await expect(api.uploadScans({ files: [], templateId: 't' })).rejects.toMatchObject({ status: 413, message: 'File too large' });
  });
});

describe('messageFromBody', () => {
  it('formats pydantic validation errors', () => {
    const body = { detail: [{ loc: ['body', 'name'], msg: 'Field required' }, { loc: ['body', 'marks_correct'], msg: 'not a number' }] };
    expect(messageFromBody(body, 'x')).toBe('name: Field required; marks_correct: not a number');
  });
  it('falls back when nothing useful is present', () => {
    expect(messageFromBody({}, 'fallback')).toBe('fallback');
  });
});
