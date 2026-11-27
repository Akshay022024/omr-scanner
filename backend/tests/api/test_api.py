from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from testpaths import SHEET80_AVAILABLE, SHEET80_ID, TEMPLATES_DIR
from omr_engine import Template
from omr_synth import expected_answers, expected_roll

ORIGIN = "http://localhost:5173"


@pytest.fixture(scope="module")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("omr")
    return Settings(
        data_dir=root / "data",
        templates_dir=TEMPLATES_DIR,
        benchmark_reports_dir=root / "reports",
        max_upload_mb=10,
        max_files=3,
    )


@pytest.fixture(scope="module")
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture(scope="module")
def sheet_png(filled_sheet: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", filled_sheet)
    assert ok
    return buf.tobytes()


@pytest.fixture(scope="module")
def answer_key(client: TestClient, template: Template, marks: dict[str, str]) -> dict:
    expected = expected_answers(template, marks)
    key_a = {q: (a if a else "A") for q, a in expected.items()}  # blanks keyed so they count as blank
    payload = {
        "name": "Midterm 2026",
        "template_id": template.id,
        "keys": {"A": key_a, "B": key_a, "C": key_a},
        "marks_correct": 4,
        "marks_wrong": -1,
        "marks_blank": 0,
    }
    r = client.post("/api/answer-keys", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _upload(client: TestClient, files: list[tuple[str, bytes, str]], **form: str):
    return client.post(
        "/api/scans",
        data={"template_id": SHEET80_ID, **form},
        files=[("files", (name, data, media)) for name, data, media in files],
    )


def test_health(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["templates"] == (2 if SHEET80_AVAILABLE else 1) and body["engine_version"]


def test_templates(client: TestClient) -> None:
    listed = client.get("/api/templates").json()
    expected_ids = [SHEET80_ID, "tamaulipas_90"] if SHEET80_AVAILABLE else ["tamaulipas_90"]
    assert [t["id"] for t in listed] == expected_ids
    tam = next(t for t in listed if t["id"] == "tamaulipas_90")
    assert tam["num_questions"] == 90 and tam["paper_sets"] == []
    if SHEET80_AVAILABLE:
        spec = client.get(f"/api/templates/{SHEET80_ID}").json()
        assert len(spec["fields"]) == 91 and spec["print_color"] == "magenta"
    assert client.get("/api/templates/tamaulipas_90").json()["print_color"] == "orange"
    for tid in expected_ids:
        img = client.get(f"/api/templates/{tid}/image")
        assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    assert client.get("/api/templates/nope").status_code == 404


def test_answer_key_crud(client: TestClient, template: Template) -> None:
    payload = {"name": "k", "template_id": template.id, "keys": {"a": {"1": "b", "2": " c "}}}
    created = client.post("/api/answer-keys", json=payload).json()
    assert created["keys"] == {"A": {"1": "B", "2": "C"}}
    key_id = created["id"]
    assert client.get(f"/api/answer-keys/{key_id}").json()["name"] == "k"
    assert any(k["id"] == key_id for k in client.get("/api/answer-keys").json())

    payload["name"] = "renamed"
    payload["marks_wrong"] = -0.25
    updated = client.put(f"/api/answer-keys/{key_id}", json=payload).json()
    assert updated["name"] == "renamed" and updated["marks_wrong"] == -0.25
    assert updated["created_at"] == created["created_at"]

    assert client.delete(f"/api/answer-keys/{key_id}").status_code == 204
    assert client.get(f"/api/answer-keys/{key_id}").status_code == 404
    assert client.delete(f"/api/answer-keys/{key_id}").status_code == 404
    assert client.get("/api/answer-keys/../../etc").status_code == 404


@pytest.mark.parametrize(
    "keys",
    [{"A": {"1": "E"}}, {"Z": {"1": "A"}}, {"A": {"81": "A"}}, {"A": {"x": "A"}}, {}],
)
def test_answer_key_validation(client: TestClient, template: Template, keys: dict) -> None:
    r = client.post("/api/answer-keys", json={"name": "bad", "template_id": template.id, "keys": keys})
    assert r.status_code == 422


def test_scan_png_with_grading(
    client: TestClient, sheet_png: bytes, answer_key: dict, template: Template, marks: dict[str, str]
) -> None:
    r = _upload(client, [("student 1.png", sheet_png, "image/png")], answer_key_id=answer_key["id"])
    assert r.status_code == 200, r.text
    body = r.json()
    [scan] = body["scans"]
    assert scan["batch_id"] == body["batch_id"] and scan["page"] == 1
    assert scan["filename"] == "student 1.png"
    assert scan["result"]["status"] == "ok"
    assert scan["result"]["answers"] == expected_answers(template, marks)
    assert scan["result"]["roll_no"] == expected_roll(template, marks)
    grade = scan["grade"]
    n_blank = sum(1 for a in expected_answers(template, marks).values() if a == "")
    assert grade["correct"] == 80 - n_blank and grade["blank"] == n_blank and grade["wrong"] == 0
    assert grade["score"] == 4 * (80 - n_blank)

    sid = scan["id"]
    assert client.get(f"/api/scans/{sid}").json()["id"] == sid
    for path, media in [("overlay.png", "image/png"), ("aligned.png", "image/png"), ("original", "image/png")]:
        resp = client.get(f"/api/scans/{sid}/{path}")
        assert resp.status_code == 200 and resp.headers["content-type"] == media
    assert client.get(f"/api/scans/{sid}/original").content == sheet_png
    assert [s["id"] for s in client.get(f"/api/scans?batch_id={body['batch_id']}").json()] == [sid]


def test_scan_pdf(client: TestClient, filled_sheet: np.ndarray, template: Template, marks: dict[str, str]) -> None:
    ok, jpg = cv2.imencode(".jpg", filled_sheet, [cv2.IMWRITE_JPEG_QUALITY, 92])
    assert ok
    doc = pymupdf.open()
    for _ in range(2):
        page = doc.new_page(width=612, height=792)
        page.insert_image(page.rect, stream=jpg.tobytes())
    r = _upload(client, [("batch.pdf", doc.tobytes(garbage=3, deflate=True), "application/pdf")])
    assert r.status_code == 200, r.text
    scans = r.json()["scans"]
    assert [s["page"] for s in scans] == [1, 2]
    for s in scans:
        assert s["grade"] is None
        assert s["result"]["answers"] == expected_answers(template, marks)
    assert len({s["id"] for s in scans}) == 2
    orig = client.get(f"/api/scans/{scans[0]['id']}/original")
    assert orig.status_code == 200 and orig.headers["content-type"] == "image/png"


def test_files_array_field_name_accepted(client: TestClient, sheet_png: bytes) -> None:
    r = client.post(
        "/api/scans", data={"template_id": SHEET80_ID}, files=[("files[]", ("a.png", sheet_png, "image/png"))]
    )
    assert r.status_code == 200 and len(r.json()["scans"]) == 1


def test_rejects_non_image(client: TestClient, settings: Settings, template: Template) -> None:
    batches_before = len(client.get("/api/batches").json())
    r = _upload(client, [("notes.png", b"hello, this is text pretending to be a png", "image/png")])
    assert r.status_code == 415
    assert len(client.get("/api/batches").json()) == batches_before


def test_upload_limits(client: TestClient, sheet_png: bytes, settings: Settings) -> None:
    big = b"\x89PNG\r\n\x1a\n" + b"\0" * (settings.max_upload_bytes + 10)
    assert _upload(client, [("big.png", big, "image/png")]).status_code == 413
    four = [(f"{i}.png", sheet_png, "image/png") for i in range(settings.max_files + 1)]
    assert _upload(client, four).status_code in (400, 413)
    assert client.post("/api/scans", data={"template_id": SHEET80_ID}).status_code == 422
    assert _upload(client, [("a.png", sheet_png, "image/png")], template_id="missing").status_code == 404


def test_pdf_page_limit(client: TestClient, settings: Settings, template: Template) -> None:
    doc = pymupdf.open()
    for _ in range(settings.max_pdf_pages + 1):
        doc.new_page(width=100, height=100)
    assert _upload(client, [("long.pdf", doc.tobytes(), "application/pdf")]).status_code == 400


def test_patch_correction_regrades(client: TestClient, sheet_png: bytes, answer_key: dict, marks: dict[str, str]) -> None:
    scan = _upload(client, [("s.png", sheet_png, "image/png")], answer_key_id=answer_key["id"]).json()["scans"][0]
    q1 = scan["result"]["answers"]["1"]
    wrong = next(o for o in "ABCD" if o != q1)
    before = scan["grade"]["score"]
    r = client.patch(f"/api/scans/{scan['id']}", json={"answers": {"1": wrong.lower()}, "roll_no": "1234567890"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["corrected"] is True
    assert body["result"]["answers"]["1"] == wrong
    assert body["result"]["roll_no"] == "1234567890"
    expected_delta = (-1 - 4) if marks["q1"] else -1  # was correct (+4) -> wrong (-1); was blank (0) -> wrong
    assert body["grade"]["score"] == before + expected_delta
    field = next(f for f in body["result"]["fields"] if f["id"] == "q1")
    assert field["value"] == wrong and field["state"] == "single" and field["confidence"] == 1.0

    assert client.patch(f"/api/scans/{scan['id']}", json={"answers": {"1": "Z"}}).status_code == 422
    assert client.patch(f"/api/scans/{scan['id']}", json={"roll_no": "12"}).status_code == 422
    assert client.patch(f"/api/scans/{scan['id']}", json={"paper_set": "Q"}).status_code == 422
    cleared = client.patch(f"/api/scans/{scan['id']}", json={"paper_set": None}).json()
    assert cleared["result"]["paper_set"] is None


def test_regrade(client: TestClient, sheet_png: bytes, answer_key: dict) -> None:
    scan = _upload(client, [("s.png", sheet_png, "image/png")]).json()["scans"][0]
    assert scan["grade"] is None
    r = client.post(f"/api/scans/{scan['id']}/regrade", json={"answer_key_id": answer_key["id"]})
    assert r.status_code == 200
    assert r.json()["grade"]["answer_key_id"] == answer_key["id"]
    missing = "00000000-0000-4000-8000-000000000000"
    assert client.post(f"/api/scans/{scan['id']}/regrade", json={"answer_key_id": missing}).status_code == 404


def test_batches_and_csv_export(client: TestClient, sheet_png: bytes, answer_key: dict, template: Template, marks: dict[str, str]) -> None:
    body = _upload(client, [("=evil.png", sheet_png, "image/png")], answer_key_id=answer_key["id"]).json()
    batch_id = body["batch_id"]
    detail = client.get(f"/api/batches/{batch_id}").json()
    assert detail["scan_count"] == 1 and detail["status_counts"]["ok"] == 1
    assert detail["mean_score"] == body["scans"][0]["grade"]["score"]
    assert any(b["id"] == batch_id for b in client.get("/api/batches").json())

    r = client.get(f"/api/batches/{batch_id}/export.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.text)))
    header = ["filename", "page", "roll_no", "paper_set", "status", "score", "max_score", "correct", "wrong",
              "blank", "multiple"] + [f"q{i}" for i in range(1, 81)]
    assert rows[0] == header
    row = dict(zip(header, rows[1], strict=True))
    assert row["filename"] == "'=evil.png"  # formula injection neutralised
    assert row["roll_no"] == expected_roll(template, marks)
    assert row["q1"] == marks["q1"]
    assert float(row["max_score"]) == 320.0
    assert client.get("/api/batches/00000000-0000-4000-8000-000000000000/export.csv").status_code == 404


def test_benchmarks_latest(client: TestClient, settings: Settings) -> None:
    assert client.get("/api/benchmarks/latest").status_code == 404
    settings.benchmark_reports_dir.mkdir(parents=True, exist_ok=True)
    (settings.benchmark_reports_dir / "latest.json").write_text(json.dumps({"tiers": {"clean": 1.0}}), encoding="utf-8")
    assert client.get("/api/benchmarks/latest").json() == {"tiers": {"clean": 1.0}}


def test_cors_only_allows_frontend_origin(client: TestClient) -> None:
    ok = client.options("/api/health", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == ORIGIN
    bad = client.options("/api/health", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers


def test_uploads_use_uuid_names(client: TestClient, settings: Settings, template: Template) -> None:
    dirs = [p for p in settings.uploads_dir.iterdir() if p.is_dir()]
    assert dirs
    for d in dirs:
        assert len(d.name) == 36 and d.name.count("-") == 4
        assert {p.name for p in d.iterdir()} <= {"original.png", "original.pdf", "aligned.png"}


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OMR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OMR_MAX_UPLOAD_MB", "7")
    monkeypatch.setenv("OMR_CORS_ORIGINS", "http://a, http://b")
    s = Settings.from_env()
    assert s.data_dir == tmp_path.resolve() and s.max_upload_mb == 7 and s.cors_origins == ("http://a", "http://b")
    assert replace(s, max_files=1).max_files == 1
