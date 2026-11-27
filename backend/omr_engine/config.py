"""All engine thresholds and tunables live in one frozen dataclass so they can be swept."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EngineConfig:
    # --- io ---------------------------------------------------------------
    max_side_px: int = 4000
    pdf_dpi: int = 200
    max_pdf_pages: int = 20

    # --- page normalisation / orientation ----------------------------------
    page_detect_max_side: int = 640
    min_page_area_frac: float = 0.20
    max_page_area_frac: float = 0.985
    page_threshold_factors: tuple[float, ...] = (1.0, 0.8, 0.6)
    orientation_scale: float = 0.125
    # Downscale the source before warping when the page is this much larger than the template.
    presize_ratio: float = 1.3

    # --- illumination normalisation ----------------------------------------
    background_scale: float = 0.125
    background_kernel: int = 7

    # --- print-colour mask (registration). Hue range, saturation floor and value floor come from
    # the template's print-colour profile (printcolor.py); the saturation threshold adapts to the
    # sheet's noise floor: median + k*MAD of S, clamped to [profile floor, print_sat_max].
    print_sat_max: int = 45
    print_noise_k: float = 6.0

    # --- ink map (red-channel dropout on the background-normalised image) ---
    # Magenta/orange print reflects red, blue/black ballpoint and pencil absorb it, so ink strength is the
    # relative red-channel darkness mapped linearly from [ink_dark_lo, ink_dark_hi] to [0, 1].
    ink_dark_lo: float = 0.20
    ink_dark_hi: float = 0.50
    # Closing joins scribble strokes into an area; opening then removes thin ticks/crosses.
    ink_close_px: int = 3
    ink_open_px: int = 7

    # --- registration -------------------------------------------------------
    ecc_scales: tuple[float, ...] = (0.0625, 0.125, 0.25)
    ecc_blur_sigmas: tuple[float, ...] = (2.0, 1.5, 1.2)
    ecc_iterations: tuple[int, ...] = (100, 60, 40)
    ecc_eps: float = 1e-5
    max_corner_shift_frac: float = 0.10
    orb_trigger_quality: float = 0.55
    orb_min_gain: float = 0.03
    orb_features: int = 4000
    orb_scale: float = 0.5
    orb_ratio: float = 0.8
    orb_match_radius_px: float = 140.0
    orb_min_inliers: int = 30
    ransac_reproj_px: float = 3.0
    anchor_search_px: int = 8
    anchor_segments_per_edge: int = 4
    anchor_min_constraints: int = 6
    anchor_outlier_px: float = 1.5
    random_seed: int = 0

    # --- registration quality and geometric sanity check --------------------
    quality_scale: float = 0.5
    quality_dilate_px: int = 1
    # Only used when the geometry check fails: below this IoU the sheet is `failed`.
    quality_fail: float = 0.10
    # Low-res correlation of the page with the template layout; below this the input is not this sheet.
    min_layout_score: float = 0.20
    # Anchor-box edges re-detected after the final warp: required coverage per direction
    # (horizontal and vertical edges separately) and maximum RMS residual in template px.
    geometry_min_coverage: float = 0.35
    geometry_max_residual_px: float = 2.5
    # Print lock: correlation of the dark template print (bubbles masked) at zero offset must be
    # high and clearly better than at one bubble pitch up/down/left/right.
    lock_scale: float = 0.25
    lock_min_score: float = 0.50
    lock_min_margin: float = 0.15
    # With failed verification, a print correlation below this means the content is not this sheet.
    lock_fail_score: float = 0.25

    # --- bubble scoring -----------------------------------------------------
    disc_radius_frac: float = 0.75
    shift_search_px: int = 4

    # --- decision -----------------------------------------------------------
    min_threshold: float = 0.30
    max_threshold: float = 0.50
    min_gap: float = 0.10
    ambiguity_margin: float = 0.08
    confidence_scale: float = 0.30
    flag_blank_answers: bool = False
