from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from ..deps import DbDep, TemplatesDep, require_uuid, template_or_404
from ..export import batch_csv
from ..records import batch_summary, scan_record
from ..schemas import BatchDetail, BatchSummary

router = APIRouter(prefix="/batches", tags=["batches"])


def _batch_row(db: DbDep, batch_id: str) -> dict[str, object]:
    row = db.get_batch(require_uuid(batch_id, "batch"))
    if row is None:
        raise HTTPException(status_code=404, detail="batch not found")
    return row


@router.get("", response_model=list[BatchSummary])
def list_batches(db: DbDep) -> list[BatchSummary]:
    return [batch_summary(b, [scan_record(r) for r in db.list_scans(b["id"])]) for b in db.list_batches()]


@router.get("/{batch_id}", response_model=BatchDetail)
def get_batch(batch_id: str, db: DbDep) -> BatchDetail:
    row = _batch_row(db, batch_id)
    scans = [scan_record(r) for r in db.list_scans(batch_id)]
    return BatchDetail(**batch_summary(row, scans).model_dump(), scans=scans)


@router.get("/{batch_id}/export.csv")
def export_batch(batch_id: str, db: DbDep, templates: TemplatesDep) -> Response:
    row = _batch_row(db, batch_id)
    tpl = template_or_404(templates, str(row["template_id"]))
    scans = [scan_record(r) for r in db.list_scans(batch_id)]
    return Response(
        content=batch_csv(scans, tpl.spec.num_questions),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="batch-{batch_id}.csv"'},
    )
