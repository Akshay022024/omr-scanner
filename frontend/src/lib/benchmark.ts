import { isNum, toFraction } from './format';

/**
 * Defensive reader for benchmarks/reports/latest.json. The exact key names are owned by the
 * benchmark runner, so every metric is looked up through a list of aliases (dotted paths allowed),
 * and missing metrics simply render as "—".
 */

export type MetricKind = 'pct' | 'ms' | 'rate' | 'count';

export interface MetricDef {
  key: string;
  label: string;
  kind: MetricKind;
  aliases: string[];
}

export const METRICS: MetricDef[] = [
  { key: 'n', label: 'Sheets', kind: 'count', aliases: ['n', 'n_sheets', 'sheets', 'num_sheets', 'count'] },
  {
    key: 'question_accuracy',
    label: 'Question acc.',
    kind: 'pct',
    aliases: ['question_accuracy', 'question_acc', 'accuracy.question', 'q_accuracy', 'questions.accuracy'],
  },
  {
    key: 'bubble_accuracy',
    label: 'Bubble acc.',
    kind: 'pct',
    aliases: ['bubble_accuracy', 'bubble_acc', 'accuracy.bubble', 'bubbles.accuracy'],
  },
  {
    key: 'roll_exact',
    label: 'Roll exact',
    kind: 'pct',
    aliases: ['roll_exact', 'roll_no_exact', 'roll_exact_match', 'roll_no_exact_match', 'roll_exact_rate', 'roll_no_exact_rate', 'roll_no_accuracy', 'roll_accuracy'],
  },
  {
    key: 'set_accuracy',
    label: 'Set acc.',
    kind: 'pct',
    aliases: ['set_accuracy', 'paper_set_accuracy', 'paper_set_acc', 'set_acc'],
  },
  {
    key: 'sheet_exact',
    label: 'Sheet exact',
    kind: 'pct',
    aliases: ['sheet_exact', 'sheet_exact_match', 'sheet_exact_rate', 'sheet_exact_match_rate', 'sheet_accuracy'],
  },
  {
    key: 'blank_precision',
    label: 'Blank P',
    kind: 'pct',
    aliases: ['blank_precision', 'blank.precision', 'blank_p', 'blank_detection.precision', 'blank_detection_precision'],
  },
  {
    key: 'blank_recall',
    label: 'Blank R',
    kind: 'pct',
    aliases: ['blank_recall', 'blank.recall', 'blank_r', 'blank_detection.recall', 'blank_detection_recall'],
  },
  {
    key: 'multiple_precision',
    label: 'Multiple P',
    kind: 'pct',
    aliases: ['multiple_precision', 'multi_precision', 'multiple.precision', 'multiple_p', 'multiple_detection.precision', 'multiple_mark.precision', 'multiple_mark_precision'],
  },
  {
    key: 'multiple_recall',
    label: 'Multiple R',
    kind: 'pct',
    aliases: ['multiple_recall', 'multi_recall', 'multiple.recall', 'multiple_r', 'multiple_detection.recall', 'multiple_mark.recall', 'multiple_mark_recall'],
  },
  {
    key: 'review_rate',
    label: 'Review rate',
    kind: 'pct', // share of sheets routed to review
    aliases: ['review_rate', 'sheet_review_rate', 'review.rate'],
  },
  {
    key: 'flags_per_sheet',
    label: 'Flags/sheet',
    kind: 'rate',
    aliases: ['avg_flags_per_sheet', 'flags_per_sheet', 'review_flags_per_sheet'],
  },
  {
    key: 'failure_rate',
    label: 'Failure rate',
    kind: 'pct',
    aliases: ['failure_rate', 'registration_failure_rate', 'fail_rate', 'failed_rate', 'registration.failure_rate'],
  },
  {
    key: 'latency_p50',
    label: 'p50',
    kind: 'ms',
    aliases: ['latency_p50_ms', 'latency_ms.p50', 'latency.p50_ms', 'latency.p50', 'p50_ms', 'latency_p50'],
  },
  {
    key: 'latency_p95',
    label: 'p95',
    kind: 'ms',
    aliases: ['latency_p95_ms', 'latency_ms.p95', 'latency.p95_ms', 'latency.p95', 'p95_ms', 'latency_p95'],
  },
  {
    key: 'latency_mean',
    label: 'Mean',
    kind: 'ms',
    aliases: ['latency_mean_ms', 'latency_ms.mean', 'latency.mean_ms', 'latency.mean', 'mean_ms', 'latency_mean'],
  },
  {
    key: 'throughput',
    label: 'Throughput',
    kind: 'rate',
    aliases: ['throughput_sheets_per_s', 'throughput', 'sheets_per_s', 'sheets_per_sec', 'throughput_per_s', 'throughput.sheets_per_s'],
  },
];

export const METRIC_BY_KEY: Record<string, MetricDef> = Object.fromEntries(METRICS.map((m) => [m.key, m]));

