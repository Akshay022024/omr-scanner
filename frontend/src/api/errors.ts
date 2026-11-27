export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, message: string, body?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

/** Extract a human-readable message from a FastAPI-style error body. */
export function messageFromBody(body: unknown, fallback: string): string {
  if (typeof body === 'string' && body.trim()) return body.trim().slice(0, 300);
  if (body && typeof body === 'object') {
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
      const parts = detail
        .map((d) => {
          if (d && typeof d === 'object') {
            const msg = (d as { msg?: unknown }).msg;
            const loc = (d as { loc?: unknown }).loc;
            const where = Array.isArray(loc) ? loc.filter((p) => p !== 'body').join('.') : '';
            return typeof msg === 'string' ? (where ? `${where}: ${msg}` : msg) : '';
          }
          return typeof d === 'string' ? d : '';
        })
        .filter(Boolean);
      if (parts.length) return parts.join('; ');
    }
    const message = (body as { message?: unknown }).message;
    if (typeof message === 'string') return message;
  }
  return fallback;
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return String(err);
}
