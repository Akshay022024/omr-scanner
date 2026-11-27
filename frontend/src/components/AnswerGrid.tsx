import { memo } from 'react';
import type { FieldResult, QuestionGrade } from '../api/types';
import { cellKind, type CellKind } from '../lib/overlay';

const CELL_LABEL: Record<CellKind, string> = {
  correct: 'correct',
  wrong: 'wrong',
  blank: 'blank',
  multiple: 'multiple marks',
  ambiguous: 'ambiguous',
  no_key: 'no key',
  answered: 'answered',
  edited: 'edited',
};

interface Props {
  numQuestions: number;
  fieldsByQ: Map<number, FieldResult>;
  draftAnswers: Record<string, string>;
  perQuestion?: Record<string, QuestionGrade>;
  expected?: Record<string, string>;
  selected: number | null;
  onSelect: (q: number) => void;
}

/** Compact grid of all questions: number, effective answer, grade state. */
export const AnswerGrid = memo(function AnswerGrid({ numQuestions, fieldsByQ, draftAnswers, perQuestion, expected, selected, onSelect }: Props) {
  const cells = [];
  for (let q = 1; q <= numQuestions; q++) {
    const field = fieldsByQ.get(q);
    const draft = draftAnswers[String(q)];
    const grade = perQuestion?.[String(q)];
    const kind = cellKind(field, draft, grade);
    const value = draft !== undefined ? draft : (field?.value ?? '');
    const exp = expected?.[String(q)];
    const showKey = exp && (kind === 'wrong' || kind === 'blank' || kind === 'multiple');
    cells.push(
      <button
        key={q}
        type="button"
        className={`qcell qcell--${kind}`}
        aria-pressed={selected === q}
        aria-label={`Question ${q}: ${value || 'blank'}, ${CELL_LABEL[kind]}${exp ? `, key ${exp}` : ''}`}
        title={`Q${q} · ${CELL_LABEL[kind]}${exp ? ` · key ${exp}` : ''}`}
        onClick={() => onSelect(q)}
        data-q={q}
      >
        <span className="qcell__n">{q}</span>
        <span className="qcell__v">{value || '·'}</span>
        {showKey && <span className="qcell__key">{exp}</span>}
      </button>,
    );
  }
  return (
    <div className="qgrid" role="group" aria-label="Answers">
      {cells}
    </div>
  );
});
