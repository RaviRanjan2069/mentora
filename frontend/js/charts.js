// Charts as plain SVG. Hover tooltips update only the chart; every chart also has a table.
import { h, icon, s } from "./dom.js";
import { pct } from "./api.js";

export function statCard({ icon: name, tone = "", label, value, note }) {
  return h(
    "div", { class: "card stat" },
    h("div", { class: `ico ${tone}` }, icon(name)),
    h("div", null,
      h("div", { class: "label" }, label),
      h("div", { class: "value" }, value),
      note ? h("div", { class: "note" }, note) : null),
  );
}

/** One-value ring (overall SRL score). */
export function ring(value, label) {
  const r = 46;
  const c = 2 * Math.PI * r;
  return s(
    "svg", { viewBox: "0 0 120 120", width: "128", height: "128", role: "img", "aria-label": `${label}: ${pct(value)}` },
    s("circle", { cx: "60", cy: "60", r, fill: "none", stroke: "var(--surface-3)", "stroke-width": "12" }),
    s("circle", {
      cx: "60", cy: "60", r, fill: "none", stroke: "var(--series-1)", "stroke-width": "12",
      "stroke-dasharray": `${c * value} ${c}`, "stroke-linecap": "round", transform: "rotate(-90 60 60)",
    }),
    s("text", { x: "60", y: "66", "text-anchor": "middle", "font-size": "22", "font-weight": "700", fill: "var(--text-primary)" },
      pct(value)),
  );
}

/** SRL phases: each row is labelled, so colour is never the only identifier. */
export function phaseBars(rows) {
  return h("div", null, rows.map((r) => h(
    "div", { class: "phase-row" },
    h("span", { class: "sw", style: { background: r.color } }),
    h("span", null, r.label),
    h("div", { class: "progress", "aria-label": `${r.label} ${pct(r.value)}` },
      h("span", { style: { width: `${Math.max(r.value * 100, 1)}%`, background: r.color } })),
    h("b", { style: { textAlign: "right" } }, pct(r.value)),
  )));
}

export const SRL_ROWS = (srl) => [
  { label: "Forethought", value: srl.forethought, color: "var(--series-1)" },
  { label: "Performance", value: srl.performance, color: "var(--series-2)" },
  { label: "Self-reflection", value: srl.reflection, color: "var(--series-3)" },
];

function table(headers, rows) {
  return h("details", null,
    h("summary", null, "View as table"),
    h("table", { class: "data" },
      h("thead", null, h("tr", null, headers.map((x) => h("th", null, x)))),
      h("tbody", null, rows.map((r) => h("tr", null, r.map((x) => h("td", null, x)))))));
}

