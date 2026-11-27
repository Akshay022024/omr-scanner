"""OMR engine: a pure, deterministic library (no web, no DB).

Public API (see ARCHITECTURE.md section 6)::

    tpl = load_template("templates/sheet80_v2")
    res = scan_image(img_bgr, tpl, config=EngineConfig())
    results = scan_document(file_bytes, filename, tpl)
    g = grade(res, answer_key)
    png = render_overlay(img_bgr, res, tpl)
"""

from .config import EngineConfig
from .grading import grade
from .io import DocumentError, detect_kind, load_document
from .models import AnswerKey, FieldResult, GradeResult, RegistrationInfo, ScanResult, TemplateSpec
from .overlay import align_to_template, render_overlay
from .pipeline import scan_document, scan_image
from .template import Template, TemplateError, load_template

__version__ = "0.1.0"

__all__ = [
    "AnswerKey",
    "DocumentError",
    "EngineConfig",
    "FieldResult",
    "GradeResult",
    "RegistrationInfo",
    "ScanResult",
    "Template",
    "TemplateError",
    "TemplateSpec",
    "__version__",
    "align_to_template",
    "detect_kind",
    "grade",
    "load_document",
    "load_template",
    "render_overlay",
    "scan_document",
    "scan_image",
]
