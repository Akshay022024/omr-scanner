"""Decode uploaded bytes (JPEG/PNG/TIFF/WebP/PDF) into BGR page images."""

from __future__ import annotations

import io
from typing import Literal

import cv2
import numpy as np
import pymupdf
from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError

FileKind = Literal["jpeg", "png", "tiff", "webp", "pdf"]

MEDIA_TYPES: dict[FileKind, str] = {
    "jpeg": "image/jpeg",
    "png": "image/png",
    "tiff": "image/tiff",
    "webp": "image/webp",
    "pdf": "application/pdf",
}
EXTENSIONS: dict[FileKind, str] = {
    "jpeg": ".jpg",
    "png": ".png",
    "tiff": ".tif",
    "webp": ".webp",
    "pdf": ".pdf",
}


class DocumentError(ValueError):
    """Raised when bytes cannot be decoded into page images."""


def detect_kind(data: bytes) -> FileKind | None:
    """Identify a supported file type from its magic bytes (never from the filename)."""
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return "tiff"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:1024].lstrip().startswith(b"%PDF-"):
        return "pdf"
    return None


def pdf_page_count(data: bytes) -> int:
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            return doc.page_count
    except (RuntimeError, ValueError) as exc:
        raise DocumentError(f"cannot open PDF: {exc}") from exc


def clamp_size(img: np.ndarray, max_side: int) -> np.ndarray:
    h, w = img.shape[:2]
    side = max(h, w)
    if side <= max_side:
        return img
    f = max_side / side
    return cv2.resize(img, (max(1, round(w * f)), max(1, round(h * f))), interpolation=cv2.INTER_AREA)


def _render_pdf(data: bytes, dpi: int, max_side: int, max_pages: int) -> list[np.ndarray]:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except (RuntimeError, ValueError) as exc:
        raise DocumentError(f"cannot open PDF: {exc}") from exc
    with doc:
        if doc.page_count == 0:
            raise DocumentError("PDF has no pages")
        if doc.page_count > max_pages:
            raise DocumentError(f"PDF has {doc.page_count} pages (limit {max_pages})")
        pages: list[np.ndarray] = []
        for page in doc:
            longest_pt = max(page.rect.width, page.rect.height, 1.0)
            zoom = min(dpi / 72.0, max_side / longest_pt)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False, colorspace=pymupdf.csRGB)
            buf = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.stride)
            rgb = buf[:, : pix.width * 3].reshape(pix.height, pix.width, 3)
            pages.append(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    return pages


def _decode_raster(data: bytes, max_side: int, max_pages: int) -> list[np.ndarray]:
    try:
        with Image.open(io.BytesIO(data)) as im:
            pages: list[np.ndarray] = []
            for frame in ImageSequence.Iterator(im):
                if len(pages) >= max_pages:
                    raise DocumentError(f"image has more than {max_pages} frames")
                upright = ImageOps.exif_transpose(frame)
                rgb = np.asarray(upright.convert("RGB"))
                pages.append(clamp_size(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), max_side))
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise DocumentError(f"cannot decode image: {exc}") from exc
    if not pages:
        raise DocumentError("image has no frames")
    return pages


def load_document(
    data: bytes, *, max_side: int = 4000, pdf_dpi: int = 200, max_pages: int = 20
) -> list[np.ndarray]:
    """Decode bytes into a list of BGR uint8 images (one per page/frame)."""
    kind = detect_kind(data)
    if kind is None:
        raise DocumentError("unsupported file type (expected JPEG, PNG, TIFF, WebP or PDF)")
    if kind == "pdf":
        return _render_pdf(data, pdf_dpi, max_side, max_pages)
    return _decode_raster(data, max_side, max_pages)
