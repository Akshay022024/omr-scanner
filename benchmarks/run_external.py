"""Score the OMR engine on REAL labelled sheets from an external dataset.

Currently supported: ``tamaulipas``, the Tamaulipas MCQ Exam Image Dataset (Universidad Politecnica
de Victoria, Mendeley Data v2, doi:10.17632/djmynjwjpy.2, CC BY 4.0). The images stay in
``benchmarks/data/external/tamaulipas/sheets`` (gitignored) and are never committed.

    .venv\\Scripts\\python.exe benchmarks\\run_external.py --dataset tamaulipas --split dev|test|all

The dev/test split is by SCHOOL and fixed in ``benchmarks/external_splits/tamaulipas.json``.
Template calibration and tuning use dev only. Labels: ``X`` = blank, ``M`` = multiple (correct if
the engine reports state ``multiple``, whatever the letters). Suspected label errors found by
looking at error crops are listed in ``benchmarks/external_splits/tamaulipas_label_notes.json``;
they are still counted as errors but are also reported separately (labels are never edited).

Writes ``benchmarks/reports/external_<dataset>.json`` / ``.md`` and up to ``--max-crops`` error
crops into ``benchmarks/data/external/<dataset>/errors/``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from omr_engine import EngineConfig, ScanResult, Template, align_to_template, load_document, load_template, scan_image  # noqa: E402
from omr_engine import __version__ as ENGINE_VERSION  # noqa: E402

DATASETS = {
    "tamaulipas": {
        "template": ROOT / "templates" / "tamaulipas_90",
        "data": ROOT / "benchmarks" / "data" / "external" / "tamaulipas",
        "split": ROOT / "benchmarks" / "external_splits" / "tamaulipas.json",
        "notes": ROOT / "benchmarks" / "external_splits" / "tamaulipas_label_notes.json",
        "citation": "Tamaulipas MCQ Exam Image Dataset, Universidad Politecnica de Victoria, Mendeley Data v2, "
        "doi:10.17632/djmynjwjpy.2, CC BY 4.0",
    }
}

_ANSWER_RE = re.compile(r"(\d+)\s*:\s*([A-Za-z])")
_ID_RE = re.compile(r"ID\s*:\s*(\S+)")


# --------------------------------------------------------------------------- labels


@dataclass(frozen=True)
class Label:
    sheet_id: str  # e.g. "6161", may contain X (blank) / M (multiple)
    answers: dict[str, str]  # question -> "A".."D", "" (X, blank) or "M" (multiple)


def parse_label(text: str) -> Label:
    lines = text.splitlines()
    m = _ID_RE.search(lines[0] if lines else "")
    if m is None:
        raise ValueError("label has no 'ID:' line")
    answers: dict[str, str] = {}
    for q, v in _ANSWER_RE.findall("\n".join(lines[1:])):
        v = v.upper()
        answers[str(int(q))] = "" if v == "X" else v
    return Label(m.group(1).upper(), answers)


# --------------------------------------------------------------------------- scoring


def _classify(expected: str, got: str, state: str) -> str:
    if expected == "M":
        return "missed_multiple"
    if state == "multiple" or len(got) > 1:
        return "false_multiple"
    if expected == "":
        return "false_fill"
    if got == "":
        return "missed_fill"
    return "wrong_option"


@dataclass
class SheetScore:
    sheet: str
    school: str
    status: str
    questions: int = 0
    correct: int = 0
    review_wrong: int = 0
    silent_wrong: int = 0
    ambiguous: int = 0
    blank_tp: int = 0
    blank_fp: int = 0
    blank_fn: int = 0
    multi_tp: int = 0
    multi_fp: int = 0
    multi_fn: int = 0
    id_exact: bool = False
    sheet_exact: bool = False
    flags: int = 0
    scan_ms: float = 0.0
    load_ms: float = 0.0
    errors: list[dict[str, Any]] = field(default_factory=list)


def score_sheet(name: str, label: Label, res: ScanResult, tpl: Template) -> SheetScore:
    s = SheetScore(sheet=name, school=name.split("_")[0], status=res.status, flags=len(res.review_flags))
    failed = res.status == "failed"
    fields = {f.id: f for f in res.fields}
    # ---- ID ----------------------------------------------------------------
    id_ok = not failed and len(label.sheet_id) == len(tpl.fields_in("roll_no"))
    for f, ch in zip(tpl.fields_in("roll_no"), label.sheet_id, strict=False):
        fr = fields.get(f.id)
        if fr is None:
            id_ok = False
            continue
        if ch == "X":
            ok = fr.state == "blank"
        elif ch == "M":
            ok = fr.state == "multiple"
        else:
            ok = fr.state == "single" and fr.value == ch
        if not ok:
            id_ok = False
            if not failed:
                s.errors.append({"field": f.id, "expected": ch, "got": fr.value, "state": fr.state,
                                 "kind": "id:" + _classify("" if ch == "X" else ch, fr.value, fr.state),
                                 "scores": fr.scores})
    s.id_exact = id_ok
    # ---- answers -------------------------------------------------------------
    all_ok = True
    for f in tpl.fields_in("answers"):
        q = str(f.question)
        if q not in label.answers:
            continue
        exp = label.answers[q]
        s.questions += 1
        fr = fields.get(f.id)
        if failed or fr is None:
            s.review_wrong += 1
            all_ok = False
            s.blank_fn += exp == ""
            s.multi_fn += exp == "M"
            continue
        got, state = fr.value, fr.state
        amb = state == "ambiguous"
        s.ambiguous += amb
        pred_multi = state == "multiple" or len(got) > 1
        ok = pred_multi if exp == "M" else (got == exp)
        if ok:
            s.correct += 1
        else:
            all_ok = False
            if amb:
                s.review_wrong += 1
            else:
                s.silent_wrong += 1
            s.errors.append({"field": f.id, "question": int(q), "expected": exp or "(blank)", "got": got or "(blank)",
                             "state": state, "kind": _classify(exp, got, state), "ambiguous": amb, "scores": fr.scores})
        gb, pb = exp == "", got == ""
        s.blank_tp += gb and pb
        s.blank_fp += (not gb) and pb
        s.blank_fn += gb and not pb
        gm = exp == "M"
        s.multi_tp += gm and pred_multi
        s.multi_fp += (not gm) and pred_multi
        s.multi_fn += gm and not pred_multi
    s.sheet_exact = not failed and all_ok and s.id_exact
    if failed:
        s.errors.append({"field": "*", "kind": "registration_failed", "error": res.error})
    return s


def _ratio(a: float, b: float) -> float | None:
    return None if b == 0 else a / b


def aggregate(scores: list[SheetScore], label_notes: set[tuple[str, str]]) -> dict[str, Any]:
    n_q = sum(s.questions for s in scores)
    correct = sum(s.correct for s in scores)
    review_wrong = sum(s.review_wrong for s in scores)
    silent = sum(s.silent_wrong for s in scores)
    lat = [s.scan_ms for s in scores]
    kinds: dict[str, int] = {}
    suspected = 0
    for s in scores:
        for e in s.errors:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
            suspected += (s.sheet, e["field"]) in label_notes
    return {
        "sheets": len(scores),
        "questions": n_q,
        "question_accuracy_strict": _ratio(correct, n_q),
        "question_accuracy_lenient": _ratio(correct + review_wrong, n_q),
        "silent_error_rate": _ratio(silent, n_q),
        "question_review_rate": _ratio(sum(s.ambiguous for s in scores), n_q),
        "blank_precision": _ratio(sum(s.blank_tp for s in scores), sum(s.blank_tp + s.blank_fp for s in scores)),
        "blank_recall": _ratio(sum(s.blank_tp for s in scores), sum(s.blank_tp + s.blank_fn for s in scores)),
        "multiple_precision": _ratio(sum(s.multi_tp for s in scores), sum(s.multi_tp + s.multi_fp for s in scores)),
        "multiple_recall": _ratio(sum(s.multi_tp for s in scores), sum(s.multi_tp + s.multi_fn for s in scores)),
        "labelled_blank": sum(s.blank_tp + s.blank_fn for s in scores),
        "labelled_multiple": sum(s.multi_tp + s.multi_fn for s in scores),
        "id_exact": _ratio(sum(s.id_exact for s in scores), len(scores)),
        "sheet_exact": _ratio(sum(s.sheet_exact for s in scores), len(scores)),
        "sheets_needs_review": _ratio(sum(s.status == "needs_review" for s in scores), len(scores)),
        "failure_rate": _ratio(sum(s.status == "failed" for s in scores), len(scores)),
        "avg_flags_per_sheet": _ratio(sum(s.flags for s in scores), len(scores)),
        "errors_by_kind": dict(sorted(kinds.items(), key=lambda kv: -kv[1])),
        "suspected_label_errors": suspected,
        "question_accuracy_strict_excl_suspected_labels": _ratio(
            correct + sum(1 for s in scores for e in s.errors if e.get("question") and (s.sheet, e["field"]) in label_notes),
            n_q,
        ),
        "latency_ms_p50": float(np.percentile(lat, 50)) if lat else None,
        "latency_ms_p95": float(np.percentile(lat, 95)) if lat else None,
        "load_ms_mean": float(np.mean([s.load_ms for s in scores])) if scores else None,
    }


# --------------------------------------------------------------------------- error crops


def save_crop(path: Path, aligned: np.ndarray, tpl: Template, sheet: str, err: dict[str, Any]) -> None:
    f = tpl.field(err["field"])
    xs = [b.x for b in f.bubbles]
    ys = [b.y for b in f.bubbles]
    r = max(b.r for b in f.bubbles)
    x0, x1 = int(min(xs) - r - 70), int(max(xs) + r + 20)
    y0, y1 = int(min(ys) - r - 12), int(max(ys) + r + 12)
    crop = aligned[max(0, y0) : y1, max(0, x0) : x1].copy()
    crop = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    scores = " ".join(f"{k}:{v:.2f}" for k, v in (err.get("scores") or {}).items())
    bar = np.full((70, crop.shape[1], 3), 255, np.uint8)
    cv2.putText(bar, f"{sheet} {err['field']}  exp={err['expected']} got={err['got']} ({err['state']})",
                (6, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 200), 1, cv2.LINE_AA)
    cv2.putText(bar, scores, (6, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (60, 60, 60), 1, cv2.LINE_AA)
    cv2.imwrite(str(path), np.vstack([bar, crop]))


# --------------------------------------------------------------------------- report


def _fmt(v: Any, pct: bool = True) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float) and pct:
        return f"{100 * v:.2f}%"
    if isinstance(v, float):
        return f"{v:.0f}"
    return str(v)


def write_markdown(report: dict[str, Any], path: Path) -> None:
    m = report["metrics"]
    rows = [
        ("Sheets", m["sheets"], False), ("Questions", m["questions"], False),
        ("Question accuracy (strict)", m["question_accuracy_strict"], True),
        ("Question accuracy (lenient: ambiguous = review)", m["question_accuracy_lenient"], True),
        ("Strict, excluding suspected label errors", m["question_accuracy_strict_excl_suspected_labels"], True),
        ("Silent error rate", m["silent_error_rate"], True),
        ("Question review rate", m["question_review_rate"], True),
        ("Blank precision", m["blank_precision"], True), ("Blank recall", m["blank_recall"], True),
        ("Multiple precision", m["multiple_precision"], True), ("Multiple recall", m["multiple_recall"], True),
        ("Labelled blanks / multiples", f"{m['labelled_blank']} / {m['labelled_multiple']}", False),
        ("ID exact match", m["id_exact"], True), ("Sheet exact match", m["sheet_exact"], True),
        ("Sheets needs_review", m["sheets_needs_review"], True), ("Failure rate", m["failure_rate"], True),
        ("Latency p50 (ms)", m["latency_ms_p50"], False), ("Latency p95 (ms)", m["latency_ms_p95"], False),
    ]
    lines = [
        f"# External benchmark: {report['dataset']} ({report['split']})", "",
        f"- Generated: {report['generated_at']}", f"- Engine version: {report['engine_version']}",
        f"- Data: {report['citation']}", f"- Schools: {', '.join(report['schools'])}", "",
        "| Metric | Value |", "|---|---:|",
    ]
    lines += [f"| {k} | {_fmt(v, pct)} |" for k, v, pct in rows]
    lines += ["", "## Errors by kind", ""]
    lines += [f"- {k}: {v}" for k, v in m["errors_by_kind"].items()] or ["- none"]
    lines += ["", f"Suspected label errors (counted above as errors): {m['suspected_label_errors']}", "",
              "## Per school", "", "| School | Sheets | Strict | Silent | ID exact |", "|---|---:|---:|---:|---:|"]
    for school, sm in report["per_school"].items():
        lines.append(f"| {school} | {sm['sheets']} | {_fmt(sm['question_accuracy_strict'])} | "
                     f"{_fmt(sm['silent_error_rate'])} | {_fmt(sm['id_exact'])} |")
    lines += ["", "## Errors", "", "| Sheet | Field | Expected | Got | State | Kind | Suspected label error |",
              "|---|---|---|---|---|---|---|"]
    for e in report["errors"][:200]:
        lines.append(f"| {e['sheet']} | {e['field']} | {e.get('expected', '')} | {e.get('got', '')} | "
                     f"{e.get('state', '')} | {e['kind']} | {'yes' if e.get('suspected_label_error') else ''} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dataset", choices=sorted(DATASETS), default="tamaulipas")
    ap.add_argument("--split", choices=["dev", "test", "all"], default="test")
    ap.add_argument("--out", default=str(ROOT / "benchmarks" / "reports"))
    ap.add_argument("--max-crops", type=int, default=30)
    ap.add_argument("--limit", type=int, default=0, help="score only the first N sheets (debugging)")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="override a template engine setting for tuning on DEV (repeatable)")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args(argv)

    ds = DATASETS[args.dataset]
    sheets_dir = ds["data"] / "sheets"
    if not sheets_dir.is_dir():
        print(f"ERROR: dataset not found at {sheets_dir}", file=sys.stderr)
        return 2
    split = json.loads(ds["split"].read_text(encoding="utf-8"))
    schools = sorted(split["dev"] + split["test"]) if args.split == "all" else sorted(split[args.split])
    notes = json.loads(ds["notes"].read_text(encoding="utf-8")) if ds["notes"].is_file() else {"suspected": []}
    label_notes = {(n["sheet"], n["field"]) for n in notes.get("suspected", [])}
    paths = sorted(p for p in sheets_dir.glob("*.jpg") if p.name.split("_")[0] in schools)
    if args.limit:
        paths = paths[: args.limit]

    tpl = load_template(ds["template"])
    if args.set:
        overrides = dict(tpl.spec.engine_overrides)
        for item in args.set:
            key, value = item.split("=", 1)
            overrides[key] = float(value) if "." in value else int(value)
        tpl.spec = tpl.spec.model_copy(update={"engine_overrides": overrides})
    cfg = EngineConfig()
    crops_dir = ds["data"] / "errors"
    crops_dir.mkdir(parents=True, exist_ok=True)
    for old in crops_dir.glob("*.png"):
        old.unlink()

    # warm-up (template features) is excluded from latency
    first = load_document(paths[0].read_bytes(), max_side=cfg.max_side_px)[0]
    scan_image(first, tpl, cfg)

    scores: list[SheetScore] = []
    crops = 0
    for p in paths:
        label = parse_label(p.with_suffix(".txt").read_text(encoding="utf-8", errors="replace"))
        t0 = time.perf_counter()
        img = load_document(p.read_bytes(), max_side=cfg.max_side_px)[0]
        t1 = time.perf_counter()
        res = scan_image(img, tpl, cfg)
        t2 = time.perf_counter()
        s = score_sheet(p.stem, label, res, tpl)
        s.load_ms, s.scan_ms = (t1 - t0) * 1000, (t2 - t1) * 1000
        scores.append(s)
        if not args.quiet:
            print(f"  {p.stem}: {res.status:<12} q={s.correct}/{s.questions} id={'ok' if s.id_exact else 'X'} "
                  f"{s.scan_ms:.0f}ms", flush=True)
        if s.errors and crops < args.max_crops and res.registration is not None:
            aligned = align_to_template(img, res, tpl)
            for e in s.errors:
                if crops >= args.max_crops or e["field"] == "*":
                    continue
                save_crop(crops_dir / f"{crops:02d}_{p.stem}_{e['field']}.png", aligned, tpl, p.stem, e)
                crops += 1

    per_school = {}
    for school in schools:
        sub = [s for s in scores if s.school == school]
        if sub:
            per_school[school] = aggregate(sub, label_notes)
    errors = [{"sheet": s.sheet, **e, "suspected_label_error": (s.sheet, e["field"]) in label_notes}
              for s in scores for e in s.errors]
    report = {
        "schema": "omr-external/1",
        "dataset": args.dataset,
        "split": args.split,
        "citation": ds["citation"],
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "engine_version": ENGINE_VERSION,
        "template_id": tpl.id,
        "engine_overrides": tpl.spec.engine_overrides,
        "schools": schools,
        "metrics": aggregate(scores, label_notes),
        "per_school": per_school,
        "errors": errors,
        "suspected_label_errors": notes.get("suspected", []),
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"external_{args.dataset}" if args.split == "test" else f"external_{args.dataset}_{args.split}"
    (out / f"{stem}.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    write_markdown(report, out / f"{stem}.md")
    m = report["metrics"]
    print(f"{args.dataset}/{args.split}: {m['sheets']} sheets, strict {_fmt(m['question_accuracy_strict'])}, "
          f"lenient {_fmt(m['question_accuracy_lenient'])}, silent {_fmt(m['silent_error_rate'])}, "
          f"ID exact {_fmt(m['id_exact'])}, p95 {m['latency_ms_p95']:.0f} ms -> {out / stem}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
