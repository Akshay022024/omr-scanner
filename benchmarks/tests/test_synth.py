"""Unit tests for the synthetic generator, degrader and metric maths (no engine needed)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from benchmarks import metrics as M
from benchmarks.synth import handwriting as hw
from benchmarks.synth.degrade import TIERS, degrade
from benchmarks.synth.generator import (
    StyleMix,
    generate_sheet,
    gt_field_values,
    load_synth_template,
)

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "templates" / "sheet80_v2"


@pytest.fixture(scope="module")
def tpl():
    if not (TEMPLATE_DIR / "template_200dpi.png").is_file():
        pytest.skip("sheet80_v2 reference image not present (third-party artwork, not in git)")
    return load_synth_template(TEMPLATE_DIR)


@pytest.fixture(scope="module")
def sheet(tpl):
    return generate_sheet(np.random.default_rng([42, 0]), tpl, StyleMix(distractor_rate=0.1, multiple_rate=0.05))


# --------------------------------------------------------------------------- #
# template + generator
# --------------------------------------------------------------------------- #
def test_template_loads(tpl):
    assert tpl.image.shape == (2200, 1700, 3)
    assert len(tpl.roll_fields) == 10
    assert tpl.set_field.options == ["A", "B", "C"]
    assert len(tpl.question_fields) == 80
    assert all(f.options == ["A", "B", "C", "D"] for f in tpl.question_fields)


def test_generator_is_deterministic(tpl):
    a_img, a_gt = generate_sheet(np.random.default_rng(7), tpl)
    b_img, b_gt = generate_sheet(np.random.default_rng(7), tpl)
    c_img, c_gt = generate_sheet(np.random.default_rng(8), tpl)
    assert np.array_equal(a_img, b_img)
    assert a_gt == b_gt
    assert not np.array_equal(a_img, c_img)


def test_ground_truth_consistency(tpl, sheet):
    img, gt = sheet
    assert img.shape == (2200, 1700, 3) and img.dtype == np.uint8
    assert gt["schema"] == "omr-gt/1"
    assert len(gt["roll_no"]) == 10 and gt["roll_no"].isdigit()
    assert gt["paper_set"] in ("A", "B", "C")
    assert sorted(gt["answers"], key=int) == [str(i) for i in range(1, 81)]
    for q, ans in gt["answers"].items():
        fl = gt["flags"][q]
        assert list(ans) == sorted(ans, key="ABCD".index), "letters must be in option order"
        assert len(set(ans)) == len(ans)
        assert fl["blank"] == (ans == "")
        assert fl["multiple"] == (len(ans) > 1)
        if fl["distractor"]:
            assert fl["distractor"] in hw.DISTRACTOR_STYLES
            assert fl["distractor_option"] not in ans
        if ans:
            assert fl["style"] in hw.FILL_STYLES
        assert sorted(fl["option_styles"]) == sorted(ans)
        assert all(st in hw.FILL_STYLES for st in fl["option_styles"].values())
    fv = gt_field_values(gt, tpl)
    assert len(fv) == 91 and fv["paper_set"] == gt["paper_set"] and fv["roll_1"] == gt["roll_no"][0]


def _disc_mean(img, b, frac=0.6):
    y0, y1 = int(b.y - b.r), int(b.y + b.r) + 1
    x0, x1 = int(b.x - b.r), int(b.x + b.r) + 1
    patch = img[y0:y1, x0:x1].mean(axis=2)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    m = (xx - b.x) ** 2 + (yy - b.y) ** 2 <= (frac * b.r) ** 2
    return float(patch[m].mean())


def test_filled_bubbles_are_dark_in_pixels(tpl, sheet):
    """GT says filled  <=>  the bubble interior actually got darker than the clean template."""
    img, gt = sheet
    fv = gt_field_values(gt, tpl)
    for f in tpl.fields:
        for b in f.bubbles:
            delta = _disc_mean(tpl.image, b) - _disc_mean(img, b)
            if b.value in fv[f.id]:
                assert delta > 60, (f.id, b.value, delta)
            elif not (f.group == "answers" and gt["flags"][str(f.question)]["distractor_option"] == b.value):
                assert abs(delta) < 3, (f.id, b.value, delta)


def test_rates_are_respected(tpl):
    mix = StyleMix(blank_rate=0.3, multiple_rate=0.2, distractor_rate=0.0, handwriting_prob=0, signature_prob=0)
    answers = []
    for i in range(3):
        _, gt = generate_sheet(np.random.default_rng([1, i]), tpl, mix)
        answers += list(gt["answers"].values())
    blank = np.mean([a == "" for a in answers])
    multi = np.mean([len(a) > 1 for a in answers])
    assert 0.18 < blank < 0.42
    assert 0.1 < multi < 0.3


def test_clean_only_mix_has_no_extras(tpl):
    _, gt = generate_sheet(np.random.default_rng(3), tpl, StyleMix.clean_only())
    assert all(len(a) == 1 for a in gt["answers"].values())
    assert not any(fl["distractor"] for fl in gt["flags"].values())
    assert set(gt["styles_used"]) == {"solid"}


# --------------------------------------------------------------------------- #
# handwriting
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("style", hw.FILL_STYLES)
def test_fill_styles_cover_the_bubble(style):
    for s in range(8):
        rng = np.random.default_rng(s)
        alpha, _ = hw.render_mark(rng, style, 14.5, hw.random_pen(rng))
        assert alpha.shape[0] % 2 == 1 and alpha.shape[0] == alpha.shape[1]
        assert 0.0 <= alpha.min() and alpha.max() <= 1.0
        assert hw.disc_coverage(alpha, 14.5) > 0.5, style


@pytest.mark.parametrize("style", hw.DISTRACTOR_STYLES)
def test_distractors_are_not_fills(style):
    for s in range(8):
        rng = np.random.default_rng(100 + s)
        alpha, _ = hw.render_mark(rng, style, 14.5, hw.random_pen(rng))
        assert hw.disc_coverage(alpha, 14.5) < 0.45, style
        if style == "smudge":
            assert alpha.max() < 0.45  # faint


def test_unknown_style_rejected():
    with pytest.raises(ValueError):
        hw.render_mark(np.random.default_rng(0), "blot", 14.5, hw.random_pen(np.random.default_rng(0)))


# --------------------------------------------------------------------------- #
# degradation
# --------------------------------------------------------------------------- #
def test_clean_tier_is_identity(sheet):
    img, _ = sheet
    out, meta = degrade(img, "clean", np.random.default_rng(0))
    assert np.array_equal(out, img) and out is not img
    assert meta["tier"] == "clean"


@pytest.mark.parametrize("tier", ["scan", "photo", "hard"])
def test_degrade_deterministic_and_resized(sheet, tier):
    img, _ = sheet
    a, ma = degrade(img, tier, np.random.default_rng([5, 1]))
    b, mb = degrade(img, tier, np.random.default_rng([5, 1]))
    assert np.array_equal(a, b) and ma == mb
    assert a.dtype == np.uint8 and a.ndim == 3
    assert a.shape[:2] != (2200, 1700)
    json.dumps(ma)  # meta must be JSON-serialisable
    if tier != "scan":
        quad = np.array(ma["page_quad"])
        fw, fh = ma["frame"]
        assert (quad[:, 0] >= 0).all() and (quad[:, 0] <= fw).all()
        assert (quad[:, 1] >= 0).all() and (quad[:, 1] <= fh).all()


def test_degrade_sizes_vary(sheet):
    img, _ = sheet
    sizes = {degrade(img, "scan", np.random.default_rng(s))[0].shape for s in range(4)}
    assert len(sizes) > 1


def test_unknown_tier(sheet):
    with pytest.raises(ValueError):
        degrade(sheet[0], "fax", np.random.default_rng(0))
    assert TIERS == ("clean", "scan", "photo", "hard")


# --------------------------------------------------------------------------- #
# metrics on toy inputs
# --------------------------------------------------------------------------- #
TOY = M.Layout(
    roll_ids=["roll_1", "roll_2"], roll_options=list("1234567890"), set_id="paper_set", set_options=list("ABC"),
    questions=[(str(i), f"q{i}", list("ABCD")) for i in range(1, 5)],
)
TOY_GT = {
    "roll_no": "12", "paper_set": "B",
    "answers": {"1": "A", "2": "", "3": "BC", "4": "D"},
    "flags": {
        "1": {"blank": False, "multiple": False, "distractor": "tick", "distractor_option": "B", "style": "solid"},
        "2": {"blank": True, "multiple": False, "distractor": None, "distractor_option": None, "style": None},
        "3": {"blank": False, "multiple": True, "distractor": None, "distractor_option": None, "style": "solid"},
        "4": {"blank": False, "multiple": False, "distractor": "smudge", "distractor_option": "A", "style": "partial"},
    },
}


def _pred(answers, roll="12", pset="B", states=None, status="ok"):
    states = states or {}
    fields = [{"id": "roll_1", "state": "single", "value": roll[0] if roll[0].isdigit() else ""},
              {"id": "roll_2", "state": "single", "value": roll[1] if roll[1].isdigit() else ""},
              {"id": "paper_set", "state": "single", "value": pset}]
    for q, v in answers.items():
        st = states.get(q) or ("blank" if v == "" else "multiple" if len(v) > 1 else "single")
        fields.append({"id": f"q{q}", "state": st, "value": v})
    return M.normalize_prediction({"status": status, "roll_no": roll, "paper_set": pset, "answers": answers,
                                   "fields": fields, "review_flags": [], "registration": {"quality": 0.9}})


def test_perfect_prediction():
    s = M.score_sheet(TOY_GT, _pred(dict(TOY_GT["answers"])), TOY, latency_s=0.1)
    assert s.q_correct == 4 and s.sheet_exact and s.roll_match and s.set_match
    assert s.bubbles_total == 2 * 10 + 3 + 4 * 4 and s.bubbles_correct == s.bubbles_total
    assert (s.blank_tp, s.blank_fp, s.blank_fn) == (1, 0, 0)
    assert (s.multi_tp, s.multi_fp, s.multi_fn) == (1, 0, 0)
    assert sorted(s.distractors) == [("smudge", False, False), ("tick", False, False)]
    agg = M.aggregate([s])
    assert agg["question_accuracy"] == 1.0 and agg["bubble_accuracy"] == 1.0
    assert agg["distractor_false_fill_rate"] == 0.0
    assert agg["latency_ms"]["p50"] == pytest.approx(100.0)


def test_error_accounting_strict_vs_lenient():
    # q1 tick read as filled -> "AB" (false multiple, flagged ambiguous); q2 blank read "C" (silent);
    # q3 multiple read "B" (missed multiple, silent); q4 correct. roll digit 2 wrong.
    pred = _pred({"1": "AB", "2": "C", "3": "B", "4": "D"}, roll="13", states={"1": "ambiguous"})
    s = M.score_sheet(TOY_GT, pred, TOY, tier="t", sample="s0")
    assert s.q_correct == 1 and s.q_review_wrong == 1 and s.q_silent_wrong == 2 and s.q_ambiguous == 1
    assert not s.roll_match and s.set_match and not s.sheet_exact
    # bubbles: roll_2 wrong at "2" and "3" (2), q1 B (1), q2 C (1), q3 C (1)
    assert s.bubbles_total - s.bubbles_correct == 5
    assert (s.blank_tp, s.blank_fp, s.blank_fn) == (0, 0, 1)
    assert (s.multi_tp, s.multi_fp, s.multi_fn) == (0, 1, 1)
    assert ("tick", True, True) in s.distractors
    kinds = {e["field"]: e["kind"] for e in s.errors}
    assert kinds == {"roll_2": "roll:wrong_option", "q1": "false_multiple:tick", "q2": "false_fill", "q3": "missed_multiple"}
    agg = M.aggregate([s])
    assert agg["question_accuracy"] == pytest.approx(0.25)
    assert agg["question_accuracy_lenient"] == pytest.approx(0.5)
    assert agg["silent_error_rate"] == pytest.approx(0.5)
    assert agg["blank_recall"] == 0.0 and agg["blank_precision"] is None
    assert agg["multiple_precision"] == 0.0 and agg["multiple_recall"] == 0.0
    assert agg["distractor_by_type"]["tick"]["false_fill_rate"] == 1.0
    assert agg["distractor_by_type"]["smudge"]["false_fill_rate"] == 0.0


def test_failed_sheet_counts_as_review_not_silent():
    s = M.score_sheet(TOY_GT, M.failed_prediction("no page"), TOY)
    assert s.failed and s.q_correct == 0 and s.q_review_wrong == 4 and s.q_silent_wrong == 0
    assert s.bubbles_correct == 0
    agg = M.aggregate([s, M.score_sheet(TOY_GT, _pred(dict(TOY_GT["answers"])), TOY)])
    assert agg["registration_failure_rate"] == 0.5
    assert agg["question_accuracy"] == 0.5 and agg["question_accuracy_lenient"] == 1.0
    assert agg["sheet_exact"] == 0.5


def test_real_ground_truth_without_flags():
    gt = {"roll_no": "12", "paper_set": "B", "answers": {"1": "A", "2": "", "3": "BC", "4": "D"}}
    s = M.score_sheet(gt, _pred(dict(gt["answers"])), TOY)
    assert s.sheet_exact and s.distractors == []


def test_aggregate_latency_and_error_samples():
    scores = [M.score_sheet(TOY_GT, _pred({"1": "A", "2": "A", "3": "BC", "4": "D"}), TOY, tier="x", sample=f"s{i}",
                            latency_s=0.1 * (i + 1)) for i in range(10)]
    agg = M.aggregate(scores)
    assert agg["latency_ms"]["p50"] == pytest.approx(550.0)
    assert agg["latency_ms"]["mean"] == pytest.approx(550.0)
    assert agg["throughput_sheets_per_s"] == pytest.approx(10 / 5.5)
    assert agg["error_breakdown"] == {"false_fill": 10}
    errs = M.pick_error_samples(scores, 4)
    assert len(errs) == 4 and errs[0]["tier"] == "x" and errs[0]["field"] == "q2"
    assert M.aggregate([]) == {"n_sheets": 0}


def test_runner_generate_only(tmp_path, tpl):
    from benchmarks import run_benchmark

    rc = run_benchmark.main(["--n", "1", "--tiers", "clean,scan", "--generate-only", "--save-samples", "1",
                             "--data-dir", str(tmp_path), "--out", str(tmp_path / "rep"), "-q"])
    assert rc == 0
    rec = json.loads((tmp_path / "scan" / "scan_0000.json").read_text(encoding="utf-8"))
    assert rec["ground_truth"]["schema"] == "omr-gt/1" and rec["degradation"]["tier"] == "scan"
    assert (tmp_path / "clean" / "clean_0000.jpg").stat().st_size > 10_000
