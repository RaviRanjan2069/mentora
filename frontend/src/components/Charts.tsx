import { ReactNode, useState } from "react";
import Icon, { IconName } from "../icons";
import { pct } from "../api";

export function StatCard({ icon, tone, label, value, note }: {
  icon: IconName; tone?: "green" | "orange" | "red"; label: string; value: ReactNode; note?: ReactNode;
}) {
  return (
    <div className="card stat">
      <div className={`ico ${tone ?? ""}`}><Icon name={icon} /></div>
      <div>
        <div className="label">{label}</div>
        <div className="value">{value}</div>
        {note && <div className="note">{note}</div>}
      </div>
    </div>
  );
}

/** One-value ring (overall SRL score). Single series: one hue, no legend. */
export function Ring({ value, label }: { value: number; label: string }) {
  const r = 46, c = 2 * Math.PI * r;
  return (
    <svg viewBox="0 0 120 120" width={128} height={128} role="img" aria-label={`${label}: ${pct(value)}`}>
      <circle cx="60" cy="60" r={r} fill="none" stroke="var(--surface-3)" strokeWidth="12" />
      <circle cx="60" cy="60" r={r} fill="none" stroke="var(--series-1)" strokeWidth="12"
              strokeDasharray={`${c * value} ${c}`} strokeLinecap="round" transform="rotate(-90 60 60)" />
      <text x="60" y="66" textAnchor="middle" fontSize="22" fontWeight="700" fill="var(--text-primary)">
        {pct(value)}
      </text>
    </svg>
  );
}

/** SRL phases: each row is directly labelled, so colour is never the only identifier. */
export function PhaseBars({ rows }: { rows: { label: string; value: number; color: string }[] }) {
  return (
    <div>
      {rows.map((r) => (
        <div className="phase-row" key={r.label}>
          <span className="sw" style={{ background: r.color }} />
          <span>{r.label}</span>
          <div className="progress" aria-label={`${r.label} ${pct(r.value)}`}>
            <span style={{ width: `${Math.max(r.value * 100, 1)}%`, background: r.color }} />
          </div>
          <b style={{ textAlign: "right" }}>{pct(r.value)}</b>
        </div>
      ))}
    </div>
  );
}

interface Series { name: string; color: string; values: (number | null)[] }

