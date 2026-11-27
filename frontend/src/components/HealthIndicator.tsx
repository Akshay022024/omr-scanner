import { useEffect, useState } from 'react';
import { api, errorMessage, USE_MOCKS } from '../api';

type HealthState = { kind: 'checking' } | { kind: 'up'; version?: string } | { kind: 'down'; reason: string };

const POLL_MS = 15000;

export function HealthIndicator() {
  const [state, setState] = useState<HealthState>({ kind: 'checking' });

  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    const check = async () => {
      try {
        const h = await api.health();
        const ok = !h.status || ['ok', 'healthy', 'up'].includes(String(h.status).toLowerCase());
        if (alive) setState(ok ? { kind: 'up', version: h.engine_version ?? h.version } : { kind: 'down', reason: String(h.status) });
      } catch (e) {
        if (alive) setState({ kind: 'down', reason: errorMessage(e) });
      } finally {
        if (alive) timer = window.setTimeout(check, POLL_MS);
      }
    };
    check();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, []);

  const text =
    state.kind === 'checking' ? 'Checking API…' : state.kind === 'up' ? (USE_MOCKS ? 'Mock API' : 'API online') : 'API offline';
  const title =
    state.kind === 'up'
      ? `Backend reachable${state.version ? ` · engine ${state.version}` : ''}`
      : state.kind === 'down'
        ? state.reason
        : 'Contacting /api/health';

  return (
    <span className={`health health--${state.kind}`} title={title} role="status" aria-live="polite">
      <span className="health__dot" aria-hidden="true" />
      <span className="health__text">{text}</span>
    </span>
  );
}
