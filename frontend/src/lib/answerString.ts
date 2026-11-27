/**
 * Parse a pasted answer-key string into {"1": "A", ...}.
 *
 * Accepted formats (case-insensitive):
 *  - compact:  "ABCDDCBA..."  (whitespace / commas / | ignored; "-", "_", ".", "?", "*" = blank)
 *  - numbered: "1-A, 2-B" / "1:A 2:B" / "1.A" / "1) A" / "1=A" / "1 A", separated by commas,
 *              semicolons, new lines or spaces. A number with no letter ("3-") = blank.
 *  - lines:    one answer per line ("A\nB\n\nD"); an empty line or "-" = blank.
 *
 * Blank questions are omitted from `answers`.
 */

export type AnswerStringFormat = 'empty' | 'compact' | 'numbered' | 'lines';

export interface ParsedAnswers {
  format: AnswerStringFormat;
  answers: Record<string, string>;
  /** Number of questions the input covered (including blanks). */
  covered: number;
  errors: string[];
  warnings: string[];
}

const BLANK_CHARS = new Set(['-', '_', '.', '?', '*']);

export function parseAnswerString(
  input: string,
  numQuestions = 80,
  options: readonly string[] = ['A', 'B', 'C', 'D'],
): ParsedAnswers {
  const opts = new Set(options.map((o) => o.toUpperCase()));
  const text = input.replace(/\r\n?/g, '\n').trim();
  const result: ParsedAnswers = { format: 'empty', answers: {}, covered: 0, errors: [], warnings: [] };
  if (!text) return result;

  if (/\d/.test(text)) {
    result.format = 'numbered';
    parseNumbered(text, numQuestions, opts, result);
  } else {
    const lines = text.split('\n').map((l) => l.trim());
    const isLines = lines.length > 1 && lines.every((l) => l.replace(/[\s,;|]/g, '').length <= 1);
    if (isLines) {
      result.format = 'lines';
      parseSequence(lines.map((l) => l.replace(/[\s,;|]/g, '')), numQuestions, opts, result, 'line');
    } else {
      result.format = 'compact';
      const chars = Array.from(text.replace(/[\s,;|]/g, ''));
      parseSequence(chars, numQuestions, opts, result, 'position');
    }
  }
  return result;
}

function parseSequence(
  tokens: string[],
  n: number,
  opts: Set<string>,
  out: ParsedAnswers,
  unit: 'position' | 'line',
) {
  const bad: string[] = [];
  tokens.forEach((raw, i) => {
    const q = i + 1;
    const t = raw.toUpperCase();
    if (t === '' || BLANK_CHARS.has(t)) return;
    if (!opts.has(t)) {
      bad.push(`${unit} ${q}: "${raw}"`);
      return;
    }
    if (q <= n) out.answers[String(q)] = t;
  });
  if (bad.length) {
    out.errors.push(
      `Invalid option${bad.length > 1 ? 's' : ''} at ${bad.slice(0, 5).join(', ')}${bad.length > 5 ? ` and ${bad.length - 5} more` : ''}. Use ${[...opts].join('/')} or "-" for blank.`,
    );
  }
  out.covered = Math.min(tokens.length, n);
  if (tokens.length > n) {
    out.errors.push(`Too many answers: got ${tokens.length}, the template has ${n} questions.`);
  } else if (tokens.length < n) {
    out.warnings.push(`Only ${tokens.length} of ${n} questions given; questions ${tokens.length + 1}–${n} will be blank.`);
  }
}

function parseNumbered(text: string, n: number, opts: Set<string>, out: ParsedAnswers) {
  // Each entry: number, optional separator, optional single letter or blank marker.
  const re = /[Qq]?(\d+)\s*(?:[-:.)=]\s*)?([A-Za-z]+|[-_?*])?/g;
  const seen = new Map<number, number>();
  const outOfRange: number[] = [];
  const badLetters: string[] = [];
  let leftover = '';
  let cursor = 0;
  let m: RegExpExecArray | null;
  let count = 0;
  while ((m = re.exec(text)) !== null) {
    leftover += text.slice(cursor, m.index);
    cursor = m.index + m[0].length;
    count += 1;
    const q = Number(m[1]);
    const letterRaw = m[2] ?? '';
    const letter = letterRaw.toUpperCase();
    if (q < 1 || q > n) {
      outOfRange.push(q);
      continue;
    }
    seen.set(q, (seen.get(q) ?? 0) + 1);
    if (letter === '' || BLANK_CHARS.has(letter)) {
      delete out.answers[String(q)];
      continue;
    }
    if (!opts.has(letter)) {
      badLetters.push(`Q${q}: "${letterRaw}"`);
      continue;
    }
    out.answers[String(q)] = letter;
  }
  leftover += text.slice(cursor);
  const junk = leftover.replace(/[\s,;|\n]/g, '');
  if (junk) out.errors.push(`Could not understand: "${junk.slice(0, 30)}${junk.length > 30 ? '…' : ''}".`);
  if (count === 0) out.errors.push('No "number-letter" pairs found.');
  if (outOfRange.length) {
    out.errors.push(`Question number${outOfRange.length > 1 ? 's' : ''} out of range (1–${n}): ${outOfRange.slice(0, 8).join(', ')}.`);
  }
  if (badLetters.length) {
    out.errors.push(`Invalid option${badLetters.length > 1 ? 's' : ''}: ${badLetters.slice(0, 5).join(', ')}. Use ${[...opts].join('/')}.`);
  }
  const dups = [...seen.entries()].filter(([, c]) => c > 1).map(([q]) => q);
  if (dups.length) out.warnings.push(`Question${dups.length > 1 ? 's' : ''} listed more than once (last one wins): ${dups.slice(0, 8).join(', ')}.`);
  out.covered = seen.size;
  const missing = n - seen.size;
  if (missing > 0 && out.errors.length === 0) out.warnings.push(`${missing} question${missing > 1 ? 's' : ''} not listed; they will be blank.`);
}

/** Inverse of the compact format: "AB-D..." with "-" for blanks. */
export function answersToString(answers: Record<string, string>, numQuestions = 80): string {
  let s = '';
  for (let q = 1; q <= numQuestions; q++) s += answers[String(q)] || '-';
  return s;
}

export function countAnswered(answers: Record<string, string> | undefined, numQuestions = 80): number {
  if (!answers) return 0;
  let c = 0;
  for (let q = 1; q <= numQuestions; q++) if (answers[String(q)]) c++;
  return c;
}
