from __future__ import annotations

import cv2
import numpy as np
import pytest

from omr_engine import EngineConfig
from omr_engine.ink import ink_map, normalize_illumination, print_mask, to_hsv
from omr_engine.printcolor import PROFILES, get_profile

PAPER = (250, 250, 250)
MAGENTA = (140, 30, 230)  # BGR
ORANGE = (60, 150, 240)
PENCIL = (87, 88, 97)  # graphite, slightly warm, as measured on the Tamaulipas scans
LIGHT_PENCIL = (150, 150, 158)
BLACK = (30, 30, 30)
BLUE_INK = (140, 50, 20)


def _swatches(colours: list[tuple[int, int, int]]) -> np.ndarray:
    img = np.full((120, 100 * len(colours) + 100, 3), PAPER, np.uint8)
    for i, c in enumerate(colours):
        cv2.circle(img, (100 * i + 100, 60), 22, c, -1)
    return img


def _at(m: np.ndarray, i: int) -> float:
    return float(m[50:71, 100 * i + 90 : 100 * i + 111].mean())


def test_profiles_registry() -> None:
    assert set(PROFILES) == {"magenta", "orange"}
    magenta = get_profile("magenta")
    assert (magenta.hue_min, magenta.hue_max, magenta.sat_floor, magenta.val_min) == (140, 179, 18, 90)
    with pytest.raises(ValueError):
        get_profile("green")


@pytest.mark.parametrize(
    ("profile", "own", "others"),
    # R - B also responds to magenta/red; irrelevant because a form is printed in a single colour
    [("magenta", MAGENTA, [ORANGE, PENCIL, BLACK, BLUE_INK]), ("orange", ORANGE, [PENCIL, BLACK, BLUE_INK])],
)
def test_strength_selects_own_colour(cfg: EngineConfig, profile: str, own: tuple, others: list) -> None:
    norm = normalize_illumination(_swatches([own, *others]), cfg)
    strength = get_profile(profile).strength(norm)
    assert _at(strength, 0) > 60
    for i in range(1, len(others) + 1):
        assert _at(strength, i) < 15, (profile, others[i - 1])
    assert float(strength[:20, :20].mean()) < 2  # paper


@pytest.mark.parametrize(
    ("profile", "own", "others"),
    [("magenta", MAGENTA, [ORANGE, PENCIL, BLACK, BLUE_INK]), ("orange", ORANGE, [MAGENTA, PENCIL, BLACK, BLUE_INK])],
)
def test_print_mask_selects_own_colour(cfg: EngineConfig, profile: str, own: tuple, others: list) -> None:
    mask = print_mask(to_hsv(normalize_illumination(_swatches([own, *others]), cfg)), get_profile(profile), cfg)
    assert _at(mask, 0) > 250
    for i in range(1, len(others) + 1):
        assert _at(mask, i) == 0, (profile, others[i - 1])


def test_ink_map_drops_orange_keeps_pencil(cfg: EngineConfig) -> None:
    ink = ink_map(normalize_illumination(_swatches([ORANGE, PENCIL, LIGHT_PENCIL]), cfg), cfg)
    assert _at(ink, 0) < 3
    assert _at(ink, 1) > 0.9 * 255
    assert _at(ink, 2) > 0.3 * 255
