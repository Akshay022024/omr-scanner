"""Apply manual reviewer corrections to a ScanResult."""

from __future__ import annotations

import re

from omr_engine import FieldResult, ScanResult, Template
from omr_engine.models import FieldState

from .schemas import ScanCorrection

_ROLL_RE = re.compile(r"^[0-9?*]+$")
_SEPARATORS = re.compile(r"[\s,;/]+")


def _state_for(value: str) -> FieldState:
    return "blank" if value == "" else "single" if len(value) == 1 else "multiple"


def _normalise_answer(raw: str, options: list[str]) -> str:
    letters = set(_SEPARATORS.sub("", raw.upper()))
    unknown = letters - set(options)
    if unknown:
        raise ValueError(f"answer {raw!r} contains letters outside {options}")
    return "".join(o for o in options if o in letters)


def apply_correction(result: ScanResult, correction: ScanCorrection, tpl: Template) -> ScanResult:
    """Return a corrected copy. Raises ValueError on invalid input.

    Corrected fields get confidence 1.0 and their review flags are removed. A PATCH means a human
    reviewed the sheet, so the low-registration-quality flag is cleared too. Failed scans stay
    failed (their reading is not trusted) but still carry the corrected values.
    """
    res = result.model_copy(deep=True)
    fields: dict[str, FieldResult] = {f.id: f for f in res.fields}
    cleared: set[str] = set()
    provided = correction.model_fields_set

    if "answers" in provided and correction.answers is not None:
        by_question = {str(f.question): f for f in tpl.fields_in("answers")}
        for q, raw in correction.answers.items():
            field = by_question.get(q.strip())
            if field is None:
                raise ValueError(f"unknown question {q!r}")
            value = _normalise_answer(raw, [b.value for b in field.bubbles])
            res.answers[str(field.question)] = value
            if field.id in fields:
                fields[field.id].value, fields[field.id].state, fields[field.id].confidence = value, _state_for(value), 1.0
            cleared.add(field.id)

    if "roll_no" in provided and correction.roll_no is not None:
        roll_fields = tpl.fields_in("roll_no")
        roll = correction.roll_no.strip()
        if len(roll) != len(roll_fields) or not _ROLL_RE.match(roll):
            raise ValueError(f"roll_no must be {len(roll_fields)} characters of 0-9, '?' or '*'")
        res.roll_no = roll
        for field, ch in zip(roll_fields, roll, strict=True):
            if field.id in fields:
                fr = fields[field.id]
                if ch.isdigit():
                    fr.value, fr.state = ch, "single"
                elif ch == "?":
                    fr.value, fr.state = "", "blank"
                else:
                    fr.state = "multiple"
                fr.confidence = 1.0
            cleared.add(field.id)

    if "paper_set" in provided:
        sets = tpl.paper_sets
        value = correction.paper_set.strip().upper() if correction.paper_set else None
        if value is not None and value not in sets:
            raise ValueError(f"paper_set must be one of {sets} or null")
        res.paper_set = value
        for field in tpl.fields_in("paper_set"):
            if field.id in fields:
                fr = fields[field.id]
                fr.value, fr.state, fr.confidence = value or "", "single" if value else "blank", 1.0
            cleared.add(field.id)

    if cleared:
        res.review_flags = [
            f for f in res.review_flags if f.split(":", 1)[0] not in cleared and f != "registration:low_quality"
        ]
        if res.status != "failed":
            res.status = "needs_review" if res.review_flags else "ok"
    return res
