"""Per-bubble fill score: ink fraction inside a disc, maximised over small local shifts."""

from __future__ import annotations

from functools import lru_cache

import cv2
import numpy as np

from .config import EngineConfig


@lru_cache(maxsize=16)
def _disc_kernel(radius: float) -> np.ndarray:
    half = int(np.ceil(radius))
    yy, xx = np.mgrid[-half : half + 1, -half : half + 1]
    disc = (xx * xx + yy * yy <= radius * radius).astype(np.float32)
    disc /= disc.sum()
    disc.setflags(write=False)
    return disc


def score_bubbles(ink: np.ndarray, centers: np.ndarray, radii: np.ndarray, cfg: EngineConfig) -> np.ndarray:
    """Return the fill score in [0, 1] for each bubble.

    ``ink`` is a float32 map in [0, 1] (aligned to the template); ``centers`` is (N, 2) x/y and
    ``radii`` the printed bubble radii, both in aligned pixel coordinates.
    """
    shift = cfg.shift_search_px
    max_half = int(np.ceil(float(radii.max()) * cfg.disc_radius_frac)) + shift + 1
    padded = cv2.copyMakeBorder(ink, max_half, max_half, max_half, max_half, cv2.BORDER_CONSTANT, value=0.0)
    scores = np.zeros(len(centers), np.float64)
    for i, ((cx, cy), r) in enumerate(zip(centers, radii, strict=True)):
        kernel = _disc_kernel(round(float(r) * cfg.disc_radius_frac, 2))
        half = kernel.shape[0] // 2
        ext = half + shift
        x0 = int(round(cx)) + max_half
        y0 = int(round(cy)) + max_half
        if not (ext <= x0 < padded.shape[1] - ext and ext <= y0 < padded.shape[0] - ext):
            continue
        patch = padded[y0 - ext : y0 + ext + 1, x0 - ext : x0 + ext + 1]
        response = cv2.filter2D(patch, cv2.CV_32F, kernel, borderType=cv2.BORDER_CONSTANT)
        core = response[half : half + 2 * shift + 1, half : half + 2 * shift + 1]
        scores[i] = float(core.max())
    return np.clip(scores, 0.0, 1.0)
