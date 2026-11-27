import { useCallback, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api, PAPER_SETS, type AnswerKey, type AnswerKeyInput } from '../api';
import { AnswerKeyEditor } from '../components/AnswerKeyEditor';
import { EmptyState, ErrorState, Spinner } from '../components/States';
import { useToast } from '../components/Toasts';
import { countAnswered } from '../lib/answerString';
import { fmtScore } from '../lib/format';
import { useAsync, useTitle } from '../lib/hooks';

function fmtMarks(k: AnswerKey): string {
  const sign = (n: number) => (n > 0 ? `+${fmtScore(n)}` : fmtScore(n));
  return `${sign(k.marks_correct)} / ${sign(k.marks_wrong)} / ${sign(k.marks_blank)}`;
}

export function KeysPage() {
  const { id } = useParams();
  useTitle('Answer keys');
  const navigate = useNavigate();
  const toast = useToast();
  const state = useAsync(() => Promise.all([api.listAnswerKeys(), api.listTemplates().catch(() => [])]), []);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const dirtyRef = useRef(false);
  const onDirtyChange = useCallback((d: boolean) => {
    dirtyRef.current = d;
  }, []);

  const keys = state.data?.[0] ?? [];
  const templates = state.data?.[1] ?? [];
  const isNew = id === 'new';
  const editing = id && !isNew ? keys.find((k) => String(k.id) === id) : undefined;
  const editorOpen = isNew || !!editing;

  const leaveEditor = (to = '/keys') => {
    if (dirtyRef.current && !window.confirm('Discard unsaved changes to this answer key?')) return;
    dirtyRef.current = false;
    navigate(to);
  };

  const save = async (input: AnswerKeyInput) => {
    setSaving(true);
    try {
      const saved = editing ? await api.updateAnswerKey(editing.id, input) : await api.createAnswerKey(input);
      const record: AnswerKey = saved && typeof saved === 'object' && 'id' in saved ? saved : { ...input, id: editing?.id ?? '' };
      state.setData((prev) => {
        const [list, tpls] = prev ?? [[], []];
        const exists = list.some((k) => String(k.id) === String(record.id));
        return [exists ? list.map((k) => (String(k.id) === String(record.id) ? record : k)) : [...list, record], tpls];
      });
      toast.success(editing ? `Saved “${input.name}”` : `Created “${input.name}”`);
      dirtyRef.current = false;
      if (!editing && record.id !== '') navigate(`/keys/${encodeURIComponent(String(record.id))}`, { replace: true });
      if (!editing && record.id === '') state.reload();
    } catch (e) {
      toast.error(e, 'Could not save answer key');
    } finally {
      setSaving(false);
    }
  };

  const remove = async (k: AnswerKey) => {
    if (!window.confirm(`Delete answer key “${k.name}”? Scans already graded with it keep their scores.`)) return;
    setDeleting(String(k.id));
    try {
      await api.deleteAnswerKey(k.id);
      state.setData((prev) => {
        const [list, tpls] = prev ?? [[], []];
        return [list.filter((x) => String(x.id) !== String(k.id)), tpls];
      });
      toast.success(`Deleted “${k.name}”`);
      if (id === String(k.id)) {
        dirtyRef.current = false;
        navigate('/keys');
      }
    } catch (e) {
      toast.error(e, 'Could not delete answer key');
    } finally {
      setDeleting(null);
    }
  };

  if (state.loading && !state.data) return <Spinner label="Loading answer keys…" />;
  if (state.error && !state.data) return <ErrorState error={state.error} onRetry={state.reload} title="Could not load answer keys" />;

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1>Answer keys</h1>
          <p className="muted">One key per exam, with answers for paper sets A, B and C and a marking scheme.</p>
        </div>
        <div className="page__actions">
          <button type="button" className="btn btn--primary" onClick={() => leaveEditor('/keys/new')} disabled={isNew}>
            New answer key
          </button>
        </div>
      </header>

      {id && !isNew && !editing && (
        <div className="notice notice--warn" role="alert">
          Answer key “{id}” was not found. <Link to="/keys">Back to the list</Link>
        </div>
      )}

      <div className={`keys-layout${editorOpen ? ' keys-layout--editing' : ''}`}>
        <section aria-label="Answer key list" className="keys-list">
          {keys.length === 0 ? (
            <EmptyState title="No answer keys yet">
              <p>Create one to grade scans automatically.</p>
            </EmptyState>
          ) : (
            <ul className="key-cards">
              {keys.map((k) => {
                const active = String(k.id) === id;
                return (
                  <li key={String(k.id)} className={`key-card${active ? ' key-card--active' : ''}`}>
                    <div className="key-card__main">
                      <Link
                        to={`/keys/${encodeURIComponent(String(k.id))}`}
                        className="key-card__name"
                        aria-current={active ? 'true' : undefined}
                        onClick={(e) => {
                          if (active) return;
                          e.preventDefault();
                          leaveEditor(`/keys/${encodeURIComponent(String(k.id))}`);
                        }}
                      >
                        {k.name}
                      </Link>
                      <span className="muted small">
                        {k.template_id} · marks {fmtMarks(k)}
                      </span>
                      <span className="key-card__sets">
                        {PAPER_SETS.map((s) => {
                          const n = countAnswered(k.keys?.[s]);
                          return (
                            <span key={s} className={`set-pill${n ? '' : ' set-pill--empty'}`} title={`Set ${s}: ${n} answers`}>
                              {s} {n}
                            </span>
                          );
                        })}
                      </span>
                    </div>
                    <button
                      type="button"
                      className="btn btn--ghost btn--sm btn--danger"
                      onClick={() => remove(k)}
                      disabled={deleting === String(k.id)}
                      aria-label={`Delete ${k.name}`}
                    >
                      {deleting === String(k.id) ? 'Deleting…' : 'Delete'}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {editorOpen && (
          <section aria-label="Answer key editor" className="keys-editor">
            <AnswerKeyEditor
              key={isNew ? 'new' : String(editing?.id)}
              initial={editing ?? null}
              templates={templates}
              saving={saving}
              onSave={save}
              onCancel={() => leaveEditor('/keys')}
              onDirtyChange={onDirtyChange}
            />
          </section>
        )}
      </div>
    </div>
  );
}
