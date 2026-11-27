"""Benchmark metrics: compare ground truth with an engine prediction, aggregate per tier.

Engine-independent: predictions are normalised into plain dicts first, so the
maths can be unit-tested on toy inputs.

Definitions (all per tier, plus overall):
  bubble_accuracy        fraction of bubbles whose filled/not-filled state matches GT
  question_accuracy      predicted answer string == GT string (blank == "" ; multiples must match exactly)
  question_accuracy_lenient
                         (correct + wrong-but-flagged-ambiguous) / total. Failed sheets count as review.
  silent_error_rate      wrong AND not flagged ambiguous (the dangerous kind) / total
  roll_exact / paper_set_accuracy / sheet_exact (80 answers + roll + set all correct)
  blank P/R              positive = GT question blank; predicted positive = predicted answer ""
  multiple P/R           positive = GT >1 letters; predicted positive = predicted >1 letters
  distractor_false_fill_rate
                         tick / cross / smudge bubbles (GT not filled) that the engine read as filled
  review_rate            fraction of sheets with status needs_review; avg_flags_per_sheet
  registration_failure_rate  fraction of sheets with status failed (or engine exception)
  latency p50/p95/mean/max (wall clock around scan_image), throughput = sheets / total scan seconds
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np


# --------------------------------------------------------------------------- #
# layout (which fields/bubbles exist) — built from the template, or by hand in tests
# --------------------------------------------------------------------------- #
@dataclass
class Layout:
    roll_ids: list[str]  # ordered roll_1..roll_N
    roll_options: list[str]
    set_id: str
    set_options: list[str]
    questions: list[tuple[str, str, list[str]]]  # (question number str, field id, options)


def layout_from_template(tpl: Any) -> Layout:
    """Build a Layout from ``generator.SynthTemplate``."""
    rf = tpl.roll_fields
    sf = tpl.set_field
    return Layout(
        roll_ids=[f.id for f in rf],
        roll_options=rf[0].options if rf else [],
        set_id=sf.id,
        set_options=sf.options,
        questions=[(str(f.question), f.id, f.options) for f in tpl.question_fields],
    )


# --------------------------------------------------------------------------- #
# prediction normalisation
# --------------------------------------------------------------------------- #
def normalize_prediction(res: Any) -> dict[str, Any]:
    """ScanResult (pydantic) or dict -> plain dict with the keys the scorer uses."""
    if res is None:
        d: dict[str, Any] = {"status": "failed", "error": "no result"}
    elif hasattr(res, "model_dump"):
        d = res.model_dump()
    else:
        d = dict(res)
    fields: dict[str, dict[str, Any]] = {}
    for f in d.get("fields") or []:
        if not isinstance(f, dict):
            f = f.model_dump() if hasattr(f, "model_dump") else vars(f)
        fields[str(f.get("id"))] = {
            "state": f.get("state"),
            "value": f.get("value") or "",
            "scores": f.get("scores"),
            "confidence": f.get("confidence"),
        }
    reg = d.get("registration") or {}
    if not isinstance(reg, dict):
        reg = reg.model_dump() if hasattr(reg, "model_dump") else vars(reg)
    return {
        "status": d.get("status") or "failed",
        "error": d.get("error"),
        "roll_no": d.get("roll_no") or "",
        "paper_set": d.get("paper_set") or "",
        "answers": {str(k): (v or "") for k, v in (d.get("answers") or {}).items()},
        "fields": fields,
        "review_flags": list(d.get("review_flags") or []),
        "registration_quality": reg.get("quality"),
        "registration_method": reg.get("method"),
        "threshold": d.get("threshold"),
        "timings_ms": d.get("timings_ms") or {},
    }


def failed_prediction(error: str) -> dict[str, Any]:
    return normalize_prediction({"status": "failed", "error": error})


# --------------------------------------------------------------------------- #
# per-sheet scoring
# --------------------------------------------------------------------------- #
def _gt_flags(gt: dict[str, Any], q: str) -> dict[str, Any]:
    fl = (gt.get("flags") or {}).get(q)
    ans = (gt.get("answers") or {}).get(q, "") or ""
    if fl is None:
        fl = {"blank": ans == "", "multiple": len(ans) > 1, "distractor": None, "distractor_option": None, "style": None}
    return fl


def _classify(expected: str, got: str) -> str:
    if expected == got:
        return "ok"
    if len(expected) > 1:
        return "multiple_mismatch" if len(got) > 1 else "missed_multiple"
    if len(got) > 1:
        return "false_multiple"
    if expected == "":
        return "false_fill"
    if got == "":
        return "missed_fill"
    return "wrong_option"


@dataclass
class SheetScore:
    tier: str
    sample: str
    status: str
    failed: bool
    bubbles_total: int = 0
    bubbles_correct: int = 0
    questions_total: int = 0
    q_correct: int = 0
    q_review_wrong: int = 0  # wrong but flagged ambiguous (or sheet failed)
    q_silent_wrong: int = 0
    q_ambiguous: int = 0
    roll_match: bool = False
    set_match: bool = False
    sheet_exact: bool = False
    blank_tp: int = 0
    blank_fp: int = 0
    blank_fn: int = 0
    multi_tp: int = 0
    multi_fp: int = 0
    multi_fn: int = 0
    distractors: list[tuple[str, bool, bool]] = field(default_factory=list)  # (type, read_as_filled, flagged)
    fill_by_style: list[tuple[str, bool]] = field(default_factory=list)  # (style, detected)
    n_flags: int = 0
    reg_quality: float | None = None
    latency_s: float | None = None
    timings_ms: dict[str, float] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)


def score_sheet(gt: dict[str, Any], pred: dict[str, Any], layout: Layout, tier: str = "", sample: str = "",
                latency_s: float | None = None) -> SheetScore:
    """Score one normalised prediction against ground truth."""
    status = pred.get("status", "failed")
    failed = status == "failed"
    s = SheetScore(tier=tier, sample=sample, status=status, failed=failed,
                   n_flags=len(pred.get("review_flags") or []), reg_quality=pred.get("registration_quality"),
                   latency_s=latency_s, timings_ms=dict(pred.get("timings_ms") or {}))
    fields = pred.get("fields") or {}
    flags_set = set(pred.get("review_flags") or [])

    def pred_value(fid: str, fallback: str) -> str:
        if fid in fields:
            return fields[fid].get("value") or ""
        return fallback

    def is_ambiguous(fid: str) -> bool:
        return (fields.get(fid, {}).get("state") == "ambiguous") or (f"{fid}:ambiguous" in flags_set)

    def bubbles(options: list[str], exp: str, got: str) -> None:
        for o in options:
            s.bubbles_total += 1
            if not failed and ((o in exp) == (o in got)):
                s.bubbles_correct += 1

    # ---- roll ---------------------------------------------------------------
    gt_roll = gt.get("roll_no", "") or ""
    pr_roll = pred.get("roll_no", "") or ""
    roll_styles = gt.get("roll_styles") or {}
    for i, fid in enumerate(layout.roll_ids):
        exp = gt_roll[i] if i < len(gt_roll) and gt_roll[i] in layout.roll_options else ""
        fb = pr_roll[i] if i < len(pr_roll) and pr_roll[i] in layout.roll_options else ""
        got = "" if failed else pred_value(fid, fb)
        bubbles(layout.roll_options, exp, got)
        if exp and roll_styles.get(fid) and not failed:
            s.fill_by_style.append((roll_styles[fid], exp in got))
        if not failed and exp != got:
            s.errors.append({"field": fid, "expected": exp, "got": got, "kind": "roll:" + _classify(exp, got),
                             "state": fields.get(fid, {}).get("state"), "style": roll_styles.get(fid),
                             "scores": fields.get(fid, {}).get("scores")})
    s.roll_match = (not failed) and pr_roll == gt_roll

    # ---- paper set -------------------------------------------------------------
    gt_set = gt.get("paper_set", "") or ""
    got_set = "" if failed else pred_value(layout.set_id, pred.get("paper_set", "") or "")
    bubbles(layout.set_options, gt_set, got_set)
    s.set_match = (not failed) and ((pred.get("paper_set") or "") == gt_set)
    if not failed and gt_set != got_set:
        s.errors.append({"field": layout.set_id, "expected": gt_set, "got": got_set, "kind": "set:" + _classify(gt_set, got_set),
                         "state": fields.get(layout.set_id, {}).get("state"),
                         "scores": fields.get(layout.set_id, {}).get("scores")})

    # ---- answers -----------------------------------------------------------------
    gt_ans = gt.get("answers") or {}
    all_q_ok = True
    for q, fid, options in layout.questions:
        exp = gt_ans.get(q, "") or ""
        fl = _gt_flags(gt, q)
        s.questions_total += 1
        if failed:
            all_q_ok = False
            s.q_review_wrong += 1
            if exp == "":
                s.blank_fn += 1
            if len(exp) > 1:
                s.multi_fn += 1
            bubbles(options, exp, "")
            continue
        got = pred_value(fid, (pred.get("answers") or {}).get(q, "") or "")
        amb = is_ambiguous(fid)
        opt_styles = fl.get("option_styles") or {}
        bubbles(options, exp, got)
        if amb:
            s.q_ambiguous += 1
        if got == exp:
            s.q_correct += 1
        else:
            all_q_ok = False
            if amb:
                s.q_review_wrong += 1
            else:
                s.q_silent_wrong += 1
            kind = _classify(exp, got)
            d_opt = fl.get("distractor_option")
            if fl.get("distractor") and d_opt and d_opt in got and d_opt not in exp:
                kind = f"{kind}:{fl['distractor']}"
            style = fl.get("style")
            missed = [o for o in exp if o not in got]
            if missed and opt_styles.get(missed[0]):
                style = opt_styles[missed[0]]  # style of the bubble that was missed
            s.errors.append({"field": fid, "expected": exp, "got": got, "kind": kind, "state": fields.get(fid, {}).get("state"),
                             "ambiguous": amb, "style": style, "distractor": fl.get("distractor"),
                             "distractor_option": d_opt, "scores": fields.get(fid, {}).get("scores")})
        # blank / multiple detection
        gb, pb = exp == "", got == ""
        s.blank_tp += gb and pb
        s.blank_fp += (not gb) and pb
        s.blank_fn += gb and (not pb)
        gm, pm = len(exp) > 1, len(got) > 1
        s.multi_tp += gm and pm
        s.multi_fp += (not gm) and pm
        s.multi_fn += gm and (not pm)
        # distractors
        if fl.get("distractor") and fl.get("distractor_option"):
            s.distractors.append((fl["distractor"], fl["distractor_option"] in got, amb))
        # fill recall per style (per filled bubble)
        for o in exp:
            st = opt_styles.get(o) or (fl.get("style") if len(exp) == 1 else None)
            if st:
                s.fill_by_style.append((st, o in got))
    s.sheet_exact = (not failed) and all_q_ok and s.roll_match and s.set_match
    if failed:
        s.errors.append({"field": "*", "expected": "", "got": "", "kind": "registration_failed",
                         "state": None, "error": pred.get("error")})
    return s


# --------------------------------------------------------------------------- #
# aggregation
# --------------------------------------------------------------------------- #
def _ratio(a: float, b: float) -> float | None:
    return None if b == 0 else float(a) / float(b)


def _pct(xs: list[float], p: float) -> float | None:
    return None if not xs else float(np.percentile(np.asarray(xs, float), p))


def aggregate(scores: Iterable[SheetScore]) -> dict[str, Any]:
    sc = list(scores)
    n = len(sc)
    if n == 0:
        return {"n_sheets": 0}
    tot = lambda attr: sum(getattr(x, attr) for x in sc)  # noqa: E731
    qt = tot("questions_total")
    lat = [x.latency_s for x in sc if x.latency_s is not None]
    dist: dict[str, list[tuple[bool, bool]]] = {}
    for x in sc:
        for t, filled, flagged in x.distractors:
            dist.setdefault(t, []).append((filled, flagged))
    all_d = [v for vs in dist.values() for v in vs]
    style_acc: dict[str, list[bool]] = {}
    for x in sc:
        for st, ok in x.fill_by_style:
            style_acc.setdefault(st, []).append(ok)
    kinds = Counter()
    kinds_style = Counter()
    for x in sc:
        for e in x.errors:
            kinds[e["kind"]] += 1
            if e.get("style"):
                kinds_style[f"{e['kind']}|{e['style']}"] += 1
    stage: dict[str, list[float]] = {}
    for x in sc:
        for k, v in (x.timings_ms or {}).items():
            if isinstance(v, (int, float)):
                stage.setdefault(k, []).append(float(v))
    reg_q = [x.reg_quality for x in sc if isinstance(x.reg_quality, (int, float))]
    bt, bp, bf = tot("blank_tp"), tot("blank_fp"), tot("blank_fn")
    mt, mp, mf = tot("multi_tp"), tot("multi_fp"), tot("multi_fn")
    return {
        "n_sheets": n,
        "bubble_accuracy": _ratio(tot("bubbles_correct"), tot("bubbles_total")),
        "question_accuracy": _ratio(tot("q_correct"), qt),
        "question_accuracy_lenient": _ratio(tot("q_correct") + tot("q_review_wrong"), qt),
        "silent_error_rate": _ratio(tot("q_silent_wrong"), qt),
        "question_review_rate": _ratio(tot("q_ambiguous"), qt),
        "questions_total": qt,
        "questions_wrong": qt - tot("q_correct"),
        "roll_exact": _ratio(sum(x.roll_match for x in sc), n),
        "paper_set_accuracy": _ratio(sum(x.set_match for x in sc), n),
        "sheet_exact": _ratio(sum(x.sheet_exact for x in sc), n),
        "blank_precision": _ratio(bt, bt + bp),
        "blank_recall": _ratio(bt, bt + bf),
        "blank_support": bt + bf,
        "multiple_precision": _ratio(mt, mt + mp),
        "multiple_recall": _ratio(mt, mt + mf),
        "multiple_support": mt + mf,
        "distractor_count": len(all_d),
        "distractor_false_fill_rate": _ratio(sum(f for f, _ in all_d), len(all_d)),
        "distractor_flagged_rate": _ratio(sum(g for _, g in all_d), len(all_d)),
        "distractor_by_type": {
            t: {"count": len(v), "false_fill_rate": _ratio(sum(f for f, _ in v), len(v)),
                "flagged_rate": _ratio(sum(g for _, g in v), len(v))}
            for t, v in sorted(dist.items())
        },
        "fill_recall_by_style": {st: {"count": len(v), "recall": _ratio(sum(v), len(v))} for st, v in sorted(style_acc.items())},
        "review_rate": _ratio(sum(x.status == "needs_review" for x in sc), n),
        "avg_flags_per_sheet": float(np.mean([x.n_flags for x in sc])),
        "registration_failure_rate": _ratio(sum(x.failed for x in sc), n),
        "registration_quality_mean": float(np.mean(reg_q)) if reg_q else None,
        "registration_quality_min": float(np.min(reg_q)) if reg_q else None,
        "latency_ms": {
            "p50": None if not lat else _pct(lat, 50) * 1000,
            "p95": None if not lat else _pct(lat, 95) * 1000,
            "mean": None if not lat else float(np.mean(lat)) * 1000,
            "max": None if not lat else float(np.max(lat)) * 1000,
        },
        "throughput_sheets_per_s": _ratio(len(lat), sum(lat)) if lat else None,
        "engine_stage_ms_mean": {k: float(np.mean(v)) for k, v in sorted(stage.items())},
        "error_breakdown": dict(kinds.most_common()),
        "error_breakdown_by_style": dict(kinds_style.most_common(15)),
    }


def pick_error_samples(scores: Iterable[SheetScore], limit: int = 20) -> list[dict[str, Any]]:
    """Up to ``limit`` misreads, round-robin across (tier, kind) so the sample is diverse."""
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for x in scores:
        for e in x.errors:
            item = {"tier": x.tier, "sample": x.sample, **{k: v for k, v in e.items() if v is not None}}
            if isinstance(item.get("scores"), dict):
                item["scores"] = {k: round(float(v), 3) for k, v in item["scores"].items()}
            buckets.setdefault((x.tier, e["kind"]), []).append(item)
    out: list[dict[str, Any]] = []
    keys = sorted(buckets)
    i = 0
    while len(out) < limit and any(buckets[k] for k in keys):
        k = keys[i % len(keys)]
        if buckets[k]:
            out.append(buckets[k].pop(0))
        i += 1
    return out
