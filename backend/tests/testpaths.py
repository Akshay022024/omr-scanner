"""Filesystem locations shared by the test modules."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = PROJECT_ROOT / "templates"
SHEET80_ID = "sheet80_v2"
TEMPLATE_DIR = TEMPLATES_DIR / SHEET80_ID
PUBLIC_TEMPLATE_DIR = TEMPLATES_DIR / "tamaulipas_90"

# The sheet80 reference image is third-party artwork kept out of git; tests that need it skip without it.
SHEET80_AVAILABLE = (TEMPLATE_DIR / "template.json").is_file() and (TEMPLATE_DIR / "template_200dpi.png").is_file()
SHEET80_SKIP_REASON = "sheet80_v2 reference image not present (third-party artwork, not in git)"
