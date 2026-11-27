"""Realistic-ish ballpoint pen marks for synthetic OMR sheets.

Everything is rendered as a float alpha patch (supersampled for antialiasing)
and composited onto the page with a *multiply* blend, which is how pen ink on
paper behaves: magenta print under the ink stays faintly visible and darkens.

All randomness comes from a ``numpy.random.Generator`` passed in by the caller,
so a given seed always produces the same pixels.

Mark styles
-----------
Filled (ground truth = filled):
    solid      ballpoint fill: irregular disc + dense hatch strokes, pressure noise
    heavy      very dark, slightly oversized fill
    partial    60-85 % of the disc covered, lighter pressure
    scribble   zig-zag polyline strokes, visible gaps, varying thickness
    overshoot  fill that spills past the printed circle and is off-centre
Distractors (ground truth = NOT filled; the scanner may flag them ambiguous):
    tick       small check mark
    cross      small x
    smudge     faint grey low-contrast remains of an "erased" mark
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

FILL_STYLES: tuple[str, ...] = ("solid", "heavy", "partial", "scribble", "overshoot")
DISTRACTOR_STYLES: tuple[str, ...] = ("tick", "cross", "smudge")
ALL_STYLES: tuple[str, ...] = FILL_STYLES + DISTRACTOR_STYLES

_SS = 4  # supersampling factor for antialiasing


@dataclass(frozen=True)
class Pen:
    """A student's pen. ``color`` is BGR *transmittance* in [0, 1] (1 = no ink)."""

    kind: str  # "blue" | "black"
    color: tuple[float, float, float]
    pressure: float  # base opacity, 0.8 .. 1.0
    width: float  # stroke width in template px (200 dpi)


# Reference ballpoint colours (BGR transmittance).  Blue ballpoint is a fairly
# dark, saturated blue; black ballpoint is a slightly bluish near-black.
_BLUE = np.array([0.50, 0.20, 0.10])
_BLACK = np.array([0.17, 0.15, 0.15])


def random_pen(rng: np.random.Generator, kind: str | None = None) -> Pen:
    """Pick a pen with slight per-sheet colour / pressure / width variation."""
    if kind is None:
        kind = "blue" if rng.random() < 0.6 else "black"
    base = _BLUE if kind == "blue" else _BLACK
    # common brightness shift + small per-channel hue shift (keeps black near-neutral)
    jitter = rng.uniform(-0.05, 0.05) + rng.uniform(-0.03, 0.03, 3) * (1.0 if kind == "blue" else 0.4)
    color = np.clip(base + jitter, 0.03, 0.75)
    return Pen(
        kind=kind,
        color=(float(color[0]), float(color[1]), float(color[2])),
        pressure=float(rng.uniform(0.88, 1.0)),
        width=float(rng.uniform(1.6, 2.8)),
    )


# --------------------------------------------------------------------------- #
# low-level helpers
# --------------------------------------------------------------------------- #
def _pressure_field(rng: np.random.Generator, shape: tuple[int, int], lo: float) -> np.ndarray:
    """Smooth random multiplicative opacity field in [lo, 1]."""
    g = rng.uniform(lo, 1.0, (4, 4)).astype(np.float32)
    f = cv2.resize(g, (shape[1], shape[0]), interpolation=cv2.INTER_CUBIC)
    return np.clip(f, lo, 1.0)


def _irregular_disc(rng: np.random.Generator, size: int, cx: float, cy: float, radius: float) -> np.ndarray:
    """Hand-filled blob: a polygon whose radius wobbles with a few harmonics. (SS scale)"""
    n = 64
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    rr = np.ones(n)
    for k in (2, 3, 5):
        rr += rng.uniform(-0.035, 0.035) * np.cos(k * t + rng.uniform(0, 2 * np.pi))
    pts = np.stack([cx + radius * rr * np.cos(t), cy + radius * rr * np.sin(t)], axis=1)
    m = np.zeros((size, size), np.uint8)
    cv2.fillPoly(m, [np.round(pts).astype(np.int32)], 255, cv2.LINE_AA)
    return m.astype(np.float32) / 255.0


