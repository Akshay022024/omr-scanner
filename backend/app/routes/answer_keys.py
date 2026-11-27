from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Response

from ..db import utc_now
from ..deps import DbDep, TemplatesDep, require_uuid, template_or_404
from ..records import answer_key_out, validate_keys
from ..schemas import AnswerKeyIn, AnswerKeyOut
from ..storage import new_id

router = APIRouter(prefix="/answer-keys", tags=["answer-keys"])


def _row(key_id: str, payload: AnswerKeyIn, templates: TemplatesDep, created_at: str) -> dict[str, object]:
    tpl = template_or_404(templates, payload.template_id)
    try:
        keys = validate_keys(payload, tpl)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "id": key_id,
        "name": payload.name.strip(),
        "template_id": payload.template_id,
        "keys_json": json.dumps(keys, sort_keys=True),
        "marks_correct": payload.marks_correct,
        "marks_wrong": payload.marks_wrong,
        "marks_blank": payload.marks_blank,
        "created_at": created_at,
        "updated_at": utc_now(),
    }


@router.get("", response_model=list[AnswerKeyOut])
def list_answer_keys(db: DbDep) -> list[AnswerKeyOut]:
    return [answer_key_out(r) for r in db.list_answer_keys()]


@router.post("", response_model=AnswerKeyOut, status_code=201)
def create_answer_key(payload: AnswerKeyIn, db: DbDep, templates: TemplatesDep) -> AnswerKeyOut:
    row = _row(new_id(), payload, templates, utc_now())
    db.insert_answer_key(row)
    return answer_key_out(row)


@router.get("/{key_id}", response_model=AnswerKeyOut)
def get_answer_key(key_id: str, db: DbDep) -> AnswerKeyOut:
    row = db.get_answer_key(require_uuid(key_id, "answer key"))
    if row is None:
        raise HTTPException(status_code=404, detail="answer key not found")
    return answer_key_out(row)


@router.put("/{key_id}", response_model=AnswerKeyOut)
def update_answer_key(key_id: str, payload: AnswerKeyIn, db: DbDep, templates: TemplatesDep) -> AnswerKeyOut:
    existing = db.get_answer_key(require_uuid(key_id, "answer key"))
    if existing is None:
        raise HTTPException(status_code=404, detail="answer key not found")
    row = _row(key_id, payload, templates, existing["created_at"])
    db.update_answer_key(row)
    return answer_key_out(row)


@router.delete("/{key_id}", status_code=204)
def delete_answer_key(key_id: str, db: DbDep) -> Response:
    if not db.delete_answer_key(require_uuid(key_id, "answer key")):
        raise HTTPException(status_code=404, detail="answer key not found")
    return Response(status_code=204)
