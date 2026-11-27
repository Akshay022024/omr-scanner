"""Per-sheet adaptive threshold and per-field decisions."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from .config import EngineConfig
from .models import FieldResult, FieldState, TemplateField


def _otsu(scores: np.ndarray, bins: int = 100) -> float:
    hist, edges = np.histogram(scores, bins=bins, range=(0.0, 1.0))
    p = hist.astype(np.float64) / max(1, hist.sum())
    centers = (edges[:-1] + edges[1:]) / 2.0
    w0 = np.cumsum(p)
    mu = np.cumsum(p * centers)
    mu_t = mu[-1]
    w1 = 1.0 - w0
    valid = (w0 > 0) & (w1 > 0)
    between = np.zeros_like(w0)
    between[valid] = (mu_t * w0[valid] - mu[valid]) ** 2 / (w0[valid] * w1[valid])
    return float(edges[int(np.argmax(between)) + 1])


def adaptive_threshold(scores: Sequence[float] | np.ndarray, cfg: EngineConfig) -> float:
    """Midpoint of the largest score gap inside [min_threshold, max_threshold].

    Sentinels at 0 and 1 make an all-blank (or all-filled) sheet fall back to the middle of the
    clamp range. When no gap of at least ``min_gap`` exists (scores spread continuously), Otsu's
    threshold is used instead. The result is always clamped.
    """
    lo, hi = cfg.min_threshold, cfg.max_threshold
    values = np.unique(np.concatenate([[0.0, 1.0], np.clip(np.asarray(scores, np.float64), 0.0, 1.0)]))
    best_gap, best_thr = -1.0, (lo + hi) / 2.0
    for a, b in zip(values[:-1], values[1:], strict=True):
        a_c, b_c = max(a, lo), min(b, hi)
        if b_c > a_c and b_c - a_c > best_gap:
            best_gap, best_thr = b_c - a_c, (a_c + b_c) / 2.0
    if best_gap < cfg.min_gap:
        best_thr = _otsu(np.asarray(scores, np.float64))
    return float(min(max(best_thr, lo), hi))


def decide_field(field: TemplateField, scores: Sequence[float], threshold: float, cfg: EngineConfig) -> FieldResult:
    """Classify one field as blank / single / multiple / ambiguous."""
    values = [b.value for b in field.bubbles]
    s = [float(x) for x in scores]
    marked = [v for v, x in zip(values, s, strict=True) if x >= threshold]
    distances = [abs(x - threshold) for x in s]
    near = min(distances) < cfg.ambiguity_margin
    state: FieldState
    if near:
        state = "ambiguous"
    elif not marked:
        state = "blank"
    elif len(marked) == 1:
        state = "single"
    else:
        state = "multiple"
    confidence = min(1.0, min(distances) / cfg.confidence_scale)
    return FieldResult(
        id=field.id,
        group=field.group,
        question=field.question,
        state=state,
        value="".join(marked),
        confidence=round(confidence, 4),
        scores={v: round(x, 4) for v, x in zip(values, s, strict=True)},
    )