/** Line chart over course weeks, 0-100%. Two series: legend + end labels + crosshair tooltip. */
export function LineChart({ labels, series }: { labels: string[]; series: Series[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 560, H = 230, m = { l: 40, r: 70, t: 12, b: 30 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const n = labels.length;
  const x = (i: number) => m.l + (n <= 1 ? iw / 2 : (i / (n - 1)) * iw);
  const y = (v: number) => m.t + (1 - v) * ih;
  if (n === 0) return <p className="empty">No answers logged yet.</p>;
  const path = (vals: (number | null)[]) => vals
    .map((v, i) => (v === null ? null : `${x(i)},${y(v)}`))
    .filter(Boolean)
    .map((p, i) => `${i === 0 ? "M" : "L"}${p}`)
    .join(" ");
  return (
    <div className="chart-wrap">
      <div className="legend" style={{ marginBottom: 6 }}>
        {series.map((s) => <span key={s.name}><i style={{ background: s.color }} />{s.name}</span>)}
      </div>
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} width={W} style={{ maxWidth: "100%", height: "auto" }}
           role="img" aria-label="Class progress by course week"
           onMouseLeave={() => setHover(null)}>
        <g className="grid">
          {[0, 0.25, 0.5, 0.75, 1].map((t) => (
            <g key={t}>
              <line x1={m.l} x2={m.l + iw} y1={y(t)} y2={y(t)} />
              <text x={m.l - 6} y={y(t) + 4} textAnchor="end">{pct(t)}</text>
            </g>
          ))}
        </g>
        {labels.map((l, i) => (
          <text key={l} x={x(i)} y={H - 10} textAnchor="middle">{l}</text>
        ))}
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={m.t} y2={m.t + ih} stroke="var(--text-muted)" strokeDasharray="3 3" />}
        {series.map((s) => (
          <g key={s.name}>
            <path d={path(s.values)} fill="none" stroke={s.color} strokeWidth={2} />
            {s.values.map((v, i) => v === null ? null : (
              <circle key={i} cx={x(i)} cy={y(v)} r={4} fill={s.color} stroke="var(--surface-1)" strokeWidth={2} />
            ))}
            {(() => {
              const last = s.values.map((v, i) => [v, i] as const).filter(([v]) => v !== null).pop();
              return last ? (
                <text x={x(last[1]) + 8} y={y(last[0] as number) + 4} style={{ fill: "var(--text-primary)" }}>
                  {pct(last[0])}
                </text>
              ) : null;
            })()}
          </g>
        ))}
        {labels.map((l, i) => (
          <rect key={`hit-${l}`} className="hit" x={x(i) - iw / Math.max(n, 1) / 2} y={m.t}
                width={iw / Math.max(n, 1)} height={ih} onMouseEnter={() => setHover(i)} />
        ))}
      </svg>
      {hover !== null && (
        <div className="tooltip" style={{ left: `${(x(hover) / W) * 100}%`, top: 24 }}>
          <b>{labels[hover]}</b>
          {series.map((s) => <div key={s.name}>{s.name}: {pct(s.values[hover])}</div>)}
        </div>
      )}
      <details>
        <summary>View as table</summary>
        <table className="data">
          <thead><tr><th>Week</th>{series.map((s) => <th key={s.name}>{s.name}</th>)}</tr></thead>
          <tbody>
            {labels.map((l, i) => (
              <tr key={l}><td>{l}</td>{series.map((s) => <td key={s.name}>{pct(s.values[i])}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}

/** Horizontal bars, value at the tip (single series). */
export function HBars({ rows }: { rows: { label: string; value: number; note?: string }[] }) {
  if (!rows.length) return <p className="empty">No data yet.</p>;
  return (
    <div>
      {rows.map((r) => (
        <div key={r.label} className="phase-row" style={{ gridTemplateColumns: "minmax(140px, 1.3fr) 1.5fr 42px" }}
             title={r.note}>
          <span>{r.label}</span>
          <div className="progress"><span style={{ width: `${Math.max(r.value * 100, 1)}%` }} /></div>
          <b style={{ textAlign: "right" }}>{pct(r.value)}</b>
        </div>
      ))}
    </div>
  );
}

/** Days with activity over the last weeks, one column per week (single hue, 5 steps). */
export function Heatmap({ days }: { days: { date: string; events: number }[] }) {
  if (!days.length) return null;
  const max = Math.max(...days.map((d) => d.events), 1);
  const level = (n: number) => (n === 0 ? 0 : Math.min(4, Math.ceil((n / max) * 4)));
  const first = new Date(`${days[0].date}T00:00:00`);
  const pad = (first.getDay() + 6) % 7; // weeks start on Monday
  const active = days.filter((d) => d.events > 0).length;
  return (
    <div>
      <div className="heatmap" role="img" aria-label={`Active on ${active} of the last ${days.length} days`}>
        {Array.from({ length: pad }, (_, i) => <span key={`pad-${i}`} style={{ visibility: "hidden" }} />)}
        {days.map((d) => (
          <span key={d.date} className={`l${level(d.events)}`}
                title={`${new Date(`${d.date}T00:00:00`).toLocaleDateString()}: ${d.events} event${d.events === 1 ? "" : "s"}`} />
        ))}
      </div>
      <div className="heatmap-legend">
        <span style={{ marginRight: "auto", width: "auto", background: "none" }}>{active} active day{active === 1 ? "" : "s"} in the last {Math.round(days.length / 7)} weeks</span>
        Less <span /><span className="l1" /><span className="l2" /><span className="l3" /><span className="l4" /> More
      </div>
    </div>
  );
}
