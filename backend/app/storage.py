"""File store for uploads: data/uploads/{scan_id}/ with fixed file names (never user-supplied)."""

from __future__ import annotations

import uuid
from pathlib import Path

import cv2
import numpy as np

ALIGNED_FILE = "aligned.png"
ORIGINAL_STEM = "original"
_PNG_COMPRESSION = 3  # fast encode; review images are written once per scan


def new_id() -> str:
    return str(uuid.uuid4())


def is_uuid(value: str) -> bool:
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


class FileStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _dir(self, scan_id: str) -> Path:
        if not is_uuid(scan_id):
            raise ValueError("invalid scan id")
        return self.root / scan_id

    def save_bytes(self, scan_id: str, name: str, data: bytes) -> str:
        directory = self._dir(scan_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / name).write_bytes(data)
        return name

    def save_png(self, scan_id: str, name: str, img: np.ndarray) -> str:
        ok, buf = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, _PNG_COMPRESSION])
        if not ok:
            raise ValueError("PNG encoding failed")
        return self.save_bytes(scan_id, name, buf.tobytes())

    def path(self, scan_id: str, name: str) -> Path | None:
        path = self._dir(scan_id) / name
        return path if path.is_file() else None
