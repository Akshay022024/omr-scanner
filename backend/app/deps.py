"""FastAPI dependencies: shared state set up by the app lifespan."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request

from omr_engine import EngineConfig, Template

from .config import Settings
from .db import Database
from .storage import FileStore, is_uuid


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_store(request: Request) -> FileStore:
    return request.app.state.store


def get_templates(request: Request) -> dict[str, Template]:
    return request.app.state.templates


def get_engine_config(request: Request) -> EngineConfig:
    return request.app.state.engine_config


SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[Database, Depends(get_db)]
StoreDep = Annotated[FileStore, Depends(get_store)]
TemplatesDep = Annotated[dict[str, Template], Depends(get_templates)]
EngineConfigDep = Annotated[EngineConfig, Depends(get_engine_config)]


def template_or_404(templates: dict[str, Template], template_id: str) -> Template:
    tpl = templates.get(template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail=f"template {template_id!r} not found")
    return tpl


def require_uuid(value: str, what: str) -> str:
    if not is_uuid(value):
        raise HTTPException(status_code=404, detail=f"{what} not found")
    return value
