import type { ReactNode } from 'react';
import { errorMessage } from '../api';
import { statusLabel } from '../lib/format';

export function Spinner({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({ error, onRetry, title = 'Something went wrong' }: { error: unknown; onRetry?: () => void; title?: string }) {
  return (
    <div className="state state--error" role="alert">
      <h2 className="state__title">{title}</h2>
      <p>{errorMessage(error)}</p>
      {onRetry && (
        <button type="button" className="btn" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="state">
      <h2 className="state__title">{title}</h2>
      {children}
    </div>
  );
}

export function StatusChip({ status }: { status: string | null | undefined }) {
  const s = status ?? 'unknown';
  const icon = s === 'ok' ? '✓' : s === 'needs_review' ? '!' : s === 'failed' ? '×' : '?';
  return (
    <span className={`chip chip--${s}`}>
      <span aria-hidden="true" className="chip__icon">
        {icon}
      </span>
      {statusLabel(status)}
    </span>
  );
}

export function ProgressBar({ value, label }: { value: number | null; label: string }) {
  const pct = value === null ? null : Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <div className="progress">
      <div
        className={`progress__track${pct === null ? ' progress__track--indeterminate' : ''}`}
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct ?? undefined}
      >
        <div className="progress__bar" style={{ width: pct === null ? '40%' : `${pct}%` }} />
      </div>
      <span className="progress__label">
        {label}
        {pct !== null ? ` · ${pct}%` : ''}
      </span>
    </div>
  );
}
