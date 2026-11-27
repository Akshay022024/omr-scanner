"""Per-template print-colour profiles (the colour the form is printed in and dropped out).

A profile defines how the printed layout is found, both for registration (a binary HSV mask)
and for locating panel edges (a soft strength map). Pen and pencil ink is always read through
red-channel dropout (see ``ink.ink_map``), which works for any print colour that reflects red,
such as magenta, orange or red-orange.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np


def _magenta_strength(norm_bgr: np.ndarray) -> np.ndarray:
    """min(R, B) - G: high on magenta, 0 on paper, black, blue ink, grey pencil and orange."""
    b, g, r = cv2.split(norm_bgr)
    return cv2.subtract(cv2.min(r, b), g)


def _orange_strength(norm_bgr: np.ndarray) -> np.ndarray:
    """R - B: high on orange, about 0 on paper, black print and grey pencil, 0 on blue ink.

    It also responds to magenta/red, which does not matter on a form printed only in orange.
    """
    b, _, r = cv2.split(norm_bgr)
    return cv2.subtract(r, b)


@dataclass(frozen=True)
class PrintProfile:
    name: str
    hue_min: int  # OpenCV hue (0..179), inclusive
    hue_max: int
    sat_floor: int  # lower clamp of the adaptive saturation threshold
    val_min: int  # print is bright; excludes dark ink/pencil of a similar hue
    strength: Callable[[np.ndarray], np.ndarray]  # normalised BGR -> uint8 soft print map


PROFILES: dict[str, PrintProfile] = {
    "magenta": PrintProfile("magenta", hue_min=140, hue_max=179, sat_floor=18, val_min=90, strength=_magenta_strength),
    # Graphite is slightly warm (R a little above B, low saturation): the value floor and a higher
    # saturation floor keep pencil marks out of the orange print mask.
    "orange": PrintProfile("orange", hue_min=3, hue_max=30, sat_floor=40, val_min=140, strength=_orange_strength),
}


def get_profile(name: str) -> PrintProfile:
    try:
        return PROFILES[name]
    except KeyError:
        raise ValueError(f"unknown print colour {name!r}; expected one of {sorted(PROFILES)}") from None
