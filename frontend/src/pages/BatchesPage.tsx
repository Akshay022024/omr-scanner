import { Link, useNavigate } from 'react-router-dom';
import { api, type BatchSummary } from '../api';
import { EmptyState, ErrorState, Spinner } from '../components/States';
import { DASH, fmtDate, fmtScore, isNum, shortId } from '../lib/format';
import { useAsync, useTitle } from '../lib/hooks';

function scanCount(b: BatchSummary): number | null {
  if (isNum(b.scan_count)) return b.scan_count;
  if (isNum(b.count)) return b.count;
  if (Array.isArray(b.scans)) return b.scans.length;
  return null;
}

function reviewCount(b: BatchSummary): number | null {
  if (isNum(b.needs_review)) return b.needs_review;
  if (isNum(b.review_count)) return b.review_count;
  if (b.status_counts && isNum(b.status_counts.needs_review)) return b.status_counts.needs_review;
  if (Array.isArray(b.scans)) return b.scans.filter((s) => s.result?.status === 'needs_review').length;
  return null;
}

export function BatchesPage() {
  useTitle('Batches');
  const navigate = useNavigate();
  const { data, error, loading, reload } = useAsync(() => api.listBatches(), []);

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1>Batches</h1>
          <p className="muted">Every upload creates a batch. Open one to see scores, review flagged sheets and export CSV.</p>
        </div>
        <div className="page__actions">
          <button type="button" className="btn" onClick={reload} disabled={loading}>
            Refresh
          </button>
          <Link to="/" className="btn btn--primary">
            New scan
          </Link>
        </div>
      </header>

      {loading && !data && <Spinner label="Loading batches…" />}
      {error && !data ? <ErrorState error={error} onRetry={reload} title="Could not load batches" /> : null}
      {data && data.length === 0 && (
        <EmptyState title="No batches yet">
          <p>
            <Link to="/">Upload answer sheets</Link> to create the first batch.
          </p>
        </EmptyState>
      )}
      {data && data.length > 0 && (
        <div className="card card--flush table-wrap">
          <table className="table">
            <caption className="sr-only">Batches</caption>
            <thead>
              <tr>
                <th scope="col">Batch</th>
                <th scope="col">Created</th>
                <th scope="col">Template</th>
                <th scope="col" className="num">
                  Pages
                </th>
                <th scope="col" className="num">
                  Needs review
                </th>
                <th scope="col" className="num">
                  Avg score
                </th>
              </tr>
            </thead>
            <tbody>
              {data.map((b) => {
                const href = `/batches/${encodeURIComponent(String(b.id))}`;
                const rc = reviewCount(b);
                return (
                  <tr key={String(b.id)} className="row-link" onClick={() => navigate(href)}>
                    <td>
                      <Link to={href} onClick={(e) => e.stopPropagation()} title={String(b.id)}>
                        {shortId(b.id)}
                      </Link>
                    </td>
                    <td>{fmtDate(b.created_at)}</td>
                    <td>{b.template_id ?? DASH}</td>
                    <td className="num">{scanCount(b) ?? DASH}</td>
                    <td className="num">{rc === null ? DASH : rc > 0 ? <span className="text-warn">{rc}</span> : 0}</td>
                    <td className="num">{fmtScore(isNum(b.mean_score) ? Math.round(b.mean_score * 100) / 100 : b.avg_score)}</td>
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
