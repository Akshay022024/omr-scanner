"""End-to-end scan: page normalise -> register -> ink -> bubbles -> decide -> assemble."""

from __future__ import annotations

import logging
from time import perf_counter

import cv2
import numpy as np

from .bubbles import score_bubbles
from .config import EngineConfig
from .decide import adaptive_threshold, decide_field
from .geometry import normalise, scale_matrix, warp_to_template
from .ink import ink_map, normalize_illumination, print_mask, to_hsv
from .io import DocumentError, load_document
from .models import FieldResult, RegistrationInfo, ScanResult, ScanStatus
from .page import estimate_page_transform
from .registration import register, template_features
from .verify import GeometryCheck, verify_alignment
from .template import Template

logger = logging.getLogger(__name__)


def _ms(start: float) -> float:
    return round((perf_counter() - start) * 1000.0, 1)


def _roll_char(field: FieldResult) -> str:
    if field.state == "single":
        return field.value
    return "*" if field.state == "multiple" else "?"


def _assemble(
    fields: list[FieldResult], quality: float, layout_score: float, geometry: GeometryCheck, cfg: EngineConfig
) -> tuple[str, str | None, dict[str, str], list[str], ScanStatus, str | None]:
    """Build roll no / paper set / answers, review flags and the sheet status.

    The geometric verification (print lock + anchor edges) is the registration gate: when it
    passes, the mask IoU is not used (it drops on blurred or low-resolution images that still read
    correctly). When it fails, a very low IoU means ``failed``; otherwise the sheet goes to review.
    """
    roll_no = "".join(_roll_char(f) for f in fields if f.group == "roll_no")
    paper = next((f for f in fields if f.group == "paper_set"), None)
    paper_set = paper.value if paper is not None and paper.state == "single" else None
    answers = {str(f.question): f.value for f in fields if f.group == "answers"}
    flags = [
        f"{f.id}:{f.state}"
        for f in fields
        if f.state in ("multiple", "ambiguous") or (f.state == "blank" and (f.group != "answers" or cfg.flag_blank_answers))
    ]
    status: ScanStatus = "ok"
    error = None
    if layout_score < cfg.min_layout_score:
        status, error = "failed", f"sheet layout not found (score {layout_score:.2f})"
    elif not geometry.ok(cfg) and quality < cfg.quality_fail:
        status, error = "failed", f"registration failed (mask IoU {quality:.2f}, geometry check failed)"
    elif not geometry.ok(cfg) and geometry.lock_score is not None and geometry.lock_score < cfg.lock_fail_score:
        status, error = "failed", f"registration failed (print correlation {geometry.lock_score:.2f})"
    else:
        if not geometry.ok(cfg):
            flags.insert(0, "registration:geometry")
        if flags:
            status = "needs_review"
    return roll_no, paper_set, answers, flags, status, error


def scan_image(img_bgr: np.ndarray, tpl: Template, config: EngineConfig | None = None) -> ScanResult:
    """Read one page image (BGR uint8). Never raises for bad images: returns status ``failed``.

    The template's ``engine_overrides`` (if any) are applied on top of ``config``.
    """
    cfg = tpl.effective_config(config or EngineConfig())
    width, height = tpl.size
    t_start = perf_counter()
    timings: dict[str, float] = {}
    try:
        if img_bgr is None or img_bgr.ndim != 3 or img_bgr.shape[2] != 3 or min(img_bgr.shape[:2]) < 64:
            raise ValueError("expected a BGR image of at least 64x64 pixels")
        feats = template_features(tpl, cfg)

        t = perf_counter()
        page = estimate_page_transform(img_bgr, feats, cfg)
        page_img = warp_to_template(page.source, page.homography, (width, height))
        page_norm = normalize_illumination(page_img, cfg)
        page_print = print_mask(to_hsv(page_norm), feats.profile, cfg)
        page_ink = ink_map(page_norm, cfg)
        timings["page"] = _ms(t)

        t = perf_counter()
        reg = register(page_print, page_norm, feats, cfg)
        geometry = verify_alignment(page_norm, reg.homography, tpl, feats, cfg)
        timings["register"] = _ms(t)

        t = perf_counter()
        ink = warp_to_template(page_ink, reg.homography, (width, height), border=cv2.BORDER_CONSTANT)
        scores = score_bubbles(ink.astype(np.float32) / 255.0, tpl.bubble_xy, tpl.bubble_r, cfg)
        threshold = adaptive_threshold(scores, cfg)
        fields = [
            decide_field(f, scores[a:b], threshold, cfg)
            for f, (a, b) in zip(tpl.spec.fields, tpl.field_slices, strict=True)
        ]
        roll_no, paper_set, answers, flags, status, error = _assemble(fields, reg.quality, page.score, geometry, cfg)
        timings["read"] = _ms(t)
    except (cv2.error, ValueError, ArithmeticError, np.linalg.LinAlgError) as exc:
        logger.warning("scan failed: %s", exc)
        timings["total"] = _ms(t_start)
        return ScanResult(
            template_id=tpl.id, status="failed", error=str(exc), aligned_size=(width, height), timings_ms=timings
        )

    to_original = scale_matrix(1.0 / page.source_scale) @ page.homography @ reg.homography
    timings["total"] = _ms(t_start)
    return ScanResult(
        template_id=tpl.id,
        status=status,
        error=error,
        roll_no=roll_no,
        paper_set=paper_set,
        answers=answers,
        fields=fields,
        review_flags=flags,
        registration=RegistrationInfo(
            method=reg.method,
            quality=round(reg.quality, 4),
            homography=[[float(v) for v in row] for row in normalise(to_original)],
            layout_score=round(page.score, 4),
            geometry_ok=geometry.ok(cfg),
            anchor_coverage=min(geometry.coverage_h, geometry.coverage_v),
            anchor_residual_px=geometry.residual_px,
            print_lock=geometry.lock_score,
            print_lock_margin=geometry.lock_margin,
        ),
        threshold=round(threshold, 4),
        aligned_size=(width, height),
        timings_ms=timings,
    )


def scan_document(
    file_bytes: bytes, filename: str, tpl: Template, config: EngineConfig | None = None
) -> list[ScanResult]:
    """Decode an uploaded file (image or PDF) and scan every page.

    Raises ``DocumentError`` when the bytes cannot be decoded.
    """
    cfg = config or EngineConfig()
    t = perf_counter()
    try:
        pages = load_document(file_bytes, max_side=cfg.max_side_px, pdf_dpi=cfg.pdf_dpi, max_pages=cfg.max_pdf_pages)
    except DocumentError as exc:
        raise DocumentError(f"{filename}: {exc}") from exc
    load_ms = _ms(t) / len(pages)
    results = []
    for img in pages:
        res = scan_image(img, tpl, cfg)
        res.timings_ms = {"load": round(load_ms, 1), **res.timings_ms}
        res.timings_ms["total"] = round(res.timings_ms["total"] + load_ms, 1)
        results.append(res)
    return results
