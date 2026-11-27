import { describe, expect, it } from 'vitest';
import type { FieldResult, TemplateField } from '../api/types';
import { bubbleKind, cellKind, describeFlag, draftValueFor, fieldBounds, parseFlag } from './overlay';

const field = (state: FieldResult['state'], value: string, id = 'q3'): FieldResult => ({ id, group: 'answers', question: 3, state, value });

describe('bubbleKind', () => {
  it('marks a single selection green when ungraded', () => {
    const f = field('single', 'B');
    expect(bubbleKind('B', { field: f })).toBe('selected');
    expect(bubbleKind('A', { field: f })).toBe('unmarked');
  });

  it('uses grade for single selections', () => {
    expect(bubbleKind('B', { field: field('single', 'B'), grade: 'correct', expected: 'B' })).toBe('correct');
    expect(bubbleKind('B', { field: field('single', 'B'), grade: 'wrong', expected: 'C' })).toBe('wrong');
  });

  it('shows the expected answer when wrong or blank', () => {
    expect(bubbleKind('C', { field: field('single', 'B'), grade: 'wrong', expected: 'C' })).toBe('expected');
    expect(bubbleKind('C', { field: field('blank', ''), grade: 'blank', expected: 'C' })).toBe('expected');
    expect(bubbleKind('A', { field: field('blank', ''), grade: 'blank', expected: 'C' })).toBe('blank');
  });

  it('does not show expected without a grade or when there is no key', () => {
    expect(bubbleKind('C', { field: field('single', 'B'), expected: 'C' })).toBe('unmarked');
    expect(bubbleKind('C', { field: field('single', 'B'), grade: 'no_key', expected: 'C' })).toBe('unmarked');
  });

  it('colours every mark of a multiple field red', () => {
    const f = field('multiple', 'AC');
    expect(bubbleKind('A', { field: f })).toBe('multiple');
    expect(bubbleKind('C', { field: f, grade: 'multiple' })).toBe('multiple');
    expect(bubbleKind('B', { field: f })).toBe('unmarked');
  });

  it('colours ambiguous fields amber', () => {
    const f = field('ambiguous', 'D');
    expect(bubbleKind('D', { field: f })).toBe('ambiguous');
    expect(bubbleKind('A', { field: f })).toBe('ambiguous-open');
  });

  it('gives blank fields a subtle outline', () => {
    expect(bubbleKind('A', { field: field('blank', '') })).toBe('blank');
  });

  it('lets user edits win over detection', () => {
    const f = field('multiple', 'AC');
    expect(bubbleKind('B', { field: f, draftValue: 'B' })).toBe('edited');
    expect(bubbleKind('A', { field: f, draftValue: 'B' })).toBe('unmarked');
    expect(bubbleKind('A', { field: f, draftValue: '' })).toBe('blank');
    // a draft equal to the detected value is not an edit
    expect(bubbleKind('A', { field: field('single', 'A'), draftValue: 'A' })).toBe('selected');
  });

  it('handles missing field results', () => {
    expect(bubbleKind('A', {})).toBe('unmarked');
  });
});

describe('cellKind', () => {
  it('prefers edit, then ambiguity, then grade', () => {
    expect(cellKind(field('single', 'A'), 'B', 'correct')).toBe('edited');
    expect(cellKind(field('ambiguous', 'A'), undefined, 'correct')).toBe('ambiguous');
    expect(cellKind(field('single', 'A'), undefined, 'wrong')).toBe('wrong');
    expect(cellKind(field('single', 'A'), undefined, 'no_key')).toBe('no_key');
  });
  it('falls back to detection state without a grade', () => {
    expect(cellKind(field('single', 'A'), undefined)).toBe('answered');
    expect(cellKind(field('multiple', 'AB'), undefined)).toBe('multiple');
    expect(cellKind(field('blank', ''), undefined)).toBe('blank');
    expect(cellKind(undefined, undefined)).toBe('blank');
  });
});

describe('flags', () => {
  it('parses question and roll flags', () => {
    expect(parseFlag('q3:multiple')).toEqual({ raw: 'q3:multiple', fieldId: 'q3', reason: 'multiple', question: 3 });
    expect(parseFlag('roll_6:blank')).toMatchObject({ fieldId: 'roll_6', reason: 'blank', question: null });
    expect(parseFlag('registration')).toMatchObject({ fieldId: 'registration', reason: '' });
  });
  it('describes flags for humans', () => {
    expect(describeFlag(parseFlag('q12:ambiguous'))).toBe('Q12: ambiguous');
    expect(describeFlag(parseFlag('roll_6:blank'))).toBe('Roll digit 6: blank');
    expect(describeFlag(parseFlag('paper_set:multiple'))).toBe('Paper set: multiple');
    expect(describeFlag(parseFlag('registration:low_quality'))).toBe('Registration: low quality');
  });
});

describe('draftValueFor', () => {
  const q: TemplateField = { id: 'q5', group: 'answers', question: 5, bubbles: [] };
  const roll: TemplateField = { id: 'roll_3', group: 'roll_no', bubbles: [] };
  const set: TemplateField = { id: 'paper_set', group: 'paper_set', bubbles: [] };
  it('maps draft answers, roll digits and paper set', () => {
    const draft = { answers: { '5': 'C' }, roll_no: '12?4', paper_set: 'B' };
    expect(draftValueFor(q, draft)).toBe('C');
    expect(draftValueFor(roll, draft)).toBe(''); // "?" in the draft = no digit
    expect(draftValueFor({ ...roll, id: 'roll_2' }, draft)).toBe('2');
    expect(draftValueFor(set, draft)).toBe('B');
  });
  it('returns undefined when not edited', () => {
    const draft = { answers: {} };
    expect(draftValueFor(q, draft)).toBeUndefined();
    expect(draftValueFor(roll, draft)).toBeUndefined();
    expect(draftValueFor(set, draft)).toBeUndefined();
  });
});

describe('fieldBounds', () => {
  it('computes a padded bounding box', () => {
    const f: TemplateField = {
      id: 'q1',
      group: 'answers',
      bubbles: [
        { value: 'A', x: 100, y: 200, r: 10 },
        { value: 'D', x: 220, y: 200, r: 10 },
      ],
    };
    expect(fieldBounds(f, 5)).toEqual({ x: 85, y: 185, w: 150, h: 30 });
  });
});
