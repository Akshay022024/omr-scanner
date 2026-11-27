import { describe, expect, it } from 'vitest';
import { answersToString, countAnswered, parseAnswerString } from './answerString';

describe('parseAnswerString', () => {
  it('returns empty for blank input', () => {
    const r = parseAnswerString('   ');
    expect(r.format).toBe('empty');
    expect(r.answers).toEqual({});
    expect(r.errors).toEqual([]);
  });

  it('parses a compact string, case-insensitive, ignoring whitespace', () => {
    const r = parseAnswerString('abcd DCBA', 8);
    expect(r.format).toBe('compact');
    expect(r.errors).toEqual([]);
    expect(r.answers).toEqual({ 1: 'A', 2: 'B', 3: 'C', 4: 'D', 5: 'D', 6: 'C', 7: 'B', 8: 'A' });
    expect(r.covered).toBe(8);
  });

  it('treats blank markers as blank in compact strings', () => {
    const r = parseAnswerString('A-B_C.D?', 8);
    expect(r.errors).toEqual([]);
    expect(r.answers).toEqual({ 1: 'A', 3: 'B', 5: 'C', 7: 'D' });
  });

  it('warns when fewer answers than questions', () => {
    const r = parseAnswerString('ABCD', 80);
    expect(r.errors).toEqual([]);
    expect(r.warnings[0]).toMatch(/Only 4 of 80/);
  });

  it('errors on too many answers', () => {
    const r = parseAnswerString('ABCDA', 4);
    expect(r.errors.join(' ')).toMatch(/Too many answers: got 5/);
  });

  it('errors on invalid letters with their position', () => {
    const r = parseAnswerString('ABXD', 4);
    expect(r.errors[0]).toMatch(/position 3: "X"/);
    expect(r.answers).toEqual({ 1: 'A', 2: 'B', 4: 'D' });
  });

  it('parses a full 80-question compact key', () => {
    const s = 'ABCD'.repeat(20);
    const r = parseAnswerString(s, 80);
    expect(r.errors).toEqual([]);
    expect(r.warnings).toEqual([]);
    expect(countAnswered(r.answers, 80)).toBe(80);
    expect(r.answers['80']).toBe('D');
  });

  it('parses numbered pairs with various separators', () => {
    const r = parseAnswerString('1-A, 2:b; 3.C\n4) D 5=a 6 B', 6);
    expect(r.format).toBe('numbered');
    expect(r.errors).toEqual([]);
    expect(r.answers).toEqual({ 1: 'A', 2: 'B', 3: 'C', 4: 'D', 5: 'A', 6: 'B' });
    expect(r.warnings).toEqual([]);
  });

  it('accepts a Q prefix and number-only entries as blank', () => {
    const r = parseAnswerString('Q1-A, Q2-, 3-B', 3);
    expect(r.errors).toEqual([]);
    expect(r.answers).toEqual({ 1: 'A', 3: 'B' });
  });

  it('reports out-of-range numbers, invalid options and duplicates', () => {
    const r = parseAnswerString('0-A, 81-B, 5-E, 2-A, 2-C', 80);
    expect(r.errors.join(' ')).toMatch(/out of range.*0, 81/);
    expect(r.errors.join(' ')).toMatch(/Q5: "E"/);
    expect(r.warnings.join(' ')).toMatch(/more than once.*2/);
    expect(r.answers['2']).toBe('C');
  });

  it('flags unparseable junk in numbered mode', () => {
    const r = parseAnswerString('1-A, hello 2-B', 80);
    expect(r.errors.join(' ')).toMatch(/Could not understand/);
  });

  it('warns about missing questions in numbered mode', () => {
    const r = parseAnswerString('1-A,2-B', 80);
    expect(r.errors).toEqual([]);
    expect(r.warnings.join(' ')).toMatch(/78 questions not listed/);
  });

  it('parses one answer per line, keeping empty lines as blanks', () => {
    const r = parseAnswerString('A\nb\n\n-\nD', 5);
    expect(r.format).toBe('lines');
    expect(r.errors).toEqual([]);
    expect(r.answers).toEqual({ 1: 'A', 2: 'B', 5: 'D' });
    expect(r.covered).toBe(5);
  });

  it('handles CRLF line endings', () => {
    const r = parseAnswerString('A\r\nB\r\nC', 3);
    expect(r.format).toBe('lines');
    expect(r.answers).toEqual({ 1: 'A', 2: 'B', 3: 'C' });
  });

  it('treats multi-letter lines as compact text', () => {
    const r = parseAnswerString('ABCD\nDCBA', 8);
    expect(r.format).toBe('compact');
    expect(r.answers['5']).toBe('D');
  });

  it('respects custom options', () => {
    const r = parseAnswerString('ABCE', 4, ['A', 'B', 'C', 'D', 'E']);
    expect(r.errors).toEqual([]);
    expect(r.answers['4']).toBe('E');
  });
});

describe('answersToString', () => {
  it('round-trips with the compact parser', () => {
    const answers = { 1: 'A', 2: 'C', 4: 'D' } as Record<string, string>;
    const s = answersToString(answers, 5);
    expect(s).toBe('AC-D-');
    expect(parseAnswerString(s, 5).answers).toEqual(answers);
  });
});
