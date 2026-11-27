import { api } from '../api';
import { AccuracyChart } from '../components/AccuracyChart';
import { EmptyState, ErrorState, Spinner } from '../components/States';
import {
  METRICS,
  accuracyVerdict,
  extractTargetChecks,
  targetsFrom,
  extractErrorsSample,
  extractOverall,
  extractTiers,
  generatedAt,
  latencyVerdict,
  metricValue,
  type MetricDef,
  type Verdict,
} from '../lib/benchmark';
import { DASH, fmtDate, fmtMs, fmtNum, fmtPct } from '../lib/format';
import { useAsync, useTitle } from '../lib/hooks';

const RUN_CMD = '.\\.venv\\Scripts\\python.exe benchmarks\\run_benchmark.py';

function fmtMetric(def: MetricDef, v: number | null): string {
  if (v === null) return DASH;
  switch (def.kind) {
    case 'pct':
      return fmtPct(v, 2);
    case 'ms':
      return fmtMs(v);
    case 'count':
      return fmtNum(v);
    case 'rate':
      return fmtNum(v, 2);
  }
}

function VerdictBadge({ v, title }: { v: Verdict; title?: string }) {
  if (v === 'na') return null;
  return (
    <span className={`verdict verdict--${v}`} title={title}>
      <span aria-hidden="true">{v === 'pass' ? '✓' : '×'}</span> {v === 'pass' ? 'pass' : 'fail'}
    </span>
  );
}