def _zigzag(
    rng: np.random.Generator,
    size: int,
    cx: float,
    cy: float,
    half_w: float,
    half_h: float,
    angle: float,
    spacing: float,
    thick: float,
    thick_jitter: float = 0.3,
    turn_overshoot: float = 0.0,
) -> np.ndarray:
    """Back-and-forth strokes covering a (rotated) rectangle, as students fill bubbles. (SS scale)"""
    m = np.zeros((size, size), np.uint8)
    ca, sa = math.cos(angle), math.sin(angle)
    pts = []
    y = -half_h
    side = -1.0
    while y <= half_h + 1e-6:
        # chord half-length of a circle at this y gives a natural bubble-shaped fill
        frac = max(0.0, 1.0 - (y / max(half_h, 1e-6)) ** 2)
        hl = half_w * math.sqrt(frac) + turn_overshoot * rng.uniform(0.0, 1.0)
        x = side * hl
        pts.append((x, y + rng.normal(0, spacing * 0.12)))
        side = -side
        y += spacing * rng.uniform(0.8, 1.2)
    if len(pts) < 2:
        return m.astype(np.float32)
    for (x1, y1), (x2, y2) in zip(pts[:-1], pts[1:]):
        p1 = (cx + x1 * ca - y1 * sa, cy + x1 * sa + y1 * ca)
        p2 = (cx + x2 * ca - y2 * sa, cy + x2 * sa + y2 * ca)
        t = max(1, int(round(thick * rng.uniform(1 - thick_jitter, 1 + thick_jitter))))
        cv2.line(m, (int(round(p1[0])), int(round(p1[1]))), (int(round(p2[0])), int(round(p2[1]))), 255, t, cv2.LINE_AA)
    return m.astype(np.float32) / 255.0


def _polyline(m: np.ndarray, pts: np.ndarray, thick: float, rng: np.random.Generator, jitter: float = 0.25) -> None:
    """Draw a polyline with per-segment thickness variation (pressure). (SS scale, in-place)"""
    for a, b in zip(pts[:-1], pts[1:]):
        t = max(1, int(round(thick * rng.uniform(1 - jitter, 1 + jitter))))
        cv2.line(m, (int(round(a[0])), int(round(a[1]))), (int(round(b[0])), int(round(b[1]))), 255, t, cv2.LINE_AA)


def _finish(alpha_ss: np.ndarray, rng: np.random.Generator, blur_lo: float = 0.35, blur_hi: float = 0.8) -> np.ndarray:
    """Downsample supersampled alpha and add a slight optical blur."""
    size = alpha_ss.shape[0] // _SS
    a = cv2.resize(alpha_ss, (size, size), interpolation=cv2.INTER_AREA)
    s = rng.uniform(blur_lo, blur_hi)
    a = cv2.GaussianBlur(a, (0, 0), s)
    return np.clip(a, 0.0, 1.0).astype(np.float32)


# --------------------------------------------------------------------------- #
# mark renderers: return (alpha patch [h,w] float32, colour override or None)
# the patch is centred on the bubble centre
# --------------------------------------------------------------------------- #
def _patch_size(r: float, extra: float = 2.0) -> int:
    return int(math.ceil(r * extra + 6)) * 2 + 1


