import { useEffect, useId, useMemo, useState, type FormEvent } from 'react';
import { OPTIONS, PAPER_SETS, type AnswerKey, type AnswerKeyInput, type PaperSet, type TemplateSummary } from '../api';
import { answersToString, countAnswered, parseAnswerString } from '../lib/answerString';
import { getTemplateCached } from '../lib/hooks';
import { KeyGrid } from './KeyGrid';

interface Props {
  initial: AnswerKey | null; // null = new key
  templates: TemplateSummary[];
  saving: boolean;
  onSave: (input: AnswerKeyInput) => void;
  onCancel: () => void;
  onDirtyChange?: (dirty: boolean) => void;
}

type Sets = Record<PaperSet, Record<string, string>>;

function initialSets(k: AnswerKey | null): Sets {
  return { A: { ...(k?.keys.A ?? {}) }, B: { ...(k?.keys.B ?? {}) }, C: { ...(k?.keys.C ?? {}) } };
}

export function AnswerKeyEditor({ initial, templates, saving, onSave, onCancel, onDirtyChange }: Props) {
  const uid = useId();
  const [name, setName] = useState(initial?.name ?? '');
  const [templateId, setTemplateId] = useState(initial?.template_id ?? templates[0]?.id ?? '');
  const [marks, setMarks] = useState({
    correct: String(initial?.marks_correct ?? 1),
    wrong: String(initial?.marks_wrong ?? 0),
    blank: String(initial?.marks_blank ?? 0),
  });
  const [sets, setSets] = useState<Sets>(() => initialSets(initial));
  const [active, setActive] = useState<PaperSet>('A');
  const [paste, setPaste] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [numQuestions, setNumQuestions] = useState(80);
  const [options, setOptions] = useState<readonly string[]>(OPTIONS);

  useEffect(() => {
    if (!templateId && templates.length) setTemplateId(templates[0].id);
  }, [templates, templateId]);

  // Number of questions / options come from the template geometry when available.
  useEffect(() => {
    if (!templateId) return;
    let alive = true;
    getTemplateCached(templateId)
      .then((t) => {
        if (!alive) return;
        const summary = templates.find((x) => x.id === templateId);
        setNumQuestions(t.num_questions ?? summary?.num_questions ?? 80);
        if (t.options?.length) setOptions(t.options);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [templateId, templates]);

  const parsed = useMemo(() => (paste.trim() ? parseAnswerString(paste, numQuestions, options) : null), [paste, numQuestions, options]);

  const marksNum = {
    correct: Number(marks.correct),
    wrong: Number(marks.wrong),
    blank: Number(marks.blank),
  };
  const marksError = (['correct', 'wrong', 'blank'] as const).filter((k) => marks[k].trim() === '' || !Number.isFinite(marksNum[k]));
  const counts = Object.fromEntries(PAPER_SETS.map((s) => [s, countAnswered(sets[s], numQuestions)])) as Record<PaperSet, number>;
  const anyAnswers = PAPER_SETS.some((s) => counts[s] > 0);
  const errors: string[] = [];
  if (!name.trim()) errors.push('Name is required.');
  if (!templateId) errors.push('Choose a template.');
  if (marksError.length) errors.push(`Marks must be numbers (${marksError.join(', ')}).`);
  if (!anyAnswers) errors.push('Enter answers for at least one paper set.');
  const partial = PAPER_SETS.filter((s) => counts[s] > 0 && counts[s] < numQuestions);

  const dirty = useMemo(() => {
    const base = initialSets(initial);
    return (
      name !== (initial?.name ?? '') ||
      templateId !== (initial?.template_id ?? templateId) ||
      marks.correct !== String(initial?.marks_correct ?? 1) ||
      marks.wrong !== String(initial?.marks_wrong ?? 0) ||
      marks.blank !== String(initial?.marks_blank ?? 0) ||
      PAPER_SETS.some((s) => answersToString(base[s], numQuestions) !== answersToString(sets[s], numQuestions))
    );
  }, [initial, name, templateId, marks, sets, numQuestions]);

  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);

  const setAnswer = (q: number, v: string) =>
    setSets((s) => {
      const next = { ...s[active] };
      if (v) next[String(q)] = v;
      else delete next[String(q)];
      return { ...s, [active]: next };
    });

  const applyPaste = () => {
    if (!parsed || parsed.errors.length) return;
    setSets((s) => ({ ...s, [active]: { ...parsed.answers } }));
    setPaste('');
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSubmitted(true);
    if (errors.length) return;
    // Only questions within the template range are kept.
    const clean = (a: Record<string, string>) =>
      Object.fromEntries(Object.entries(a).filter(([q, v]) => Number(q) >= 1 && Number(q) <= numQuestions && v));
    onSave({
      name: name.trim(),
      template_id: templateId,
      marks_correct: marksNum.correct,
      marks_wrong: marksNum.wrong,
      marks_blank: marksNum.blank,
      keys: { A: clean(sets.A), B: clean(sets.B), C: clean(sets.C) },
    });
  };

  return (
    <form className="card key-editor" onSubmit={submit} aria-labelledby={`${uid}-title`} noValidate>
      <h2 id={`${uid}-title`} className="card__title">
        {initial ? `Edit “${initial.name}”` : 'New answer key'}
      </h2>

      <div className="form-row">
        <label className="field field--grow">
          <span className="field__label">Name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} required aria-invalid={submitted && !name.trim()} placeholder="e.g. Midterm 2026 · Grade 7" />
        </label>
        <label className="field">
          <span className="field__label">Template</span>
          <select value={templateId} onChange={(e) => setTemplateId(e.target.value)} required>
            {templates.length === 0 && <option value="">No templates</option>}
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name || t.id}
              </option>
            ))}
          </select>
        </label>
      </div>

      <fieldset className="form-row marks">
        <legend className="field__label">Marking scheme</legend>
        {(
          [
            ['correct', 'Correct'],
            ['wrong', 'Wrong / multiple'],
            ['blank', 'Blank'],
          ] as const
        ).map(([k, label]) => (
          <label key={k} className="field field--marks">
            <span className="field__label">{label}</span>
            <input
              type="number"
              step="any"
              inputMode="decimal"
              value={marks[k]}
              onChange={(e) => setMarks((m) => ({ ...m, [k]: e.target.value }))}
              aria-invalid={marksError.includes(k)}
            />
          </label>
        ))}
        <p className="field__hint marks__hint">Negative values are allowed (e.g. −1 for a wrong answer). Multiple marks count as wrong.</p>
      </fieldset>

      <div className="tabs" role="tablist" aria-label="Paper set">
        {PAPER_SETS.map((s) => (
          <button
            key={s}
            type="button"
            role="tab"
            id={`${uid}-tab-${s}`}
            aria-selected={active === s}
            aria-controls={`${uid}-panel`}
            tabIndex={active === s ? 0 : -1}
            className="tab"
            onClick={() => setActive(s)}
            onKeyDown={(e) => {
              const i = PAPER_SETS.indexOf(active);
              if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
                e.preventDefault();
                const next = PAPER_SETS[(i + (e.key === 'ArrowRight' ? 1 : PAPER_SETS.length - 1)) % PAPER_SETS.length];
                setActive(next);
                document.getElementById(`${uid}-tab-${next}`)?.focus();
              }
            }}
          >
            Set {s}{' '}
            <span className={`tab__count${counts[s] === numQuestions ? ' tab__count--full' : ''}`}>
              {counts[s]}/{numQuestions}
            </span>
          </button>
        ))}
      </div>

      <div id={`${uid}-panel`} role="tabpanel" aria-labelledby={`${uid}-tab-${active}`} className="tabpanel">
        <div className="paste">
          <label className="field">
            <span className="field__label">Paste answers for set {active}</span>
            <textarea
              rows={3}
              value={paste}
              onChange={(e) => setPaste(e.target.value)}
              placeholder={'ABCDDCBA…  or  1-A, 2-B, 3-C  or one answer per line ("-" = blank)'}
              aria-describedby={`${uid}-paste-fb`}
              spellCheck={false}
              className="mono"
            />
          </label>
          <div id={`${uid}-paste-fb`} className="paste__fb" aria-live="polite">
            {parsed && (
              <>
                <p className={parsed.errors.length ? 'text-bad' : 'text-good'}>
                  {parsed.errors.length
                    ? 'Cannot apply:'
                    : `Recognised ${parsed.format} format · ${countAnswered(parsed.answers, numQuestions)} answers`}
                </p>
                {parsed.errors.length > 0 && (
                  <ul className="text-bad">
                    {parsed.errors.map((e) => (
                      <li key={e}>{e}</li>
                    ))}
                  </ul>
                )}
                {parsed.warnings.length > 0 && (
                  <ul className="text-warn">
                    {parsed.warnings.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </div>
          <div className="paste__actions">
            <button type="button" className="btn btn--sm" onClick={applyPaste} disabled={!parsed || parsed.errors.length > 0}>
              Apply to set {active} (replaces it)
            </button>
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={() => setPaste(answersToString(sets[active], numQuestions))}
              title="Load the current set as a compact string"
            >
              Load current as text
            </button>
            {PAPER_SETS.filter((s) => s !== active).map((s) => (
              <button
                key={s}
                type="button"
                className="btn btn--ghost btn--sm"
                disabled={counts[s] === 0}
                onClick={() => {
                  if (counts[active] > 0 && !window.confirm(`Replace set ${active} with a copy of set ${s}?`)) return;
                  setSets((cur) => ({ ...cur, [active]: { ...cur[s] } }));
                }}
              >
                Copy from {s}
              </button>
            ))}
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              disabled={counts[active] === 0}
              onClick={() => {
                if (window.confirm(`Clear all answers in set ${active}?`)) setSets((cur) => ({ ...cur, [active]: {} }));
              }}
            >
              Clear set
            </button>
          </div>
        </div>

        <KeyGrid numQuestions={numQuestions} options={options} answers={sets[active]} onChange={setAnswer} setLabel={active} />
      </div>

      {submitted && errors.length > 0 && (
        <div className="notice notice--bad" role="alert">
          <ul>
            {errors.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </div>
      )}
      {partial.length > 0 && (
        <p className="notice notice--warn">
          Set{partial.length > 1 ? 's' : ''} {partial.join(', ')} {partial.length > 1 ? 'are' : 'is'} incomplete; unanswered questions are graded as “no key”.
        </p>
      )}

      <div className="form-actions form-actions--sticky">
        <button type="button" className="btn" onClick={onCancel} disabled={saving}>
          Cancel
        </button>
        <button type="submit" className="btn btn--primary" disabled={saving}>
          {saving ? 'Saving…' : initial ? 'Save changes' : 'Create answer key'}
        </button>
      </div>
    </form>
  );
}
