"""Small homography helpers shared by the page, registration and overlay stages.

Convention: every homography maps *canonical template coordinates* to *image coordinates*, so
an image is resampled into template space with ``WARP_INVERSE_MAP``.
"""

from __future__ import annotations

import cv2
import numpy as np


def scale_matrix(sx: float, sy: float | None = None) -> np.ndarray:
    return np.diag([sx, sx if sy is None else sy, 1.0])


def rescale_homography(h: np.ndarray, scale: float) -> np.ndarray:
    """Express ``h`` (full-res template -> full-res image) at a uniform ``scale`` on both sides."""
    s = scale_matrix(scale)
    return s @ h @ np.linalg.inv(s)


def normalise(h: np.ndarray) -> np.ndarray:
    return h / h[2, 2]


def corners(width: float, height: float) -> np.ndarray:
    return np.array([[0, 0], [width, 0], [width, height], [0, height]], np.float64)


def apply(h: np.ndarray, pts: np.ndarray) -> np.ndarray:
    pts = np.asarray(pts, np.float64).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(pts, h).reshape(-1, 2)


def warp_to_template(
    img: np.ndarray,
    h: np.ndarray,
    size: tuple[int, int],
    *,
    interpolation: int = cv2.INTER_LINEAR,
    border: int = cv2.BORDER_REPLICATE,
) -> np.ndarray:
    """Resample ``img`` into template space of ``size`` = (width, height)."""
    return cv2.warpPerspective(img, h, size, flags=interpolation | cv2.WARP_INVERSE_MAP, borderMode=border)


def max_corner_shift(h: np.ndarray, width: float, height: float) -> float:
    """Largest displacement of a template corner under ``h`` (distance from identity)."""
    c = corners(width, height)
    return float(np.max(np.linalg.norm(apply(h, c) - c, axis=1)))


def is_plausible(h: np.ndarray | None, width: float, height: float, max_shift_frac: float) -> bool:
    if h is None or not np.all(np.isfinite(h)) or abs(h[2, 2]) < 1e-12:
        return False
    hn = normalise(h)
    if np.linalg.det(hn[:2, :2]) <= 0:
        return False
    return max_corner_shift(hn, width, height) <= max_shift_frac * float(np.hypot(width, height))
