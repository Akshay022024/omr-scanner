from __future__ import annotations

import pytest

from omr_engine import AnswerKey, ScanResult, grade


def _result(answers: dict[str, str], paper_set: str | None = "A") -> ScanResult:
    return ScanResult(template_id="t", status="ok", paper_set=paper_set, answers=answers, aligned_size=(1700, 2200))


def _key(**kwargs: float) -> AnswerKey:
    return AnswerKey(
        id="k1",
        name="Test",
        template_id="t",
        keys={"A": {"1": "A", "2": "B", "3": "C", "4": "D", "5": "A"}, "B": {"1": "D", "2": "D"}},
        **kwargs,
    )


def test_negative_marking_arithmetic() -> None:
    res = _result({"1": "A", "2": "C", "3": "", "4": "AD", "5": "A", "6": "B"})
    g = grade(res, _key(marks_correct=4, marks_wrong=-1, marks_blank=0))
    assert (g.correct, g.wrong, g.blank, g.multiple) == (2, 1, 1, 1)
    assert g.score == pytest.approx(4 + 4 - 1 - 1)  # multiple counts as wrong
    assert g.max_score == pytest.approx(20)
    assert g.per_question["4"] == "multiple"
    assert g.per_question["6"] == "no_key"
    assert g.paper_set_used == "A"


def test_blank_marks_and_set_selection() -> None:
    res = _result({"1": "D", "2": ""}, paper_set="B")
    g = grade(res, _key(marks_correct=1, marks_wrong=-0.25, marks_blank=-0.1))
    assert g.paper_set_used == "B"
    assert g.score == pytest.approx(1 - 0.1)
    assert g.max_score == pytest.approx(2)


def test_unknown_paper_set_with_several_keys_grades_nothing() -> None:
    g = grade(_result({"1": "A"}, paper_set=None), _key())
    assert g.paper_set_used is None
    assert g.score == 0 and g.max_score == 0
    assert g.per_question == {"1": "no_key"}


def test_single_key_used_when_set_missing() -> None:
    key = AnswerKey(id="k", name="n", template_id="t", keys={"a": {"1": "b"}})
    g = grade(_result({"1": "B"}, paper_set=None), key)
    assert key.keys == {"A": {"1": "B"}}  # normalised to upper case
    assert g.paper_set_used == "A" and g.correct == 1
