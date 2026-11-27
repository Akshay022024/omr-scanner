import type { AnswerKey, GradeResult, QuestionGrade } from '../api/types';

/**
 * Client-side mirror of the engine's grading rules (ARCHITECTURE.md §5 step 8): used by the
 * mock API only. The backend's GradeResult is always authoritative.
 */
export function gradeAnswers(
  answers: Record<string, string>,
  paperSet: string | null | undefined,
  key: AnswerKey,
  numQuestions = 80,
): GradeResult {
  const sets = Object.keys(key.keys).filter((s) => Object.keys(key.keys[s as 'A'] ?? {}).length > 0);
  const setUsed = paperSet && key.keys[paperSet as 'A'] ? paperSet : sets.length === 1 ? sets[0] : null;
  const setKey = setUsed ? key.keys[setUsed as 'A'] ?? {} : {};
  const per: Record<string, QuestionGrade> = {};
  let correct = 0;
  let wrong = 0;
  let blank = 0;
  let multiple = 0;
  let keyed = 0;
  for (let q = 1; q <= numQuestions; q++) {
    const k = setKey[String(q)];
    const v = answers[String(q)] ?? '';
    let g: QuestionGrade;
    if (!k) g = 'no_key';
    else if (v === '') g = 'blank';
    else if (v.length > 1) g = 'multiple';
    else g = v === k ? 'correct' : 'wrong';
    per[String(q)] = g;
    if (k) keyed++;
    if (g === 'correct') correct++;
    else if (g === 'wrong') wrong++;
    else if (g === 'blank') blank++;
    else if (g === 'multiple') multiple++;
  }
  const score = correct * key.marks_correct + (wrong + multiple) * key.marks_wrong + blank * key.marks_blank;
  return {
    answer_key_id: key.id,
    paper_set_used: setUsed,
    score: Math.round(score * 100) / 100,
    max_score: keyed * key.marks_correct,
    correct,
    wrong,
    blank,
    multiple,
    per_question: per,
  };
}
