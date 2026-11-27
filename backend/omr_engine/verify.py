"""Geometric verification of the final alignment, independent of the print-mask IoU.

Two complementary checks:

* **Print lock** - the template's dark (non-dropout) print, e.g. question numbers and labels,
  with bubbles masked out, is correlated with the aligned image at zero offset and at one bubble
  pitch up/down/left/right. A warp that is off by a row or column correlates better at a shifted
  position. Big black glyphs survive blur and low resolution, so this works on poor photos too.
* **Anchor edges** - the panel edges (print-coloured or black) are re-detected after the warp; when enough of them
  are found, their RMS offset must be small.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .config import EngineConfig
from .geometry import warp_to_template
from .ink import ink_strength, normalize_illumination
from .registration import TemplateFeatures, blur, edge_map, measure_edges
from .template import Template

_LOCK_BLUR = 1.0
_LOCK_BORDER = 16
_BUBBLE_PAD_PX = 6
_MIN_PRINT_ENERGY = 1e-3


@dataclass(frozen=True)
class GeometryCheck:
    coverage_h: float  # fraction of horizontal anchor-edge segments re-found
    coverage_v: float
    residual_px: float | None  # robust RMS offset of the re-found segments (template px)
    lock_score: float | None  # print correlation at zero offset (None: template has no dark print)
    lock_margin: float | None  # zero-offset correlation minus the best one-pitch-shifted correlation

    def ok(self, cfg: EngineConfig) -> bool:
        edges_conclusive = min(self.coverage_h, self.coverage_v) >= cfg.geometry_min_coverage
        edges_bad = edges_conclusive and (self.residual_px is None or self.residual_px > cfg.geometry_max_residual_px)
        if self.lock_score is None or self.lock_margin is None:
            return edges_conclusive and not edges_bad
        lock_ok = self.lock_score >= cfg.lock_min_score and self.lock_margin >= cfg.lock_min_margin
        return lock_ok and not edges_bad


@dataclass(frozen=True)
class _PrintLock:
    mask: np.ndarray  # uint8 0/1, full resolution: 1 where dark template print is compared
    template: np.ndarray | None  # float32 at cfg.lock_scale, None when there is no dark print
    shifts: tuple[tuple[int, int], ...]  # one-pitch offsets at cfg.lock_scale


def _bubble_pitch(tpl: Template) -> tuple[float, float]:
    """Typical horizontal and vertical distance between neighbouring bubbles."""
    xy = tpl.bubble_xy
    d = xy[None, :, :] - xy[:, None, :]
    dist = np.hypot(d[..., 0], d[..., 1])
    np.fill_diagonal(dist, np.inf)
    same_row = np.abs(d[..., 1]) < 3
    same_col = np.abs(d[..., 0]) < 3
    px = np.where(same_row, dist, np.inf).min(axis=1)
    py = np.where(same_col, dist, np.inf).min(axis=1)
    return float(np.median(px[np.isfinite(px)])), float(np.median(py[np.isfinite(py)]))


def _dark_print(norm_bgr: np.ndarray, mask: np.ndarray, cfg: EngineConfig) -> np.ndarray:
    dark = ink_strength(norm_bgr, cfg) * mask
    small = cv2.resize(dark, None, fx=cfg.lock_scale, fy=cfg.lock_scale, interpolation=cv2.INTER_AREA)
    return blur(small.astype(np.float32), _LOCK_BLUR)


def _build_print_lock(tpl: Template, cfg: EngineConfig) -> _PrintLock:
    w, h = tpl.size
    mask = np.ones((h, w), np.uint8)
    for (x, y), r in zip(tpl.bubble_xy, tpl.bubble_r, strict=True):
        cv2.circle(mask, (int(round(x)), int(round(y))), int(round(r + _BUBBLE_PAD_PX)), 0, -1)
    template = _dark_print(normalize_illumination(tpl.reference, cfg), mask, cfg)
    pitch_x, pitch_y = _bubble_pitch(tpl)
    sx, sy = int(round(pitch_x * cfg.lock_scale)), int(round(pitch_y * cfg.lock_scale))
    shifts = ((0, sy), (0, -sy), (sx, 0), (-sx, 0))
    has_print = float(template.std()) / 255.0 > _MIN_PRINT_ENERGY
    return _PrintLock(mask, template if has_print else None, shifts)


def _ncc(a: np.ndarray, b: np.ndarray) -> float:
    a = a - a.mean()
    b = b - b.mean()
    denom = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / denom) if denom > 1e-9 else 0.0


def _lock_scores(aligned: np.ndarray, lock: _PrintLock) -> tuple[float, float] | None:
    if lock.template is None:
        return None
    m = _LOCK_BORDER
    base = lock.template[m:-m, m:-m]
    hgt, wid = aligned.shape

    def at(dx: int, dy: int) -> float:
        return _ncc(base, aligned[m + dy : hgt - m + dy, m + dx : wid - m + dx])

    zero = at(0, 0)
    shifted = max(at(dx, dy) for dx, dy in lock.shifts)
    return zero, zero - shifted


def verify_alignment(
    page_norm: np.ndarray, homography: np.ndarray, tpl: Template, feats: TemplateFeatures, cfg: EngineConfig
) -> GeometryCheck:
    """Check the final template -> page homography against print layout and panel edges."""
    lock = tpl.cached(("print_lock", cfg), lambda: _build_print_lock(tpl, cfg))
    aligned = warp_to_template(page_norm, homography, feats.size, border=cv2.BORDER_REPLICATE)
    edges = measure_edges(edge_map(aligned, feats.profile, feats.anchor_source, cfg), feats, cfg)
    cov_h = float(edges.horizontal.sum()) / max(1, edges.total_horizontal)
    cov_v = float((~edges.horizontal).sum()) / max(1, edges.total_vertical)
    residual = None
    if len(edges.offsets):
        # robust RMS: ignore the worst 20 % (a neighbouring line occasionally wins the search)
        sq = np.sort(edges.offsets**2)
        residual = round(float(np.sqrt(sq[: max(1, int(np.ceil(0.8 * len(sq))))].mean())), 3)
    scores = _lock_scores(_dark_print(aligned, lock.mask, cfg), lock)
    return GeometryCheck(
        coverage_h=round(cov_h, 4),
        coverage_v=round(cov_v, 4),
        residual_px=residual,
        lock_score=None if scores is None else round(scores[0], 4),
        lock_margin=None if scores is None else round(scores[1], 4),
    )
