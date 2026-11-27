"""OMR benchmark runner: generate seeded synthetic sheets -> degrade -> scan_image -> metrics -> reports.

Usage (from the project root):
    .\\.venv\\Scripts\\python.exe benchmarks\\run_benchmark.py --n 50 --tiers clean,scan,photo,hard --seed 42
    .\\.venv\\Scripts\\python.exe benchmarks\\run_benchmark.py --n 5 --save-samples 5 --generate-only

Writes <out>/latest.json, <out>/latest.md and <out>/history/<timestamp>.json.
Sheets with ground truth in benchmarks/data/real/ (<name>.jpg + <name>.json) are scored as tier "real".
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import platform
import sys
import time
import traceback
import zlib
from pathlib import Path
from typing import Any

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks import metrics as M  # noqa: E402
from benchmarks.synth.degrade import TIERS, degrade  # noqa: E402
from benchmarks.synth.generator import StyleMix, generate_sheet, load_synth_template  # noqa: E402

TARGETS = {  # question_accuracy targets (ARCHITECTURE.md section 1)
    "clean": 0.999,
    "scan": 0.995,
    "photo": 0.98,
}
LATENCY_P95_TARGET_MS = 1500.0
IMG_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp"}


# --------------------------------------------------------------------------- #
# engine
# --------------------------------------------------------------------------- #
def import_engine() -> tuple[Any, str | None]:
    backend = ROOT / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    try:
        import omr_engine  # type: ignore
        for name in ("load_template", "scan_image"):
            if not hasattr(omr_engine, name):
                return None, f"omr_engine is missing `{name}`"
        return omr_engine, None
    except Exception as e:  # ImportError or a broken engine module
        return None, f"{type(e).__name__}: {e}"


def engine_version(eng: Any) -> str | None:
    v = getattr(eng, "__version__", None)
    if v:
        return str(v)
    try:
        from importlib.metadata import version

        return version("omr_engine")
    except Exception:
        return None


def engine_config_dump(eng: Any) -> tuple[Any, dict[str, Any] | None]:
    cls = getattr(eng, "EngineConfig", None)
    if cls is None:
        return None, None
    cfg = cls()
    try:
        if dataclasses.is_dataclass(cfg):
            d = dataclasses.asdict(cfg)
        elif hasattr(cfg, "model_dump"):
            d = cfg.model_dump()
        else:
            d = dict(vars(cfg))
        d = json.loads(json.dumps(d, default=str))
    except Exception:
        d = {"repr": repr(cfg)}
    return cfg, d


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def tier_seed(tier: str) -> int:
    return zlib.crc32(tier.encode()) & 0x7FFFFFFF


def imwrite(path: Path, img: np.ndarray, q: int = 95) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ext = path.suffix.lower()
    params = [cv2.IMWRITE_JPEG_QUALITY, q] if ext in (".jpg", ".jpeg") else []
    ok, buf = cv2.imencode(ext, img, params)
    if not ok:
        raise RuntimeError(f"encode failed for {path}")
    buf.tofile(str(path))


def imread(path: Path) -> np.ndarray | None:
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None


def _json_default(o: Any) -> Any:
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def run_scan(eng: Any, img: np.ndarray, tpl: Any, cfg: Any) -> tuple[dict[str, Any], float]:
    t0 = time.perf_counter()
    try:
        res = eng.scan_image(img, tpl, config=cfg) if cfg is not None else eng.scan_image(img, tpl)
        dt_s = time.perf_counter() - t0
        return M.normalize_prediction(res), dt_s
    except Exception as e:
        dt_s = time.perf_counter() - t0
        pred = M.failed_prediction(f"exception: {type(e).__name__}: {e}")
        pred["exception"] = traceback.format_exc(limit=3)
        return pred, dt_s


def fmt(v: Any, pct: bool = True, digits: int = 2) -> str:
    if v is None:
        return "-"
    if pct:
        return f"{100 * v:.{digits}f}%"
    return f"{v:.{digits}f}" if isinstance(v, float) else str(v)


# --------------------------------------------------------------------------- #
# reports
# --------------------------------------------------------------------------- #
def write_markdown(report: dict[str, Any], path: Path) -> None:
    tiers = report["tiers"]
    names = list(tiers) + (["overall"] if report.get("overall") else [])
    get = lambda n: tiers[n] if n in tiers else report["overall"]  # noqa: E731
    rows = [
        ("Sheets", "n_sheets", "int"),
        ("Question accuracy (strict)", "question_accuracy", "pct"),
        ("Question accuracy (lenient)", "question_accuracy_lenient", "pct"),
        ("Silent error rate", "silent_error_rate", "pct3"),
        ("Bubble accuracy", "bubble_accuracy", "pct3"),
        ("Roll no exact", "roll_exact", "pct"),
        ("Paper set accuracy", "paper_set_accuracy", "pct"),
        ("Sheet exact match", "sheet_exact", "pct"),
        ("Blank precision", "blank_precision", "pct"),
        ("Blank recall", "blank_recall", "pct"),
        ("Multiple precision", "multiple_precision", "pct"),
        ("Multiple recall", "multiple_recall", "pct"),
        ("Distractor false-fill", "distractor_false_fill_rate", "pct"),
        ("Distractor flagged", "distractor_flagged_rate", "pct"),
        ("Question review rate", "question_review_rate", "pct"),
        ("Sheets needs_review", "review_rate", "pct"),
        ("Avg flags / sheet", "avg_flags_per_sheet", "num"),
        ("Registration failures", "registration_failure_rate", "pct"),
        ("Registration quality (mean)", "registration_quality_mean", "num3"),
        ("Latency p50 (ms)", ("latency_ms", "p50"), "ms"),
        ("Latency p95 (ms)", ("latency_ms", "p95"), "ms"),
        ("Latency mean (ms)", ("latency_ms", "mean"), "ms"),
        ("Throughput (sheets/s)", "throughput_sheets_per_s", "num"),
    ]

    def cell(m: dict[str, Any], key: Any, kind: str) -> str:
        v = m.get(key[0], {}).get(key[1]) if isinstance(key, tuple) else m.get(key)
        if v is None:
            return "-"
        if kind == "int":
            return str(v)
        if kind == "pct":
            return f"{100 * v:.2f}%"
        if kind == "pct3":
            return f"{100 * v:.3f}%"
        if kind == "ms":
            return f"{v:.0f}"
        if kind == "num3":
            return f"{v:.3f}"
        return f"{v:.2f}"

    cfg = report["config"]
    lines = [
        "# OMR benchmark report",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Engine version: {report.get('engine_version') or 'unknown'}",
        f"- Seed: {cfg['seed']}, sheets per synthetic tier: {cfg['n']}, tiers: {', '.join(cfg['tiers'])}",
        "",
        "| Metric | " + " | ".join(names) + " |",
        "|---|" + "---:|" * len(names),
    ]
    for label, key, kind in rows:
        lines.append(f"| {label} | " + " | ".join(cell(get(n), key, kind) for n in names) + " |")
    lines += ["", "## Targets", "", "| Target | Value | Status |", "|---|---:|---|"]
    for t in report.get("targets_check", []):
        lines.append(f"| {t['name']} | {t['value']} | {'PASS' if t['pass'] else 'FAIL'} |")
    lines += ["", "## Top error patterns", ""]
    for name in names:
        eb = get(name).get("error_breakdown") or {}
        if eb:
            lines.append(f"- **{name}**: " + ", ".join(f"{k} x{v}" for k, v in list(eb.items())[:8]))
    fr = (report.get("overall") or {}).get("fill_recall_by_style") or {}
    if fr:
        lines += ["", "## Fill recall by mark style (overall)", "", "| Style | Count | Recall |", "|---|---:|---:|"]
        for st, v in fr.items():
            lines.append(f"| {st} | {v['count']} | {fmt(v['recall'])} |")
    dbt = (report.get("overall") or {}).get("distractor_by_type") or {}
    if dbt:
        lines += ["", "## Distractors (GT = not filled)", "", "| Type | Count | Read as filled | Flagged |", "|---|---:|---:|---:|"]
        for t, v in dbt.items():
            lines.append(f"| {t} | {v['count']} | {fmt(v['false_fill_rate'])} | {fmt(v['flagged_rate'])} |")
    if report.get("errors_sample"):
        lines += ["", "## Sample misreads", "", "| Tier | Sample | Field | Expected | Got | Kind | State | Style |",
                  "|---|---|---|---|---|---|---|---|"]
        for e in report["errors_sample"]:
            lines.append(f"| {e.get('tier')} | {e.get('sample')} | {e.get('field')} | {e.get('expected') or '(blank)'} | "
                         f"{e.get('got') or '(blank)'} | {e.get('kind')} | {e.get('state') or '-'} | {e.get('style') or e.get('distractor') or '-'} |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def check_targets(report: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for tier, target in TARGETS.items():
        m = report["tiers"].get(tier)
        if not m or m.get("question_accuracy") is None:
            continue
        v = m["question_accuracy"]
        out.append({"name": f"{tier} question accuracy >= {100 * target:.1f}%", "value": f"{100 * v:.3f}%", "pass": v >= target})
    ov = report.get("overall") or {}
    p95 = (ov.get("latency_ms") or {}).get("p95")
    if p95 is not None:
        out.append({"name": f"latency p95 < {LATENCY_P95_TARGET_MS:.0f} ms", "value": f"{p95:.0f} ms", "pass": p95 < LATENCY_P95_TARGET_MS})
    return out


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="OMR scanner benchmark (synthetic + optional real sheets)")
    ap.add_argument("--n", type=int, default=50, help="sheets per synthetic tier")
    ap.add_argument("--tiers", default="clean,scan,photo,hard", help=f"comma list from {','.join(TIERS)}")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--save-samples", type=int, default=0, metavar="K", help="save first K samples per tier to --data-dir/<tier>/")
    ap.add_argument("--out", default=str(ROOT / "benchmarks" / "reports"))
    ap.add_argument("--data-dir", default=str(ROOT / "benchmarks" / "data"))
    ap.add_argument("--template", default=str(ROOT / "templates" / "sheet80_v2"))
    ap.add_argument("--real-dir", default=None, help="default: <data-dir>/real")
    ap.add_argument("--no-real", action="store_true", help="skip the real tier")
    ap.add_argument("--blank-rate", type=float, default=0.05)
    ap.add_argument("--multiple-rate", type=float, default=0.02)
    ap.add_argument("--distractor-rate", type=float, default=0.02)
    ap.add_argument("--generate-only", action="store_true", help="only generate/save samples (no engine needed)")
    ap.add_argument("--check-targets", action="store_true", help="exit 1 if an MVP target is missed")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args(argv)

    tiers = [t.strip() for t in args.tiers.split(",") if t.strip()]
    bad = [t for t in tiers if t not in TIERS]
    if bad:
        ap.error(f"unknown tier(s) {bad}; choose from {TIERS}")
    out_dir, data_dir = Path(args.out), Path(args.data_dir)
    real_dir = Path(args.real_dir) if args.real_dir else data_dir / "real"
    log = (lambda *a: None) if args.quiet else (lambda *a: print(*a, flush=True))

    synth_tpl = load_synth_template(args.template)
    layout = M.layout_from_template(synth_tpl)
    mix = StyleMix(blank_rate=args.blank_rate, multiple_rate=args.multiple_rate, distractor_rate=args.distractor_rate)

    eng = tpl = cfg = cfg_dump = None
    if not args.generate_only:
        eng, err = import_engine()
        if eng is None:
            print(
                "ERROR: cannot import the OMR engine (backend/omr_engine).\n"
                f"  reason: {err}\n"
                "  The benchmark needs omr_engine.load_template / scan_image (see ARCHITECTURE.md section 6).\n"
                "  To only generate synthetic samples, re-run with --generate-only --save-samples K.",
                file=sys.stderr,
            )
            return 2
        tpl = eng.load_template(args.template)
        cfg, cfg_dump = engine_config_dump(eng)
        # warm-up (lazy init, template masks, ...) is excluded from latency
        t0 = time.perf_counter()
        run_scan(eng, synth_tpl.image.copy(), tpl, cfg)
        warmup_ms = (time.perf_counter() - t0) * 1000
        log(f"engine {engine_version(eng) or '(no version)'} loaded; warm-up scan {warmup_ms:.0f} ms")
    else:
        warmup_ms = None

    scores: dict[str, list[M.SheetScore]] = {t: [] for t in tiers}
    synth_s = 0.0
    t_start = time.perf_counter()
    for i in range(args.n):
        t0 = time.perf_counter()
        sheet, gt = generate_sheet(np.random.default_rng([args.seed, i]), synth_tpl, mix)
        synth_s += time.perf_counter() - t0
        for tier in tiers:
            t0 = time.perf_counter()
            img, meta = degrade(sheet, tier, np.random.default_rng([args.seed, i, tier_seed(tier)]))
            synth_s += time.perf_counter() - t0
            sample = f"{tier}_{i:04d}"
            pred = None
            if eng is not None:
                pred, lat = run_scan(eng, img, tpl, cfg)
                sc = M.score_sheet(gt, pred, layout, tier=tier, sample=sample, latency_s=lat)
                scores[tier].append(sc)
                if not args.quiet:
                    print(f"  {sample}: {pred['status']:<12} q_acc={sc.q_correct}/{sc.questions_total} "
                          f"roll={'ok' if sc.roll_match else 'X'} set={'ok' if sc.set_match else 'X'} {lat * 1000:.0f}ms", flush=True)
            if i < args.save_samples:
                imwrite(data_dir / tier / f"{sample}.jpg", img)
                rec = {"ground_truth": gt, "degradation": meta, "seed": [args.seed, i, tier_seed(tier)]}
                if pred is not None:
                    rec["prediction"] = {k: pred.get(k) for k in ("status", "roll_no", "paper_set", "answers", "review_flags",
                                                                  "registration_quality", "registration_method", "error")}
                (data_dir / tier / f"{sample}.json").write_text(json.dumps(rec, indent=1, default=_json_default), encoding="utf-8")
        if args.quiet is False and eng is None:
            print(f"  generated sample {i + 1}/{args.n}", flush=True)

    if eng is None:
        log(f"generated {args.n} x {len(tiers)} samples in {synth_s:.1f}s "
            f"({'saved to ' + str(data_dir) if args.save_samples else 'not saved'}); --generate-only: no scoring.")
        return 0

    # ---- real tier -------------------------------------------------------------
    real_scores: list[M.SheetScore] = []
    if not args.no_real and real_dir.is_dir():
        for p in sorted(real_dir.iterdir()):
            if p.suffix.lower() not in IMG_EXTS:
                continue
            gj = p.with_suffix(".json")
            if not gj.exists():
                continue
            try:
                gt = json.loads(gj.read_text(encoding="utf-8"))
                gt = gt.get("ground_truth", gt)
            except Exception as e:
                log(f"  real/{p.name}: bad ground truth json ({e}); skipped")
                continue
            img = imread(p)
            if img is None:
                log(f"  real/{p.name}: cannot decode; skipped")
                continue
            pred, lat = run_scan(eng, img, tpl, cfg)
            real_scores.append(M.score_sheet(gt, pred, layout, tier="real", sample=p.stem, latency_s=lat))
            log(f"  real/{p.name}: {pred['status']}")

    # ---- report -----------------------------------------------------------------
    now = dt.datetime.now(dt.timezone.utc)
    tier_metrics = {t: M.aggregate(scores[t]) for t in tiers}
    if real_scores:
        tier_metrics["real"] = M.aggregate(real_scores)
    all_synth = [s for t in tiers for s in scores[t]]
    report: dict[str, Any] = {
        "schema": "omr-benchmark/1",
        "generated_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "engine_version": engine_version(eng),
        "config": {
            "n": args.n, "seed": args.seed, "tiers": tiers, "template": Path(args.template).name,
            "style_mix": dataclasses.asdict(mix), "engine_config": cfg_dump,
            "real_dir_scored": len(real_scores), "warmup_ms": warmup_ms,
            "platform": {"python": platform.python_version(), "system": platform.system(), "machine": platform.machine(),
                         "processor": platform.processor(), "opencv": cv2.__version__, "numpy": np.__version__},
            "synth_seconds": round(synth_s, 2), "wall_seconds": round(time.perf_counter() - t_start, 2),
        },
        "targets": {"question_accuracy": TARGETS, "latency_p95_ms": LATENCY_P95_TARGET_MS},
        "tiers": tier_metrics,
        "overall": M.aggregate(all_synth),
        "overall_note": "overall aggregates the synthetic tiers only; the real tier is reported separately",
        "errors_sample": M.pick_error_samples(all_synth + real_scores, 20),
    }
    report["targets_check"] = check_targets(report)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "history").mkdir(parents=True, exist_ok=True)
    js = json.dumps(report, indent=2, default=_json_default)
    (out_dir / "latest.json").write_text(js, encoding="utf-8")
    (out_dir / "history" / f"{now.strftime('%Y%m%d-%H%M%S')}.json").write_text(js, encoding="utf-8")
    write_markdown(report, out_dir / "latest.md")

    # ---- console summary -----------------------------------------------------------
    log("")
    log(f"{'tier':<8}{'n':>5}{'q_acc':>10}{'lenient':>10}{'roll':>9}{'set':>9}{'sheet':>9}{'fail':>8}{'review':>8}{'p95ms':>8}")
    for name, m in list(tier_metrics.items()) + [("overall", report["overall"])]:
        if not m.get("n_sheets"):
            continue
        log(f"{name:<8}{m['n_sheets']:>5}{fmt(m['question_accuracy']):>10}{fmt(m['question_accuracy_lenient']):>10}"
            f"{fmt(m['roll_exact'], digits=1):>9}{fmt(m['paper_set_accuracy'], digits=1):>9}{fmt(m['sheet_exact'], digits=1):>9}"
            f"{fmt(m['registration_failure_rate'], digits=1):>8}{fmt(m['review_rate'], digits=0):>8}"
            f"{(m['latency_ms']['p95'] or 0):>8.0f}")
    for t in report["targets_check"]:
        log(f"  [{'PASS' if t['pass'] else 'FAIL'}] {t['name']}: {t['value']}")
    log(f"reports written to {out_dir}")
    if args.check_targets and not all(t["pass"] for t in report["targets_check"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
