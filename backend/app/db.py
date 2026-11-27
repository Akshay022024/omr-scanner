"""SQLite repository layer (stdlib sqlite3, WAL mode, parameterised SQL only)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MIGRATIONS: list[str] = [
    """
    CREATE TABLE answer_keys (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        template_id TEXT NOT NULL,
        keys_json TEXT NOT NULL,
        marks_correct REAL NOT NULL,
        marks_wrong REAL NOT NULL,
        marks_blank REAL NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE batches (
        id TEXT PRIMARY KEY,
        template_id TEXT NOT NULL,
        answer_key_id TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE scans (
        id TEXT PRIMARY KEY,
        batch_id TEXT NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
        filename TEXT NOT NULL,
        page INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        original_file TEXT,
        original_media_type TEXT,
        answer_key_id TEXT,
        result_json TEXT NOT NULL,
        grade_json TEXT,
        corrected INTEGER NOT NULL DEFAULT 0,
        corrections_json TEXT
    );
    CREATE INDEX idx_scans_batch ON scans(batch_id, created_at, page);
    """,
]


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
            current = row["v"] or 0
            for version, script in enumerate(MIGRATIONS, start=1):
                if version > current:
                    conn.executescript(script)
                    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))

    # ------------------------------------------------------------------ answer keys

    def list_answer_keys(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM answer_keys ORDER BY created_at, name")]

    def get_answer_key(self, key_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM answer_keys WHERE id = ?", (key_id,)).fetchone()
            return dict(row) if row else None

    def insert_answer_key(self, row: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO answer_keys (id, name, template_id, keys_json, marks_correct, marks_wrong, marks_blank,"
                " created_at, updated_at) VALUES (:id, :name, :template_id, :keys_json, :marks_correct, :marks_wrong,"
                " :marks_blank, :created_at, :updated_at)",
                row,
            )

    def update_answer_key(self, row: dict[str, Any]) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE answer_keys SET name = :name, template_id = :template_id, keys_json = :keys_json,"
                " marks_correct = :marks_correct, marks_wrong = :marks_wrong, marks_blank = :marks_blank,"
                " updated_at = :updated_at WHERE id = :id",
                row,
            )
            return cur.rowcount > 0

    def delete_answer_key(self, key_id: str) -> bool:
        with self.connect() as conn:
            return conn.execute("DELETE FROM answer_keys WHERE id = ?", (key_id,)).rowcount > 0

    # ------------------------------------------------------------------ batches

    def insert_batch(self, batch_id: str, template_id: str, answer_key_id: str | None) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO batches (id, template_id, answer_key_id, created_at) VALUES (?, ?, ?, ?)",
                (batch_id, template_id, answer_key_id, utc_now()),
            )

    def get_batch(self, batch_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
            return dict(row) if row else None

    def list_batches(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM batches ORDER BY created_at DESC, id")]

    # ------------------------------------------------------------------ scans

    def insert_scan(self, row: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO scans (id, batch_id, filename, page, created_at, original_file, original_media_type,"
                " answer_key_id, result_json, grade_json, corrected, corrections_json) VALUES (:id, :batch_id,"
                " :filename, :page, :created_at, :original_file, :original_media_type, :answer_key_id, :result_json,"
                " :grade_json, 0, NULL)",
                row,
            )

    def get_scan(self, scan_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
            return dict(row) if row else None

    def list_scans(self, batch_id: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if batch_id is None:
                rows = conn.execute(
                    "SELECT * FROM scans ORDER BY created_at DESC, filename, page LIMIT ?", (limit,)
                )
            else:
                rows = conn.execute(
                    "SELECT * FROM scans WHERE batch_id = ? ORDER BY created_at, filename, page LIMIT ?",
                    (batch_id, limit),
                )
            return [dict(r) for r in rows]

    def update_scan(self, scan_id: str, fields: dict[str, Any]) -> None:
        allowed = {"result_json", "grade_json", "corrected", "corrections_json", "answer_key_id"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"cannot update columns {sorted(unknown)}")
        assignments = ", ".join(f"{name} = :{name}" for name in sorted(fields))
        with self.connect() as conn:
            conn.execute(f"UPDATE scans SET {assignments} WHERE id = :id", {**fields, "id": scan_id})
