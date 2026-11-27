from __future__ import annotations

from dataclasses import replace

import pytest

from omr_engine import EngineConfig, Template
from omr_engine.decide import adaptive_threshold, decide_field


def test_threshold_in_gap_between_blanks_and_marks(cfg: EngineConfig) -> None:
    scores = [0.0] * 300 + [0.02, 0.15, 0.2] + [0.78, 0.9, 1.0] * 30
    thr = adaptive_threshold(scores, cfg)
    assert cfg.min_threshold <= thr <= cfg.max_threshold
    assert 0.2 < thr < 0.78


def test_threshold_all_blank_sheet_uses_clamp_range(cfg: EngineConfig) -> None:
    thr = adaptive_threshold([0.0] * 423, cfg)
    assert cfg.min_threshold <= thr <= cfg.max_threshold


def test_threshold_is_clamped(cfg: EngineConfig) -> None:
    # gap between 0.9 and 1.0 only: must still stay within the clamp range
    thr = adaptive_threshold([0.9] * 100 + [1.0] * 100, cfg)
    assert thr == pytest.approx(cfg.max_threshold) or cfg.min_threshold <= thr <= cfg.max_threshold


def test_threshold_otsu_fallback_when_no_gap() -> None:
    cfg = replace(EngineConfig(), min_gap=0.5)
    thr = adaptive_threshold([i / 100 for i in range(101)], cfg)
    assert cfg.min_threshold <= thr <= cfg.max_threshold


@pytest.mark.parametrize(
    ("scores", "state", "value"),
    [
        ([0.0, 0.01, 0.0, 0.02], "blank", ""),
        ([0.0, 0.95, 0.0, 0.01], "single", "B"),
        ([0.9, 0.0, 0.85, 0.0], "multiple", "AC"),
        ([0.0, 0.95, 0.0, 0.37], "ambiguous", "B"),  # D is within the margin below 0.40
        ([0.0, 0.0, 0.42, 0.0], "ambiguous", "C"),
        ([0.0, 0.0, 0.36, 0.0], "ambiguous", ""),
        ([0.2, 0.0, 0.0, 0.0], "blank", ""),  # a tick-sized score far below the threshold
    ],
)
def test_decide_field_states(template: Template, cfg: EngineConfig, scores: list[float], state: str, value: str) -> None:
    field = template.field("q1")
    res = decide_field(field, scores, 0.40, cfg)
    assert res.state == state
    assert res.value == value
    assert res.question == 1
    assert set(res.scores) == {"A", "B", "C", "D"}
    assert 0.0 <= res.confidence <= 1.0


def test_confidence_grows_with_distance(template: Template, cfg: EngineConfig) -> None:
    field = template.field("q1")
    low = decide_field(field, [0.0, 0.55, 0.0, 0.0], 0.40, cfg).confidence
    high = decide_field(field, [0.0, 1.0, 0.0, 0.0], 0.40, cfg).confidence
    assert high > low
