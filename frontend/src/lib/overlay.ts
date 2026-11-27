import type { FieldResult, QuestionGrade, TemplateField } from '../api/types';

/**
 * Visual state of one bubble in the review overlay. Colours are applied in CSS
 * (`.bubble--<kind>`) so they follow the light/dark theme.
 */
export type BubbleKind =
  | 'selected' // marked, single, no grade available
  | 'correct' // marked and graded correct
  | 'wrong' // marked (single) and graded wrong
  | 'multiple' // one of several marks in a multiple field
  | 'ambiguous' // marked but near the threshold
  | 'ambiguous-open' // unmarked bubble in an ambiguous field
  | 'blank' // bubble in a field with no marks
  | 'expected' // the key's answer, shown when the student got it wrong / left it blank
  | 'edited' // user's manual correction (not yet saved or saved as a correction)
  | 'unmarked'; // unmarked bubble in an otherwise decided field

export interface BubbleContext {
  field?: FieldResult;
  /** Effective value after manual edits; undefined when the user has not touched this field. */
  draftValue?: string;
  grade?: QuestionGrade;
  /** The answer key's value for this question, when known. */
  expected?: string;
}

export function isEdited(ctx: BubbleContext): boolean {
  return ctx.draftValue !== undefined && ctx.draftValue !== (ctx.field?.value ?? '');
}

export function bubbleKind(bubbleValue: string, ctx: BubbleContext): BubbleKind {
  const showExpected =
    !!ctx.expected && ctx.expected.includes(bubbleValue) && ctx.grade !== undefined && ctx.grade !== 'correct' && ctx.grade !== 'no_key';

  if (isEdited(ctx)) {
    const v = ctx.draftValue ?? '';
    if (v.includes(bubbleValue)) return 'edited';
    return v === '' ? 'blank' : 'unmarked';
  }

  const field = ctx.field;
  if (!field) return 'unmarked';
  const marked = field.value.includes(bubbleValue);

  switch (field.state) {
    case 'blank':
      return showExpected ? 'expected' : 'blank';
    case 'multiple':
      if (marked) return 'multiple';
      return showExpected ? 'expected' : 'unmarked';
    case 'ambiguous':
      return marked ? 'ambiguous' : 'ambiguous-open';
    case 'single':
    default:
      if (marked) {
        if (ctx.grade === 'correct') return 'correct';
        if (ctx.grade === 'wrong') return 'wrong';
        return 'selected';
      }
      return showExpected ? 'expected' : 'unmarked';
  }
}

/** Summary state of a question cell in the answer grid. */
export type CellKind = 'correct' | 'wrong' | 'blank' | 'multiple' | 'ambiguous' | 'no_key' | 'answered' | 'edited';

export function cellKind(field: FieldResult | undefined, draftValue: string | undefined, grade?: QuestionGrade): CellKind {
  if (isEdited({ field, draftValue })) return 'edited';
  if (field?.state === 'ambiguous') return 'ambiguous';
  if (grade) {
    if (grade === 'no_key') return 'no_key';
    return grade;
  }
  if (!field) return 'blank';
  if (field.state === 'multiple') return 'multiple';
  if (field.state === 'blank' || field.value === '') return 'blank';
  return 'answered';
}

export interface ParsedFlag {
  raw: string;
  fieldId: string;
  reason: string;
  question: number | null;
}

/** "q3:multiple" → {fieldId:"q3", reason:"multiple", question:3}; "roll_6:blank" → {fieldId:"roll_6", ...}. */
export function parseFlag(flag: string): ParsedFlag {
  const idx = flag.indexOf(':');
  const fieldId = (idx >= 0 ? flag.slice(0, idx) : flag).trim();
  const reason = idx >= 0 ? flag.slice(idx + 1).trim() : '';
  const m = /^q(\d+)$/i.exec(fieldId);
  return { raw: flag, fieldId, reason, question: m ? Number(m[1]) : null };
}

export function describeFlag(f: ParsedFlag): string {
  let what = f.fieldId;
  if (f.question !== null) what = `Q${f.question}`;
  else if (/^roll_(\d+)$/.test(f.fieldId)) what = `Roll digit ${f.fieldId.slice(5)}`;
  else if (f.fieldId === 'paper_set') what = 'Paper set';
  else if (f.fieldId === 'registration') what = 'Registration';
  return f.reason ? `${what}: ${f.reason.replace(/_/g, ' ')}` : what;
}

/** Draft edits on the Review page. Keys present = user has set them. */
export interface ReviewDraft {
  answers: Record<string, string>;
  roll_no?: string;
  paper_set?: string;
}

/** Effective value for a template field under the current draft; undefined = not edited. */
export function draftValueFor(field: TemplateField, draft: ReviewDraft): string | undefined {
  if (field.group === 'answers' && field.question !== undefined) {
    return draft.answers[String(field.question)];
  }
  if (field.group === 'roll_no' && draft.roll_no !== undefined) {
    const m = /(\d+)$/.exec(field.id);
    if (!m) return undefined;
    const ch = draft.roll_no.charAt(Number(m[1]) - 1);
    return /\d/.test(ch) ? ch : '';
  }
  if (field.group === 'paper_set' && draft.paper_set !== undefined) {
    return draft.paper_set;
  }
  return undefined;
}

/** Bounding box (template px) of a field's bubbles, with padding. */
export function fieldBounds(field: TemplateField, pad = 6): { x: number; y: number; w: number; h: number } {
  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  for (const b of field.bubbles) {
    x0 = Math.min(x0, b.x - b.r);
    y0 = Math.min(y0, b.y - b.r);
    x1 = Math.max(x1, b.x + b.r);
    y1 = Math.max(y1, b.y + b.r);
  }
  if (!Number.isFinite(x0)) return { x: 0, y: 0, w: 0, h: 0 };
  return { x: x0 - pad, y: y0 - pad, w: x1 - x0 + 2 * pad, h: y1 - y0 + 2 * pad };
}
