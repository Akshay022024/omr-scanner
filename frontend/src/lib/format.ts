export const DASH = '—';

export function isNum(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v);
}

/** Ratios may arrive as 0..1 or as 0..100; anything above 1 is treated as a percentage. */
export function toFraction(v: unknown): number | null {
  if (!isNum(v)) return null;
  return v > 1.000001 ? v / 100 : v;
}

export function fmtPct(v: unknown, digits = 1): string {
  const f = toFraction(v);
  if (f === null) return DASH;
  return `${(f * 100).toFixed(digits)}%`;
}

export function fmtNum(v: unknown, digits = 0): string {
  if (!isNum(v)) return DASH;
  return v.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** Score like 57 / 80 or 57.5 / 80. */
export function fmtScore(v: unknown): string {
  if (!isNum(v)) return DASH;
  return Number.isInteger(v) ? String(v) : v.toFixed(2).replace(/0+$/, '').replace(/\.$/, '');
}

export function fmtMs(v: unknown): string {
  if (!isNum(v)) return DASH;
  return v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${Math.round(v)} ms`;
}

export function fmtDate(v: unknown): string {
  if (typeof v !== 'string' && typeof v !== 'number') return DASH;
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return String(v);
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function shortId(id: unknown): string {
  const s = String(id ?? '');
  return s.length > 10 ? s.slice(0, 8) : s;
}

export function statusLabel(s: string | null | undefined): string {
  switch (s) {
    case 'ok':
      return 'OK';
    case 'needs_review':
      return 'Needs review';
    case 'failed':
      return 'Failed';
    default:
      return s ? s : DASH;
  }
}