function cellText(v: unknown): string {
  if (v === null || v === undefined) return DASH;
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

export function BenchmarksPage() {
  useTitle('Benchmarks');
  const { data, error, loading, reload } = useAsync(() => api.latestBenchmark(), []);

  if (loading && data === undefined) return <Spinner label="Loading benchmark report…" />;
  if (error && data === undefined) return <ErrorState error={error} onRetry={reload} title="Could not load benchmark report" />;

  if (data === null || data === undefined) {
    return (
      <div className="page">
        <header className="page__header">
          <h1>Benchmarks</h1>
        </header>
        <EmptyState title="No benchmark report yet">
          <p>Generate one from the project root, then refresh this page:</p>
          <pre className="code">
            <code>{RUN_CMD}</code>
          </pre>
          <button type="button" className="btn" onClick={reload}>
            Refresh
          </button>
        </EmptyState>
      </div>
    );
  }

  const tiers = extractTiers(data);
  const overall = extractOverall(data);
  const targets = targetsFrom(data);
  const checks = extractTargetChecks(data);
  const engineVersion = typeof data.engine_version === 'string' ? data.engine_version : null;
  const cfg = (data.config && typeof data.config === 'object' ? data.config : {}) as Record<string, unknown>;
  const targetText = Object.entries(targets.accuracy)
    .map(([tier, v]) => `${tier} ≥ ${(v * 100).toFixed(1)}%`)
    .join(', ');
  const errors = extractErrorsSample(data);
  const errorCols = errors.length ? Array.from(new Set(errors.slice(0, 50).flatMap((e) => Object.keys(e)))).slice(0, 10) : [];
  const rows = overall ? [...tiers, { name: 'overall', data: overall }] : tiers;
  const tableMetrics = METRICS.filter((m) => m.key !== 'latency_mean');

  const headline = overall ?? tiers[0]?.data;
  const headlineItems = headline
    ? (['question_accuracy', 'bubble_accuracy', 'sheet_exact', 'latency_p95', 'throughput'] as const).map((k) => {
        const def = METRICS.find((m) => m.key === k)!;
        return { def, value: metricValue(headline, k) };
      })
    : [];

  const passCount = tiers.filter((t) => accuracyVerdict(t.name, metricValue(t.data, 'question_accuracy'), targets.accuracy) === 'pass').length;
  const targetTiers = tiers.filter((t) => targets.accuracy[t.name] !== undefined && metricValue(t.data, 'question_accuracy') !== null).length;

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1>Benchmarks</h1>
          <p className="muted">
            Latest synthetic benchmark · generated {fmtDate(generatedAt(data))}
            {engineVersion && ` · engine ${engineVersion}`}
            {typeof cfg.n === 'number' && ` · ${cfg.n} sheets/tier`}
            {typeof cfg.seed === 'number' && ` · seed ${cfg.seed}`}
            {targetTiers > 0 && ` · ${passCount} of ${targetTiers} tiers meet the accuracy target`}
          </p>
        </div>
        <div className="page__actions">
          <button type="button" className="btn" onClick={reload} disabled={loading}>
            Refresh
          </button>
        </div>
      </header>

      {headlineItems.length > 0 && (
        <section className="stats" aria-label={overall ? 'Overall results' : `Results for ${tiers[0]?.name}`}>
          {headlineItems.map(({ def, value }) => (
            <div key={def.key} className="stat">
              <span className="stat__label">
                {def.key === 'latency_p95' ? 'Latency p95' : def.key === 'throughput' ? 'Throughput (sheets/s)' : def.label}
              </span>
              <span className="stat__value">{fmtMetric(def, value)}</span>
              <span className="stat__sub">
                {def.key === 'latency_p95' ? <VerdictBadge v={latencyVerdict(value, targets.p95Ms)} title={`target < ${targets.p95Ms} ms`} /> : overall ? 'overall' : tiers[0]?.name}
              </span>
            </div>
          ))}
        </section>
      )}

      {checks.length > 0 && (
        <section className="card checks" aria-label="Target checks">
          <h2 className="card__title">Target checks</h2>
          <ul className="checks__list">
            {checks.map((c) => (
              <li key={c.name} className={`check check--${c.pass === null ? 'na' : c.pass ? 'pass' : 'fail'}`}>
                <span className="check__icon" aria-hidden="true">
                  {c.pass === null ? '–' : c.pass ? '✓' : '×'}
                </span>
                <span className="check__name">{c.name}</span>
                <span className="check__value mono">{c.value || DASH}</span>
                <span className="sr-only">{c.pass === null ? 'not evaluated' : c.pass ? 'pass' : 'fail'}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {tiers.length === 0 ? (
        <EmptyState title="The report has no per-tier results">
          <p className="muted small">Expected a “tiers” object in latest.json.</p>
        </EmptyState>
      ) : (
        <>
          <section className="card">
            <h2 className="card__title">Question accuracy by tier</h2>
            <AccuracyChart bars={tiers.map((t) => ({ tier: t.name, value: metricValue(t.data, 'question_accuracy') }))} targets={targets.accuracy} />
          </section>

          <section className="card card--flush">
            <h2 className="card__title card__title--pad">Per-tier metrics</h2>
            <div className="table-wrap">
              <table className="table table--dense">
                <caption className="sr-only">Benchmark metrics per tier, with pass/fail against MVP targets</caption>
                <thead>
                  <tr>
                    <th scope="col">Tier</th>
                    {tableMetrics.map((m) => (
                      <th key={m.key} scope="col" className="num">
                        {m.kind === 'ms' ? `Latency ${m.label}` : m.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((t) => {
                    const qa = metricValue(t.data, 'question_accuracy');
                    const p95 = metricValue(t.data, 'latency_p95');
                    const target = targets.accuracy[t.name];
                    return (
                      <tr key={t.name} className={t.name === 'overall' ? 'row-total' : ''}>
                        <th scope="row">{t.name}</th>
                        {tableMetrics.map((m) => {
                          const v = metricValue(t.data, m.key);
                          return (
                            <td key={m.key} className="num">
                              {fmtMetric(m, v)}
                              {m.key === 'question_accuracy' && (
                                <VerdictBadge v={accuracyVerdict(t.name, qa, targets.accuracy)} title={target !== undefined ? `target ≥ ${(target * 100).toFixed(1)}%` : undefined} />
                              )}
                              {m.key === 'latency_p95' && <VerdictBadge v={latencyVerdict(p95, targets.p95Ms)} title={`target < ${targets.p95Ms} ms`} />}
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="muted small card__foot">
              Targets: question accuracy {targetText} (other tiers: reported only); latency p95 &lt; {targets.p95Ms} ms. Review rate is the share of sheets
              routed to review; throughput is sheets per second.
            </p>
          </section>
        </>
      )}

      {errors.length > 0 && (
        <section className="card card--flush">
          <h2 className="card__title card__title--pad">
            Error sample <span className="muted small">({errors.length})</span>
          </h2>
          <div className="table-wrap">
            <table className="table table--dense">
              <caption className="sr-only">Sample of benchmark errors</caption>
              <thead>
                <tr>
                  {errorCols.map((c) => (
                    <th key={c} scope="col">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {errors.slice(0, 50).map((e, i) => (
                  <tr key={i}>
                    {errorCols.map((c) => (
                      <td key={c} className="mono small">
                        {cellText(e[c])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
