import { ACCURACY_TARGETS, accuracyVerdict } from '../lib/benchmark';
import { toFraction } from '../lib/format';

export interface AccuracyBar {
  tier: string;
  value: number | null; // 0..1 (or 0..100)
}

/**
 * Hand-drawn horizontal bar chart of question accuracy per tier, with target ticks.
 * The axis starts above 0 because the interesting range is the last few percent; the floor is labelled.
 */
export function AccuracyChart({ bars, targets = ACCURACY_TARGETS }: { bars: AccuracyBar[]; targets?: Record<string, number> }) {
  const values = bars.map((b) => toFraction(b.value)).filter((v): v is number => v !== null);
  if (!values.length) return <p className="muted">No question-accuracy values in this report.</p>;

  const tierTargets = bars.map((b) => targets[b.tier]).filter((t): t is number => t !== undefined);
  const minVal = Math.min(...values, ...tierTargets);
  // Round the axis floor down to a 5% step, at most 0, at least 0 below the smallest value.
  const floor = Math.max(0, Math.floor((minVal - 0.01) * 20) / 20);
  const span = 1 - floor;

  const rowH = 34;
  const labelW = 64;
  const valueW = 64;
  const W = 560;
  const plotW = W - labelW - valueW;
  const top = 8;
  const H = top + bars.length * rowH + 28;
  const x = (v: number) => labelW + ((Math.max(floor, Math.min(1, v)) - floor) / span) * plotW;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => floor + t * span);

  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-labelledby="acc-chart-title acc-chart-desc" preserveAspectRatio="xMinYMin meet">
        <title id="acc-chart-title">Question accuracy per tier</title>
        <desc id="acc-chart-desc">
          {bars.map((b) => `${b.tier}: ${toFraction(b.value) === null ? 'no data' : `${((toFraction(b.value) ?? 0) * 100).toFixed(2)}%`}`).join('; ')}
        </desc>
        {ticks.map((t) => (
          <g key={t}>
            <line className="chart__grid" x1={x(t)} x2={x(t)} y1={top} y2={top + bars.length * rowH} />
            <text className="chart__tick" x={x(t)} y={top + bars.length * rowH + 18} textAnchor="middle">
              {(t * 100).toFixed(span < 0.2 ? 1 : 0)}%
            </text>
          </g>
        ))}
        {bars.map((b, i) => {
          const v = toFraction(b.value);
          const y = top + i * rowH;
          const target = targets[b.tier];
          const verdict = accuracyVerdict(b.tier, b.value, targets);
          const barW = v === null ? 0 : Math.max(8, x(v) - labelW);
          return (
            <g key={b.tier} className="chart__row">
              <text className="chart__label" x={labelW - 8} y={y + rowH / 2 + 4} textAnchor="end">
                {b.tier}
              </text>
              {v !== null && (
                <path
                  className={`chart__bar chart__bar--${verdict}`}
                  d={`M${labelW},${y + 8} h${barW - 4} a4,4 0 0 1 4,4 v${rowH - 24} a4,4 0 0 1 -4,4 h${-(barW - 4)} z`}
                >
                  <title>{`${b.tier}: ${(v * 100).toFixed(2)}%${target !== undefined ? ` (target ≥ ${(target * 100).toFixed(1)}%)` : ''}`}</title>
                </path>
              )}
              {target !== undefined && (
                <line className="chart__target" x1={x(target)} x2={x(target)} y1={y + 4} y2={y + rowH - 4}>
                  <title>{`Target ≥ ${(target * 100).toFixed(1)}%`}</title>
                </line>
              )}
              <text className="chart__value" x={W - valueW + 6} y={y + rowH / 2 + 4}>
                {v === null ? '—' : `${(v * 100).toFixed(2)}%`}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption className="muted small">
        Axis starts at {(floor * 100).toFixed(0)}%. Dashed ticks mark the MVP target per tier; tiers without a tick are reported only.
      </figcaption>
    </figure>
  );
}
