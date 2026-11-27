"""Aligned review images with coloured bubble markers."""

from __future__ import annotations

import cv2
import numpy as np

from .geometry import warp_to_template
from .models import ScanResult
from .template import Template

# BGR
_COLOURS = {
    "single": (60, 170, 40),
    "multiple": (40, 40, 220),
    "ambiguous": (0, 170, 255),
}


def align_to_template(img_bgr: np.ndarray, result: ScanResult, tpl: Template) -> np.ndarray:
    """Resample the original image into template space using the scan's homography.

    Falls back to a plain resize when the scan has no registration (failed scan).
    """
    width, height = tpl.size
    if result.registration is None or result.registration.homography is None:
        return cv2.resize(img_bgr, (width, height), interpolation=cv2.INTER_AREA)
    h = np.array(result.registration.homography, np.float64)
    return warp_to_template(img_bgr, h, (width, height), border=cv2.BORDER_CONSTANT)


def render_overlay(img_bgr: np.ndarray, result: ScanResult, tpl: Template, *, already_aligned: bool = False) -> np.ndarray:
    """Aligned image with circles: green = marked, red = multiple, amber = ambiguous.

    Pass ``already_aligned=True`` when ``img_bgr`` is already in template space.
    """
    canvas = img_bgr.copy() if already_aligned else align_to_template(img_bgr, result, tpl)
    by_id = {f.id: f for f in result.fields}
    for field in tpl.spec.fields:
        fr = by_id.get(field.id)
        if fr is None or fr.state == "blank":
            continue
        colour = _COLOURS[fr.state]
        chosen = set(fr.value)
        if not chosen and fr.scores:
            chosen = {max(fr.scores, key=lambda v: fr.scores[v])}
        for b in field.bubbles:
            if b.value in chosen:
                cv2.circle(canvas, (int(round(b.x)), int(round(b.y))), int(round(b.r + 4)), colour, 3, cv2.LINE_AA)
    return canvas
