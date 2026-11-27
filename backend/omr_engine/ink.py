"""Illumination normalisation, print-colour mask (registration) and pen/pencil ink map (reading)."""

from __future__ import annotations

import cv2
import numpy as np

from .config import EngineConfig
from .printcolor import PrintProfile


def normalize_illumination(img_bgr: np.ndarray, cfg: EngineConfig) -> np.ndarray:
    """Divide each channel by a large-kernel estimate of the paper background.

    The background is the local per-channel maximum (paper is the brightest thing on the sheet),
    computed at low resolution. This removes shadows, gradients and colour casts: paper maps to
    white and print/ink keep their relative colour.
    """
    h, w = img_bgr.shape[:2]
    sw = max(8, round(w * cfg.background_scale))
    sh = max(8, round(h * cfg.background_scale))
    small = cv2.resize(img_bgr, (sw, sh), interpolation=cv2.INTER_AREA)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (cfg.background_kernel, cfg.background_kernel))
    bg = cv2.dilate(small, k)
    bg = cv2.GaussianBlur(bg, (0, 0), cfg.background_kernel / 2.0)
    bg = cv2.resize(bg, (w, h), interpolation=cv2.INTER_LINEAR)
    bg = np.maximum(bg, 1)
    return cv2.divide(img_bgr, bg, scale=255.0)


def to_hsv(img_bgr: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)


def print_saturation_threshold(hsv: np.ndarray, profile: PrintProfile, cfg: EngineConfig) -> int:
    """Saturation cut just above the paper's noise floor (median + k*MAD of S, clamped).

    Thin, blurred print lines are only faintly saturated, so a fixed high cut loses them; a
    noisy image needs a higher cut to avoid speckle.
    """
    sat = hsv[::4, ::4, 1].astype(np.float32)
    med = float(np.median(sat))
    mad = 1.4826 * float(np.median(np.abs(sat - med)))
    ceiling = max(profile.sat_floor, cfg.print_sat_max)
    return int(round(min(max(med + cfg.print_noise_k * mad, profile.sat_floor), ceiling)))


def print_mask(hsv: np.ndarray, profile: PrintProfile, cfg: EngineConfig) -> np.ndarray:
    """uint8 0/255 mask of the form's print colour (used for registration)."""
    lo = np.array([profile.hue_min, print_saturation_threshold(hsv, profile, cfg), profile.val_min], np.uint8)
    hi = np.array([profile.hue_max, 255, 255], np.uint8)
    return cv2.inRange(hsv, lo, hi)

def _ink_lut(lo: float, hi: float) -> np.ndarray:
    darkness = 1.0 - np.arange(256, dtype=np.float64) / 255.0
    return np.clip((darkness - lo) / (hi - lo) * 255.0, 0, 255).round().astype(np.uint8)


def ink_strength(norm_bgr: np.ndarray, cfg: EngineConfig) -> np.ndarray:
    """uint8 per-pixel red-channel darkness mapped from [ink_dark_lo, ink_dark_hi] to [0, 255]."""
    return cv2.LUT(np.ascontiguousarray(norm_bgr[:, :, 2]), _ink_lut(cfg.ink_dark_lo, cfg.ink_dark_hi))


def ink_map(norm_bgr: np.ndarray, cfg: EngineConfig) -> np.ndarray:
    """uint8 soft ink strength (0 = paper/print, 255 = solid pen) from a normalised BGR image.

    Red-channel dropout: magenta or orange print and the paper all reflect red, while blue and
    black ballpoint and graphite pencil (even light, greyish strokes) absorb it. Strength is relative to the normalised
    paper white, so it is independent of exposure and colour cast. A small closing merges
    scribble strokes into an area and an opening removes thin ticks/crosses, which therefore
    score far below genuine fills.
    """
    strength = ink_strength(norm_bgr, cfg)
    if cfg.ink_close_px > 1:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (cfg.ink_close_px, cfg.ink_close_px))
        strength = cv2.morphologyEx(strength, cv2.MORPH_CLOSE, k)
    if cfg.ink_open_px > 1:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (cfg.ink_open_px, cfg.ink_open_px))
        strength = cv2.morphologyEx(strength, cv2.MORPH_OPEN, k)
    return strength