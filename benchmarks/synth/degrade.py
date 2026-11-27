"""Degradation tiers that turn a clean 1700x2200 render into realistic inputs.

Tiers (ARCHITECTURE.md section 10), all driven by a ``numpy.random.Generator``:

clean  digital render, unchanged (1700x2200).
scan   flatbed scan: +-2 deg rotation, 0.97-1.03 scale, small shift, resampled to
       150-300 dpi (output is a Letter page at that dpi), faint grey scanner-lid
       border, slight blur, gaussian noise, JPEG q60-90.
photo  phone photo: page printed on slightly cream paper, gentle paper bend,
       perspective warp onto a textured / dark desk with the page smaller than the
       frame, drop shadow, uneven illumination + shadow band, colour cast,
       defocus blur, sensor noise, JPEG q70-92. Frames 1200x1600 .. 3000x4000.
hard   like photo but strong perspective, stronger bend and shadows, low
       resolution frame, motion blur, more noise, JPEG q50-75.

``degrade(img, tier, rng) -> (image, meta)``; ``meta`` is JSON-serialisable and
records every sampled parameter (including the page->frame homography, which
ignores the small non-linear bend).
"""
from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np

TIERS: tuple[str, ...] = ("clean", "scan", "photo", "hard")


# --------------------------------------------------------------------------- #
# shared helpers
# --------------------------------------------------------------------------- #
def _jpeg(img: np.ndarray, q: int) -> np.ndarray:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(q)])
    if not ok:  # pragma: no cover
        raise RuntimeError("jpeg encode failed")
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def _smooth_noise(rng: np.random.Generator, h: int, w: int, cells: int) -> np.ndarray:
    """Low-frequency noise in [0, 1] of size (h, w)."""
    ch = max(2, int(cells * h / max(h, w)) + 1)
    cw = max(2, int(cells * w / max(h, w)) + 1)
    g = rng.random((ch, cw)).astype(np.float32)
    n = cv2.resize(g, (w, h), interpolation=cv2.INTER_CUBIC)
    n -= n.min()
    return n / max(float(n.max()), 1e-6)


