import { ApiError, messageFromBody } from './errors';
import type {
  AnswerKey,
  AnswerKeyInput,
  BatchSummary,
  BenchmarkReport,
  Health,
  Id,
  ScanPatch,
  ScanRecord,
  TemplateGeometry,
  TemplateSummary,
  UploadResponse,
} from './types';

export interface UploadRequest {
  files: File[];
  templateId: string;
  answerKeyId?: Id | null;
}

export interface UploadProgress {
  loaded: number;
  total: number;
  /** 0..1, or null when the browser cannot compute the total. */
  fraction: number | null;
}

export interface ApiUrls {
  aligned(scanId: Id): string;
  original(scanId: Id): string;
  overlay(scanId: Id): string;
  exportCsv(batchId: Id): string;
  templateImage(templateId: string): string;
}

export interface ApiClient {
  readonly mode: 'http' | 'mock';
  readonly urls: ApiUrls;
  health(): Promise<Health>;
  listTemplates(): Promise<TemplateSummary[]>;
  getTemplate(id: string): Promise<TemplateGeometry>;
  listAnswerKeys(): Promise<AnswerKey[]>;
  getAnswerKey(id: Id): Promise<AnswerKey>;
  createAnswerKey(input: AnswerKeyInput): Promise<AnswerKey>;
  updateAnswerKey(id: Id, input: AnswerKeyInput): Promise<AnswerKey>;
  deleteAnswerKey(id: Id): Promise<void>;
  uploadScans(req: UploadRequest, onProgress?: (p: UploadProgress) => void, signal?: AbortSignal): Promise<UploadResponse>;
  listScans(batchId?: Id): Promise<ScanRecord[]>;
  getScan(id: Id): Promise<ScanRecord>;
  patchScan(id: Id, patch: ScanPatch): Promise<ScanRecord>;
  regradeScan(id: Id, answerKeyId: Id): Promise<ScanRecord>;
  listBatches(): Promise<BatchSummary[]>;
  getBatch(id: Id): Promise<BatchSummary>;
  /** Resolves to null when the backend answers 404 (benchmark not run yet). */
  latestBenchmark(): Promise<BenchmarkReport | null>;
}

export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export interface HttpClientOptions {
  baseUrl?: string;
  fetchImpl?: FetchLike;
  xhrFactory?: () => XMLHttpRequest;
}

const enc = (id: Id) => encodeURIComponent(String(id));

/** Join base + path + optional query (undefined/null/'' params are dropped). */
export function buildUrl(baseUrl: string, path: string, query?: Record<string, Id | null | undefined>): string {
  const base = baseUrl.replace(/\/+$/, '');
  const p = path.startsWith('/') ? path : `/${path}`;
  let url = `${base}${p}`;
  if (query) {
    const qs = Object.entries(query)
      .filter(([, v]) => v !== undefined && v !== null && v !== '')
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
      .join('&');
    if (qs) url += `?${qs}`;
  }
  return url;
}

export function makeUrls(baseUrl: string): ApiUrls {
  return {
    aligned: (id) => buildUrl(baseUrl, `/scans/${enc(id)}/aligned.png`),
    original: (id) => buildUrl(baseUrl, `/scans/${enc(id)}/original`),
    overlay: (id) => buildUrl(baseUrl, `/scans/${enc(id)}/overlay.png`),
    exportCsv: (id) => buildUrl(baseUrl, `/batches/${enc(id)}/export.csv`),
    templateImage: (id) => buildUrl(baseUrl, `/templates/${enc(id)}/image`),
  };
}

/** Multipart body for POST /api/scans: `files` repeated, `template_id`, optional `answer_key_id`. */
export function buildScanFormData(req: UploadRequest): FormData {
  const fd = new FormData();
  for (const f of req.files) fd.append('files', f, f.name);
  fd.append('template_id', req.templateId);
  if (req.answerKeyId !== undefined && req.answerKeyId !== null && req.answerKeyId !== '') {
    fd.append('answer_key_id', String(req.answerKeyId));
  }
  return fd;
}

/** Accept either a bare array or an object wrapping one (`{items: [...]}`, `{scans: [...]}`, ...). */
export function asArray<T>(data: unknown, ...keys: string[]): T[] {
  if (Array.isArray(data)) return data as T[];
  if (data && typeof data === 'object') {
    for (const k of [...keys, 'items', 'results', 'data']) {
      const v = (data as Record<string, unknown>)[k];
      if (Array.isArray(v)) return v as T[];
    }
  }
  return [];
}

function isScanRecord(x: unknown): x is ScanRecord {
  return !!x && typeof x === 'object' && 'result' in x && 'id' in x;
}

