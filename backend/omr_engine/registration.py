"""Fine alignment of a page-normalised image to the template.

Layers: (a) ECC homography on blurred print-colour masks, coarse-to-fine; (b) ORB + RANSAC
fallback; (c) anchor-box refinement from the panel edges. Every candidate is scored by the IoU
of the warped print mask against the template print mask and the best one wins. Panel edges are
located on a soft print-strength map (faint hairlines survive there), or on the darkness map for
templates whose frames are printed in black.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .config import EngineConfig
from .geometry import is_plausible, normalise, rescale_homography, warp_to_template
from .ink import ink_strength, normalize_illumination, print_mask, to_hsv
from .printcolor import PrintProfile
from .models import RegistrationMethod
from .template import Template

_ANCHOR_EDGE_TRIM = 0.08
_TEMPLATE_DOMINANCE = 0.5
_INPUT_DOMINANCE = 0.6
_MIN_EDGE_STRENGTH = 0.05  # relative to the template's edge strength
_MIN_EDGE_SNR = 4.0
_QUALITY_TOLERANCE = 0.005
_DARK_FRAME_ERODE = 5


@dataclass(frozen=True)
class EdgeSegment:
    """A piece of an anchor-box edge. ``horizontal`` edges constrain y, vertical edges x."""

    horizontal: bool
    peak: float  # template coordinate of the line across the edge (sub-pixel)
    lo: int  # span along the edge
    hi: int
    strength: float


@dataclass(frozen=True)
class TemplateFeatures:
    size: tuple[int, int]
    profile: PrintProfile
    anchor_source: str  # "print" | "dark"
    ecc_levels: tuple[tuple[float, np.ndarray], ...]  # (scale, blurred float32 mask)
    orientation: np.ndarray  # blurred float32 mask at cfg.orientation_scale
    print_bbox: tuple[float, float, float, float]
    quality_mask: np.ndarray  # bool, at cfg.quality_scale, dilated
    segments: tuple[EdgeSegment, ...]
    orb_points: np.ndarray  # (N, 2) at cfg.orb_scale
    orb_descriptors: np.ndarray





# --------------------------------------------------------------------------- mask helpers


def downscale_mask(mask: np.ndarray, scale: float) -> np.ndarray:
    """uint8 0/255 mask -> float32 [0, 1] at ``scale`` using area averaging."""
    h, w = mask.shape[:2]
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    return cv2.resize(mask, size, interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0


def blur(img: np.ndarray, sigma: float) -> np.ndarray:
    return cv2.GaussianBlur(img, (0, 0), sigma) if sigma > 0 else img


def content_bbox(mask: np.ndarray, pct: float = 0.5) -> tuple[float, float, float, float] | None:
    ys, xs = np.nonzero(mask)
    if len(xs) < 100:
        return None
    x0, x1 = np.percentile(xs, [pct, 100 - pct])
    y0, y1 = np.percentile(ys, [pct, 100 - pct])
    if x1 - x0 < 10 or y1 - y0 < 10:
        return None
    return float(x0), float(y0), float(x1), float(y1)


def _quality_binary(mask_small: np.ndarray, dilate_px: int) -> np.ndarray:
    binary = (mask_small > 0.25).astype(np.uint8)
    if dilate_px > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * dilate_px + 1, 2 * dilate_px + 1))
        binary = cv2.dilate(binary, k)
    return binary.astype(bool)


# --------------------------------------------------------------------------- template features


def _profile(maskf: np.ndarray, horizontal: bool, center: int, lo: int, hi: int, radius: int) -> np.ndarray:
    h, w = maskf.shape
    a, b = center - radius, center + radius + 1
    if horizontal:
        if a < 0 or b > h:
            return np.zeros(0, np.float32)
        return maskf[a:b, lo:hi].mean(axis=1)
    if a < 0 or b > w:
        return np.zeros(0, np.float32)
    return maskf[lo:hi, a:b].mean(axis=0)


def _peak(profile: np.ndarray, dominance: float, min_snr: float = 0.0) -> tuple[float, float] | None:
    """Return (sub-pixel index, strength above the median) of a single dominant peak, or None."""
    if profile.size < 5:
        return None
    p = profile - float(np.median(profile))
    i = int(np.argmax(p))
    strength = float(p[i])
    if strength <= 1e-6 or i == 0 or i == p.size - 1:
        return None
    # the peak's own extent (above half maximum, at least +-2 px) is excluded from the
    # dominance test, so thick lines are not mistaken for two competing lines
    a, b = i, i
    while a > 0 and p[a - 1] > 0.5 * strength:
        a -= 1
    while b < p.size - 1 and p[b + 1] > 0.5 * strength:
        b += 1
    a, b = min(a, i - 2), max(b, i + 2)
    if a <= 0 or b >= p.size - 1:
        return None
    others = np.concatenate([p[:a], p[b + 1 :]])
    if others.size and float(others.max()) >= dominance * strength:
        return None
    if min_snr > 0 and others.size:
        noise = 1.4826 * float(np.median(np.abs(others - np.median(others))))
        if strength < min_snr * max(noise, 1e-4):
            return None
    if b - a > 4:  # wide (thick) line: centroid of the above-half-maximum part
        idx = np.arange(a, b + 1)
        w = np.clip(p[a : b + 1] - 0.5 * strength, 0, None)
        return float((idx * w).sum() / w.sum()), strength
    left, mid, right = float(p[i - 1]), strength, float(p[i + 1])
    denom = left - 2 * mid + right
    offset = 0.5 * (left - right) / denom if abs(denom) > 1e-9 else 0.0
    return i + float(np.clip(offset, -0.5, 0.5)), strength


def edge_map(norm_bgr: np.ndarray, profile: PrintProfile, anchor_source: str, cfg: EngineConfig) -> np.ndarray:
    """float32 map used to locate panel edges: smoothed print strength, or darkness for black frames.

    Thick black frames would give a wide, flat-topped profile, so the darkness map is eroded first:
    the frames shrink to a thin core line (sharp peak on the line centre) and thin text vanishes.
    """
    if anchor_source == "dark":
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (_DARK_FRAME_ERODE, _DARK_FRAME_ERODE))
        return blur(cv2.erode(ink_strength(norm_bgr, cfg), k).astype(np.float32) / 255.0, 1.0)
    return blur(profile.strength(norm_bgr).astype(np.float32) / 255.0, 1.0)


def _anchor_segments(maskf: np.ndarray, tpl: Template, cfg: EngineConfig) -> tuple[EdgeSegment, ...]:
    radius = cfg.anchor_search_px
    n = cfg.anchor_segments_per_edge
    segments: list[EdgeSegment] = []
    for x, y, w, h in tpl.spec.anchors.values():
        edges = [
            (True, y, x, x + w),
            (True, y + h, x, x + w),
            (False, x, y, y + h),
            (False, x + w, y, y + h),
        ]
        for horizontal, line, start, end in edges:
            trim = int((end - start) * _ANCHOR_EDGE_TRIM)
            bounds = np.linspace(start + trim, end - trim, n + 1).round().astype(int)
            for lo, hi in zip(bounds[:-1], bounds[1:], strict=True):
                # Locate the printed line near the nominal anchor coordinate, then re-centre on it
                # and require that it is the only line within the search window.
                coarse = _peak(_profile(maskf, horizontal, line, lo, hi, radius), dominance=1.0)
                if coarse is None:
                    continue
                center = int(round(line - radius + coarse[0]))
                found = _peak(_profile(maskf, horizontal, center, lo, hi, radius), _TEMPLATE_DOMINANCE)
                if found is None:
                    continue
                segments.append(EdgeSegment(horizontal, center - radius + found[0], int(lo), int(hi), found[1]))
    return tuple(segments)


def _build_features(tpl: Template, cfg: EngineConfig) -> TemplateFeatures:
    norm = normalize_illumination(tpl.reference, cfg)
    profile = tpl.print_profile
    mag = print_mask(to_hsv(norm), profile, cfg)
    levels = tuple(
        (s, blur(downscale_mask(mag, s), sigma)) for s, sigma in zip(cfg.ecc_scales, cfg.ecc_blur_sigmas, strict=True)
    )
    orientation = blur(downscale_mask(mag, cfg.orientation_scale), 1.5)
    bbox = content_bbox(mag)
    if bbox is None:
        raise ValueError(f"template {tpl.id} has no {profile.name} print")
    quality = _quality_binary(downscale_mask(mag, cfg.quality_scale), cfg.quality_dilate_px)
    segments = _anchor_segments(edge_map(norm, profile, tpl.spec.anchor_source, cfg), tpl, cfg)
    gray = cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, None, fx=cfg.orb_scale, fy=cfg.orb_scale, interpolation=cv2.INTER_AREA)
    kps, des = cv2.ORB_create(nfeatures=cfg.orb_features).detectAndCompute(small, None)
    points = np.array([kp.pt for kp in kps], np.float32).reshape(-1, 2)
    return TemplateFeatures(
        size=tpl.size,
        profile=profile,
        anchor_source=tpl.spec.anchor_source,
        ecc_levels=levels,
        orientation=orientation,
        print_bbox=bbox,
        quality_mask=quality,
        segments=segments,
        orb_points=points,
        orb_descriptors=des if des is not None else np.zeros((0, 32), np.uint8),
    )


def template_features(tpl: Template, cfg: EngineConfig) -> TemplateFeatures:
    """Registration features of ``tpl`` for ``cfg`` (computed once, then cached on the template)."""
    return tpl.cached(("features", cfg), lambda: _build_features(tpl, cfg))


# --------------------------------------------------------------------------- quality


class _QualityScorer:
    """IoU of the warped (dilated) print mask vs the template mask, at reduced resolution."""

    def __init__(self, page_print: np.ndarray, feats: TemplateFeatures, cfg: EngineConfig) -> None:
        self._cfg = cfg
        self._feats = feats
        self._small = downscale_mask(page_print, cfg.quality_scale)

    def __call__(self, h: np.ndarray) -> float:
        tmask = self._feats.quality_mask
        size = (tmask.shape[1], tmask.shape[0])
        warped = warp_to_template(self._small, rescale_homography(h, self._cfg.quality_scale), size,
                                  border=cv2.BORDER_CONSTANT)
        binary = _quality_binary(warped, self._cfg.quality_dilate_px)
        union = np.logical_or(binary, tmask).sum()
        return float(np.logical_and(binary, tmask).sum() / union) if union else 0.0


# --------------------------------------------------------------------------- (a) ECC


def _ecc(page_print: np.ndarray, feats: TemplateFeatures, cfg: EngineConfig) -> np.ndarray | None:
    """Coarse-to-fine ECC. A failure at a finer level keeps the last plausible coarser estimate."""
    w, hgt = feats.size
    h: np.ndarray | None = None
    current = np.eye(3)
    for (scale, tmpl), sigma, iterations in zip(feats.ecc_levels, cfg.ecc_blur_sigmas, cfg.ecc_iterations, strict=True):
        inp = blur(downscale_mask(page_print, scale), sigma)
        hs = rescale_homography(current, scale).astype(np.float32)
        criteria = (cv2.TERM_CRITERIA_COUNT | cv2.TERM_CRITERIA_EPS, iterations, cfg.ecc_eps)
        try:
            _, hs = cv2.findTransformECC(tmpl, inp, hs, cv2.MOTION_HOMOGRAPHY, criteria, None, 1)
        except cv2.error:
            break
        candidate = normalise(rescale_homography(hs.astype(np.float64), 1.0 / scale))
        if not is_plausible(candidate, w, hgt, cfg.max_corner_shift_frac):
            break
        h = current = candidate
    return h


# --------------------------------------------------------------------------- (b) ORB


def _orb(page_gray: np.ndarray, feats: TemplateFeatures, cfg: EngineConfig) -> np.ndarray | None:
    if len(feats.orb_points) < cfg.orb_min_inliers:
        return None
    s = cfg.orb_scale
    small = cv2.resize(page_gray, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    kps, des = cv2.ORB_create(nfeatures=cfg.orb_features).detectAndCompute(small, None)
    if des is None or len(kps) < cfg.orb_min_inliers:
        return None
    pts = np.array([kp.pt for kp in kps], np.float32)
    radius = cfg.orb_match_radius_px * s
    src, dst = [], []
    for pair in cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(feats.orb_descriptors, des, k=2):
        if len(pair) < 2 or pair[0].distance >= cfg.orb_ratio * pair[1].distance:
            continue
        p_t, p_i = feats.orb_points[pair[0].queryIdx], pts[pair[0].trainIdx]
        if float(np.hypot(*(p_t - p_i))) <= radius:
            src.append(p_t)
            dst.append(p_i)
    if len(src) < cfg.orb_min_inliers:
        return None
    cv2.setRNGSeed(cfg.random_seed)
    hs, inliers = cv2.findHomography(np.array(src), np.array(dst), cv2.RANSAC, cfg.ransac_reproj_px * s)
    if hs is None or inliers is None or int(inliers.sum()) < cfg.orb_min_inliers:
        return None
    h = normalise(rescale_homography(hs, 1.0 / s))
    w, hgt = feats.size
    return h if is_plausible(h, w, hgt, cfg.max_corner_shift_frac) else None


# --------------------------------------------------------------------------- (c) anchors


@dataclass(frozen=True)
class EdgeMeasurements:
    """Normal offsets of the anchor-box edges found in an aligned edge map."""

    rows: np.ndarray  # (N, 6) design matrix of the affine correction
    offsets: np.ndarray  # (N,) measured offset along the edge normal, template px
    horizontal: np.ndarray  # (N,) bool
    total_horizontal: int  # number of usable template segments per direction
    total_vertical: int


def measure_edges(aligned_edges: np.ndarray, feats: TemplateFeatures, cfg: EngineConfig) -> EdgeMeasurements:
    """Offsets of the anchor edges in an aligned ``edge_map`` image."""
    radius = cfg.anchor_search_px
    w, h = feats.size
    rows: list[list[float]] = []
    offsets: list[float] = []
    horizontal: list[bool] = []
    for seg in feats.segments:
        center = int(round(seg.peak))
        profile = _profile(aligned_edges, seg.horizontal, center, seg.lo, seg.hi, radius)
        found = _peak(profile, _INPUT_DOMINANCE, _MIN_EDGE_SNR)
        if found is None or found[1] < _MIN_EDGE_STRENGTH * seg.strength:
            continue
        mid = (seg.lo + seg.hi) / 2.0
        if seg.horizontal:
            rows.append([0, 0, 0, 1, mid / w, seg.peak / h])
        else:
            rows.append([1, seg.peak / w, mid / h, 0, 0, 0])
        offsets.append(center - radius + found[0] - seg.peak)
        horizontal.append(seg.horizontal)
    n_h = sum(1 for s in feats.segments if s.horizontal)
    return EdgeMeasurements(
        rows=np.array(rows, np.float64).reshape(-1, 6),
        offsets=np.array(offsets, np.float64),
        horizontal=np.array(horizontal, bool),
        total_horizontal=n_h,
        total_vertical=len(feats.segments) - n_h,
    )


def refine_with_anchors(aligned_edges: np.ndarray, feats: TemplateFeatures, cfg: EngineConfig) -> np.ndarray | None:
    """Affine correction C (template -> aligned coordinates) from the anchor-box edge positions.

    Each edge segment measures the offset of a printed panel line along its normal; the six
    affine parameters are solved by least squares with iterative outlier rejection.
    """
    m = measure_edges(aligned_edges, feats, cfg)
    w, h = feats.size
    n_h = int(m.horizontal.sum())
    if n_h < cfg.anchor_min_constraints or len(m.offsets) - n_h < cfg.anchor_min_constraints:
        return None
    keep = np.ones(len(m.offsets), bool)
    params = np.zeros(6)
    for _ in range(3):
        params, *_ = np.linalg.lstsq(m.rows[keep], m.offsets[keep], rcond=None)
        residual = np.abs(m.rows @ params - m.offsets)
        new_keep = residual <= cfg.anchor_outlier_px
        if new_keep.sum() < 2 * cfg.anchor_min_constraints or np.array_equal(new_keep, keep):
            break
        keep = new_keep
    a0, a1, a2, a3, a4, a5 = params
    correction = np.array([[1 + a1 / w, a2 / h, a0], [a4 / w, 1 + a5 / h, a3], [0.0, 0.0, 1.0]])
    if not is_plausible(correction, w, h, cfg.anchor_search_px / float(np.hypot(w, h))):
        return None
    return correction

# --------------------------------------------------------------------------- driver


@dataclass(frozen=True)
class Registration:
    homography: np.ndarray  # template -> page-normalised image coordinates
    method: RegistrationMethod
    quality: float


def register(page_print: np.ndarray, page_norm: np.ndarray, feats: TemplateFeatures, cfg: EngineConfig) -> Registration:
    """Find the homography template -> page-normalised image, choosing the best layer by quality.

    ``page_print`` is the binary print-colour mask and ``page_norm`` the illumination-normalised BGR
    page image, both in coarse (page-normalised) template space.
    """
    quality = _QualityScorer(page_print, feats, cfg)
    candidates = [(np.eye(3), "identity", quality(np.eye(3)))]

    h_ecc = _ecc(page_print, feats, cfg)
    if h_ecc is not None:
        candidates.append((h_ecc, "ecc", quality(h_ecc)))
    homography, method, q_best = max(candidates, key=lambda c: c[2])

    if q_best < cfg.orb_trigger_quality:
        h_orb = _orb(cv2.cvtColor(page_norm, cv2.COLOR_BGR2GRAY), feats, cfg)
        if h_orb is not None:
            q = quality(h_orb)
            # ORB is noisier than ECC on these repetitive layouts: it must win clearly.
            margin = cfg.orb_min_gain if method == "ecc" else 0.0
            if q > q_best + margin:
                homography, method, q_best = h_orb, "orb", q

    page_edges = edge_map(page_norm, feats.profile, feats.anchor_source, cfg)
    size = feats.size
    correction = refine_with_anchors(warp_to_template(page_edges, homography, size), feats, cfg)
    if correction is not None:
        h_ref = normalise(homography @ correction)
        q = quality(h_ref)
        if q >= q_best - _QUALITY_TOLERANCE:
            homography, method, q_best = h_ref, "anchors", q

    return Registration(homography, method, q_best)