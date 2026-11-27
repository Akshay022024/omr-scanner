"""Second template (orange print, pencil marks, real scans). Sheet tests skip when the dataset
(benchmarks/data/external/tamaulipas, gitignored) has not been downloaded."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from omr_engine import Template, load_document, load_template, scan_image
from testpaths import PROJECT_ROOT, TEMPLATES_DIR

SHEETS = PROJECT_ROOT / "benchmarks" / "data" / "external" / "tamaulipas" / "sheets"
# Dev-split sheets only (the test split is reserved for the external benchmark).
SAMPLES = ["School001_Grade10_File0001", "School021_Grade12_File0004"]


@pytest.fixture(scope="module")
def tam() -> Template:
    return load_template(TEMPLATES_DIR / "tamaulipas_90")


def _label(path: Path) -> tuple[str, dict[str, str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    sheet_id = re.search(r"ID\s*:\s*(\S+)", text).group(1)
    answers = {str(int(q)): ("" if v == "X" else v) for q, v in re.findall(r"(\d+)\s*:\s*([A-DXM])", text.split("\n", 1)[1])}
    return sheet_id, answers


def test_template_loads(tam: Template) -> None:
    spec = tam.spec
    assert spec.print_color == "orange" and spec.anchor_source == "dark"
    assert tam.size == (1700, 2200)
    assert len(tam.fields_in("answers")) == 90
    assert [f.id for f in tam.fields_in("roll_no")] == ["id_1", "id_2", "id_3", "id_4"]
    assert all([b.value for b in f.bubbles] == [str(d) for d in range(10)] for f in tam.fields_in("roll_no"))
    assert sum(len(f.bubbles) for f in spec.fields) == 400
    assert tam.paper_sets == []
    assert len(spec.anchors) == 2


def test_blank_reference_reads_blank(tam: Template) -> None:
    res = scan_image(tam.reference.copy(), tam)
    assert res.status != "failed"
    assert all(v == "" for v in res.answers.values())
    assert res.roll_no == "????"
    assert res.registration is not None and res.registration.geometry_ok


@pytest.mark.skipif(not SHEETS.is_dir(), reason="Tamaulipas dataset not downloaded")
@pytest.mark.parametrize("name", SAMPLES)
def test_reads_real_sheet(tam: Template, name: str) -> None:
    img = load_document((SHEETS / f"{name}.jpg").read_bytes())[0]
    sheet_id, answers = _label(SHEETS / f"{name}.txt")
    res = scan_image(img, tam)
    assert res.status in ("ok", "needs_review")
    assert res.registration is not None and res.registration.geometry_ok
    correct = sum(res.answers.get(q) == a for q, a in answers.items() if a != "M")
    assert correct >= 0.97 * sum(1 for a in answers.values() if a != "M")
    assert res.roll_no == sheet_id
