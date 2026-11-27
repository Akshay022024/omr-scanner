"""FastAPI app factory: settings, CORS, routers, optional static frontend, lifespan."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import omr_engine
from omr_engine import EngineConfig, Template, TemplateError, load_template
from omr_engine.registration import template_features

from .config import Settings
from .db import Database
from .routes import answer_keys, batches, benchmarks, health, scans, templates
from .storage import FileStore

logger = logging.getLogger(__name__)


def load_templates(settings: Settings, cfg: EngineConfig) -> dict[str, Template]:
    """Load every template directory and pre-compute its registration features."""
    found: dict[str, Template] = {}
    if not settings.templates_dir.is_dir():
        logger.warning("templates directory %s not found", settings.templates_dir)
        return found
    for sub in sorted(p for p in settings.templates_dir.iterdir() if p.is_dir()):
        if not (sub / "template.json").is_file():
            continue
        try:
            tpl = load_template(sub)
        except TemplateError as exc:
            logger.error("skipping template %s: %s", sub.name, exc)
            continue
        template_features(tpl, tpl.effective_config(cfg))
        found[tpl.id] = tpl
    return found


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    cfg = EngineConfig()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.uploads_dir.mkdir(parents=True, exist_ok=True)
        db = Database(settings.db_path)
        db.init()
        app.state.settings = settings
        app.state.db = db
        app.state.store = FileStore(settings.uploads_dir)
        app.state.engine_config = cfg
        app.state.templates = load_templates(settings, cfg)
        yield

    app = FastAPI(title="OMR Scanner API", version=omr_engine.__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )
    for module in (health, templates, answer_keys, scans, batches, benchmarks):
        app.include_router(module.router, prefix="/api")
    if settings.frontend_dist is not None and settings.frontend_dist.is_dir():
        app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True), name="frontend")
    return app


app = create_app()