def render_mark(
    rng: np.random.Generator, style: str, r: float, pen: Pen
) -> tuple[np.ndarray, tuple[float, float, float] | None]:
    """Render a single mark for a bubble of radius ``r`` (template px).

    Returns the alpha patch (odd square, centred on the bubble) and an optional
    colour override (used by ``smudge``, which is greyer than the pen).
    """
    if style not in ALL_STYLES:
        raise ValueError(f"unknown mark style {style!r}")
    size = _patch_size(r)
    S = size * _SS
    c = S / 2.0
    R = r * _SS
    th = pen.width * _SS
    # small hand placement error
    ox, oy = rng.normal(0, 0.06 * R, 2)
    color: tuple[float, float, float] | None = None

    if style in ("solid", "heavy", "overshoot"):
        if style == "solid":
            rad = R * rng.uniform(0.88, 1.04)
            base_op = rng.uniform(0.86, 0.96)
            lo = 0.85
        elif style == "heavy":
            rad = R * rng.uniform(1.0, 1.12)
            base_op = rng.uniform(0.95, 1.0)
            lo = 0.93
        else:  # overshoot
            rad = R * rng.uniform(1.15, 1.35)
            ang = rng.uniform(0, 2 * np.pi)
            off = R * rng.uniform(0.08, 0.2)
            ox, oy = off * math.cos(ang), off * math.sin(ang)
            base_op = rng.uniform(0.82, 0.95)
            lo = 0.82
        disc = _irregular_disc(rng, S, c + ox, c + oy, rad)
        strokes = _zigzag(
            rng, S, c + ox, c + oy, rad * 1.02, rad * 0.97, rng.uniform(0, np.pi),
            spacing=th * rng.uniform(0.7, 1.1), thick=th, turn_overshoot=R * 0.06,
        )
        a = np.maximum(disc * base_op, strokes * np.clip(disc * 1.5, 0, 1))
        a *= _pressure_field(rng, a.shape, lo) * pen.pressure
        alpha = _finish(a, rng)

    elif style == "partial":
        rad = R * rng.uniform(0.9, 1.02)
        disc = _irregular_disc(rng, S, c + ox, c + oy, rad)
        cov = rng.uniform(0.60, 0.85)
        yy, xx = np.mgrid[0:S, 0:S].astype(np.float32)
        ang = rng.uniform(0, 2 * np.pi)
        proj = (xx - c) * math.cos(ang) + (yy - c) * math.sin(ang)
        # wavy cut edge instead of a perfect chord
        perp = -(xx - c) * math.sin(ang) + (yy - c) * math.cos(ang)
        proj = proj + 0.12 * R * np.sin(perp / R * rng.uniform(2.0, 4.0) + rng.uniform(0, 6.28))
        inside = disc > 0.5
        thr = float(np.quantile(proj[inside], cov)) if inside.any() else 0.0
        keep = cv2.GaussianBlur((proj <= thr).astype(np.float32), (0, 0), _SS * 0.8)
        strokes = _zigzag(rng, S, c + ox, c + oy, rad, rad * 0.95, rng.uniform(0, np.pi),
                          spacing=th * rng.uniform(1.0, 1.6), thick=th)
        op = rng.uniform(0.6, 0.9)
        a = np.maximum(disc * op, strokes * disc) * keep
        a *= _pressure_field(rng, a.shape, 0.7) * pen.pressure
        alpha = _finish(a, rng)

    elif style == "scribble":
        rad = R * rng.uniform(0.85, 1.05)
        strokes = _zigzag(
            rng, S, c + ox, c + oy, rad, rad * rng.uniform(0.8, 0.98), rng.uniform(0, np.pi),
            spacing=th * rng.uniform(1.0, 1.6), thick=th * rng.uniform(1.1, 1.6),
            thick_jitter=0.4, turn_overshoot=R * 0.18,
        )
        # often a second, crossing pass
        if rng.random() < 0.6:
            strokes = np.maximum(strokes, _zigzag(
                rng, S, c + ox, c + oy, rad * 0.9, rad * 0.85, rng.uniform(0, np.pi),
                spacing=th * rng.uniform(1.8, 3.0), thick=th, thick_jitter=0.4,
            ))
        a = strokes * _pressure_field(rng, strokes.shape, 0.75) * pen.pressure
        alpha = _finish(a, rng, 0.3, 0.6)

    elif style == "tick":
        m = np.zeros((S, S), np.uint8)
        sz = R * rng.uniform(0.8, 1.15)
        rot = rng.uniform(-0.3, 0.3)
        base = np.array([[-0.55, -0.05], [-0.15, 0.45], [0.65, -0.7]])
        base[:, 0] += rng.normal(0, 0.05, 3)
        base[:, 1] += rng.normal(0, 0.05, 3)
        cr, sr = math.cos(rot), math.sin(rot)
        rotm = np.array([[cr, -sr], [sr, cr]])
        pts = (base @ rotm.T) * sz + np.array([c + ox, c + oy])
        # densify for a curved, pressure-varying stroke
        dense = np.concatenate([np.linspace(pts[i], pts[i + 1], 6) for i in range(2)])
        dense += rng.normal(0, 0.15 * _SS, dense.shape)
        _polyline(m, dense, th * rng.uniform(0.9, 1.2), rng)
        a = (m.astype(np.float32) / 255.0) * pen.pressure
        alpha = _finish(a, rng, 0.3, 0.6)

    elif style == "cross":
        m = np.zeros((S, S), np.uint8)
        sz = R * rng.uniform(0.55, 0.85)
        rot = rng.uniform(-0.35, 0.35)
        for k in (0, 1):
            ang = rot + (np.pi / 4 if k == 0 else -np.pi / 4)
            d = np.array([math.cos(ang), math.sin(ang)]) * sz
            p1 = np.array([c + ox, c + oy]) - d * rng.uniform(0.85, 1.1)
            p2 = np.array([c + ox, c + oy]) + d * rng.uniform(0.85, 1.1)
            dense = np.linspace(p1, p2, 6) + rng.normal(0, 0.15 * _SS, (6, 2))
            _polyline(m, dense, th * rng.uniform(0.9, 1.2), rng)
        a = (m.astype(np.float32) / 255.0) * pen.pressure
        alpha = _finish(a, rng, 0.3, 0.6)

    else:  # smudge: faint, grey, low-contrast leftover of an erased fill
        rad = R * rng.uniform(0.8, 1.2)
        disc = _irregular_disc(rng, S, c + ox, c + oy, rad)
        strokes = _zigzag(rng, S, c + ox, c + oy, rad, rad * 0.9, rng.uniform(0, np.pi),
                          spacing=th * 1.5, thick=th)
        a = np.maximum(disc * 0.6, strokes) * _pressure_field(rng, disc.shape, 0.4)
        a = cv2.GaussianBlur(a, (0, 0), _SS * rng.uniform(1.5, 3.0))
        a *= rng.uniform(0.22, 0.40)
        alpha = _finish(a, rng, 0.6, 1.0)
        pc = np.array(pen.color)
        grey = np.array([0.6, 0.6, 0.62])
        color = tuple(float(v) for v in (0.35 * pc + 0.65 * grey))

    return alpha, color


