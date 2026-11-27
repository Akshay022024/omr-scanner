import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api, OPTIONS, PAPER_SETS, type FieldResult, type ScanPatch, type ScanRecord, type TemplateField } from '../api';
import { AnswerGrid } from '../components/AnswerGrid';
import { ReviewOverlay } from '../components/ReviewOverlay';
import { ScanViewer, type ScanViewerHandle } from '../components/ScanViewer';
import { ErrorState, Spinner, StatusChip } from '../components/States';
import { useToast } from '../components/Toasts';
import { DASH, fmtMs, fmtPct, fmtScore, isNum } from '../lib/format';
import { getTemplateCached, useAsync, useTitle } from '../lib/hooks';
import { describeFlag, fieldBounds, parseFlag, type ReviewDraft } from '../lib/overlay';
import { needsReview, queueNeighbours, sortScans } from '../lib/queue';

const EMPTY_DRAFT: ReviewDraft = { answers: {} };
const KEY_TO_OPTION: Record<string, string> = { '1': 'A', '2': 'B', '3': 'C', '4': 'D', a: 'A', b: 'B', c: 'C', d: 'D' };
const LOW_QUALITY = 0.8;

function isTypingTarget(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false;
  const tag = t.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || t.isContentEditable;
}

function buildPatch(scan: ScanRecord, draft: ReviewDraft): ScanPatch {
  const patch: ScanPatch = {};
  const answers: Record<string, string> = {};
  for (const [q, v] of Object.entries(draft.answers)) {
    if ((scan.result.answers[q] ?? '') !== v) answers[q] = v;
  }
  if (Object.keys(answers).length) patch.answers = answers;
  if (draft.roll_no !== undefined && draft.roll_no !== (scan.result.roll_no ?? '')) patch.roll_no = draft.roll_no;
  if (draft.paper_set !== undefined && draft.paper_set !== (scan.result.paper_set ?? '')) patch.paper_set = draft.paper_set || null;
  return patch;
}