async function parseBody(res: Response): Promise<unknown> {
  if (res.status === 204) return null;
  const text = await res.text();
  if (!text) return null;
  const ct = res.headers.get('content-type') ?? '';
  if (ct.includes('json') || /^[\s]*[[{]/.test(text)) {
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  }
  return text;
}

export function createHttpClient(opts: HttpClientOptions = {}): ApiClient {
  const baseUrl = opts.baseUrl ?? '/api';
  const doFetch: FetchLike = opts.fetchImpl ?? ((input, init) => fetch(input, init));
  const xhrFactory = opts.xhrFactory ?? (() => new XMLHttpRequest());

  async function request<T>(method: string, path: string, body?: unknown, query?: Record<string, Id | null | undefined>): Promise<T> {
    const init: RequestInit = { method, headers: { Accept: 'application/json' } };
    if (body !== undefined) {
      init.headers = { Accept: 'application/json', 'Content-Type': 'application/json' };
      init.body = JSON.stringify(body);
    }
    let res: Response;
    try {
      res = await doFetch(buildUrl(baseUrl, path, query), init);
    } catch (e) {
      throw new ApiError(0, `Cannot reach the API (${e instanceof Error ? e.message : 'network error'}). Is the backend running on :8000?`);
    }
    const data = await parseBody(res);
    if (!res.ok) {
      throw new ApiError(res.status, messageFromBody(data, `${method} ${path} failed (HTTP ${res.status})`), data);
    }
    return data as T;
  }

  const client: ApiClient = {
    mode: 'http',
    urls: makeUrls(baseUrl),
    health: () => request<Health>('GET', '/health'),
    listTemplates: async () => {
      const data = await request<unknown>('GET', '/templates');
      return asArray<TemplateSummary | string>(data, 'templates').map((t) =>
        typeof t === 'string' ? { id: t, name: t } : t,
      );
    },
    getTemplate: (id) => request<TemplateGeometry>('GET', `/templates/${enc(id)}`),
    listAnswerKeys: async () => asArray<AnswerKey>(await request<unknown>('GET', '/answer-keys'), 'answer_keys', 'keys'),
    getAnswerKey: (id) => request<AnswerKey>('GET', `/answer-keys/${enc(id)}`),
    createAnswerKey: (input) => request<AnswerKey>('POST', '/answer-keys', input),
    updateAnswerKey: (id, input) => request<AnswerKey>('PUT', `/answer-keys/${enc(id)}`, input),
    deleteAnswerKey: async (id) => {
      await request<unknown>('DELETE', `/answer-keys/${enc(id)}`);
    },
    uploadScans: (req, onProgress, signal) =>
      new Promise<UploadResponse>((resolve, reject) => {
        const xhr = xhrFactory();
        xhr.open('POST', buildUrl(baseUrl, '/scans'));
        xhr.setRequestHeader('Accept', 'application/json');
        xhr.upload.onprogress = (ev) => {
          onProgress?.({
            loaded: ev.loaded,
            total: ev.total,
            fraction: ev.lengthComputable && ev.total > 0 ? ev.loaded / ev.total : null,
          });
        };
        xhr.onload = () => {
          let data: unknown = xhr.responseText;
          try {
            data = xhr.responseText ? JSON.parse(xhr.responseText) : null;
          } catch {
            /* keep text */
          }
          if (xhr.status >= 200 && xhr.status < 300) resolve(data as UploadResponse);
          else reject(new ApiError(xhr.status, messageFromBody(data, `Upload failed (HTTP ${xhr.status})`), data));
        };
        xhr.onerror = () => reject(new ApiError(0, 'Upload failed: cannot reach the API. Is the backend running on :8000?'));
        xhr.onabort = () => reject(new ApiError(0, 'Upload cancelled'));
        if (signal) {
          if (signal.aborted) {
            reject(new ApiError(0, 'Upload cancelled'));
            return;
          }
          signal.addEventListener('abort', () => xhr.abort(), { once: true });
        }
        xhr.send(buildScanFormData(req));
      }),
    listScans: async (batchId) =>
      asArray<ScanRecord>(await request<unknown>('GET', '/scans', undefined, { batch_id: batchId }), 'scans'),
    getScan: (id) => request<ScanRecord>('GET', `/scans/${enc(id)}`),
    patchScan: async (id, patch) => {
      const data = await request<unknown>('PATCH', `/scans/${enc(id)}`, patch);
      return isScanRecord(data) ? data : client.getScan(id);
    },
    regradeScan: async (id, answerKeyId) => {
      const data = await request<unknown>('POST', `/scans/${enc(id)}/regrade`, { answer_key_id: answerKeyId });
      return isScanRecord(data) ? data : client.getScan(id);
    },
    listBatches: async () => asArray<BatchSummary>(await request<unknown>('GET', '/batches'), 'batches'),
    getBatch: (id) => request<BatchSummary>('GET', `/batches/${enc(id)}`),
    latestBenchmark: async () => {
      try {
        return await request<BenchmarkReport>('GET', '/benchmarks/latest');
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null;
        throw e;
      }
    },
  };
  return client;
}
