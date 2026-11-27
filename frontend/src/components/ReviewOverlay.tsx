import { memo } from 'react';
import type { FieldResult, QuestionGrade, TemplateField } from '../api/types';
import { bubbleKind, draftValueFor, fieldBounds, type ReviewDraft } from '../lib/overlay';

interface Props {
  fields: TemplateField[];
  resultById: Map<string, FieldResult>;
  draft: ReviewDraft;
  perQuestion?: Record<string, QuestionGrade>;
  expected?: Record<string, string>;
  selectedFieldId?: string | null;
  highlightFieldId?: string | null;
  onSelectField?: (field: TemplateField) => void;
}

/** SVG content (template px coordinates) drawn on top of the aligned image. */
export const ReviewOverlay = memo(function ReviewOverlay({
  fields,
  resultById,
  draft,
  perQuestion,
  expected,
  selectedFieldId,
  highlightFieldId,
  onSelectField,
}: Props) {
  return (
    <g className="overlay">
      {fields.map((f) => {
        const res = resultById.get(f.id);
        const q = f.question !== undefined ? String(f.question) : undefined;
        const ctx = {
          field: res,
          draftValue: draftValueFor(f, draft),
          grade: q ? perQuestion?.[q] : undefined,
          expected: q ? expected?.[q] : undefined,
        };
        const selected = f.id === selectedFieldId;
        const highlighted = f.id === highlightFieldId;
        const box = selected || highlighted ? fieldBounds(f, 8) : null;
        const label = q ? `Q${q}` : f.id === 'paper_set' ? 'Paper set' : f.id.replace('roll_', 'Roll digit ');
        return (
          <g
            key={f.id}
            className={`ofield${res?.state ? ` ofield--${res.state}` : ''}`}
            onClick={onSelectField ? () => onSelectField(f) : undefined}
          >
            {box && (
              <rect
                className={`ofield__box${highlighted ? ' ofield__box--flag' : ''}${selected ? ' ofield__box--selected' : ''}`}
                x={box.x}
                y={box.y}
                width={box.w}
                height={box.h}
                rx={10}
              />
            )}
            {f.bubbles.map((b) => {
              const kind = bubbleKind(b.value, ctx);
              const score = res?.scores?.[b.value];
              return (
                <circle key={b.value} className={`bubble bubble--${kind}`} cx={b.x} cy={b.y} r={b.r}>
                  <title>
                    {`${label} ${b.value}: ${kind.replace('-', ' ')}${typeof score === 'number' ? ` · fill ${(score * 100).toFixed(0)}%` : ''}`}
                  </title>
                </circle>
              );
            })}
          </g>
        );
      })}
    </g>
  );
});
