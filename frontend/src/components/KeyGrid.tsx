import { memo } from 'react';

interface Props {
  numQuestions: number;
  options: readonly string[];
  answers: Record<string, string>;
  onChange: (q: number, value: string) => void;
  setLabel: string;
}

/** Answer-key editor grid: one row per question with an option toggle button per choice. */
export const KeyGrid = memo(function KeyGrid({ numQuestions, options, answers, onChange, setLabel }: Props) {
  const rows = [];
  for (let q = 1; q <= numQuestions; q++) {
    const cur = answers[String(q)] ?? '';
    rows.push(
      <div key={q} className={`krow${cur ? '' : ' krow--empty'}`} role="group" aria-label={`Set ${setLabel}, question ${q}`}>
        <span className="krow__n" aria-hidden="true">
          {q}
        </span>
        {options.map((o) => (
          <button
            key={o}
            type="button"
            className="kopt"
            aria-pressed={cur === o}
            aria-label={`Question ${q} answer ${o}`}
            onClick={() => onChange(q, cur === o ? '' : o)}
          >
            {o}
          </button>
        ))}
      </div>,
    );
  }
  return <div className="kgrid">{rows}</div>;
});
