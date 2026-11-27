"""Synthetic filled-sheet generator.

``generate_sheet(rng, template, style_mix)`` renders the real template image
(1700x2200, 200 dpi) and simulates one student: roll number, paper set and 80
answers, with configurable blank / multiple / distractor rates, plus optional
handwriting in the details panel, signature and stray rough-work strokes.

It deliberately does **not** import the engine; it reads template.json itself so
the benchmark measures the engine instead of sharing its code.

Ground-truth schema (``omr-gt/1``) — also used for hand-labelled real photos::

    {
      "schema": "omr-gt/1",
      "template_id": "sheet80_v2",
      "roll_no": "0123456789",          # 10 chars
      "paper_set": "B",                 # "" if blank
      "answers": {"1": "B", "2": "", "3": "AC", ...},   # letters in option order
      "flags": {"1": {"blank": false, "multiple": false, "distractor": null,
                      "distractor_option": null, "style": "solid"}, ...},  # optional
      "pen": {...}, "extras": {...}                                         # optional
    }
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from . import handwriting as hw

GT_SCHEMA = "omr-gt/1"
TEMPLATE_W, TEMPLATE_H = 1700, 2200


# --------------------------------------------------------------------------- #
# template (engine-independent loader)
# --------------------------------------------------------------------------- #
@dataclass
class Bubble:
    value: str
    x: float
    y: float
    r: float


@dataclass
class Field:
    id: str
    group: str  # roll_no | paper_set | answers
    type: str
    bubbles: list[Bubble]
    question: int | None = None

    @property
    def options(self) -> list[str]:
        return [b.value for b in self.bubbles]


@dataclass
class SynthTemplate:
    id: str
    width: int
    height: int
    options: list[str]
    num_questions: int
    fields: list[Field]
    image: np.ndarray  # BGR reference render
    anchors: dict[str, list[float]] = field(default_factory=dict)

    @property
    def roll_fields(self) -> list[Field]:
        return sorted([f for f in self.fields if f.group == "roll_no"], key=lambda f: int(f.id.split("_")[1]))

    @property
    def set_field(self) -> Field:
        return next(f for f in self.fields if f.group == "paper_set")

    @property
    def question_fields(self) -> list[Field]:
        return sorted([f for f in self.fields if f.group == "answers"], key=lambda f: f.question or 0)

    def field_by_id(self, fid: str) -> Field:
        for f in self.fields:
            if f.id == fid:
                return f
        raise KeyError(fid)


def load_synth_template(template_dir: str | Path) -> SynthTemplate:
    d = Path(template_dir)
    data = json.loads((d / "template.json").read_text(encoding="utf-8"))
    img_path = d / data.get("reference_image", "template_200dpi.png")
    img = cv2.imdecode(np.fromfile(str(img_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"cannot read template image {img_path}")
    W, H = int(data["page"]["width_px"]), int(data["page"]["height_px"])
    if img.shape[:2] != (H, W):
        img = cv2.resize(img, (W, H), interpolation=cv2.INTER_AREA)
    fields = [
        Field(
            id=f["id"], group=f["group"], type=f["type"], question=f.get("question"),
            bubbles=[Bubble(str(b["value"]), float(b["x"]), float(b["y"]), float(b["r"])) for b in f["bubbles"]],
        )
        for f in data["fields"]
    ]
    return SynthTemplate(
        id=data["id"], width=W, height=H, options=list(data["options"]),
        num_questions=int(data["num_questions"]), fields=fields, image=img, anchors=data.get("anchors", {}),
    )


# --------------------------------------------------------------------------- #
# style mix
# --------------------------------------------------------------------------- #
@dataclass
class StyleMix:
    # relative weights of fill styles for filled bubbles
    fill_weights: dict[str, float] = field(default_factory=lambda: {
        "solid": 0.45, "heavy": 0.15, "partial": 0.15, "scribble": 0.15, "overshoot": 0.10,
    })
    # probability a student sticks to one dominant style for the whole sheet
    consistent_student: float = 0.6
    blank_rate: float = 0.05
    multiple_rate: float = 0.02
    distractor_rate: float = 0.02
    distractor_weights: dict[str, float] = field(default_factory=lambda: {"tick": 1.0, "cross": 1.0, "smudge": 1.0})
    set_blank_rate: float = 0.0
    handwriting_prob: float = 0.85  # name/details text + roll digits in boxes
    signature_prob: float = 0.8
    stray_marks_max: int = 2  # rough-work strokes outside bubbles (0..max)
    pen_kind: str | None = None  # force "blue"/"black"

    @classmethod
    def clean_only(cls) -> "StyleMix":
        """Only solid fills, no blanks/multiples/distractors/handwriting (useful for tests)."""
        return cls(fill_weights={"solid": 1.0}, consistent_student=1.0, blank_rate=0.0, multiple_rate=0.0,
                   distractor_rate=0.0, handwriting_prob=0.0, signature_prob=0.0, stray_marks_max=0)


def _weighted_choice(rng: np.random.Generator, weights: dict[str, float]) -> str:
    keys = list(weights)
    p = np.array([weights[k] for k in keys], float)
    p = p / p.sum()
    return keys[int(rng.choice(len(keys), p=p))]


# --------------------------------------------------------------------------- #
# details panel geometry (template px). Measured from template_200dpi.png.
# --------------------------------------------------------------------------- #
_DETAIL_LINES = [  # (x_start, baseline_y, max_width, kind)
    (270, 620, 520, "name"),
    (275, 668, 520, "name"),
    (255, 716, 320, "school"),
    (650, 716, 150, "city"),
    (185, 764, 250, "grade"),
    (590, 764, 210, "date"),
]
_SIGNATURE_BOXES = [(120, 1985, 330, 75), (1240, 1985, 330, 75)]
# purely fictional, generic names (no real student data)
_FIRST = ["Aarav", "Diya", "Kabir", "Meera", "Rohan", "Anaya", "Vivaan", "Isha", "Arjun", "Sara", "Neel", "Tara"]
_LAST = ["Sharma", "Verma", "Rao", "Iyer", "Patel", "Singh", "Gupta", "Nair", "Das", "Mehta"]
_SCHOOLS = ["Green Valley School", "City Public School", "St. Mary Academy", "Model High School"]
_CITIES = ["Pune", "Delhi", "Indore", "Mysore", "Nagpur", "Surat"]


def _random_details(rng: np.random.Generator) -> list[str]:
    pick = lambda xs: xs[int(rng.integers(len(xs)))]  # noqa: E731
    return [
        f"{pick(_FIRST)} {pick(_LAST)}",
        f"{pick(_FIRST)} {pick(_LAST)}",
        pick(_SCHOOLS),
        pick(_CITIES),
        str(int(rng.integers(3, 11))),
        f"{int(rng.integers(1, 29)):02d}/{int(rng.integers(1, 13)):02d}/2026",
    ]


# --------------------------------------------------------------------------- #
# main entry
# --------------------------------------------------------------------------- #
def generate_sheet(
    rng: np.random.Generator, template: SynthTemplate, style_mix: StyleMix | None = None
) -> tuple[np.ndarray, dict[str, Any]]:
    """Render one filled sheet. Returns (BGR uint8 1700x2200, ground-truth dict)."""
    mix = style_mix or StyleMix()
    img = template.image.copy()
    pen = hw.random_pen(rng, mix.pen_kind)
    dominant = _weighted_choice(rng, mix.fill_weights) if rng.random() < mix.consistent_student else None

    def fill_style() -> str:
        if dominant is not None and rng.random() < 0.85:
            return dominant
        return _weighted_choice(rng, mix.fill_weights)

    styles_used: dict[str, int] = {}

    def mark(b: Bubble, style: str) -> None:
        styles_used[style] = styles_used.get(style, 0) + 1
        hw.draw_mark(img, rng, style, b.x, b.y, b.r, pen)

    # ---- roll number -------------------------------------------------------
    roll_digits = "".join(str(int(d)) for d in rng.integers(0, 10, len(template.roll_fields)))
    roll_styles = {}
    for f, d in zip(template.roll_fields, roll_digits):
        b = next(bb for bb in f.bubbles if bb.value == d)
        st = fill_style()
        roll_styles[f.id] = st
        mark(b, st)

    # ---- paper set -----------------------------------------------------------
    sf = template.set_field
    paper_set = ""
    if rng.random() >= mix.set_blank_rate:
        paper_set = sf.options[int(rng.integers(len(sf.options)))]
        mark(next(bb for bb in sf.bubbles if bb.value == paper_set), fill_style())

    # ---- answers ---------------------------------------------------------------
    answers: dict[str, str] = {}
    flags: dict[str, dict[str, Any]] = {}
    for f in template.question_fields:
        q = str(f.question)
        opts = f.options
        u = rng.random()
        if u < mix.blank_rate:
            chosen: list[str] = []
        elif u < mix.blank_rate + mix.multiple_rate:
            k = 2 if rng.random() < 0.85 else 3
            chosen = sorted(rng.choice(opts, size=k, replace=False).tolist(), key=opts.index)
        else:
            chosen = [opts[int(rng.integers(len(opts)))]]
        distractor = None
        d_opt = None
        if rng.random() < mix.distractor_rate:
            free = [o for o in opts if o not in chosen]
            if free:
                distractor = _weighted_choice(rng, mix.distractor_weights)
                d_opt = free[int(rng.integers(len(free)))]
        q_style = fill_style() if chosen else None
        # distractor drawn first (an erased mark / tick precedes the final answer)
        if distractor is not None:
            mark(next(bb for bb in f.bubbles if bb.value == d_opt), distractor)
        option_styles: dict[str, str] = {}
        for o in chosen:
            st = q_style if len(chosen) == 1 else fill_style()
            option_styles[o] = st
            mark(next(bb for bb in f.bubbles if bb.value == o), st)
        answers[q] = "".join(chosen)
        flags[q] = {
            "blank": not chosen,
            "multiple": len(chosen) > 1,
            "distractor": distractor,
            "distractor_option": d_opt,
            "style": q_style,
            "option_styles": option_styles,
        }

    # ---- handwriting outside bubbles ------------------------------------------
    extras: dict[str, Any] = {"handwriting": False, "signature": False, "stray_marks": 0}
    if rng.random() < mix.handwriting_prob:
        extras["handwriting"] = True
        for (x, y, mw, _kind), text in zip(_DETAIL_LINES, _random_details(rng)):
            if rng.random() < 0.92:
                hw.draw_text(img, rng, text, x + rng.uniform(0, 20), y + rng.uniform(-3, 2),
                             rng.uniform(22, 30), pen, max_width=mw)
        # digits written in the roll / set boxes above the bubble columns
        for f, d in zip(template.roll_fields, roll_digits):
            x = f.bubbles[0].x
            hw.draw_text(img, rng, d, x - 9 + rng.uniform(-3, 3), 141 + rng.uniform(-3, 3),
                         rng.uniform(26, 34), pen, max_width=26)
        if paper_set:
            hw.draw_text(img, rng, paper_set, sf.bubbles[0].x - 10 + rng.uniform(-3, 3), 145 + rng.uniform(-3, 3),
                         rng.uniform(28, 34), pen, max_width=28)
    if rng.random() < mix.signature_prob:
        extras["signature"] = True
        x, y, w, h = _SIGNATURE_BOXES[0]
        hw.draw_signature(img, rng, x + rng.uniform(0, 40), y, w * rng.uniform(0.6, 0.9), h, pen)
    n_stray = int(rng.integers(0, mix.stray_marks_max + 1)) if mix.stray_marks_max > 0 else 0
    for _ in range(n_stray):
        # in the bottom free area or the right margin, away from bubbles
        if rng.random() < 0.5:
            x, y = rng.uniform(150, 1500), rng.uniform(1950, 2050)
        else:
            x, y = rng.uniform(1610, 1660), rng.uniform(900, 1800)
        hw.draw_stray_stroke(img, rng, x, y, rng.uniform(15, 50), pen)
    extras["stray_marks"] = n_stray

    gt: dict[str, Any] = {
        "schema": GT_SCHEMA,
        "template_id": template.id,
        "roll_no": roll_digits,
        "paper_set": paper_set,
        "answers": answers,
        "flags": flags,
        "roll_styles": roll_styles,
        "pen": {"kind": pen.kind, "color_bgr": list(pen.color), "pressure": pen.pressure, "width": pen.width},
        "dominant_style": dominant,
        "styles_used": styles_used,
        "extras": extras,
    }
    return img, gt


def gt_field_values(gt: dict[str, Any], template: SynthTemplate) -> dict[str, str]:
    """Ground truth as field-id -> value string (letters/digits marked), for bubble-level scoring."""
    out: dict[str, str] = {}
    roll = gt.get("roll_no", "") or ""
    for i, f in enumerate(template.roll_fields):
        out[f.id] = roll[i] if i < len(roll) and roll[i].isdigit() else ""
    out[template.set_field.id] = gt.get("paper_set", "") or ""
    for f in template.question_fields:
        out[f.id] = gt.get("answers", {}).get(str(f.question), "") or ""
    return out