# --------------------------------------------------------------------------- #
# compositing
# --------------------------------------------------------------------------- #
def composite(img: np.ndarray, alpha: np.ndarray, x0: int, y0: int, color: tuple[float, float, float]) -> None:
    """Multiply-blend ``alpha`` (patch whose top-left is at x0, y0) into ``img`` (uint8 BGR, in place)."""
    h, w = alpha.shape
    H, W = img.shape[:2]
    xa, ya = max(0, x0), max(0, y0)
    xb, yb = min(W, x0 + w), min(H, y0 + h)
    if xa >= xb or ya >= yb:
        return
    a = alpha[ya - y0:yb - y0, xa - x0:xb - x0][..., None]
    roi = img[ya:yb, xa:xb].astype(np.float32)
    col = np.asarray(color, np.float32).reshape(1, 1, 3)
    out = roi * (1.0 - a * (1.0 - col))
    img[ya:yb, xa:xb] = np.clip(out + 0.5, 0, 255).astype(np.uint8)


def draw_mark(img: np.ndarray, rng: np.random.Generator, style: str, cx: float, cy: float, r: float, pen: Pen) -> None:
    """Render and composite one mark centred at (cx, cy)."""
    alpha, color = render_mark(rng, style, r, pen)
    size = alpha.shape[0]
    x0 = int(round(cx)) - size // 2
    y0 = int(round(cy)) - size // 2
    composite(img, alpha, x0, y0, color if color is not None else pen.color)


def disc_coverage(alpha: np.ndarray, r: float, frac: float = 0.75, thr: float = 0.35) -> float:
    """Fraction of the centred disc of radius ``frac*r`` where alpha > thr (test/diagnostic helper)."""
    size = alpha.shape[0]
    c = (size - 1) / 2.0
    yy, xx = np.mgrid[0:size, 0:size]
    inside = (xx - c) ** 2 + (yy - c) ** 2 <= (frac * r) ** 2
    return float((alpha[inside] > thr).mean())


# --------------------------------------------------------------------------- #
# free handwriting (names, roll digits, signatures) — dark strokes outside bubbles
# --------------------------------------------------------------------------- #
_FONTS = (cv2.FONT_HERSHEY_SCRIPT_SIMPLEX, cv2.FONT_HERSHEY_SCRIPT_COMPLEX)


