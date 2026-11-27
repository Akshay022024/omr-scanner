"""Grade a ScanResult against an AnswerKey."""

from __future__ import annotations

from .models import AnswerKey, GradeResult, QuestionOutcome, ScanResult


def _select_paper_set(result: ScanResult, key: AnswerKey) -> str | None:
    """Use the scanned paper set; fall back to the only set in the key when unambiguous."""
    if result.paper_set and result.paper_set in key.keys:
        return result.paper_set
    if len(key.keys) == 1:
        return next(iter(key.keys))
    return None


def grade(result: ScanResult, answer_key: AnswerKey) -> GradeResult:
    """Score answers: multiple marks count as wrong (and are tallied separately)."""
    paper_set = _select_paper_set(result, answer_key)
    keyed = answer_key.keys.get(paper_set, {}) if paper_set else {}
    questions = sorted(set(result.answers) | set(keyed), key=lambda q: (not q.isdigit(), int(q) if q.isdigit() else 0, q))
    per_question: dict[str, QuestionOutcome] = {}
    correct = wrong = blank = multiple = 0
    score = 0.0
    for q in questions:
        expected = keyed.get(q)
        given = result.answers.get(q, "")
        if not expected:
            per_question[q] = "no_key"
            continue
        if given == "":
            per_question[q] = "blank"
            blank += 1
            score += answer_key.marks_blank
        elif len(given) > 1:
            per_question[q] = "multiple"
            multiple += 1
            score += answer_key.marks_wrong
        elif given == expected:
            per_question[q] = "correct"
            correct += 1
            score += answer_key.marks_correct
        else:
            per_question[q] = "wrong"
            wrong += 1
            score += answer_key.marks_wrong
    return GradeResult(
        answer_key_id=answer_key.id,
        paper_set_used=paper_set,
        score=round(score, 4),
        max_score=round(sum(1 for v in keyed.values() if v) * answer_key.marks_correct, 4),
        correct=correct,
        wrong=wrong,
        blank=blank,
        multiple=multiple,
        per_question=per_question,
    )
