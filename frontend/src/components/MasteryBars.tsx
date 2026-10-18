import { useState } from "react";
import { MasteryRow } from "../api";

/** Horizontal bars, one per concept. Concepts not practised yet are drawn faint. */
export default function MasteryBars({ rows }: { rows: MasteryRow[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 560, rowH = 24, bar = 12, labelW = 196, valueW = 44;
  const iw = W - labelW - valueW;
  const H = rows.length * rowH + 8;
  const pct = (v: number) => `${Math.round(v * 100)}%`;
  const h = hover !== null ? rows[hover] : null;

  return (
    <div className="chart-wrap">
      {/* Fixed pixel width (shrinks on narrow screens) so text stays at its real size. */}
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} width={W} style={{ maxWidth: "100%", height: "auto" }} role="img"
           aria-label="Estimated mastery for each course concept">
        {rows.map((r, i) => {
          const yTop = 4 + i * rowH + (rowH - bar) / 2;
          const w = Math.max(r.mastery * iw, 2);
          const radius = Math.min(4, w / 2);
          // square at the baseline, 4px rounded at the data end
          const path = `M${labelW},${yTop} h${w - radius} a${radius},${radius} 0 0 1 ${radius},${radius}
                        v${bar - 2 * radius} a${radius},${radius} 0 0 1 ${-radius},${radius} h${-(w - radius)} Z`;
          return (
            <g key={r.key} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect className="hit" x={0} y={4 + i * rowH} width={W} height={rowH} />
              <text x={labelW - 8} y={yTop + bar - 2} textAnchor="end">{r.concept}</text>
              <path className={`bar ${r.practised ? "" : "unpractised"}`} d={path} />
              <text x={labelW + w + 6} y={yTop + bar - 2}>{r.practised ? pct(r.mastery) : "–"}</text>
            </g>
          );
        })}
      </svg>
      {h && (
        <div className="tooltip" style={{ left: `${(labelW / W) * 100}%`, top: `${((4 + (hover ?? 0) * rowH) / H) * 100}%` }}>
          {h.concept}: {pct(h.mastery)} {h.practised ? "" : "(not practised yet, estimate is the prior)"}
        </div>
      )}
      <details>
        <summary>View as table</summary>
        <table className="data">
          <thead><tr><th>Concept</th><th>Estimated mastery</th><th>Practised</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key}><td>{r.concept}</td><td>{pct(r.mastery)}</td><td>{r.practised ? "yes" : "no"}</td></tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}