export function ReviewPage() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const viewerRef = useRef<ScanViewerHandle>(null);

  const scanState = useAsync(() => api.getScan(id), [id]);
  const scan = scanState.data && String(scanState.data.id) === id ? scanState.data : undefined;
  const templateId = scan?.result?.template_id;
  const tplState = useAsync(() => (templateId ? getTemplateCached(templateId) : Promise.resolve(null)), [templateId]);
  const batchId = scan?.batch_id;
  const batchState = useAsync(
    () => (batchId !== undefined && batchId !== null ? api.listScans(batchId).then(sortScans) : Promise.resolve([] as ScanRecord[])),
    [batchId === undefined ? '' : String(batchId)],
  );
  const keyId = scan?.grade?.answer_key_id ?? scan?.answer_key_id ?? undefined;
  const keyState = useAsync(
    () => (keyId !== undefined && keyId !== null ? api.getAnswerKey(keyId).catch(() => null) : Promise.resolve(null)),
    [keyId === undefined || keyId === null ? '' : String(keyId)],
  );

  const [draft, setDraft] = useState<ReviewDraft>(EMPTY_DRAFT);
  const [selectedQ, setSelectedQ] = useState<number | null>(null);
  const [highlightField, setHighlightField] = useState<string | null>(null);
  const [mode, setMode] = useState<'aligned' | 'original'>('aligned');
  const [showOverlay, setShowOverlay] = useState(true);
  const [saving, setSaving] = useState(false);

  useTitle(scan ? `Review ${scan.filename}` : 'Review');

  const tpl = tplState.data ?? null;
  const numQuestions = tpl?.num_questions ?? 80;
  const width = scan?.result?.aligned_size?.[0] ?? tpl?.page?.width_px ?? 1700;
  const height = scan?.result?.aligned_size?.[1] ?? tpl?.page?.height_px ?? 2200;
  const options = tpl?.options?.length ? tpl.options : [...OPTIONS];
  const rollLength = tpl ? tpl.fields.filter((f) => f.group === 'roll_no').length || 10 : 10;

  const resultById = useMemo(() => new Map<string, FieldResult>((scan?.result?.fields ?? []).map((f) => [f.id, f])), [scan]);
  const fieldsByQ = useMemo(() => {
    const m = new Map<number, FieldResult>();
    for (const f of scan?.result?.fields ?? []) {
      const q = f.question ?? (/^q(\d+)$/.exec(f.id) ? Number(f.id.slice(1)) : null);
      if (q) m.set(q, f);
    }
    return m;
  }, [scan]);
  const tplFieldById = useMemo(() => new Map<string, TemplateField>((tpl?.fields ?? []).map((f) => [f.id, f])), [tpl]);

  const flags = useMemo(() => (scan?.result?.review_flags ?? []).map(parseFlag), [scan]);

  // Reset local state whenever another scan is opened.
  useEffect(() => {
    setDraft(EMPTY_DRAFT);
    setHighlightField(null);
    setMode('aligned');
  }, [id]);
  useEffect(() => {
    if (!scan) return;
    const firstQ = flags.find((f) => f.question !== null)?.question ?? null;
    setSelectedQ(firstQ ?? 1);
    // only when the scan identity changes (not after a save of the same scan)
  }, [scan?.id]);

  const perQuestion = scan?.grade?.per_question;
  const expected = useMemo(() => {
    const key = keyState.data;
    if (!key) return undefined;
    const set = (scan?.grade?.paper_set_used ?? scan?.result?.paper_set ?? '') as 'A';
    return key.keys[set] ?? undefined;
  }, [keyState.data, scan]);

  const patch = useMemo(() => (scan ? buildPatch(scan, draft) : {}), [scan, draft]);
  const dirty = Object.keys(patch).length > 0;
  const changeCount = (patch.answers ? Object.keys(patch.answers).length : 0) + (patch.roll_no !== undefined ? 1 : 0) + (patch.paper_set !== undefined ? 1 : 0);

  // Warn before closing the tab with unsaved corrections.
  useEffect(() => {
    if (!dirty) return;
    const h = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', h);
    return () => window.removeEventListener('beforeunload', h);
  }, [dirty]);

  const batchScans = batchState.data ?? [];
  const nav = useMemo(() => queueNeighbours(batchScans, id, needsReview), [batchScans, id]);
  const allNav = useMemo(() => queueNeighbours(batchScans, id, () => true), [batchScans, id]);

  const goTo = useCallback(
    (target?: ScanRecord) => {
      if (!target) return;
      if (dirty && !window.confirm('Discard unsaved corrections on this sheet?')) return;
      navigate(`/scans/${encodeURIComponent(String(target.id))}`);
    },
    [dirty, navigate],
  );

  const setAnswer = useCallback(
    (q: number, value: string, advance = false) => {
      setDraft((d) => ({ ...d, answers: { ...d.answers, [String(q)]: value } }));
      if (advance) setSelectedQ((cur) => (cur !== null && cur < numQuestions ? cur + 1 : cur));
    },
    [numQuestions],
  );

  const revertAnswer = (q: number) =>
    setDraft((d) => {
      const answers = { ...d.answers };
      delete answers[String(q)];
      return { ...d, answers };
    });

  const focusField = useCallback(
    (fieldId: string) => {
      const f = tplFieldById.get(fieldId);
      if (f) viewerRef.current?.focusRegion(fieldBounds(f, 30));
    },
    [tplFieldById],
  );

  const selectQuestion = useCallback(
    (q: number, focus = false) => {
      setSelectedQ(q);
      setHighlightField(null);
      if (focus) focusField(`q${q}`);
    },
    [focusField],
  );

  const onSelectField = useCallback(
    (f: TemplateField) => {
      if (f.question !== undefined) {
        setSelectedQ(f.question);
        setHighlightField(null);
        document.querySelector<HTMLElement>(`.qcell[data-q="${f.question}"]`)?.scrollIntoView({ block: 'nearest' });
      } else {
        setHighlightField(f.id);
        document.getElementById(f.group === 'paper_set' ? 'review-set' : 'review-roll')?.focus();
      }
    },
    [],
  );

  const save = useCallback(async () => {
    if (!scan || !dirty || saving) return;
    setSaving(true);
    try {
      const rec = await api.patchScan(scan.id, patch);
      scanState.setData(rec);
      setDraft(EMPTY_DRAFT);
      batchState.setData((prev) => (prev ?? []).map((s) => (String(s.id) === String(rec.id) ? rec : s)));
      toast.success(`Saved ${changeCount} correction${changeCount === 1 ? '' : 's'}${rec.grade ? ` · score ${fmtScore(rec.grade.score)} / ${fmtScore(rec.grade.max_score)}` : ''}`);
    } catch (e) {
      toast.error(e, 'Save failed');
    } finally {
      setSaving(false);
    }
  }, [scan, dirty, saving, patch, scanState, batchState, toast, changeCount]);

  // Keyboard shortcuts.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault();
        void save();
        return;
      }
      if (e.ctrlKey || e.metaKey || e.altKey || isTypingTarget(e.target)) return;
      const k = e.key;
      const lower = k.toLowerCase();
      if (e.shiftKey && k.startsWith('Arrow')) return; // viewer panning
      if (lower === 'j' || k === 'ArrowRight' || k === 'ArrowDown') {
        e.preventDefault();
        goTo(nav.next);
      } else if (lower === 'k' || k === 'ArrowLeft' || k === 'ArrowUp') {
        e.preventDefault();
        goTo(nav.prev);
      } else if (KEY_TO_OPTION[lower] && selectedQ !== null && !e.shiftKey) {
        const opt = KEY_TO_OPTION[lower];
        if (!options.includes(opt)) return;
        e.preventDefault();
        setAnswer(selectedQ, opt, true);
      } else if ((k === '0' || k === '-' || k === 'Backspace' || k === 'Delete') && selectedQ !== null) {
        e.preventDefault();
        setAnswer(selectedQ, '', true);
      } else if (lower === 'o') {
        setMode((m) => (m === 'aligned' ? 'original' : 'aligned'));
      } else if (lower === 'v') {
        setShowOverlay((v) => !v);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [goTo, nav.next, nav.prev, selectedQ, setAnswer, save, options]);

  if (scanState.loading && !scan) return <Spinner label="Loading scan…" />;
  if (scanState.error && !scan) return <ErrorState error={scanState.error} onRetry={scanState.reload} title="Could not load scan" />;
  if (!scan) return <Spinner label="Loading scan…" />;

  const r = scan.result;
  const g = scan.grade ?? null;
  const quality = r.registration?.quality;
  const rollValue = draft.roll_no ?? r.roll_no ?? '';
  const setValue = draft.paper_set ?? r.paper_set ?? '';
  // Backend rule: exactly one character per roll digit, each 0-9, "?" (unreadable) or "*" (multiple).
  // Only validated once the user edits it.
  const rollInvalid = draft.roll_no !== undefined && !new RegExp(`^[0-9?*]{${rollLength}}$`).test(draft.roll_no);
  const rollHasUnknown = /[?*]/.test(rollValue);
  const selField = selectedQ !== null ? fieldsByQ.get(selectedQ) : undefined;
  const selDraft = selectedQ !== null ? draft.answers[String(selectedQ)] : undefined;
  const selValue = selDraft !== undefined ? selDraft : (selField?.value ?? '');
  const selGrade = selectedQ !== null ? perQuestion?.[String(selectedQ)] : undefined;
  const selExpected = selectedQ !== null ? expected?.[String(selectedQ)] : undefined;
  const selectedFieldId = highlightField ? null : selectedQ !== null ? `q${selectedQ}` : null;
  const batchHref = `/batches/${encodeURIComponent(String(scan.batch_id))}`;

  const overlay =
    tpl && mode === 'aligned' ? (
      <ReviewOverlay
        fields={tpl.fields}
        resultById={resultById}
        draft={draft}
        perQuestion={perQuestion}
        expected={expected}
        selectedFieldId={selectedFieldId}
        highlightFieldId={highlightField}
        onSelectField={onSelectField}
      />
    ) : null;

  const imgSrc = mode === 'aligned' ? api.urls.aligned(scan.id) : api.urls.original(scan.id);

  return (
    <div className="review">
      <div className="review__bar">
        <nav className="breadcrumbs" aria-label="Breadcrumb">
          <Link to="/batches">Batches</Link> <span aria-hidden="true">/</span> <Link to={batchHref}>Batch</Link>{' '}
          <span aria-hidden="true">/</span>{' '}
          <span aria-current="page" className="truncate" title={scan.filename}>
            {scan.filename}
            {scan.page ? ` · p${scan.page}` : ''}
          </span>
        </nav>
        <div className="review__nav" role="group" aria-label="Sheet navigation">
          <button type="button" className="btn btn--sm" onClick={() => goTo(nav.prev)} disabled={!nav.prev} title="Previous sheet needing review (K / ←)">
            ‹ Prev flagged
          </button>
          <span className="muted review__pos">
            {nav.total ? (nav.position ? `${nav.position} / ${nav.total} flagged` : `${nav.total} flagged`) : 'No flagged sheets'}
          </span>
          <button type="button" className="btn btn--sm" onClick={() => goTo(nav.next)} disabled={!nav.next} title="Next sheet needing review (J / →)">
            Next flagged ›
          </button>
          <span className="review__sep" aria-hidden="true" />
          <button type="button" className="btn btn--ghost btn--sm" onClick={() => goTo(allNav.prev)} disabled={!allNav.prev} aria-label="Previous sheet in batch">
            ‹ Sheet
          </button>
          <button type="button" className="btn btn--ghost btn--sm" onClick={() => goTo(allNav.next)} disabled={!allNav.next} aria-label="Next sheet in batch">
            Sheet ›
          </button>
        </div>
      </div>

      <div className="review__body">
        <section className="review__image" aria-label="Sheet image">
          <ScanViewer
            ref={viewerRef}
            key={`${String(scan.id)}-${mode}`}
            src={imgSrc}
            alt={mode === 'aligned' ? `Aligned scan of ${scan.filename}` : `Original upload ${scan.filename}`}
            width={width}
            height={height}
            overlay={overlay}
            showOverlay={showOverlay && mode === 'aligned'}
            toolbarExtra={
              <span className="viewer__extra">
                <label className="toggle">
                  <input type="checkbox" checked={mode === 'original'} onChange={(e) => setMode(e.target.checked ? 'original' : 'aligned')} />
                  <span>Original (O)</span>
                </label>
                <label className="toggle">
                  <input type="checkbox" checked={showOverlay} disabled={mode !== 'aligned'} onChange={(e) => setShowOverlay(e.target.checked)} />
                  <span>Overlay (V)</span>
                </label>
              </span>
            }
            errorContent={
              mode === 'aligned' ? (
                <>
                  <p>The aligned image is not available{r.status === 'failed' ? ' because this page failed to process' : ''}.</p>
                  <button type="button" className="btn btn--sm" onClick={() => setMode('original')}>
                    Show original
                  </button>
                </>
              ) : (
                <>
                  <p>The original cannot be shown inline (PDF uploads are not rendered in the browser).</p>
                  <a className="btn btn--sm" href={api.urls.original(scan.id)} target="_blank" rel="noreferrer">
                    Open in new tab
                  </a>
                </>
              )
            }
          />
          {mode === 'aligned' && (
            <ul className="legend" aria-label="Overlay legend">
              <li>
                <span className="legend__sw bubble-sw--selected" /> marked
              </li>
              {g && (
                <>
                  <li>
                    <span className="legend__sw bubble-sw--correct" /> correct
                  </li>
                  <li>
                    <span className="legend__sw bubble-sw--wrong" /> wrong
                  </li>
                  <li>
                    <span className="legend__sw bubble-sw--expected" /> key answer
                  </li>
                </>
              )}
              <li>
                <span className="legend__sw bubble-sw--multiple" /> multiple
              </li>
              <li>
                <span className="legend__sw bubble-sw--ambiguous" /> ambiguous
              </li>
              <li>
                <span className="legend__sw bubble-sw--blank" /> blank field
              </li>
              <li>
                <span className="legend__sw bubble-sw--edited" /> your correction
              </li>
            </ul>
          )}
          {tplState.error ? <p className="notice notice--warn">Template geometry could not be loaded, so the overlay is hidden.</p> : null}
        </section>

        <aside className="review__panel" aria-label="Scan details and corrections">
          <div className="panel-section">
            <div className="panel-row">
              <StatusChip status={r.status} />
              {scan.corrected && <span className="tag">corrected</span>}
              {dirty && <span className="tag tag--warn">{changeCount} unsaved</span>}
            </div>
            {r.status === 'failed' && r.error && <p className="notice notice--bad">{r.error}</p>}
          </div>

          <div className="panel-section panel-grid">
            <label className="field">
              <span className="field__label">Roll no</span>
              <input
                id="review-roll"
                className={`mono${highlightField?.startsWith('roll_') ? ' input--flag' : ''}`}
                value={rollValue}
                inputMode="numeric"
                maxLength={rollLength}
                aria-invalid={rollInvalid}
                aria-describedby="roll-hint"
                onChange={(e) => setDraft((d) => ({ ...d, roll_no: e.target.value.replace(/\s/g, '') }))}
              />
              <span id="roll-hint" className={`field__hint${rollInvalid ? ' text-bad' : rollHasUnknown ? ' text-warn' : ''}`}>
                {rollInvalid
                  ? `Enter exactly ${rollLength} characters: digits, ? (unreadable) or * (multiple)`
                  : rollHasUnknown
                    ? `? = unreadable digit, * = multiple marks`
                    : `${rollLength} digits`}
              </span>
            </label>
            <label className="field">
              <span className="field__label">Paper set</span>
              <select
                id="review-set"
                className={highlightField === 'paper_set' ? 'input--flag' : ''}
                value={setValue}
                onChange={(e) => setDraft((d) => ({ ...d, paper_set: e.target.value }))}
              >
                <option value="">Not detected</option>
                {PAPER_SETS.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="panel-section">
            <h2 className="panel-title">Score</h2>
            {g ? (
              <div className="score">
                <span className="score__big">
                  {fmtScore(g.score)}
                  <span className="muted"> / {fmtScore(g.max_score)}</span>
                </span>
                <span className="score__parts">
                  <span className="text-good">{g.correct} correct</span> · <span className="text-bad">{g.wrong} wrong</span> · <span>{g.blank} blank</span> ·{' '}
                  <span className="text-warn">{g.multiple} multiple</span>
                </span>
                <span className="muted small">
                  {keyState.data ? `Key “${keyState.data.name}”` : 'Answer key'}
                  {g.paper_set_used ? ` · set ${g.paper_set_used}` : ''}
                  {dirty ? ' · updates after save' : ''}
                </span>
              </div>
            ) : (
              <p className="muted small">Not graded. Re-grade the batch with an answer key to score it.</p>
            )}
          </div>

          <div className="panel-section">
            <h2 className="panel-title">Registration</h2>
            <dl className="kv">
              <dt>Quality</dt>
              <dd className={isNum(quality) && quality < LOW_QUALITY ? 'text-warn' : ''}>{fmtPct(quality)}</dd>
              <dt>Method</dt>
              <dd>{r.registration?.method ?? DASH}</dd>
              <dt>Threshold</dt>
              <dd>{isNum(r.threshold) ? r.threshold.toFixed(2) : DASH}</dd>
              <dt>Time</dt>
              <dd>{fmtMs(r.timings_ms?.total)}</dd>
            </dl>
          </div>

          <div className="panel-section">
            <h2 className="panel-title">Review flags {flags.length > 0 && <span className="count">{flags.length}</span>}</h2>
            {flags.length === 0 ? (
              <p className="muted small">No flags.</p>
            ) : (
              <ul className="flags">
                {flags.map((f) => (
                  <li key={f.raw}>
                    <button
                      type="button"
                      className={`flag flag--${f.reason || 'other'}${(f.question !== null && selectedQ === f.question && !highlightField) || highlightField === f.fieldId ? ' flag--active' : ''}`}
                      onClick={() => {
                        if (f.question !== null) {
                          selectQuestion(f.question, true);
                          document.querySelector<HTMLElement>(`.qcell[data-q="${f.question}"]`)?.scrollIntoView({ block: 'nearest' });
                        } else {
                          setHighlightField(f.fieldId);
                          focusField(f.fieldId);
                        }
                      }}
                    >
                      {describeFlag(f)}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="panel-section">
            <h2 className="panel-title">Answers</h2>
            {selectedQ !== null && (
              <div className="qedit" role="group" aria-label={`Set answer for question ${selectedQ}`}>
                <span className="qedit__label">
                  Q{selectedQ}
                  <span className="muted small">
                    {' '}
                    detected {selField?.value || 'blank'}
                    {selField?.state && selField.state !== 'single' ? ` (${selField.state})` : ''}
                    {selGrade ? ` · ${selGrade.replace('_', ' ')}` : ''}
                    {selExpected ? ` · key ${selExpected}` : ''}
                  </span>
                </span>
                <div className="qedit__btns">
                  {options.map((o, i) => (
                    <button key={o} type="button" className="btn btn--opt" aria-pressed={selValue === o} onClick={() => setAnswer(selectedQ, o)} title={`${o} (${i + 1})`}>
                      {o}
                    </button>
                  ))}
                  <button type="button" className="btn btn--opt btn--opt-blank" aria-pressed={selValue === ''} onClick={() => setAnswer(selectedQ, '')} title="Blank (0)">
                    Blank
                  </button>
                  {selDraft !== undefined && (
                    <button type="button" className="btn btn--ghost btn--sm" onClick={() => revertAnswer(selectedQ)}>
                      Revert
                    </button>
                  )}
                </div>
              </div>
            )}
            <AnswerGrid
              numQuestions={numQuestions}
              fieldsByQ={fieldsByQ}
              draftAnswers={draft.answers}
              perQuestion={perQuestion}
              expected={expected}
              selected={selectedQ}
              onSelect={(q) => selectQuestion(q, true)}
            />
          </div>

          <details className="panel-section shortcuts">
            <summary>Keyboard shortcuts</summary>
            <ul>
              <li>
                <kbd>J</kbd> / <kbd>→</kbd> next flagged sheet, <kbd>K</kbd> / <kbd>←</kbd> previous
              </li>
              <li>
                <kbd>1</kbd>–<kbd>4</kbd> or <kbd>A</kbd>–<kbd>D</kbd> set answer, <kbd>0</kbd> / <kbd>Del</kbd> blank (moves to next question)
              </li>
              <li>
                <kbd>Ctrl</kbd>+<kbd>S</kbd> save · <kbd>O</kbd> original image · <kbd>V</kbd> overlay
              </li>
              <li>
                In the image: wheel zoom, drag pan, <kbd>+</kbd>/<kbd>−</kbd>, <kbd>F</kbd> fit
              </li>
            </ul>
          </details>

          <div className="panel-actions">
            <button type="button" className="btn" onClick={() => setDraft(EMPTY_DRAFT)} disabled={!dirty || saving}>
              Discard
            </button>
            <button type="button" className="btn btn--primary" onClick={() => void save()} disabled={!dirty || saving || rollInvalid}>
              {saving ? 'Saving…' : dirty ? `Save ${changeCount} change${changeCount === 1 ? '' : 's'}` : 'Saved'}
            </button>
          </div>
        </aside>
      </div>
    </div>
  );
}
