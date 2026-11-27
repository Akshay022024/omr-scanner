"""Settings from environment variables (no secrets are needed by the MVP)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else default


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if not value:
        return default
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return parsed


@dataclass(frozen=True)
class Settings:
    data_dir: Path = PROJECT_ROOT / "data"
    templates_dir: Path = PROJECT_ROOT / "templates"
    benchmark_reports_dir: Path = PROJECT_ROOT / "benchmarks" / "reports"
    frontend_dist: Path | None = None
    max_upload_mb: int = 20
    max_files: int = 50
    max_pdf_pages: int = 20
    cors_origins: tuple[str, ...] = field(default=("http://localhost:5173",))

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def db_path(self) -> Path:
        return self.data_dir / "omr.db"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @classmethod
    def from_env(cls) -> Settings:
        origins = os.environ.get("OMR_CORS_ORIGINS")
        frontend = os.environ.get("OMR_FRONTEND_DIST")
        return cls(
            data_dir=_env_path("OMR_DATA_DIR", PROJECT_ROOT / "data"),
            templates_dir=_env_path("OMR_TEMPLATES_DIR", PROJECT_ROOT / "templates"),
            benchmark_reports_dir=_env_path("OMR_BENCHMARK_REPORTS_DIR", PROJECT_ROOT / "benchmarks" / "reports"),
            frontend_dist=Path(frontend).resolve() if frontend else None,
            max_upload_mb=_env_int("OMR_MAX_UPLOAD_MB", 20),
            max_files=_env_int("OMR_MAX_FILES", 50),
            max_pdf_pages=_env_int("OMR_MAX_PDF_PAGES", 20),
            cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()) if origins else ("http://localhost:5173",),
        )
