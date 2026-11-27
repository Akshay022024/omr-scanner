from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException

from ..deps import SettingsDep

router = APIRouter(prefix="/benchmarks", tags=["benchmarks"])


@router.get("/latest")
def latest_benchmark(settings: SettingsDep) -> dict[str, Any]:
    path = settings.benchmark_reports_dir / "latest.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="no benchmark report yet")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="benchmark report is unreadable") from exc