def draw_text(
    img: np.ndarray,
    rng: np.random.Generator,
    text: str,
    x: float,
    baseline_y: float,
    height: float,
    pen: Pen,
    max_width: float | None = None,
) -> None:
    """Handwriting-like text: Hershey script font, slanted + wobbly, composited as ink."""
    font = _FONTS[int(rng.integers(len(_FONTS)))]
    scale = height * _SS / 22.0  # Hershey script cap height ~22 px at scale 1
    thick = max(1, int(round(pen.width * _SS * rng.uniform(0.8, 1.1))))
    (tw, th), base = cv2.getTextSize(text, font, scale, thick)
    if max_width is not None and tw > max_width * _SS:
        scale *= max_width * _SS / tw
        (tw, th), base = cv2.getTextSize(text, font, scale, thick)
    pad = int(height * _SS)
    W, H = tw + 2 * pad, th + base + 2 * pad
    m = np.zeros((H, W), np.uint8)
    cv2.putText(m, text, (pad, pad + th), font, scale, 255, thick, cv2.LINE_AA)
    # slant + slight rotation + wobble
    shear = rng.uniform(-0.25, 0.05)
    rot = math.radians(rng.uniform(-2.5, 2.5))
    A = np.array([[math.cos(rot), -math.sin(rot) + shear, 0.0], [math.sin(rot), math.cos(rot), 0.0]], np.float32)
    A[:, 2] = np.array([W / 2, H / 2]) - A[:, :2] @ np.array([W / 2, H / 2])
    m = cv2.warpAffine(m, A, (W, H), flags=cv2.INTER_LINEAR)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    amp = rng.uniform(0.5, 1.5) * _SS
    mapx = xx + amp * np.sin(yy / (6.0 * _SS) + rng.uniform(0, 6.28))
    mapy = yy + amp * np.sin(xx / (9.0 * _SS) + rng.uniform(0, 6.28))
    m = cv2.remap(m, mapx, mapy, cv2.INTER_LINEAR)
    small = cv2.resize(m.astype(np.float32) / 255.0, (W // _SS, H // _SS), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), 0.5) * pen.pressure
    composite(img, small, int(round(x - pad / _SS)), int(round(baseline_y - (pad + th) / _SS)), pen.color)


def draw_signature(img: np.ndarray, rng: np.random.Generator, x: float, y: float, w: float, h: float, pen: Pen) -> None:
    """A loopy scribble signature inside the box (x, y, w, h)."""
    S = _SS
    Wp, Hp = int(w * S), int(h * S)
    m = np.zeros((Hp, Wp), np.uint8)
    n = 220
    t = np.linspace(0, 1, n)
    loops = rng.uniform(4, 9)
    xs = (0.05 + 0.9 * t) * Wp + rng.uniform(0.03, 0.08) * Wp * np.cos(2 * np.pi * loops * t + rng.uniform(0, 6))
    ys = 0.55 * Hp + rng.uniform(0.15, 0.3) * Hp * np.sin(2 * np.pi * loops * t * rng.uniform(0.9, 1.1)) \
        + rng.uniform(-0.1, 0.1) * Hp * np.sin(2 * np.pi * t * rng.uniform(0.5, 2))
    pts = np.stack([xs, ys], 1)
    _polyline(m, pts, pen.width * S, rng, 0.35)
    if rng.random() < 0.7:  # underline flourish
        x1, x2 = rng.uniform(0.0, 0.2) * Wp, rng.uniform(0.7, 1.0) * Wp
        yl = rng.uniform(0.8, 0.92) * Hp
        _polyline(m, np.linspace([x1, yl], [x2, yl - rng.uniform(-0.1, 0.1) * Hp], 10), pen.width * S, rng)
    a = cv2.resize(m.astype(np.float32) / 255.0, (Wp // S, Hp // S), interpolation=cv2.INTER_AREA)
    a = cv2.GaussianBlur(a, (0, 0), 0.5) * pen.pressure
    composite(img, a, int(x), int(y), pen.color)


def draw_stray_stroke(img: np.ndarray, rng: np.random.Generator, x: float, y: float, length: float, pen: Pen) -> None:
    """A short stray pen line / doodle (rough work that students are told not to do)."""
    S = _SS
    size = int(length * 1.4) + 8
    m = np.zeros((size * S, size * S), np.uint8)
    ang = rng.uniform(0, np.pi)
    c = size * S / 2
    d = np.array([math.cos(ang), math.sin(ang)]) * length * S / 2
    pts = np.linspace([c, c] - d, [c, c] + d, 12)
    pts += np.cumsum(rng.normal(0, 0.6 * S, pts.shape), axis=0)
    _polyline(m, pts, pen.width * S, rng)
    a = cv2.resize(m.astype(np.float32) / 255.0, (size, size), interpolation=cv2.INTER_AREA) * pen.pressure
    composite(img, a, int(x - size / 2), int(y - size / 2), pen.color)
