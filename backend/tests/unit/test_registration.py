from __future__ import annotations

import cv2
import numpy as np
import pytest

from omr_engine import EngineConfig, Template
from omr_engine.geometry import apply, warp_to_template
from omr_engine.ink import normalize_illumination, print_mask, to_hsv
from omr_engine.page import estimate_page_transform, order_corners
from omr_engine.registration import register, template_features
from omr_engine.verify import verify_alignment
from omr_synth import photograph


def _register(img: np.ndarray, tpl: Template, cfg: EngineConfig) -> tuple[np.ndarray, np.ndarray, str]:
    """Full coarse + fine registration; returns (template -> image homography, page_norm, method)."""
    feats = template_features(tpl, cfg)
    page = estimate_page_transform(img, feats, cfg)
    page_img = warp_to_template(page.source, page.homography, tpl.size)
    norm = normalize_illumination(page_img, cfg)
    reg = register(print_mask(to_hsv(norm), feats.profile, cfg), norm, feats, cfg)
    to_image = np.diag([1 / page.source_scale, 1 / page.source_scale, 1.0]) @ page.homography @ reg.homography
    return to_image, norm, reg.method


def _bubble_error(h_est: np.ndarray, h_true: np.ndarray, tpl: Template) -> np.ndarray:
    scale = float(np.sqrt(abs(np.linalg.det(h_true[:2, :2]))))
    return np.linalg.norm(apply(h_est, tpl.bubble_xy) - apply(h_true, tpl.bubble_xy), axis=1) / scale


@pytest.mark.parametrize(
    ("angle", "scale", "persp"),
    [(3.0, 0.9, 0.03), (-3.0, 1.05, 0.02), (1.0, 0.75, 0.05)],
)
def test_recovers_rotation_perspective_scale(
    template: Template, cfg: EngineConfig, filled_sheet: np.ndarray, angle: float, scale: float, persp: float
) -> None:
    img, h_true = photograph(filled_sheet, angle_deg=angle, scale=scale, perspective=persp, canvas=(2100, 2600))
    h_est, _, method = _register(img, template, cfg)
    err = _bubble_error(h_est, h_true, template)
    assert method in {"ecc", "anchors", "orb"}
    assert err.mean() < 1.0
    assert err.max() < 2.0


def test_recovers_180_degree_rotation(template: Template, cfg: EngineConfig, filled_sheet: np.ndarray) -> None:
    img = cv2.rotate(filled_sheet, cv2.ROTATE_180)
    h, w = filled_sheet.shape[:2]
    h_true = np.array([[-1, 0, w - 1], [0, -1, h - 1], [0, 0, 1]], np.float64)
    h_est, _, _ = _register(img, template, cfg)
    assert _bubble_error(h_est, h_true, template).max() < 2.0


def test_verification_catches_row_and_column_shift(template: Template, cfg: EngineConfig, filled_sheet: np.ndarray) -> None:
    img, _ = photograph(filled_sheet, angle_deg=2.0, scale=0.9, perspective=0.02)
    feats = template_features(template, cfg)
    page = estimate_page_transform(img, feats, cfg)
    norm = normalize_illumination(warp_to_template(page.source, page.homography, template.size), cfg)
    reg = register(print_mask(to_hsv(norm), feats.profile, cfg), norm, feats, cfg)
    assert verify_alignment(norm, reg.homography, template, feats, cfg).ok(cfg)
    for dx, dy in [(0, 54), (0, -54), (37, 0), (-37, 0)]:
        shifted = reg.homography @ np.array([[1, 0, dx], [0, 1, dy], [0, 0, 1.0]])
        check = verify_alignment(norm, shifted, template, feats, cfg)
        assert not check.ok(cfg), (dx, dy, check)


def test_order_corners() -> None:
    pts = np.array([[10, 90], [90, 85], [5, 5], [95, 10]], np.float64)
    assert order_corners(pts).tolist() == [[5, 5], [95, 10], [90, 85], [10, 90]]
