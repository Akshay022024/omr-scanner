from __future__ import annotations

from fastapi import APIRouter

import omr_engine

from ..deps import TemplatesDep
from ..schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(templates: TemplatesDep) -> HealthResponse:
    return HealthResponse(status="ok", engine_version=omr_engine.__version__, templates=len(templates))
