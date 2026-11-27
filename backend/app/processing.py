"""Upload validation and synchronous scan processing (MVP)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from omr_engine import EngineConfig, ScanResult, Template, align_to_template, scan_image
from omr_engine.io import EXTENSIONS, MEDIA_TYPES, DocumentError, FileKind, detect_kind, load_document, pdf_page_count

from .db import Database, utc_now
from .records import grade_with, scan_record
from .schemas import ScanRecord
from .storage import ALIGNED_FILE, ORIGINAL_STEM, FileStore, new_id

logger = logging.getLogger(__name__)

_UNSAFE_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class UploadRejected(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class ValidatedUpload:
    filename: str
    data: bytes
    kind: FileKind


def display_name(raw: str | None) -> str:
    """A display-only filename (never used for paths): basename, no control chars, bounded length."""
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = _UNSAFE_CHARS.sub("", name).strip()
    return name[:200] or "upload"


def validate_upload(raw_name: str | None, data: bytes, max_pdf_pages: int) -> ValidatedUpload:
    name = display_name(raw_name)
    kind = detect_kind(data)
    if kind is None:
        raise UploadRejected(415, f"{name}: unsupported file type (JPEG, PNG, TIFF, WebP or PDF required)")
    if kind == "pdf":
        try:
            pages = pdf_page_count(data)
        except DocumentError as exc:
            raise UploadRejected(400, f"{name}: {exc}") from exc
        if pages > max_pdf_pages:
            raise UploadRejected(400, f"{name}: PDF has {pages} pages (limit {max_pdf_pages})")
    return ValidatedUpload(name, data, kind)


def _failed_result(tpl: Template, error: str) -> ScanResult:
    return ScanResult(template_id=tpl.id, status="failed", error=error, aligned_size=tpl.size)


def process_upload(
    upload: ValidatedUpload,
    batch_id: str,
    tpl: Template,
    answer_key_id: str | None,
    db: Database,
    store: FileStore,
    max_pdf_pages: int,
    cfg: EngineConfig,
) -> list[ScanRecord]:
    """Decode, scan, store files and insert one scan row per page.

    The uploaded bytes are kept as the original for single-page images (and undecodable files);
    PDF pages and multi-frame TIFF pages are stored as rendered PNGs.
    """
    decode_error = ""
    try:
        pages = load_document(upload.data, max_side=cfg.max_side_px, pdf_dpi=cfg.pdf_dpi, max_pages=max_pdf_pages)
    except DocumentError as exc:
        logger.info("decode failed for upload: %s", exc)
        pages = []
        decode_error = str(exc)
    keep_raw = not pages or (upload.kind != "pdf" and len(pages) == 1)
    records: list[ScanRecord] = []
    for page_no, img in enumerate(pages or [None], start=1):
        scan_id = new_id()
        if keep_raw:
            original = store.save_bytes(scan_id, ORIGINAL_STEM + EXTENSIONS[upload.kind], upload.data)
            media_type = MEDIA_TYPES[upload.kind]
        else:
            original = store.save_png(scan_id, ORIGINAL_STEM + ".png", img)
            media_type = "image/png"
        if img is None:
            result = _failed_result(tpl, decode_error)
        else:
            result = scan_image(img, tpl, cfg)
            store.save_png(scan_id, ALIGNED_FILE, align_to_template(img, result, tpl))
        grade = grade_with(db, result, answer_key_id)
        row = {
            "id": scan_id,
            "batch_id": batch_id,
            "filename": upload.filename,
            "page": page_no,
            "created_at": utc_now(),
            "original_file": original,
            "original_media_type": media_type,
            "answer_key_id": answer_key_id,
            "result_json": result.model_dump_json(),
            "grade_json": grade.model_dump_json() if grade else None,
        }
        db.insert_scan(row)
        records.append(scan_record({**row, "corrected": 0}))
    return records
