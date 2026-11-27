"""CSV export of a batch."""

from __future__ import annotations

import csv
import io

from .schemas import ScanRecord

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _safe_text(value: str) -> str:
    """Neutralise spreadsheet formula injection in free-text cells."""
    return "'" + value if value.startswith(_FORMULA_PREFIXES) else value


def batch_csv(scans: list[ScanRecord], num_questions: int) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(
        ["filename", "page", "roll_no", "paper_set", "status", "score", "max_score", "correct", "wrong", "blank",
         "multiple"]
        + [f"q{i}" for i in range(1, num_questions + 1)]
    )
    for s in scans:
        r, g = s.result, s.grade
        grade_cells = (
            [g.score, g.max_score, g.correct, g.wrong, g.blank, g.multiple] if g is not None else [""] * 6
        )
        writer.writerow(
            [_safe_text(s.filename), s.page, _safe_text(r.roll_no), r.paper_set or "", r.status, *grade_cells]
            + [r.answers.get(str(i), "") for i in range(1, num_questions + 1)]
        )
    return out.getvalue()
