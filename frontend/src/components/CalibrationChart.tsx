import { useState } from "react";
import { CalibrationPoint } from "../api";

/** Confidence (x) vs accuracy (y). Points on the dashed diagonal = well calibrated. */
export default function CalibrationChart({ points }: { points: CalibrationPoint[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 340, H = 270, m = { l: 58, r: 14, t: 12, b: 42 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const x = (v: number) => m.l + v * iw;
  const y = (v: number) => m.t + (1 - v) * ih;
  const maxN = Math.max(1, ...points.map((p) => p.n));
  const r = (n: number) => 4 + 5 * Math.sqrt(n / maxN); // >= 4 (8px marker)
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  const pct = (v: number) => `${Math.round(v * 100)}%`;

  if (points.length === 0) {
    return <p className="muted">Rate your confidence before answering practice questions to see this chart.</p>;
  }
  const p = hover !== null ? points[hover] : null;

  return (
    <div className="chart-wrap">
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} width={W} style={{ maxWidth: "100%", height: "auto" }} role="img"
           aria-label="Calibration chart: confidence against accuracy. Points on the diagonal mean your confidence matched your results.">
        <g className="grid">
          {ticks.map((t) => (
            <g key={t}>
              <line x1={x(0)} x2={x(1)} y1={y(t)} y2={y(t)} />
              <text x={m.l - 6} y={y(t) + 4} textAnchor="end">{pct(t)}</text>
              <text x={x(t)} y={H - m.b + 16} textAnchor="middle">{pct(t)}</text>
            </g>
          ))}
        </g>
        <line className="ref" x1={x(0)} y1={y(0)} x2={x(1)} y2={y(1)} />
        <text className="axis-title" x={x(0.98)} y={y(0.98) + 16} textAnchor="end">perfectly calibrated</text>
        <text className="axis-title" x={m.l + iw / 2} y={H - 4} textAnchor="middle">How sure you were</text>
        <text className="axis-title" transform={`translate(14 ${m.t + ih / 2}) rotate(-90)`} textAnchor="middle">
          How often you were right
        </text>
        {points.map((pt, i) => (
          <g key={i}>
            <circle className="hit" cx={x(pt.confidence)} cy={y(pt.accuracy)} r={r(pt.n) + 8} tabIndex={0}
                    onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}
                    onFocus={() => setHover(i)} onBlur={() => setHover(null)}
                    aria-label={`Confidence ${pct(pt.confidence)}, accuracy ${pct(pt.accuracy)}, ${pt.n} answers`} />
            <circle className="dot" cx={x(pt.confidence)} cy={y(pt.accuracy)} r={r(pt.n)} pointerEvents="none" />
          </g>
        ))}
      </svg>
      {p && (
        <div className="tooltip" style={{ left: `${(x(p.confidence) / W) * 100}%`, top: `${(y(p.accuracy) / H) * 100 - 14}%` }}>
          Sure: {pct(p.confidence)} · Right: {pct(p.accuracy)} · {p.n} answer{p.n === 1 ? "" : "s"}
        </div>
      )}
      <details>
        <summary>View as table</summary>
        <table className="data">
          <thead><tr><th>How sure</th><th>How often right</th><th>Answers</th></tr></thead>
          <tbody>
            {points.map((pt, i) => (
              <tr key={i}><td>{pct(pt.confidence)}</td><td>{pct(pt.accuracy)}</td><td>{pt.n}</td></tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}
