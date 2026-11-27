from __future__ import annotations

import json

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException

from omr_engine import render_overlay

from ..corrections import apply_correction
from ..deps import DbDep, EngineConfigDep, SettingsDep, StoreDep, TemplatesDep, require_uuid, template_or_404
from ..processing import UploadRejected, ValidatedUpload, process_upload, validate_upload
from ..records import grade_with, scan_record
from ..schemas import RegradeRequest, ScanCorrection, ScanRecord, ScanUploadResponse
from ..storage import ALIGNED_FILE, new_id

router = APIRouter(prefix="/scans", tags=["scans"])

_FILE_FIELDS = ("files", "files[]")
_CHUNK = 1024 * 1024
_FORM_OVERHEAD = 64 * 1024


async def _read_limited(upload: UploadFile, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(_CHUNK):
        total += len(chunk)
        if total > limit:
            raise HTTPException(status_code=413, detail=f"{upload.filename or 'file'}: exceeds {limit // (1024 * 1024)} MB")
        chunks.append(chunk)
    return b"".join(chunks)


def _load_row(db: DbDep, scan_id: str) -> dict[str, object]:
    row = db.get_scan(require_uuid(scan_id, "scan"))
    if row is None:
        raise HTTPException(status_code=404, detail="scan not found")
    return row


def _check_answer_key(db: DbDep, answer_key_id: str, template_id: str) -> None:
    row = db.get_answer_key(require_uuid(answer_key_id, "answer key"))
    if row is None:
        raise HTTPException(status_code=404, detail="answer key not found")
    if row["template_id"] != template_id:
        raise HTTPException(status_code=400, detail="answer key belongs to a different template")


@router.post("", response_model=ScanUploadResponse)
async def upload_scans(
    request: Request,
    db: DbDep,
    store: StoreDep,
    templates: TemplatesDep,
    settings: SettingsDep,
    cfg: EngineConfigDep,
) -> ScanUploadResponse:
    """multipart/form-data: ``files`` (or ``files[]``), ``template_id``, optional ``answer_key_id``."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > settings.max_files * (settings.max_upload_bytes + _FORM_OVERHEAD):
        raise HTTPException(status_code=413, detail="request too large")
    try:
        async with request.form(max_files=settings.max_files, max_fields=20) as form:
            template_id = form.get("template_id")
            answer_key_id = form.get("answer_key_id") or None
            files = [v for k, v in form.multi_items() if k in _FILE_FIELDS and isinstance(v, UploadFile)]
            if not isinstance(template_id, str) or not template_id:
                raise HTTPException(status_code=422, detail="template_id is required")
            if answer_key_id is not None and not isinstance(answer_key_id, str):
                raise HTTPException(status_code=422, detail="answer_key_id must be a string")
            if not files:
                raise HTTPException(status_code=422, detail="at least one file is required")
            tpl = template_or_404(templates, template_id)
            if answer_key_id:
                _check_answer_key(db, answer_key_id, template_id)
            uploads: list[ValidatedUpload] = []
            for f in files:
                data = await _read_limited(f, settings.max_upload_bytes)
                uploads.append(validate_upload(f.filename, data, settings.max_pdf_pages))
    except MultiPartException as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except UploadRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    batch_id = new_id()
    db.insert_batch(batch_id, tpl.id, answer_key_id)

    def run() -> list[ScanRecord]:
        records: list[ScanRecord] = []
        for upload in uploads:
            records += process_upload(upload, batch_id, tpl, answer_key_id, db, store, settings.max_pdf_pages, cfg)
        return records

    return ScanUploadResponse(batch_id=batch_id, scans=await run_in_threadpool(run))


@router.get("", response_model=list[ScanRecord])
def list_scans(db: DbDep, batch_id: str | None = Query(default=None)) -> list[ScanRecord]:
    if batch_id is not None:
        require_uuid(batch_id, "batch")
    return [scan_record(r) for r in db.list_scans(batch_id)]


@router.get("/{scan_id}", response_model=ScanRecord)
def get_scan(scan_id: str, db: DbDep) -> ScanRecord:
    return scan_record(_load_row(db, scan_id))


@router.get("/{scan_id}/aligned.png", response_class=FileResponse)
def get_aligned(scan_id: str, db: DbDep, store: StoreDep) -> FileResponse:
    _load_row(db, scan_id)
    path = store.path(scan_id, ALIGNED_FILE)
    if path is None:
        raise HTTPException(status_code=404, detail="aligned image not available")
    return FileResponse(path, media_type="image/png")


@router.get("/{scan_id}/overlay.png")
def get_overlay(scan_id: str, db: DbDep, store: StoreDep, templates: TemplatesDep) -> Response:
    record = scan_record(_load_row(db, scan_id))
    path = store.path(scan_id, ALIGNED_FILE)
    if path is None:
        raise HTTPException(status_code=404, detail="aligned image not available")
    tpl = template_or_404(templates, record.result.template_id)
    aligned = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
    ok, buf = cv2.imencode(".png", render_overlay(aligned, record.result, tpl, already_aligned=True))
    if not ok:
        raise HTTPException(status_code=500, detail="overlay rendering failed")
    return Response(content=buf.tobytes(), media_type="image/png")


@router.get("/{scan_id}/original", response_class=FileResponse)
def get_original(scan_id: str, db: DbDep, store: StoreDep) -> FileResponse:
    row = _load_row(db, scan_id)
    path = store.path(scan_id, str(row["original_file"])) if row["original_file"] else None
    if path is None:
        raise HTTPException(status_code=404, detail="original file not available")
    return FileResponse(path, media_type=str(row["original_media_type"]))


@router.patch("/{scan_id}", response_model=ScanRecord)
def correct_scan(scan_id: str, correction: ScanCorrection, db: DbDep, templates: TemplatesDep) -> ScanRecord:
    row = _load_row(db, scan_id)
    record = scan_record(row)
    tpl = template_or_404(templates, record.result.template_id)
    try:
        corrected = apply_correction(record.result, correction, tpl)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    history = json.loads(str(row["corrections_json"])) if row["corrections_json"] else []
    history.append(correction.model_dump(exclude_unset=True))
    grade = grade_with(db, corrected, record.answer_key_id)
    db.update_scan(
        scan_id,
        {
            "result_json": corrected.model_dump_json(),
            "grade_json": grade.model_dump_json() if grade else None,
            "corrected": 1,
            "corrections_json": json.dumps(history),
        },
    )
    return scan_record(_load_row(db, scan_id))


@router.post("/{scan_id}/regrade", response_model=ScanRecord)
def regrade_scan(scan_id: str, body: RegradeRequest, db: DbDep) -> ScanRecord:
    record = scan_record(_load_row(db, scan_id))
    _check_answer_key(db, body.answer_key_id, record.result.template_id)
    grade = grade_with(db, record.result, body.answer_key_id)
    db.update_scan(
        scan_id,
        {"answer_key_id": body.answer_key_id, "grade_json": grade.model_dump_json() if grade else None},
    )
    return scan_record(_load_row(db, scan_id))
