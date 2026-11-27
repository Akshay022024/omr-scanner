"""Conversions between database rows and API/engine models."""

from __future__ import annotations

import json
from typing import Any

from omr_engine import AnswerKey, GradeResult, ScanResult, Template, grade

from .db import Database
from .schemas import AnswerKeyIn, AnswerKeyOut, BatchSummary, ScanRecord


def validate_keys(payload: AnswerKeyIn, tpl: Template) -> dict[str, dict[str, str]]:
    """Normalise answer-key letters and check them against the template. Raises ValueError."""
    allowed_sets = set(tpl.paper_sets) or {"A"}
    options = set(tpl.spec.options)
    keys: dict[str, dict[str, str]] = {}
    for paper_set, answers in payload.keys.items():
        s = paper_set.strip().upper()
        if s not in allowed_sets:
            raise ValueError(f"paper set {paper_set!r} is not one of {sorted(allowed_sets)}")
        normalised: dict[str, str] = {}
        for q, a in answers.items():
            q_clean = q.strip()
            if not q_clean.isdigit() or not 1 <= int(q_clean) <= tpl.spec.num_questions:
                raise ValueError(f"question {q!r} is outside 1..{tpl.spec.num_questions}")
            letter = a.strip().upper()
            if letter == "":
                continue
            if letter not in options:
                raise ValueError(f"answer {a!r} for question {q_clean} is not one of {sorted(options)}")
            normalised[str(int(q_clean))] = letter
        keys[s] = normalised
    if not keys:
        raise ValueError("answer key needs at least one paper set")
    return keys


def answer_key_model(row: dict[str, Any]) -> AnswerKey:
    return AnswerKey(
        id=row["id"],
        name=row["name"],
        template_id=row["template_id"],
        keys=json.loads(row["keys_json"]),
        marks_correct=row["marks_correct"],
        marks_wrong=row["marks_wrong"],
        marks_blank=row["marks_blank"],
    )


def answer_key_out(row: dict[str, Any]) -> AnswerKeyOut:
    key = answer_key_model(row)
    return AnswerKeyOut(**key.model_dump(), created_at=row["created_at"], updated_at=row["updated_at"])


def grade_with(db: Database, result: ScanResult, answer_key_id: str | None) -> GradeResult | None:
    if not answer_key_id:
        return None
    row = db.get_answer_key(answer_key_id)
    return grade(result, answer_key_model(row)) if row else None


def scan_record(row: dict[str, Any]) -> ScanRecord:
    return ScanRecord(
        id=row["id"],
        batch_id=row["batch_id"],
        filename=row["filename"],
        page=row["page"],
        created_at=row["created_at"],
        answer_key_id=row["answer_key_id"],
        result=ScanResult.model_validate_json(row["result_json"]),
        grade=GradeResult.model_validate_json(row["grade_json"]) if row["grade_json"] else None,
        corrected=bool(row["corrected"]),
    )


def batch_summary(row: dict[str, Any], scans: list[ScanRecord]) -> BatchSummary:
    counts = {"ok": 0, "needs_review": 0, "failed": 0}
    for s in scans:
        counts[s.result.status] += 1
    scores = [s.grade.score for s in scans if s.grade is not None]
    return BatchSummary(
        id=row["id"],
        template_id=row["template_id"],
        answer_key_id=row["answer_key_id"],
        created_at=row["created_at"],
        scan_count=len(scans),
        status_counts=counts,
        corrected_count=sum(1 for s in scans if s.corrected),
        mean_score=round(sum(scores) / len(scores), 4) if scores else None,
    )
