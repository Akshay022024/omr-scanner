"""Minimal synthetic-sheet helpers for tests (the full generator lives in benchmarks/synth)."""

from __future__ import annotations

import cv2
import numpy as np

from omr_engine import Template

DARK_BLUE = (140, 50, 20)  # BGR, typical blue ballpoint
BLACK = (30, 30, 30)


def random_marks(tpl: Template, seed: int, blank_rate: float = 0.05) -> dict[str, str]:
    """One value per field (roll digits, paper set, answers); some answers left blank."""
    rng = np.random.default_rng(seed)
    marks: dict[str, str] = {}
    for field in tpl.spec.fields:
        if field.group == "answers" and rng.random() < blank_rate:
            marks[field.id] = ""
            continue
        marks[field.id] = field.bubbles[int(rng.integers(len(field.bubbles)))].value
    return marks


def fill_sheet(
    tpl: Template,
    marks: dict[str, str],
    colour: tuple[int, int, int] = DARK_BLUE,
    radius_frac: float = 0.9,
) -> np.ndarray:
    """Draw filled discs on a copy of the template reference image. Values may hold several letters."""
    img = tpl.reference.copy()
    for field in tpl.spec.fields:
        chosen = set(marks.get(field.id, ""))
        for b in field.bubbles:
            if b.value in chosen:
                centre = (int(round(b.x * 4)), int(round(b.y * 4)))
                cv2.circle(img, centre, int(round(b.r * radius_frac * 4)), colour, -1, cv2.LINE_AA, shift=2)
    return img


def expected_answers(tpl: Template, marks: dict[str, str]) -> dict[str, str]:
    return {str(f.question): marks.get(f.id, "") for f in tpl.fields_in("answers")}


def expected_roll(tpl: Template, marks: dict[str, str]) -> str:
    return "".join(marks.get(f.id, "") or "?" for f in tpl.fields_in("roll_no"))


def photograph(
    img: np.ndarray,
    angle_deg: float = 3.0,
    scale: float = 0.9,
    perspective: float = 0.03,
    canvas: tuple[int, int] = (2000, 2500),
    background: tuple[int, int, int] = (70, 80, 90),
) -> tuple[np.ndarray, np.ndarray]:
    """Place the sheet on a dark background with rotation, scale and a mild perspective tilt.

    Returns the image and the ground-truth homography (template px -> image px).
    """
    h, w = img.shape[:2]
    cw, ch = canvas
    src = np.array([[0, 0], [w, 0], [w, h], [0, h]], np.float32)
    dx = perspective * w
    dst = np.array([[dx, 0], [w - dx, 0], [w, h], [0, h]], np.float32)  # top edge narrower
    tilt = cv2.getPerspectiveTransform(src, dst)
    theta = np.deg2rad(angle_deg)
    rot = np.array(
        [
            [scale * np.cos(theta), -scale * np.sin(theta), 0],
            [scale * np.sin(theta), scale * np.cos(theta), 0],
            [0, 0, 1],
        ]
    )
    to_origin = np.array([[1, 0, -w / 2], [0, 1, -h / 2], [0, 0, 1]], np.float64)
    to_canvas = np.array([[1, 0, cw / 2], [0, 1, ch / 2], [0, 0, 1]], np.float64)
    m = to_canvas @ rot @ to_origin @ tilt
    return cv2.warpPerspective(img, m, canvas, flags=cv2.INTER_LINEAR, borderValue=background), m
