from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse

from omr_engine import TemplateSpec

from ..deps import TemplatesDep, template_or_404
from ..schemas import TemplateSummary

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=list[TemplateSummary])
def list_templates(templates: TemplatesDep) -> list[TemplateSummary]:
    return [
        TemplateSummary(
            id=t.id,
            name=t.spec.name,
            version=t.spec.version,
            num_questions=t.spec.num_questions,
            options=t.spec.options,
            paper_sets=t.paper_sets,
        )
        for t in sorted(templates.values(), key=lambda t: t.id)
    ]


@router.get("/{template_id}", response_model=TemplateSpec)
def get_template(template_id: str, templates: TemplatesDep) -> TemplateSpec:
    return template_or_404(templates, template_id).spec


@router.get("/{template_id}/image", response_class=FileResponse)
def get_template_image(template_id: str, templates: TemplatesDep) -> FileResponse:
    tpl = template_or_404(templates, template_id)
    return FileResponse(tpl.reference_path, media_type="image/png")
