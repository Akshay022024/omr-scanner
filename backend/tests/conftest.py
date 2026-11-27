from __future__ import annotations

import sys
from pathlib import Path

# Make `omr_engine`, `app` and the test helpers importable even when pytest is started from the
# project root with several directories (e.g. `pytest backend benchmarks`), where
# backend/pyproject.toml is not used as the configuration file.
_TESTS = Path(__file__).resolve().parent
for _p in (_TESTS.parent, _TESTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from omr_engine import EngineConfig, Template, load_template  # noqa: E402
from omr_synth import fill_sheet, random_marks  # noqa: E402
from testpaths import SHEET80_AVAILABLE, SHEET80_SKIP_REASON, TEMPLATE_DIR  # noqa: E402


@pytest.fixture(scope="session")
def template() -> Template:
    if not SHEET80_AVAILABLE:
        pytest.skip(SHEET80_SKIP_REASON)
    return load_template(TEMPLATE_DIR)


@pytest.fixture(scope="session")
def cfg() -> EngineConfig:
    return EngineConfig()


@pytest.fixture(scope="session")
def marks(template: Template) -> dict[str, str]:
    return random_marks(template, seed=11)


@pytest.fixture(scope="session")
def filled_sheet(template: Template, marks: dict[str, str]) -> np.ndarray:
    return fill_sheet(template, marks)
