import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api, type AnswerKey, type TemplateSummary } from '../api';
import { Dropzone } from '../components/Dropzone';
import { ErrorState, ProgressBar, Spinner } from '../components/States';
import { useToast } from '../components/Toasts';
import { mergeFiles, MAX_FILES } from '../lib/files';
import { fmtBytes } from '../lib/format';
import { useAsync, useTitle } from '../lib/hooks';

type Phase = { kind: 'idle' } | { kind: 'uploading'; fraction: number | null } | { kind: 'processing' };

export function ScanPage() {
  useTitle('Scan');
  const toast = useToast();
  const navigate = useNavigate();
  const lists = useAsync(() => Promise.all([api.listTemplates(), api.listAnswerKeys()]), []);
  const [templateId, setTemplateId] = useState('');
  const [answerKeyId, setAnswerKeyId] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [rejected, setRejected] = useState<{ name: string; reason: string }[]>([]);
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' });
  const abortRef = useRef<AbortController | null>(null);

  const templates: TemplateSummary[] = lists.data?.[0] ?? [];
  const keys: AnswerKey[] = lists.data?.[1] ?? [];

  useEffect(() => {
    if (!templateId && templates.length) setTemplateId(templates[0].id);
  }, [templates, templateId]);

  const keysForTemplate = useMemo(() => keys.filter((k) => !templateId || !k.template_id || k.template_id === templateId), [keys, templateId]);

  useEffect(() => {
    if (answerKeyId && !keysForTemplate.some((k) => String(k.id) === answerKeyId)) setAnswerKeyId('');
  }, [keysForTemplate, answerKeyId]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const totalBytes = files.reduce((a, f) => a + f.size, 0);
  const busy = phase.kind !== 'idle';

  const addFiles = (incoming: File[]) => {
    const res = mergeFiles(files, incoming);
    setFiles(res.accepted);
    setRejected(res.rejected);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!files.length || !templateId) return;
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setPhase({ kind: 'uploading', fraction: 0 });
    try {
      const res = await api.uploadScans(
        { files, templateId, answerKeyId: answerKeyId || null },
        (p) => {
          if (p.fraction !== null && p.fraction >= 1) setPhase({ kind: 'processing' });
          else setPhase({ kind: 'uploading', fraction: p.fraction });
        },
        ctrl.signal,
      );
      const n = res.scans?.length ?? 0;
      const review = res.scans?.filter((s) => s.result?.status !== 'ok').length ?? 0;
      toast.success(`Processed ${n} page${n === 1 ? '' : 's'}${review ? ` · ${review} need review` : ''}`);
      setFiles([]);
      navigate(`/batches/${encodeURIComponent(String(res.batch_id))}`);
    } catch (err) {
      if (!ctrl.signal.aborted) toast.error(err, 'Upload failed');
      setPhase({ kind: 'idle' });
    } finally {
      abortRef.current = null;
    }
  };

  if (lists.loading && !lists.data) return <Spinner label="Loading templates and answer keys…" />;
  if (lists.error && !lists.data) return <ErrorState error={lists.error} onRetry={lists.reload} title="Could not load templates" />;

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1>Scan answer sheets</h1>
          <p className="muted">Upload a batch of scans, PDFs or phone photos. Each page is read, graded and flagged for review if needed.</p>
        </div>
      </header>

      <form className="card scan-form" onSubmit={submit} aria-busy={busy}>
        <div className="form-row">
          <label className="field">
            <span className="field__label">Template</span>
            <select value={templateId} onChange={(e) => setTemplateId(e.target.value)} disabled={busy} required>
              {templates.length === 0 && <option value="">No templates available</option>}
              {templates.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name || t.id}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field__label">
              Answer key <span className="muted">(optional)</span>
            </span>
            <select value={answerKeyId} onChange={(e) => setAnswerKeyId(e.target.value)} disabled={busy}>
              <option value="">No grading</option>
              {keysForTemplate.map((k) => (
                <option key={String(k.id)} value={String(k.id)}>
                  {k.name}
                </option>
              ))}
            </select>
            <span className="field__hint">
              <Link to="/keys/new">Create an answer key</Link>
            </span>
          </label>
        </div>

        <Dropzone onFiles={addFiles} disabled={busy} />

        {rejected.length > 0 && (
          <div className="notice notice--warn" role="alert">
            <strong>
              {rejected.length} file{rejected.length === 1 ? ' was' : 's were'} not added:
            </strong>
            <ul>
              {rejected.slice(0, 10).map((r, i) => (
                <li key={`${r.name}-${i}`}>
                  {r.name}: {r.reason}
                </li>
              ))}
              {rejected.length > 10 && <li>…and {rejected.length - 10} more</li>}
            </ul>
          </div>
        )}

        {files.length > 0 && (
          <div className="file-list">
            <div className="file-list__head">
              <span>
                {files.length} / {MAX_FILES} files · {fmtBytes(totalBytes)}
              </span>
              <button type="button" className="btn btn--ghost btn--sm" onClick={() => setFiles([])} disabled={busy}>
                Clear all
              </button>
            </div>
            <ul>
              {files.map((f, i) => (
                <li key={`${f.name}-${f.size}-${i}`} className="file-list__item">
                  <span className="file-list__name" title={f.name}>
                    {f.name}
                  </span>
                  <span className="muted">{fmtBytes(f.size)}</span>
                  <button
                    type="button"
                    className="btn btn--ghost btn--sm"
                    aria-label={`Remove ${f.name}`}
                    onClick={() => setFiles((fs) => fs.filter((_, j) => j !== i))}
                    disabled={busy}
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {phase.kind === 'uploading' && <ProgressBar value={phase.fraction} label="Uploading" />}
        {phase.kind === 'processing' && <ProgressBar value={null} label="Upload complete · reading sheets on the server" />}

        <div className="form-actions">
          {busy && (
            <button type="button" className="btn" onClick={() => abortRef.current?.abort()}>
              Cancel
            </button>
          )}
          <button type="submit" className="btn btn--primary" disabled={busy || !files.length || !templateId}>
            {busy ? 'Working…' : `Scan ${files.length || ''} file${files.length === 1 ? '' : 's'}`.replace('  ', ' ')}
          </button>
        </div>
      </form>
    </div>
  );
}
