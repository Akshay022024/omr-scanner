from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from omr_engine import Template, TemplateError, load_template
from testpaths import PUBLIC_TEMPLATE_DIR


def test_loads_sheet80_template(template: Template) -> None:
    spec = template.spec
    assert template.id == "sheet80_v2"
    assert template.size == (1700, 2200)
    assert len(spec.fields) == 91
    assert sum(len(f.bubbles) for f in spec.fields) == 423
    assert len(template.fields_in("answers")) == 80
    assert len(template.fields_in("roll_no")) == 10
    assert template.paper_sets == ["A", "B", "C"]
    assert template.bubble_xy.shape == (423, 2)
    assert template.field_slices[-1] == (419, 423)
    assert set(spec.anchors) >= {"roll_box", "answers_col_1", "answers_col_4"}


def _copy_template(tmp_path: Path) -> Path:
    dst = tmp_path / "tpl"
    shutil.copytree(PUBLIC_TEMPLATE_DIR, dst, ignore=shutil.ignore_patterns("*.pdf"))
    return dst


def test_missing_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(TemplateError):
        load_template(tmp_path / "nope")


def test_duplicate_field_ids_rejected(tmp_path: Path) -> None:
    d = _copy_template(tmp_path)
    data = json.loads((d / "template.json").read_text(encoding="utf-8"))
    data["fields"][1]["id"] = data["fields"][0]["id"]
    (d / "template.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(TemplateError, match="duplicate field ids"):
        load_template(d)


def test_missing_question_rejected(tmp_path: Path) -> None:
    d = _copy_template(tmp_path)
    data = json.loads((d / "template.json").read_text(encoding="utf-8"))
    data["fields"] = [f for f in data["fields"] if f["id"] != "q40"]
    (d / "template.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(TemplateError, match="questions"):
        load_template(d)


def test_bubble_outside_page_rejected(tmp_path: Path) -> None:
    d = _copy_template(tmp_path)
    data = json.loads((d / "template.json").read_text(encoding="utf-8"))
    data["fields"][0]["bubbles"][0]["x"] = 5000
    (d / "template.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(TemplateError, match="outside"):
        load_template(d)


def test_reference_image_path_cannot_escape(tmp_path: Path) -> None:
    d = _copy_template(tmp_path)
    data = json.loads((d / "template.json").read_text(encoding="utf-8"))
    data["reference_image"] = "../template_200dpi.png"
    shutil.copy(d / "template_200dpi.png", tmp_path / "template_200dpi.png")
    (d / "template.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(TemplateError, match="reference image"):
        load_template(d)
