from __future__ import annotations

import cv2
import numpy as np

from omr_engine import EngineConfig
from omr_engine.bubbles import score_bubbles


def _ink_with_disc(cx: float, cy: float, r: float, size: int = 120) -> np.ndarray:
    ink = np.zeros((size, size), np.float32)
    cv2.circle(ink, (int(cx), int(cy)), int(r), 1.0, -1)
    return ink


def test_full_fill_scores_one(cfg: EngineConfig) -> None:
    ink = _ink_with_disc(60, 60, 13)
    s = score_bubbles(ink, np.array([[60.0, 60.0]]), np.array([14.5]), cfg)
    assert s[0] > 0.99


def test_empty_scores_zero(cfg: EngineConfig) -> None:
    s = score_bubbles(np.zeros((120, 120), np.float32), np.array([[60.0, 60.0]]), np.array([14.5]), cfg)
    assert s[0] == 0.0


def test_shift_search_absorbs_misalignment(cfg: EngineConfig) -> None:
    ink = _ink_with_disc(63, 57, 13)  # 3 px off in x and y
    s = score_bubbles(ink, np.array([[60.0, 60.0]]), np.array([14.5]), cfg)
    assert s[0] > 0.99


def test_half_fill_scores_about_half(cfg: EngineConfig) -> None:
    ink = _ink_with_disc(60, 60, 13)
    ink[:, 61:] = 0
    s = score_bubbles(ink, np.array([[60.0, 60.0]]), np.array([14.5]), cfg)
    assert 0.45 < s[0] < 0.75  # the shift search can slide toward the filled half


def test_neighbour_ink_does_not_leak(cfg: EngineConfig) -> None:
    ink = _ink_with_disc(96, 60, 14)  # neighbour bubble 36 px to the right
    s = score_bubbles(ink, np.array([[60.0, 60.0]]), np.array([14.5]), cfg)
    assert s[0] < 0.01


def test_partial_soft_ink(cfg: EngineConfig) -> None:
    ink = _ink_with_disc(60, 60, 13) * 0.6
    s = score_bubbles(ink, np.array([[60.0, 60.0]]), np.array([14.5]), cfg)
    assert abs(s[0] - 0.6) < 0.02