def _paper_and_print(page: np.ndarray, rng: np.random.Generator, strength: float) -> tuple[np.ndarray, dict]:
    """Printed-on-paper look: cream paper tone, print density, fibre texture."""
    f = page.astype(np.float32) / 255.0
    tone = np.array([rng.uniform(0.93, 1.0), rng.uniform(0.96, 1.0), rng.uniform(0.98, 1.0)], np.float32)
    tone = 1.0 - (1.0 - tone) * strength
    gamma = float(rng.uniform(0.9, 1.15))
    f = np.power(f, gamma) * tone.reshape(1, 1, 3)
    h, w = page.shape[:2]
    tex = (_smooth_noise(rng, h // 4, w // 4, 60) - 0.5) * 0.03 * strength
    tex = cv2.resize(tex, (w, h), interpolation=cv2.INTER_LINEAR)
    f = f + tex[..., None]
    out = np.clip(f * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return out, {"paper_tone": tone.tolist(), "print_gamma": gamma}


def _bend(page: np.ndarray, rng: np.random.Generator, amp_lo: float, amp_hi: float) -> tuple[np.ndarray, dict]:
    """Gentle non-linear paper curl (template-px amplitude), remapped on the page itself."""
    h, w = page.shape[:2]
    ax = float(rng.uniform(amp_lo, amp_hi)) * (1 if rng.random() < 0.5 else -1)
    ay = float(rng.uniform(amp_lo, amp_hi)) * (1 if rng.random() < 0.5 else -1)
    if abs(ax) < 0.05 and abs(ay) < 0.05:
        return page, {"bend_px": [0.0, 0.0]}
    # compute the displacement field at low resolution, upscale
    sh, sw = h // 8, w // 8
    yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)
    u, v = xx / max(sw - 1, 1), yy / max(sh - 1, 1)
    dy = ay * np.sin(np.pi * u) * (0.6 + 0.4 * v)  # bow along x (page sags)
    dx = ax * np.sin(np.pi * v) * (0.6 + 0.4 * u)
    dx = cv2.resize(dx, (w, h), interpolation=cv2.INTER_LINEAR)
    dy = cv2.resize(dy, (w, h), interpolation=cv2.INTER_LINEAR)
    gy, gx = np.mgrid[0:h, 0:w].astype(np.float32)
    out = cv2.remap(page, gx + dx, gy + dy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return out, {"bend_px": [ax, ay]}


def _desk_background(rng: np.random.Generator, h: int, w: int, kind: str) -> np.ndarray:
    """Textured desk / table / fabric background (BGR uint8)."""
    sh, sw = max(8, h // 4), max(8, w // 4)
    if kind == "wood":
        base = np.array([rng.uniform(40, 90), rng.uniform(80, 130), rng.uniform(120, 180)], np.float32)  # BGR brown
        yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)
        warp = _smooth_noise(rng, sh, sw, 6) * rng.uniform(10, 30)
        freq = rng.uniform(0.05, 0.15)
        grain = 0.5 + 0.5 * np.sin((xx if rng.random() < 0.5 else yy) * freq + warp)
        fine = _smooth_noise(rng, sh, sw, max(sh, sw) // 3)
        lum = 0.75 + 0.2 * grain + 0.1 * fine
    elif kind == "dark":
        base = np.array([rng.uniform(25, 55)] * 3, np.float32) + rng.uniform(-8, 8, 3).astype(np.float32)
        lum = 0.8 + 0.3 * _smooth_noise(rng, sh, sw, 10) + 0.15 * rng.random((sh, sw)).astype(np.float32)
    else:  # "table": light grey / beige laminate with speckle
        g = rng.uniform(120, 190)
        base = np.array([g * rng.uniform(0.85, 1.0), g * rng.uniform(0.9, 1.0), g], np.float32)
        lum = 0.85 + 0.15 * _smooth_noise(rng, sh, sw, 8) + 0.08 * rng.random((sh, sw)).astype(np.float32)
    bg = lum[..., None] * base.reshape(1, 1, 3)
    bg = cv2.resize(bg, (w, h), interpolation=cv2.INTER_LINEAR)
    return np.clip(bg, 0, 255).astype(np.uint8)


def _illumination(rng: np.random.Generator, h: int, w: int, grad_min: float, shadow_dark: tuple[float, float],
                  shadow_prob: float) -> tuple[np.ndarray, dict]:
    """Multiplicative light field: linear gradient x vignette x optional soft shadow band."""
    sh, sw = max(8, h // 8), max(8, w // 8)
    yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)
    u, v = xx / (sw - 1), yy / (sh - 1)
    ang = rng.uniform(0, 2 * np.pi)
    proj = (u - 0.5) * math.cos(ang) + (v - 0.5) * math.sin(ang)
    proj = (proj - proj.min()) / max(float(np.ptp(proj)), 1e-6)
    g0 = float(rng.uniform(grad_min, 1.0))
    light = g0 + (1.0 - g0) * proj
    vig = float(rng.uniform(0.0, 0.25))
    light *= 1.0 - vig * ((u - 0.5) ** 2 + (v - 0.5) ** 2) * 2
    meta: dict[str, Any] = {"gradient_min": g0, "vignette": vig, "shadow": None}
    if rng.random() < shadow_prob:
        # soft shadow cast by a hand / phone: a half-plane with blurred edge
        sang = rng.uniform(0, 2 * np.pi)
        off = rng.uniform(-0.1, 0.35)
        d = (u - 0.5) * math.cos(sang) + (v - 0.5) * math.sin(sang) - off
        soft = rng.uniform(0.03, 0.12)
        mask = 1.0 / (1.0 + np.exp(-d / soft))
        dark = float(rng.uniform(*shadow_dark))
        light *= 1.0 - (1.0 - dark) * mask
        meta["shadow"] = {"darkness": dark, "angle": sang, "offset": off}
    light = cv2.resize(light.astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR)
    return light, meta


def _motion_kernel(length: int, angle_deg: float) -> np.ndarray:
    k = np.zeros((length, length), np.float32)
    c = (length - 1) / 2.0
    dx, dy = math.cos(math.radians(angle_deg)) * c, math.sin(math.radians(angle_deg)) * c
    cv2.line(k, (int(round(c - dx)), int(round(c - dy))), (int(round(c + dx)), int(round(c + dy))), 1.0, 1, cv2.LINE_AA)
    return k / max(float(k.sum()), 1e-6)


# --------------------------------------------------------------------------- #
# tiers
# --------------------------------------------------------------------------- #
def _scan(img: np.ndarray, rng: np.random.Generator) -> tuple[np.ndarray, dict]:
    page, meta = _paper_and_print(img, rng, strength=0.5)
    h, w = page.shape[:2]
    dpi = int(rng.integers(150, 301))
    out_w, out_h = int(round(8.5 * dpi)), int(round(11 * dpi))
    rot = float(rng.uniform(-2.0, 2.0))
    scale = float(rng.uniform(0.97, 1.03))
    k = out_w / w * scale
    tx = float(rng.uniform(-0.012, 0.012)) * out_w
    ty = float(rng.uniform(-0.012, 0.012)) * out_h
    M = cv2.getRotationMatrix2D((w / 2, h / 2), rot, k)
    M[0, 2] += out_w / 2 - w / 2 + tx
    M[1, 2] += out_h / 2 - h / 2 + ty
    lid = int(rng.integers(215, 250))
    out = cv2.warpAffine(page, M, (out_w, out_h), flags=cv2.INTER_AREA if k < 1 else cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_CONSTANT, borderValue=(lid, lid, lid))
    sigma_blur = float(rng.uniform(0.3, 0.8)) * dpi / 200
    out = cv2.GaussianBlur(out, (0, 0), sigma_blur)
    noise = float(rng.uniform(1.5, 5.0))
    f = out.astype(np.float32) + rng.normal(0, noise, out.shape).astype(np.float32)
    # faint grey cast typical of scanners
    f *= float(rng.uniform(0.95, 1.0))
    out = np.clip(f + 0.5, 0, 255).astype(np.uint8)
    q = int(rng.integers(60, 91))
    out = _jpeg(out, q)
    H = np.vstack([M, [0, 0, 1]])
    meta.update({"dpi": dpi, "rotation_deg": rot, "scale": scale, "shift_px": [tx, ty], "lid_grey": lid,
                 "blur_sigma": sigma_blur, "noise_sigma": noise, "jpeg_q": q, "homography": H.tolist()})
    return out, meta


_PHOTO_FRAMES = [(1200, 1600), (1536, 2048), (1920, 2560), (2448, 3264), (3000, 4000)]
_PHOTO_FRAME_P = [0.1, 0.25, 0.3, 0.25, 0.1]
_HARD_FRAMES = [(1080, 1440), (1200, 1600), (1536, 2048)]


def _photo_like(img: np.ndarray, rng: np.random.Generator, hard: bool) -> tuple[np.ndarray, dict]:
    page, meta = _paper_and_print(img, rng, strength=1.0)
    page, bmeta = _bend(page, rng, *( (2.0, 8.0) if hard else (0.0, 3.0) ))
    meta.update(bmeta)
    ph, pw = page.shape[:2]
    if hard:
        fw, fh = _HARD_FRAMES[int(rng.integers(len(_HARD_FRAMES)))]
    else:
        fw, fh = _PHOTO_FRAMES[int(rng.choice(len(_PHOTO_FRAMES), p=_PHOTO_FRAME_P))]

    # page size and placement in the frame
    frac = float(rng.uniform(0.62, 0.85) if hard else rng.uniform(0.6, 0.88))
    page_h = frac * fh
    page_w = page_h * pw / ph
    if page_w > 0.92 * fw:
        page_w = 0.92 * fw
        page_h = page_w * ph / pw
    rot = math.radians(rng.uniform(-12, 12) if hard else rng.uniform(-6, 6))
    persp = float(rng.uniform(0.06, 0.14) if hard else rng.uniform(0.0, 0.07))
    cx = fw / 2 + rng.uniform(-0.08, 0.08) * fw
    cy = fh / 2 + rng.uniform(-0.06, 0.06) * fh
    base = np.array([[-page_w / 2, -page_h / 2], [page_w / 2, -page_h / 2],
                     [page_w / 2, page_h / 2], [-page_w / 2, page_h / 2]])
    # keystone: one edge shorter (camera tilt) + per-corner jitter
    tilt_axis = int(rng.integers(0, 2))
    tilt = rng.uniform(-1, 1) * persp
    if tilt_axis == 0:  # top/bottom edge length differs
        base[:2, 0] *= 1 - tilt
        base[2:, 0] *= 1 + tilt
    else:
        base[[0, 3], 1] *= 1 - tilt
        base[[1, 2], 1] *= 1 + tilt
    base += rng.uniform(-0.35, 0.35, base.shape) * persp * page_h
    cr, sr = math.cos(rot), math.sin(rot)
    dst = base @ np.array([[cr, sr], [-sr, cr]]) + np.array([cx, cy])
    # shrink about centre until every corner sits inside a 2.5 % margin
    margin = 0.025 * min(fw, fh)
    for _ in range(40):
        if (dst[:, 0].min() >= margin and dst[:, 0].max() <= fw - margin
                and dst[:, 1].min() >= margin and dst[:, 1].max() <= fh - margin):
            break
        c = dst.mean(axis=0)
        dst = c + (dst - c) * 0.97
        dst += np.clip(np.array([fw / 2, fh / 2]) - c, -10, 10) * 0.2
    src = np.array([[0, 0], [pw, 0], [pw, ph], [0, ph]], np.float32)
    H = cv2.getPerspectiveTransform(src, dst.astype(np.float32))

    bg_kind = ["wood", "dark", "table"][int(rng.integers(3))]
    frame = _desk_background(rng, fh, fw, bg_kind)
    # drop shadow of the page on the desk
    mask_small = np.zeros((fh // 4, fw // 4), np.float32)
    sd = rng.uniform(0.005, 0.02) * fh
    sdir = rng.uniform(0, 2 * np.pi)
    shadow_quad = (dst + np.array([math.cos(sdir), math.sin(sdir)]) * sd) / 4
    cv2.fillPoly(mask_small, [np.round(shadow_quad).astype(np.int32)], 1.0)
    mask_small = cv2.GaussianBlur(mask_small, (0, 0), max(1.0, sd / 4))
    shadow = cv2.resize(mask_small, (fw, fh), interpolation=cv2.INTER_LINEAR)
    frame = (frame.astype(np.float32) * (1 - 0.45 * shadow[..., None]))

    warped = cv2.warpPerspective(page, H, (fw, fh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    pmask = cv2.warpPerspective(np.full((ph, pw), 255, np.uint8), H, (fw, fh), flags=cv2.INTER_LINEAR,
                                borderMode=cv2.BORDER_CONSTANT, borderValue=0).astype(np.float32)[..., None] / 255.0
    f = warped.astype(np.float32) * pmask + frame * (1 - pmask)

    light, lmeta = _illumination(
        rng, fh, fw, grad_min=0.55 if hard else 0.72,
        shadow_dark=(0.4, 0.65) if hard else (0.6, 0.85), shadow_prob=0.85 if hard else 0.5,
    )
    # white-balance error: colour temperature (warm = less blue / more red) + small green tint
    temp = float(rng.uniform(-1.0, 0.6) if hard else rng.uniform(-0.7, 0.5))  # <0 warm (tungsten), >0 cool
    tint = float(rng.uniform(-0.02, 0.03))
    cast = np.array([1.0 + 0.12 * temp, 1.0 + tint, 1.0 - 0.08 * temp], np.float32)
    cast /= float(cast.max())
    cast *= float(rng.uniform(1.0, 1.05))
    exposure = float(rng.uniform(0.85, 1.08))
    f *= (light * exposure)[..., None]
    f *= cast.reshape(1, 1, 3)

    # optics: defocus (+ motion for hard). Sigma scales with frame size.
    scale_px = fh / 2000.0
    blur = float(rng.uniform(0.5, 1.4) if hard else rng.uniform(0.3, 1.2)) * scale_px
    f = cv2.GaussianBlur(f, (0, 0), blur)
    motion = None
    if hard:
        L = int(rng.integers(3, 8))
        if L % 2 == 0:
            L += 1
        mang = float(rng.uniform(0, 180))
        f = cv2.filter2D(f, -1, _motion_kernel(L, mang))
        motion = {"length": L, "angle_deg": mang}
    noise = float(rng.uniform(4.0, 9.0) if hard else rng.uniform(2.0, 5.0))
    f += rng.normal(0, noise, (fh, fw, 1)).astype(np.float32)  # luma noise
    f += rng.normal(0, noise * 0.4, (fh, fw, 3)).astype(np.float32)  # chroma noise
    out = np.clip(f + 0.5, 0, 255).astype(np.uint8)
    q = int(rng.integers(50, 76) if hard else rng.integers(70, 93))
    out = _jpeg(out, q)
    meta.update({
        "frame": [fw, fh], "page_frac": frac, "rotation_deg": math.degrees(rot), "perspective": persp,
        "background": bg_kind, "illumination": lmeta, "colour_temp": temp, "colour_cast_bgr": cast.tolist(),
        "exposure": exposure,
        "blur_sigma": blur, "motion_blur": motion, "noise_sigma": noise, "jpeg_q": q,
        "page_quad": dst.tolist(), "homography": H.tolist(),
    })
    return out, meta


def degrade(img: np.ndarray, tier: str, rng: np.random.Generator) -> tuple[np.ndarray, dict[str, Any]]:
    """Apply a degradation tier to a clean BGR render. Returns (image, meta)."""
    if tier == "clean":
        return img.copy(), {"tier": "clean", "homography": np.eye(3).tolist()}
    if tier == "scan":
        out, meta = _scan(img, rng)
    elif tier == "photo":
        out, meta = _photo_like(img, rng, hard=False)
    elif tier == "hard":
        out, meta = _photo_like(img, rng, hard=True)
    else:
        raise ValueError(f"unknown tier {tier!r}; expected one of {TIERS}")
    meta["tier"] = tier
    meta["size"] = [int(out.shape[1]), int(out.shape[0])]
    return out, meta
