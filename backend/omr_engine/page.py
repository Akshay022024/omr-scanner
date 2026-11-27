"""Coarse page normalisation: page quad / content box detection and orientation.

Several candidate transforms (detected paper quad, print-colour content box, full frame), each in four
orientations, are scored against the template's printed layout at low resolution; the best one
becomes the starting point for fine registration.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .config import EngineConfig
from .geometry import apply, corners, scale_matrix, warp_to_template
from .ink import normalize_illumination, print_mask, to_hsv
from .registration import TemplateFeatures, blur, content_bbox


@dataclass(frozen=True)
class PageTransform:
    homography: np.ndarray  # template -> ``source`` coordinates
    source: np.ndarray  # input image, possibly downscaled by ``source_scale``
    source_scale: float
    candidate: str  # "quad" | "content" | "frame"
    rotation: int  # degrees: 0, 90, 180 or 270
    score: float


def order_corners(pts: np.ndarray) -> np.ndarray:
    """Order 4 points as top-left, top-right, bottom-right, bottom-left."""
    pts = np.asarray(pts, np.float64).reshape(4, 2)
    center = pts.mean(axis=0)
    angles = np.arctan2(pts[:, 1] - center[1], pts[:, 0] - center[0])
    ordered = pts[np.argsort(angles)]
    start = int(np.argmin(ordered.sum(axis=1)))
    return np.roll(ordered, -start, axis=0)


def _quad_from_mask(mask: np.ndarray, cfg: EngineConfig) -> np.ndarray | None:
    h, w = mask.shape
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    hull = cv2.convexHull(max(contours, key=cv2.contourArea))
    area_frac = cv2.contourArea(hull) / float(h * w)
    if not (cfg.min_page_area_frac <= area_frac <= cfg.max_page_area_frac):
        return None
    perimeter = cv2.arcLength(hull, True)
    for eps in (0.02, 0.03, 0.05, 0.08):
        approx = cv2.approxPolyDP(hull, eps * perimeter, True)
        if len(approx) == 4:
            return order_corners(approx.reshape(4, 2))
    return order_corners(cv2.boxPoints(cv2.minAreaRect(hull)))


def find_page_quads(gray: np.ndarray, cfg: EngineConfig) -> list[np.ndarray]:
    """Candidate paper quadrilaterals (paper brighter than the background).

    Several brightness cuts (Otsu and progressively lower ones, for shadowed pages) plus an
    edge-based mask are tried; near-duplicates are removed. Empty for full-frame scans.
    """
    h, w = gray.shape
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    otsu, _ = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    k = max(3, (min(h, w) // 40) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    masks = []
    for factor in cfg.page_threshold_factors:
        _, bright = cv2.threshold(blurred, otsu * factor, 255, cv2.THRESH_BINARY)
        bright = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, kernel)
        masks.append(cv2.morphologyEx(bright, cv2.MORPH_OPEN, kernel))
    edges = cv2.dilate(cv2.Canny(blurred, 30, 90), kernel)
    filled = np.zeros_like(edges)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        cv2.drawContours(filled, [max(contours, key=cv2.contourArea)], -1, 255, cv2.FILLED)
        masks.append(cv2.erode(filled, kernel, iterations=1))
    quads: list[np.ndarray] = []
    tol = 0.01 * max(h, w)
    for mask in masks:
        quad = _quad_from_mask(mask, cfg)
        if quad is not None and all(np.abs(quad - q).max() > tol for q in quads):
            quads.append(quad)
    return quads


def _rotation(k: int, width: float, height: float) -> tuple[np.ndarray, tuple[float, float]]:
    """Template -> canvas rotated clockwise by k*90 degrees, and the canvas size."""
    mats = {
        0: (np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]], np.float64), (width, height)),
        1: (np.array([[0, -1, height], [1, 0, 0], [0, 0, 1]], np.float64), (height, width)),
        2: (np.array([[-1, 0, width], [0, -1, height], [0, 0, 1]], np.float64), (width, height)),
        3: (np.array([[0, 1, 0], [-1, 0, width], [0, 0, 1]], np.float64), (height, width)),
    }
    return mats[k]


def _quad_candidates(quad: np.ndarray, width: float, height: float) -> list[tuple[int, np.ndarray]]:
    src = corners(width, height).astype(np.float32)
    out = []
    for k in range(4):
        dst = np.roll(quad, -k, axis=0).astype(np.float32)
        out.append((k, cv2.getPerspectiveTransform(src, dst).astype(np.float64)))
    return out


def _content_candidates(
    bbox: tuple[float, float, float, float], tbbox: tuple[float, float, float, float], width: float, height: float
) -> list[tuple[int, np.ndarray]]:
    x0, y0, x1, y1 = bbox
    out = []
    for k in range(4):
        rot, _ = _rotation(k, width, height)
        tb = apply(rot, np.array([[tbbox[0], tbbox[1]], [tbbox[2], tbbox[3]]]))
        rx0, ry0 = tb.min(axis=0)
        rx1, ry1 = tb.max(axis=0)
        sx, sy = (x1 - x0) / (rx1 - rx0), (y1 - y0) / (ry1 - ry0)
        affine = np.array([[sx, 0, x0 - rx0 * sx], [0, sy, y0 - ry0 * sy], [0, 0, 1]], np.float64)
        out.append((k, affine @ rot))
    return out


def _ncc(a: np.ndarray, b: np.ndarray) -> float:
    a = a - a.mean()
    b = b - b.mean()
    denom = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / denom) if denom > 1e-9 else -1.0


def estimate_page_transform(img: np.ndarray, feats: TemplateFeatures, cfg: EngineConfig) -> PageTransform:
    """Pick the best coarse template -> image transform over all candidates and orientations."""
    width, height = feats.size
    ih, iw = img.shape[:2]
    f_small = min(1.0, cfg.page_detect_max_side / max(ih, iw))
    small = cv2.resize(img, (max(1, round(iw * f_small)), max(1, round(ih * f_small))), interpolation=cv2.INTER_AREA)
    sh, sw = small.shape[:2]
    mag = print_mask(to_hsv(normalize_illumination(small, cfg)), feats.profile, cfg)
    mag_f = blur(mag.astype(np.float32) / 255.0, 1.0)

    candidates: list[tuple[str, int, np.ndarray]] = []
    for quad in find_page_quads(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), cfg):
        candidates += [("quad", k, hm) for k, hm in _quad_candidates(quad, width, height)]
    bbox = content_bbox(mag)
    if bbox is not None:
        candidates += [("content", k, hm) for k, hm in _content_candidates(bbox, feats.print_bbox, width, height)]
    candidates += [("frame", k, hm) for k, hm in _quad_candidates(corners(sw, sh), width, height)]

    so = cfg.orientation_scale
    target = feats.orientation
    osize = (target.shape[1], target.shape[0])
    to_small_canvas = np.linalg.inv(scale_matrix(so))
    scored = [
        (_ncc(blur(warp_to_template(mag_f, hm @ to_small_canvas, osize, border=cv2.BORDER_CONSTANT), 1.5), target), i)
        for i, (_, _, hm) in enumerate(candidates)
    ]
    score, best_index = max(scored, key=lambda t: (t[0], -t[1]))
    name, k, h_small = candidates[best_index]

    # Downscale the source so the page is roughly template-sized (avoids aliasing in the warp).
    top, bottom = apply(h_small, np.array([[width / 2, 0], [width / 2, height]]))
    page_h_orig = float(np.hypot(*(bottom - top))) / f_small
    s_src = height / page_h_orig if page_h_orig > cfg.presize_ratio * height else 1.0
    source = img
    if s_src < 1.0:
        source = cv2.resize(img, (max(1, round(iw * s_src)), max(1, round(ih * s_src))), interpolation=cv2.INTER_AREA)
    homography = scale_matrix(s_src / f_small) @ h_small
    return PageTransform(homography, source, s_src, name, 90 * k, score)

