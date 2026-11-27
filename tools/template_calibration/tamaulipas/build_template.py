"""Build templates/tamaulipas_90 (blank reference PNG + template.json) from filled DEV sheets.

No blank form is published with the dataset, so the blank reference is synthesised: N dev sheets
are aligned to a reference (ECC homography on the darkness map: black frames, numbers and orange
print) and combined per pixel. Round 1 (median) is deskewed on the black answers frame and all
sheets are re-aligned to it. The sharp median is used for the printed layout; inside the bubbles
an upper brightness percentile replaces it, so that marks shared by most students (popular
answers) are removed as well. Bubbles are then detected on the orange
print of the median, grouped into the 4x10 ID block and 3 columns x 30 questions x 4 options, and
the two black frames become the registration anchors.

Usage (from the project root):
    .venv\\Scripts\\python.exe tools\\template_calibration\\tamaulipas\\build_template.py [--n 21] [--overlay out.png]

Only sheets from the DEV schools listed in benchmarks/external_splits/tamaulipas.json are used.
Dataset: Tamaulipas MCQ Exam Image Dataset, Universidad Politecnica de Victoria, Mendeley Data v2,
doi:10.17632/djmynjwjpy.2, CC BY 4.0.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

from omr_engine import EngineConfig  # noqa: E402
from omr_engine.ink import normalize_illumination  # noqa: E402
from omr_engine.printcolor import get_profile  # noqa: E402

SHEETS = ROOT / "benchmarks" / "data" / "external" / "tamaulipas" / "sheets"
SPLIT = ROOT / "benchmarks" / "external_splits" / "tamaulipas.json"
OUT = ROOT / "templates" / "tamaulipas_90"
W, H = 1700, 2200  # 200 dpi US Letter, same canonical space as the other templates
PENCIL_OVERRIDES = {"ink_dark_lo": 0.12, "ink_dark_hi": 0.40, "ink_close_px": 5, "min_threshold": 0.25, "max_threshold": 0.45}


def load_page(path: Path) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"cannot read {path}")
    return cv2.resize(img, (W, H), interpolation=cv2.INTER_AREA)


def darkness(img: np.ndarray, scale: float) -> np.ndarray:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(255.0 - small.astype(np.float32), (0, 0), 1.5) / 255.0


def align(img: np.ndarray, ref: np.ndarray) -> np.ndarray | None:
    """Warp ``img`` onto ``ref`` with a coarse-to-fine ECC homography on darkness maps.

    A non-converging finer level keeps the coarser estimate; None if even the coarsest fails.
    """
    h = np.eye(3, dtype=np.float32)
    for level, scale in enumerate((0.125, 0.25, 0.5)):
        s = np.diag([scale, scale, 1.0]).astype(np.float32)
        hs = s @ h @ np.linalg.inv(s)
        crit = (cv2.TERM_CRITERIA_COUNT | cv2.TERM_CRITERIA_EPS, 100, 1e-6)
        try:
            _, hs = cv2.findTransformECC(darkness(ref, scale), darkness(img, scale), hs.astype(np.float32),
                                         cv2.MOTION_HOMOGRAPHY, crit, None, 1)
        except cv2.error:
            if level == 0:
                return None
            break
        h = np.linalg.inv(s) @ hs @ s
    return cv2.warpPerspective(img, h, (W, H), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                               borderMode=cv2.BORDER_REPLICATE)


def combine(pages: list[np.ndarray], ref: np.ndarray, pct: float) -> tuple[np.ndarray, np.ndarray]:
    """Per-pixel median and upper percentile of the pages aligned to ``ref`` (in row bands).

    The median keeps thin print sharp. Pencil marks only ever darken a pixel, so the upper
    percentile also drops marks that more than half of the students share (popular answers).
    """
    stack = np.stack([a for a in (align(p, ref) for p in pages) if a is not None])
    med = np.empty(stack.shape[1:], np.uint8)
    upper = np.empty(stack.shape[1:], np.uint8)
    for y in range(0, H, 100):
        band = stack[:, y : y + 100]
        med[y : y + 100] = np.median(band, axis=0).round().astype(np.uint8)
        upper[y : y + 100] = np.percentile(band, pct, axis=0).round().astype(np.uint8)
    return med, upper


def clean_bubbles(med: np.ndarray, upper: np.ndarray, fields: list[dict]) -> np.ndarray:
    """Median everywhere except inside the bubbles, where the mark-free upper percentile is used."""
    mask = np.zeros(med.shape[:2], np.uint8)
    for f in fields:
        for b in f["bubbles"]:
            cv2.circle(mask, (round(b["x"]), round(b["y"])), round(b["r"] + 3), 255, -1)
    out = med.copy()
    out[mask > 0] = upper[mask > 0]
    return out


def deskew(img: np.ndarray) -> np.ndarray:
    """Rotate so that the top edge of the large black answers frame is horizontal."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, dark = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    pts = max(contours, key=cv2.contourArea).reshape(-1, 2).astype(np.float64)
    x0, x1 = np.percentile(pts[:, 0], [10, 90])
    top = pts[(pts[:, 0] > x0) & (pts[:, 0] < x1) & (pts[:, 1] < pts[:, 1].min() + 25)]
    # keep the upper envelope: the smallest y per x column
    cols: dict[int, float] = {}
    for x, y in top:
        cols[int(x)] = min(cols.get(int(x), np.inf), y)
    xs = np.array(sorted(cols))
    slope = np.polyfit(xs, [cols[x] for x in xs], 1)[0]
    rot = cv2.getRotationMatrix2D((W / 2, H / 2), float(np.degrees(np.arctan(slope))), 1.0)
    return cv2.warpAffine(img, rot, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

def detect_bubbles(blank: np.ndarray) -> list[tuple[float, float, float]]:
    """(x, y, r) of every orange printed circle (ring + letter, holes filled)."""
    cfg = EngineConfig()
    strength = get_profile("orange").strength(normalize_illumination(blank, cfg))
    _, mask = cv2.threshold(strength, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    out = []
    for c in contours:
        (x, y), r = cv2.minEnclosingCircle(c)
        area = cv2.contourArea(cv2.convexHull(c))
        if 8 <= r <= 25 and area > 0.6 * np.pi * r * r:
            out.append((float(x), float(y), float(r)))
    return out


def rows(points: list[tuple[float, float, float]], tol: float) -> list[list[tuple[float, float, float]]]:
    out: list[list[tuple[float, float, float]]] = []
    for p in sorted(points, key=lambda p: p[1]):
        if out and abs(np.mean([q[1] for q in out[-1]]) - p[1]) < tol:
            out[-1].append(p)
        else:
            out.append([p])
    return [sorted(r) for r in out]


def frame_anchors(blank: np.ndarray) -> dict[str, list[int]]:
    """Centre lines of the two thick black frames, as (x, y, w, h)."""
    gray = cv2.cvtColor(blank, cv2.COLOR_BGR2GRAY)
    _, dark = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY_INV)
    contours, hierarchy = cv2.findContours(dark, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for i, c in enumerate(contours):
        x, y, w, h = cv2.boundingRect(c)
        if hierarchy[0][i][3] != -1 or w < 0.5 * W or h < 100:
            continue
        child = hierarchy[0][i][2]
        best = None
        while child != -1:  # largest hole = inside of the frame
            cx, cy, cw, ch = cv2.boundingRect(contours[child])
            if best is None or cw * ch > best[2] * best[3]:
                best = (cx, cy, cw, ch)
            child = hierarchy[0][child][0]
        if best is None:
            continue
        ix, iy, iw, ih = best
        # centre line between the outer and inner borders
        x0, y0 = (x + ix) / 2, (y + iy) / 2
        x1, y1 = (x + w + ix + iw) / 2, (y + h + iy + ih) / 2
        boxes.append([round(x0), round(y0), round(x1 - x0), round(y1 - y0)])
    boxes.sort(key=lambda b: b[1])
    if len(boxes) != 2:
        raise RuntimeError(f"expected 2 black frames, found {len(boxes)}")
    return {"id_frame": boxes[0], "answers_frame": boxes[1]}


def build_fields(bubbles: list[tuple[float, float, float]], id_frame: list[int]) -> tuple[list[dict], float]:
    radius = round(float(np.median([b[2] for b in bubbles])), 1)
    # drop other orange glyphs (e.g. the "ID:" label) that are not bubble-sized
    bubbles = [b for b in bubbles if abs(b[2] - radius) <= 0.15 * radius]
    fy1 = id_frame[1] + id_frame[3]
    id_b = [b for b in bubbles if b[1] < fy1]
    ans_b = [b for b in bubbles if b[1] > fy1]
    id_rows = rows(id_b, tol=radius)
    if len(id_rows) != 4 or any(len(r) != 10 for r in id_rows):
        raise RuntimeError(f"ID block: rows {[len(r) for r in id_rows]}")
    fields = [
        {"id": f"id_{i + 1}", "group": "roll_no", "type": "digit",
         "bubbles": [{"value": str(v), "x": round(x, 1), "y": round(y, 1), "r": radius} for v, (x, y, _) in enumerate(r)]}
        for i, r in enumerate(id_rows)
    ]
    xs = np.array(sorted(b[0] for b in ans_b))
    gaps = np.argsort(np.diff(xs))[-2:]  # the two widest gaps separate the 3 columns
    cuts = sorted(xs[g] + (xs[g + 1] - xs[g]) / 2 for g in gaps)
    for col in range(3):
        lo = -np.inf if col == 0 else cuts[col - 1]
        hi = np.inf if col == 2 else cuts[col]
        col_rows = rows([b for b in ans_b if lo < b[0] < hi], tol=radius)
        if len(col_rows) != 30 or any(len(r) != 4 for r in col_rows):
            raise RuntimeError(f"answer column {col + 1}: rows {[len(r) for r in col_rows]}")
        for ri, r in enumerate(col_rows):
            q = col * 30 + ri + 1
            fields.append({"id": f"q{q}", "group": "answers", "type": "choice", "question": q,
                           "bubbles": [{"value": v, "x": round(x, 1), "y": round(y, 1), "r": radius}
                                       for v, (x, y, _) in zip("ABCD", r)]})
    fields.sort(key=lambda f: (f["group"] != "roll_no", f.get("question") or 0, f["id"]))
    return fields, radius


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40, help="number of dev sheets combined")
    ap.add_argument("--percentile", type=float, default=80.0, help="per-pixel brightness percentile")
    ap.add_argument("--overlay", type=Path, help="write a visual check image here")
    args = ap.parse_args()

    split = json.loads(SPLIT.read_text(encoding="utf-8"))
    dev = sorted(p for p in SHEETS.glob("*.jpg") if p.name.split("_")[0] in set(split["dev"]))
    picks = [dev[i] for i in np.linspace(0, len(dev) - 1, min(args.n, len(dev))).round().astype(int)]
    pages = [load_page(p) for p in picks]
    first, _ = combine(pages, pages[0], args.percentile)
    med, upper = combine(pages, deskew(first), args.percentile)

    anchors = frame_anchors(med)
    fields, radius = build_fields(detect_bubbles(med), anchors["id_frame"])
    blank = clean_bubbles(med, upper, fields)
    OUT.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(OUT / "template_200dpi.png"), blank)
    spec = {
        "id": "tamaulipas_90",
        "name": "Tamaulipas MCQ answer sheet (90 questions, 4-digit ID)",
        "version": 1,
        "page": {"width_px": W, "height_px": H, "dpi": 200, "paper": "letter"},
        "print_color": "orange",
        "reference_image": "template_200dpi.png",
        "anchors": anchors,
        "anchor_source": "dark",
        "num_questions": 90,
        "options": ["A", "B", "C", "D"],
        "fields": fields,
        # Pencil-filled sheets: graphite is lighter and grainier than ballpoint. Tuned on the DEV
        # schools only (benchmarks/run_external.py --split dev --set ...).
        "engine_overrides": PENCIL_OVERRIDES,
        "source": "Reference synthesised from DEV sheets of the Tamaulipas MCQ Exam Image Dataset, Universidad "
        "Politecnica de Victoria, Mendeley Data v2, doi:10.17632/djmynjwjpy.2, CC BY 4.0",
    }
    (OUT / "template.json").write_text(json.dumps(spec, indent=1), encoding="utf-8")
    print(f"p{args.percentile:.0f} of {len(pages)} dev sheets; bubble r={radius}; fields={len(fields)}; "
          f"bubbles={sum(len(f['bubbles']) for f in fields)}; anchors={anchors}")

    if args.overlay:
        vis = blank.copy()
        for f in fields:
            for b in f["bubbles"]:
                cv2.circle(vis, (round(b["x"]), round(b["y"])), round(b["r"]), (0, 160, 0), 2)
            b0 = f["bubbles"][0]
            cv2.putText(vis, f["id"], (round(b0["x"] - 60), round(b0["y"] + 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 0, 0), 1)
        for x, y, w, h in anchors.values():
            cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 0, 255), 1)
        cv2.imwrite(str(args.overlay), vis)


if __name__ == "__main__":
    main()
