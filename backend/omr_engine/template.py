"""Template loading/validation and geometry helpers."""

from __future__ import annotations

import dataclasses
import json
import threading
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .config import EngineConfig
from .models import TemplateField, TemplateSpec
from .printcolor import PrintProfile, get_profile

TEMPLATE_FILENAME = "template.json"


class TemplateError(ValueError):
    """Raised when a template directory or its files are invalid."""


class Template:
    """A validated template plus its reference image and per-config derived caches."""

    def __init__(self, spec: TemplateSpec, directory: Path, reference: np.ndarray) -> None:
        w, h = spec.page.width_px, spec.page.height_px
        if reference.shape[:2] != (h, w):
            raise TemplateError(
                f"reference image is {reference.shape[1]}x{reference.shape[0]}, expected {w}x{h}"
            )
        self.spec = spec
        self.directory = directory
        self.reference = reference
        self._cache: dict[Any, Any] = {}
        self._cache_lock = threading.Lock()
        self._fields_by_id = {f.id: f for f in spec.fields}
        self.bubble_xy = np.array([[b.x, b.y] for f in spec.fields for b in f.bubbles], np.float64)
        self.bubble_r = np.array([b.r for f in spec.fields for b in f.bubbles], np.float64)
        offsets: list[tuple[int, int]] = []
        start = 0
        for f in spec.fields:
            offsets.append((start, start + len(f.bubbles)))
            start += len(f.bubbles)
        self.field_slices = offsets

    @property
    def id(self) -> str:
        return self.spec.id

    @property
    def size(self) -> tuple[int, int]:
        """(width, height) of the canonical template space."""
        return self.spec.page.width_px, self.spec.page.height_px

    @property
    def print_profile(self) -> PrintProfile:
        return get_profile(self.spec.print_color)

    @property
    def reference_path(self) -> Path:
        return self.directory / self.spec.reference_image

    def field(self, field_id: str) -> TemplateField:
        return self._fields_by_id[field_id]

    def fields_in(self, group: str) -> list[TemplateField]:
        return [f for f in self.spec.fields if f.group == group]

    @property
    def paper_sets(self) -> list[str]:
        sets = self.fields_in("paper_set")
        return [b.value for b in sets[0].bubbles] if sets else []

    def effective_config(self, cfg: EngineConfig) -> EngineConfig:
        """``cfg`` with this template's ``engine_overrides`` applied."""
        return dataclasses.replace(cfg, **self.spec.engine_overrides) if self.spec.engine_overrides else cfg

    def cached(self, key: Any, factory: Any) -> Any:
        """Return a derived object (e.g. registration features) computed once per key."""
        with self._cache_lock:
            if key not in self._cache:
                self._cache[key] = factory()
            return self._cache[key]


def load_template(directory: str | Path) -> Template:
    """Load ``template.json`` and its reference image from ``directory``."""
    path = Path(directory)
    json_path = path / TEMPLATE_FILENAME
    if not json_path.is_file():
        raise TemplateError(f"{json_path} not found")
    try:
        spec = TemplateSpec.model_validate(json.loads(json_path.read_text(encoding="utf-8")))
    except (ValueError, json.JSONDecodeError) as exc:
        raise TemplateError(f"invalid template {json_path}: {exc}") from exc
    known = {f.name for f in dataclasses.fields(EngineConfig)}
    unknown = set(spec.engine_overrides) - known
    if unknown:
        raise TemplateError(f"invalid template {json_path}: unknown engine_overrides {sorted(unknown)}")
    ref_path = (path / spec.reference_image).resolve()
    if ref_path.parent != path.resolve() or not ref_path.is_file():
        raise TemplateError(f"reference image {spec.reference_image!r} not found in {path}")
    reference = cv2.imdecode(np.fromfile(str(ref_path), np.uint8), cv2.IMREAD_COLOR)
    if reference is None:
        raise TemplateError(f"cannot decode reference image {ref_path}")
    return Template(spec, path, reference)
