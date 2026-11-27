from __future__ import annotations

import cv2
import numpy as np

from omr_engine import EngineConfig, Template
from omr_engine.ink import ink_map, normalize_illumination, print_mask, to_hsv
from omr_engine.printcolor import get_profile
from omr_synth import BLACK, DARK_BLUE

MAGENTA = (140, 30, 230)  # BGR, as printed on the sheet


def _patch_scene() -> np.ndarray:
    """White paper with a magenta ring + letter, a blue disc, a black disc and a grey (light) disc."""
    img = np.full((200, 400, 3), 245, np.uint8)
    cv2.circle(img, (50, 100), 15, MAGENTA, 2, cv2.LINE_AA)
    cv2.putText(img, "A", (42, 108), cv2.FONT_HERSHEY_SIMPLEX, 0.6, MAGENTA, 2, cv2.LINE_AA)
    cv2.circle(img, (150, 100), 13, DARK_BLUE, -1, cv2.LINE_AA)
    cv2.circle(img, (250, 100), 13, BLACK, -1, cv2.LINE_AA)
    cv2.circle(img, (350, 100), 13, (140, 140, 140), -1, cv2.LINE_AA)  # light black-pen pressure
    return img


def _disc_mean(m: np.ndarray, cx: int, cy: int, r: int = 9) -> float:
    mask = np.zeros(m.shape, np.uint8)
    cv2.circle(mask, (cx, cy), r, 1, -1)
    return float(m[mask > 0].mean()) / 255.0


def test_magenta_removed_blue_black_and_grey_kept(cfg: EngineConfig) -> None:
    ink = ink_map(normalize_illumination(_patch_scene(), cfg), cfg)
    assert _disc_mean(ink, 50, 100, 16) < 0.02
    assert _disc_mean(ink, 150, 100) > 0.95
    assert _disc_mean(ink, 250, 100) > 0.95
    assert _disc_mean(ink, 350, 100) > 0.6


def test_ink_robust_to_shading_and_colour_cast(cfg: EngineConfig) -> None:
    img = _patch_scene().astype(np.float32)
    gradient = np.linspace(1.0, 0.55, img.shape[1], dtype=np.float32)[None, :, None]
    cast = np.array([0.9, 1.0, 0.85], np.float32)  # BGR
    shaded = np.clip(img * gradient * cast, 0, 255).astype(np.uint8)
    ink = ink_map(normalize_illumination(shaded, cfg), cfg)
    assert _disc_mean(ink, 50, 100, 16) < 0.02
    assert _disc_mean(ink, 150, 100) > 0.9
    assert _disc_mean(ink, 250, 100) > 0.9


def test_thin_tick_is_suppressed(cfg: EngineConfig) -> None:
    img = np.full((80, 80, 3), 245, np.uint8)
    cv2.line(img, (25, 40), (35, 52), BLACK, 2, cv2.LINE_AA)
    cv2.line(img, (35, 52), (55, 25), BLACK, 2, cv2.LINE_AA)
    ink = ink_map(normalize_illumination(img, cfg), cfg)
    assert _disc_mean(ink, 40, 40, 11) < 0.15


def test_template_bubbles_have_no_ink(template: Template, cfg: EngineConfig) -> None:
    """Magenta letters printed inside every bubble must not register as ink."""
    ink = ink_map(normalize_illumination(template.reference, cfg), cfg)
    for (x, y), r in zip(template.bubble_xy, template.bubble_r, strict=True):
        assert _disc_mean(ink, int(x), int(y), int(r * 0.75)) < 0.02


def test_magenta_mask_finds_print_not_ink(cfg: EngineConfig) -> None:
    mask = print_mask(to_hsv(normalize_illumination(_patch_scene(), cfg)), get_profile("magenta"), cfg)
    assert mask[85, 50] == 255 or mask[100, 35] == 255  # ring
    assert _disc_mean(mask, 150, 100) == 0.0
    assert _disc_mean(mask, 250, 100) == 0.0
