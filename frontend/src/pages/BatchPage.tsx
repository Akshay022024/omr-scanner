import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api, type ScanRecord, type ScanStatus } from '../api';
import { EmptyState, ErrorState, ProgressBar, Spinner, StatusChip } from '../components/States';
import { useToast } from '../components/Toasts';
import { DASH, fmtDate, fmtScore, shortId } from '../lib/format';
import { useAsync, useTitle } from '../lib/hooks';
import { sortScans } from '../lib/queue';

type Filter = 'all' | ScanStatus;

const FILTERS: { value: Filter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'needs_review', label: 'Needs review' },
  { value: 'failed', label: 'Failed' },
  { value: 'ok', label: 'OK' },
];

export function BatchPage() {
  const { id = '' } = useParams();
  useTitle(`Batch ${shortId(id)}`);
  const toast = useToast();
  const navigate = useNavigate();
  const [filter, setFilter] = useState<Filter>('all');
  const [regradeKey, setRegradeKey] = useState('');
  const [regrading, setRegrading] = useState<{ done: number; total: number } | null>(null);

  const state = useAsync(async () => {
    const [batch, scans, keys] = await Promise.all([
      api.getBatch(id).catch(() => null), // summary is optional; the scan list is the source of truth
      api.listScans(id),
      api.listAnswerKeys().catch(() => []),
    ]);
    const list = scans.length ? scans : (batch?.scans ?? []);
    return { batch, scans: sortScans(list), keys };
  }, [id]);

  const scans = state.data?.scans ?? [];
  const batch = state.data?.batch ?? null;
  const keys = state.data?.keys ?? [];

  const stats = useMemo(() => {
    const graded = scans.filter((s) => s.grade);
    const avg = graded.length ? graded.reduce((a, s) => a + (s.grade?.score ?? 0), 0) / graded.length : null;
    const maxScore = graded.length ? graded[0].grade?.max_score ?? null : null;
    return {
      total: scans.length,
      graded: graded.length,
      avg,
      maxScore,
      review: scans.filter((s) => s.result?.status === 'needs_review').length,
      failed: scans.filter((s) => s.result?.status === 'failed').length,
      corrected: scans.filter((s) => s.corrected).length,
    };
  }, [scans]);

  const visible = filter === 'all' ? scans : scans.filter((s) => s.result?.status === filter);
  const firstReview = scans.find((s) => s.result?.status === 'needs_review' || s.result?.status === 'failed');
  const templateId = batch?.template_id ?? scans[0]?.result?.template_id;
  const keyOptions = keys.filter((k) => !templateId || !k.template_id || k.template_id === templateId);
  const currentKeyId = scans.find((s) => s.grade)?.grade?.answer_key_id ?? scans.find((s) => s.answer_key_id)?.answer_key_id ?? batch?.answer_key_id ?? null;
  const currentKey = keys.find((k) => String(k.id) === String(currentKeyId));

  const regrade = async () => {
    if (!regradeKey || !scans.length) return;
    const targets = scans.filter((s) => s.result?.status !== 'failed');
    setRegrading({ done: 0, total: targets.length });
    const updated = new Map<string, ScanRecord>();
    let failures = 0;
    for (let i = 0; i < targets.length; i++) {
      try {
        const rec = await api.regradeScan(targets[i].id, regradeKey);
        updated.set(String(rec.id), rec);
      } catch (e) {
        failures++;
        if (failures === 1) toast.error(e, `Re-grade failed for ${targets[i].filename}`);
      }
      setRegrading({ done: i + 1, total: targets.length });
    }
    state.setData((prev) => ({
      batch: prev?.batch ?? null,
      keys: prev?.keys ?? [],
      scans: (prev?.scans ?? []).map((s) => updated.get(String(s.id)) ?? s),
    }));
    setRegrading(null);
    if (failures) toast.error(`${failures} of ${targets.length} scans could not be re-graded`);
    else toast.success(`Re-graded ${targets.length} scan${targets.length === 1 ? '' : 's'}`);
  };

  if (state.loading && !state.data) return <Spinner label="Loading batch…" />;
  if (state.error && !state.data) return <ErrorState error={state.error} onRetry={state.reload} title="Could not load batch" />;

  return (
    <div className="page">
      <nav className="breadcrumbs" aria-label="Breadcrumb">
        <Link to="/batches">Batches</Link> <span aria-hidden="true">/</span> <span aria-current="page">{shortId(id)}</span>
      </nav>
      <header className="page__header">
        <div>
          <h1>Batch {shortId(id)}</h1>
          <p className="muted">
            {fmtDate(batch?.created_at ?? scans[0]?.created_at)} · template {templateId ?? DASH}
            {currentKey ? ` · graded with “${currentKey.name}”` : ''}
          </p>
        </div>
        <div className="page__actions">
          {firstReview && (
            <Link className="btn btn--warn" to={`/scans/${encodeURIComponent(String(firstReview.id))}`}>
              Review flagged
            </Link>
          )}
          <a className="btn" href={api.urls.exportCsv(id)} download={`batch-${shortId(id)}.csv`}>
            Export CSV
          </a>
        </div>
      </header>

      <section className="stats" aria-label="Batch summary">
        <div className="stat">
          <span className="stat__label">Pages</span>
          <span className="stat__value">{stats.total}</span>
          <span className="stat__sub">{stats.corrected ? `${stats.corrected} corrected` : ' '}</span>
        </div>
        <div className="stat">
          <span className="stat__label">Average score</span>
          <span className="stat__value">{stats.avg === null ? DASH : fmtScore(Math.round(stats.avg * 100) / 100)}</span>
          <span className="stat__sub">{stats.maxScore !== null ? `out of ${fmtScore(stats.maxScore)} · ${stats.graded} graded` : 'not graded'}</span>
        </div>
        <div className={`stat${stats.review ? ' stat--warn' : ''}`}>
          <span className="stat__label">Needs review</span>
          <span className="stat__value">{stats.review}</span>
          <span className="stat__sub">{stats.total ? `${Math.round((stats.review / stats.total) * 100)}% of pages` : ' '}</span>
        </div>
        <div className={`stat${stats.failed ? ' stat--bad' : ''}`}>
          <span className="stat__label">Failed</span>
          <span className="stat__value">{stats.failed}</span>
          <span className="stat__sub">could not be read</span>
        </div>
      </section>

      <section className="card regrade" aria-label="Re-grade batch">
        <label className="field field--inline">
          <span className="field__label">Re-grade with</span>
          <select value={regradeKey} onChange={(e) => setRegradeKey(e.target.value)} disabled={!!regrading}>
            <option value="">Choose an answer key…</option>
            {keyOptions.map((k) => (
              <option key={String(k.id)} value={String(k.id)}>
                {k.name}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="btn" onClick={regrade} disabled={!regradeKey || !!regrading || !scans.length}>
          {regrading ? 'Re-grading…' : 'Re-grade all'}
        </button>
        {regrading && <ProgressBar value={regrading.total ? regrading.done / regrading.total : null} label={`${regrading.done} / ${regrading.total}`} />}
      </section>

      <div className="segmented" role="group" aria-label="Filter by status">
        {FILTERS.map((f) => {
          const count = f.value === 'all' ? scans.length : scans.filter((s) => s.result?.status === f.value).length;
          return (
            <button key={f.value} type="button" className="segmented__btn" aria-pressed={filter === f.value} onClick={() => setFilter(f.value)}>
              {f.label} <span className="segmented__count">{count}</span>
            </button>
          );
        })}
      </div>

      {scans.length === 0 ? (
        <EmptyState title="This batch has no scans" />
      ) : visible.length === 0 ? (
        <EmptyState title="No scans match this filter" />
      ) : (
        <div className="card card--flush table-wrap">
          <table className="table">
            <caption className="sr-only">Scans in batch {String(id)}</caption>
            <thead>
              <tr>
                <th scope="col">File</th>
                <th scope="col">Roll no</th>
                <th scope="col">Set</th>
                <th scope="col" className="num">
                  Score
                </th>
                <th scope="col" className="num">
                  <abbr title="Correct / wrong / blank / multiple">C / W / B / M</abbr>
                </th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((s) => {
                const href = `/scans/${encodeURIComponent(String(s.id))}`;
                const g = s.grade;
                return (
                  <tr key={String(s.id)} className="row-link" onClick={() => navigate(href)}>
                    <td className="cell-file">
                      <Link to={href} onClick={(e) => e.stopPropagation()} title={s.filename}>
                        {s.filename}
                      </Link>
                      {s.page ? <span className="muted"> · p{s.page}</span> : null}
                    </td>
                    <td className="mono">{s.result?.roll_no || DASH}</td>
                    <td>{s.result?.paper_set || DASH}</td>
                    <td className="num">{g ? `${fmtScore(g.score)} / ${fmtScore(g.max_score)}` : DASH}</td>
                    <td className="num mono">
                      {g ? (
                        <>
                          <span className="text-good">{g.correct}</span> / <span className="text-bad">{g.wrong}</span> / <span className="muted">{g.blank}</span> /{' '}
                          <span className="text-warn">{g.multiple}</span>
                        </>
                      ) : (
                        DASH
                      )}
                    </td>
                    <td>
                      <StatusChip status={s.result?.status} />
                      {s.corrected && <span className="tag">corrected</span>}
                      {s.result?.status === 'failed' && s.result?.error && (
                        <span className="cell-error" title={s.result.error}>
                          {s.result.error}
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