/** Line chart over course weeks, 0-100%: legend, end labels, crosshair tooltip. */
export function lineChart(labels, series) {
  const n = labels.length;
  if (n === 0) return h("p", { class: "empty" }, "No answers logged yet.");
  const W = 560, H = 230, m = { l: 40, r: 70, t: 12, b: 30 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const x = (i) => m.l + (n <= 1 ? iw / 2 : (i / (n - 1)) * iw);
  const y = (v) => m.t + (1 - v) * ih;
  const path = (vals) => vals
    .map((v, i) => (v === null ? null : `${x(i)},${y(v)}`))
    .filter(Boolean)
    .map((p, i) => `${i === 0 ? "M" : "L"}${p}`)
    .join(" ");
  const cross = s("line", { y1: m.t, y2: m.t + ih, stroke: "var(--text-muted)", "stroke-dasharray": "3 3", visibility: "hidden" });
  const tip = h("div", { class: "tooltip", hidden: true });
  const show = (i) => {
    cross.setAttribute("x1", x(i));
    cross.setAttribute("x2", x(i));
    cross.setAttribute("visibility", "visible");
    tip.replaceChildren(h("b", null, labels[i]), series.map((sr) => h("div", null, `${sr.name}: ${pct(sr.values[i])}`)));
    tip.style.left = `${(x(i) / W) * 100}%`;
    tip.style.top = "24px";
    tip.hidden = false;
  };
  const hide = () => {
    cross.setAttribute("visibility", "hidden");
    tip.hidden = true;
  };
  const svg = s(
    "svg", {
      class: "chart", viewBox: `0 0 ${W} ${H}`, width: W, style: "max-width:100%;height:auto",
      role: "img", "aria-label": "Class progress by course week", onMouseleave: hide,
    },
    s("g", { class: "grid" }, [0, 0.25, 0.5, 0.75, 1].map((t) => s("g", null,
      s("line", { x1: m.l, x2: m.l + iw, y1: y(t), y2: y(t) }),
      s("text", { x: m.l - 6, y: y(t) + 4, "text-anchor": "end" }, pct(t))))),
    labels.map((l, i) => s("text", { x: x(i), y: H - 10, "text-anchor": "middle" }, l)),
    cross,
    series.map((sr) => {
      const last = sr.values.map((v, i) => [v, i]).filter(([v]) => v !== null).pop();
      return s("g", null,
        s("path", { d: path(sr.values), fill: "none", stroke: sr.color, "stroke-width": "2" }),
        sr.values.map((v, i) => (v === null ? null : s("circle", {
          cx: x(i), cy: y(v), r: "4", fill: sr.color, stroke: "var(--surface-1)", "stroke-width": "2",
        }))),
        last ? s("text", { x: x(last[1]) + 8, y: y(last[0]) + 4, style: "fill:var(--text-primary)" }, pct(last[0])) : null);
    }),
    labels.map((l, i) => s("rect", {
      class: "hit", x: x(i) - iw / Math.max(n, 1) / 2, y: m.t, width: iw / Math.max(n, 1), height: ih,
      onMouseenter: () => show(i),
    })),
  );
  return h(
    "div", { class: "chart-wrap" },
    h("div", { class: "legend", style: { marginBottom: 6 } },
      series.map((sr) => h("span", null, h("i", { style: { background: sr.color } }), sr.name))),
    svg, tip,
    table(["Week", ...series.map((sr) => sr.name)], labels.map((l, i) => [l, ...series.map((sr) => pct(sr.values[i]))])),
  );
}

/** Horizontal bars, value at the tip (single series). */
export function hBars(rows) {
  if (!rows.length) return h("p", { class: "empty" }, "No data yet.");
  return h("div", null, rows.map((r) => h(
    "div", { class: "phase-row", style: { gridTemplateColumns: "minmax(140px, 1.3fr) 1.5fr 42px" }, title: r.note ?? null },
    h("span", null, r.label),
    h("div", { class: "progress" }, h("span", { style: { width: `${Math.max(r.value * 100, 1)}%` } })),
    h("b", { style: { textAlign: "right" } }, pct(r.value)),
  )));
}

/** Days with activity over the last weeks, one column per week (single hue, 5 steps). */
export function heatmap(days) {
  if (!days.length) return null;
  const max = Math.max(...days.map((d) => d.events), 1);
  const level = (n) => (n === 0 ? 0 : Math.min(4, Math.ceil((n / max) * 4)));
  const first = new Date(`${days[0].date}T00:00:00`);
  const pad = (first.getDay() + 6) % 7; // weeks start on Monday
  const active = days.filter((d) => d.events > 0).length;
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  return h(
    "div", null,
    h("div", { class: "heatmap", role: "img", "aria-label": `Active on ${active} of the last ${days.length} days` },
      Array.from({ length: pad }, () => h("span", { style: { visibility: "hidden" } })),
      days.map((d) => h("span", {
        class: `l${level(d.events)}`,
        title: `${new Date(`${d.date}T00:00:00`).toLocaleDateString()}: ${plural(d.events, "event")}`,
      }))),
    h("div", { class: "heatmap-legend" },
      h("span", { style: { marginRight: "auto", width: "auto", background: "none" } },
        `${plural(active, "active day")} in the last ${Math.round(days.length / 7)} weeks`),
      "Less ", h("span"), h("span", { class: "l1" }), h("span", { class: "l2" }), h("span", { class: "l3" }),
      h("span", { class: "l4" }), " More"),
  );
}

/** Confidence (x) vs accuracy (y); points on the dashed diagonal are well calibrated. */
export function calibrationChart(points) {
  if (!points.length) {
    return h("p", { class: "muted" }, "Rate your confidence before answering practice questions to see this chart.");
  }
  const W = 340, H = 270, m = { l: 58, r: 14, t: 12, b: 42 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const x = (v) => m.l + v * iw;
  const y = (v) => m.t + (1 - v) * ih;
  const maxN = Math.max(1, ...points.map((p) => p.n));
  const r = (n) => 4 + 5 * Math.sqrt(n / maxN);
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  const tip = h("div", { class: "tooltip", hidden: true });
  const show = (p) => {
    tip.textContent = `Sure: ${pct(p.confidence)} · Right: ${pct(p.accuracy)} · ${p.n} answer${p.n === 1 ? "" : "s"}`;
    tip.style.left = `${(x(p.confidence) / W) * 100}%`;
    tip.style.top = `${(y(p.accuracy) / H) * 100 - 14}%`;
    tip.hidden = false;
  };
  const hide = () => {
    tip.hidden = true;
  };
  const svg = s(
    "svg", {
      class: "chart", viewBox: `0 0 ${W} ${H}`, width: W, style: "max-width:100%;height:auto", role: "img",
      "aria-label": "Calibration chart: confidence against accuracy. Points on the diagonal mean your confidence matched your results.",
    },
    s("g", { class: "grid" }, ticks.map((t) => s("g", null,
      s("line", { x1: x(0), x2: x(1), y1: y(t), y2: y(t) }),
      s("text", { x: m.l - 6, y: y(t) + 4, "text-anchor": "end" }, pct(t)),
      s("text", { x: x(t), y: H - m.b + 16, "text-anchor": "middle" }, pct(t))))),
    s("line", { class: "ref", x1: x(0), y1: y(0), x2: x(1), y2: y(1) }),
    s("text", { class: "axis-title", x: x(0.98), y: y(0.98) + 16, "text-anchor": "end" }, "perfectly calibrated"),
    s("text", { class: "axis-title", x: m.l + iw / 2, y: H - 4, "text-anchor": "middle" }, "How sure you were"),
    s("text", { class: "axis-title", transform: `translate(14 ${m.t + ih / 2}) rotate(-90)`, "text-anchor": "middle" },
      "How often you were right"),
    points.map((p) => s("g", null,
      s("circle", {
        class: "hit", cx: x(p.confidence), cy: y(p.accuracy), r: r(p.n) + 8, tabindex: "0",
        "aria-label": `Confidence ${pct(p.confidence)}, accuracy ${pct(p.accuracy)}, ${p.n} answers`,
        onMouseenter: () => show(p), onMouseleave: hide, onFocus: () => show(p), onBlur: hide,
      }),
      s("circle", { class: "dot", cx: x(p.confidence), cy: y(p.accuracy), r: r(p.n), "pointer-events": "none" }))),
  );
  return h("div", { class: "chart-wrap" }, svg, tip,
    table(["How sure", "How often right", "Answers"], points.map((p) => [pct(p.confidence), pct(p.accuracy), p.n])));
}

/** One bar per concept; concepts not practised yet are drawn faint. */
export function masteryBars(rows) {
  const W = 560, rowH = 24, bar = 12, labelW = 196, valueW = 44;
  const iw = W - labelW - valueW;
  const H = rows.length * rowH + 8;
  const tip = h("div", { class: "tooltip", hidden: true });
  const svg = s(
    "svg", {
      class: "chart", viewBox: `0 0 ${W} ${H}`, width: W, style: "max-width:100%;height:auto", role: "img",
      "aria-label": "Estimated mastery for each course concept",
    },
    rows.map((r, i) => {
      const yTop = 4 + i * rowH + (rowH - bar) / 2;
      const w = Math.max(r.mastery * iw, 2);
      const rad = Math.min(4, w / 2);
      const d = `M${labelW},${yTop} h${w - rad} a${rad},${rad} 0 0 1 ${rad},${rad} `
        + `v${bar - 2 * rad} a${rad},${rad} 0 0 1 ${-rad},${rad} h${-(w - rad)} Z`;
      return s("g", {
        onMouseenter: () => {
          tip.textContent = `${r.concept}: ${pct(r.mastery)} ${r.practised ? "" : "(not practised yet, estimate is the prior)"}`;
          tip.style.left = `${(labelW / W) * 100}%`;
          tip.style.top = `${((4 + i * rowH) / H) * 100}%`;
          tip.hidden = false;
        },
        onMouseleave: () => {
          tip.hidden = true;
        },
      },
      s("rect", { class: "hit", x: "0", y: 4 + i * rowH, width: W, height: rowH }),
      s("text", { x: labelW - 8, y: yTop + bar - 2, "text-anchor": "end" }, r.concept),
      s("path", { class: `bar ${r.practised ? "" : "unpractised"}`, d }),
      s("text", { x: labelW + w + 6, y: yTop + bar - 2 }, r.practised ? pct(r.mastery) : "–"));
    }),
  );
  return h("div", { class: "chart-wrap" }, svg, tip,
    table(["Concept", "Estimated mastery", "Practised"], rows.map((r) => [r.concept, pct(r.mastery), r.practised ? "yes" : "no"])));
}
