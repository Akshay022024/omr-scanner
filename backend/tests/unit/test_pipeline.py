from __future__ import annotations

import cv2
import numpy as np
import pymupdf
import pytest

from omr_engine import DocumentError, EngineConfig, Template, render_overlay, scan_document, scan_image
from omr_synth import expected_answers, expected_roll, fill_sheet, photograph, random_marks


def _assert_reads(res, tpl: Template, marks: dict[str, str]) -> None:
    assert res.answers == expected_answers(tpl, marks)
    assert res.roll_no == expected_roll(tpl, marks)
    assert res.paper_set == marks["paper_set"]


def test_clean_sheet_reads_exactly(template: Template, filled_sheet: np.ndarray, marks: dict[str, str]) -> None:
    res = scan_image(filled_sheet, template)
    _assert_reads(res, template, marks)
    assert res.status == "ok"
    assert res.review_flags == []
    assert res.registration is not None and res.registration.geometry_ok
    assert res.aligned_size == (1700, 2200)
    assert set(res.timings_ms) >= {"page", "register", "read", "total"}


def test_photo_rotated_3deg_with_perspective_reads_exactly(
    template: Template, filled_sheet: np.ndarray, marks: dict[str, str]
) -> None:
    img, _ = photograph(filled_sheet, angle_deg=3.0, scale=0.9, perspective=0.03)
    res = scan_image(img, template)
    _assert_reads(res, template, marks)
    assert res.status == "ok"


def test_black_pen_degraded_scan(template: Template) -> None:
    marks = random_marks(template, seed=5)
    sheet = fill_sheet(template, marks, colour=(40, 40, 40), radius_frac=0.8)
    img, _ = photograph(sheet, angle_deg=-1.5, scale=0.7, perspective=0.0, background=(250, 250, 250))
    img = cv2.GaussianBlur(img, (0, 0), 1.0)
    ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
    res = scan_image(cv2.imdecode(enc, cv2.IMREAD_COLOR), template)
    _assert_reads(res, template, marks)


def test_multiple_and_blank_flags(template: Template, marks: dict[str, str]) -> None:
    marks = {**marks, "q1": "AC", "q2": "", "roll_3": ""}
    res = scan_image(fill_sheet(template, marks), template)
    assert res.answers["1"] == "AC" and res.answers["2"] == ""
    assert res.roll_no[2] == "?"
    assert "q1:multiple" in res.review_flags
    assert "roll_3:blank" in res.review_flags
    assert "q2:blank" not in res.review_flags  # blank answers are not flagged by default
    assert res.status == "needs_review"
    field = next(f for f in res.fields if f.id == "q1")
    assert field.state == "multiple" and field.value == "AC"


def test_scan_is_deterministic(template: Template, filled_sheet: np.ndarray) -> None:
    img, _ = photograph(filled_sheet, angle_deg=2.0, scale=0.85, perspective=0.02)
    a = scan_image(img, template).model_dump(exclude={"timings_ms"})
    b = scan_image(img, template).model_dump(exclude={"timings_ms"})
    assert a == b


@pytest.mark.parametrize("kind", ["white", "noise"])
def test_non_sheet_images_fail(template: Template, kind: str) -> None:
    rng = np.random.default_rng(0)
    img = np.full((1500, 1200, 3), 255, np.uint8) if kind == "white" else rng.integers(0, 255, (1500, 1200, 3), np.uint8)
    res = scan_image(img, template)
    assert res.status == "failed"
    assert res.error


def test_tiny_image_fails_gracefully(template: Template) -> None:
    res = scan_image(np.zeros((10, 10, 3), np.uint8), template)
    assert res.status == "failed" and res.registration is None


def test_scan_document_png_and_pdf(template: Template, filled_sheet: np.ndarray, marks: dict[str, str]) -> None:
    ok, png = cv2.imencode(".png", filled_sheet)
    assert ok
    [res] = scan_document(png.tobytes(), "sheet.png", template)
    _assert_reads(res, template, marks)
    assert "load" in res.timings_ms

    doc = pymupdf.open()
    for _ in range(2):
        page = doc.new_page(width=612, height=792)
        page.insert_image(page.rect, stream=png.tobytes())
    results = scan_document(doc.tobytes(), "sheets.pdf", template)
    assert len(results) == 2
    for r in results:
        _assert_reads(r, template, marks)


def test_scan_document_rejects_garbage(template: Template) -> None:
    with pytest.raises(DocumentError):
        scan_document(b"not an image at all", "x.txt", template)


def test_render_overlay(template: Template, filled_sheet: np.ndarray, cfg: EngineConfig) -> None:
    img, _ = photograph(filled_sheet)
    res = scan_image(img, template, cfg)
    overlay = render_overlay(img, res, template)
    assert overlay.shape == (2200, 1700, 3)
    q1 = template.field("q1")
    b = next(b for b in q1.bubbles if b.value == res.answers["1"])
    ring = overlay[int(b.y), int(b.x + b.r + 4)]
    assert tuple(int(v) for v in ring) != (255, 255, 255)