/** MVP question-accuracy targets (ARCHITECTURE.md §1). `hard` is reported only. */
export const ACCURACY_TARGETS: Record<string, number> = { clean: 0.999, scan: 0.995, photo: 0.98 };
export const P95_TARGET_MS = 1500;
export const TIER_ORDER = ['clean', 'scan', 'photo', 'hard', 'real'];

export function getPath(obj: unknown, path: string): unknown {
  let cur: unknown = obj;
  for (const part of path.split('.')) {
    if (!cur || typeof cur !== 'object') return undefined;
    cur = (cur as Record<string, unknown>)[part];
  }
  return cur;
}

/** Look a metric up in a tier object (also inside a nested `metrics` object). */
export function metricValue(tier: unknown, key: string): number | null {
  const def = METRIC_BY_KEY[key];
  const aliases = def ? def.aliases : [key];
  const scopes = [tier, getPath(tier, 'metrics')];
  for (const scope of scopes) {
    for (const a of aliases) {
      const v = getPath(scope, a);
      if (isNum(v)) return v;
    }
  }
  return null;
}

export interface Targets {
  accuracy: Record<string, number>;
  p95Ms: number;
}

/** Targets embedded in the report (`targets.question_accuracy`, `targets.latency_p95_ms`) win over the defaults. */
export function targetsFrom(report: unknown): Targets {
  const acc = getPath(report, 'targets.question_accuracy');
  const p95 = getPath(report, 'targets.latency_p95_ms');
  const accuracy: Record<string, number> = { ...ACCURACY_TARGETS };
  if (isObj(acc)) {
    for (const [k, v] of Object.entries(acc)) if (isNum(v)) accuracy[k] = toFraction(v) ?? v;
  }
  return { accuracy, p95Ms: isNum(p95) ? p95 : P95_TARGET_MS };
}

export interface TargetCheck {
  name: string;
  value: string;
  pass: boolean | null;
}

export function extractTargetChecks(report: unknown): TargetCheck[] {
  const c = isObj(report) ? report.targets_check : undefined;
  if (!Array.isArray(c)) return [];
  return c.filter(isObj).map((x) => ({
    name: String(x.name ?? ''),
    value: x.value === undefined || x.value === null ? '' : String(x.value),
    pass: typeof x.pass === 'boolean' ? x.pass : null,
  }));
}

export interface TierEntry {
  name: string;
  data: Record<string, unknown>;
}

function isObj(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === 'object' && !Array.isArray(v);
}

/** Extract per-tier metric objects; supports `{tiers: {clean: {...}}}` and `{tiers: [{tier: "clean", ...}]}`. */
export function extractTiers(report: unknown): TierEntry[] {
  if (!isObj(report)) return [];
  const container = report.tiers ?? report.per_tier ?? report.results ?? report.by_tier;
  let tiers: TierEntry[] = [];
  if (Array.isArray(container)) {
    tiers = container.filter(isObj).map((t, i) => ({
      name: String(t.tier ?? t.name ?? t.id ?? `tier ${i + 1}`),
      data: t,
    }));
  } else if (isObj(container)) {
    tiers = Object.entries(container)
      .filter(([, v]) => isObj(v))
      .map(([name, v]) => ({ name, data: v as Record<string, unknown> }));
  }
  tiers = tiers.filter((t) => t.name !== 'overall');
  return tiers.sort((a, b) => {
    const ia = TIER_ORDER.indexOf(a.name);
    const ib = TIER_ORDER.indexOf(b.name);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.name.localeCompare(b.name);
  });
}

export function extractOverall(report: unknown): Record<string, unknown> | null {
  if (!isObj(report)) return null;
  const c = report.overall ?? report.summary ?? getPath(report, 'tiers.overall');
  return isObj(c) ? c : null;
}

export type Verdict = 'pass' | 'fail' | 'na';

export function accuracyVerdict(tier: string, accuracy: number | null, targets: Record<string, number> = ACCURACY_TARGETS): Verdict {
  const target = targets[tier];
  if (target === undefined || accuracy === null) return 'na';
  const f = toFraction(accuracy);
  if (f === null) return 'na';
  return f + 1e-9 >= target ? 'pass' : 'fail';
}

export function latencyVerdict(p95: number | null, targetMs = P95_TARGET_MS): Verdict {
  if (p95 === null) return 'na';
  return p95 < targetMs ? 'pass' : 'fail';
}

export function extractErrorsSample(report: unknown): Record<string, unknown>[] {
  if (!isObj(report)) return [];
  const e = report.errors_sample ?? report.error_samples ?? report.errors;
  return Array.isArray(e) ? e.filter(isObj) : [];
}

export function generatedAt(report: unknown): string | null {
  if (!isObj(report)) return null;
  const v = report.generated_at ?? report.timestamp ?? report.created_at;
  return typeof v === 'string' || typeof v === 'number' ? String(v) : null;
}
