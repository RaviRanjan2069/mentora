// Progress: real performance across all subjects (My Learning answers, Subjects quizzes,
// roadmaps), with line graphs over time.
import { api, errorText, pct, timeAgo } from "../api.js";
import { h, icon, plural, render, s } from "../dom.js";
import { errorLine, skeleton } from "../ui.js";
import { subjectBadge } from "./subjects.js";

const RANGES = [[7, "7 days"], [30, "30 days"], [90, "90 days"], [0, "All time"]];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const dayLabel = (iso) => {
  const [, mo, d] = iso.split("-").map(Number);
  return `${d} ${MONTHS[mo - 1]}`;
};
// distinct colours per subject (the overall line uses the brand blue)
const PALETTE = ["#e07a2d", "#16a34a", "#9333ea", "#0891b2", "#db2777", "#ca8a04", "#4f46e5", "#dc2626"];
const colours = new Map();
const colourOf = (name) => {
  if (!colours.has(name)) colours.set(name, PALETTE[colours.size % PALETTE.length]);
  return colours.get(name);
};
function lastSeen(iso) {
  const days = Math.round((new Date().setHours(0, 0, 0, 0) - new Date(`${iso}T00:00:00`).getTime()) / 86400000);
  return days <= 0 ? "today" : days === 1 ? "yesterday" : `${days} days ago`;
}
const STORE = "mentora-progress-range";

function savedRange() {
  try {
    const raw = window.localStorage.getItem(STORE);
    const v = raw === null ? NaN : Number(raw);
    return RANGES.some(([d]) => d === v) ? v : 30;
  } catch {
    return 30;
  }
}

/** A responsive line chart: several series, gaps for missing values, crosshair tooltip,
 * and a table for screen readers. series: [{name, color, values, width?, dash?, area?}] */
function lineGraph(labels, series, { percent = true, height = 260, width = 920, title = "Chart", xName = "Day" } = {}) {
  const n = labels.length;
  if (!n || !series.some((sr) => sr.values.some((v) => v !== null && v !== undefined))) {
    return h("p", { class: "empty" }, "No answers in this period yet.");
  }
  const W = width, H = height, m = { l: 46, r: 16, t: 14, b: 30 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const max = percent ? 1 : Math.max(1, ...series.flatMap((sr) => sr.values.filter((v) => v !== null)));
  const niceMax = percent ? 1 : Math.ceil(max / 5) * 5 || 5;
  const x = (i) => m.l + (n <= 1 ? iw / 2 : (i / (n - 1)) * iw);
  const y = (v) => m.t + (1 - v / niceMax) * ih;
  const fmt = (v) => (v === null || v === undefined ? "–" : percent ? pct(v) : String(v));
  const pts = (vals) => vals.map((v, i) => (v === null || v === undefined ? null : [x(i), y(v)])).filter(Boolean);
  const pathOf = (vals) => pts(vals).map(([px, py], i) => `${i ? "L" : "M"}${px.toFixed(1)},${py.toFixed(1)}`).join(" ");
  const ticks = Math.min(n, 7);
  const tickIdx = [...new Set(Array.from({ length: ticks }, (_, k) => Math.round((k * (n - 1)) / Math.max(1, ticks - 1))))];
  const yTicks = percent ? [0, 0.25, 0.5, 0.75, 1] : [0, niceMax / 2, niceMax].map((v) => Math.round(v));

  const cross = s("line", { y1: m.t, y2: m.t + ih, class: "lg-cross", visibility: "hidden" });
  const dots = s("g", { visibility: "hidden" });
  const tip = h("div", { class: "lg-tip", hidden: true });
  const show = (i) => {
    cross.setAttribute("x1", x(i));
    cross.setAttribute("x2", x(i));
    cross.setAttribute("visibility", "visible");
    dots.replaceChildren(...series.filter((sr) => sr.values[i] !== null && sr.values[i] !== undefined)
      .map((sr) => s("circle", { cx: x(i), cy: y(sr.values[i]), r: 4.5, fill: sr.color, stroke: "var(--surface-1)", "stroke-width": 2 })));
    dots.setAttribute("visibility", "visible");
    tip.replaceChildren(h("b", null, dayLabel(labels[i])),
      ...series.map((sr) => h("div", { class: "lg-tip-row" }, h("i", { style: { background: sr.color } }), h("span", null, sr.name), h("b", null, fmt(sr.values[i])))));
    tip.style.left = `${(x(i) / W) * 100}%`;
    tip.classList.toggle("left", x(i) > W * 0.6);
    tip.hidden = false;
  };
  const hide = () => {
    cross.setAttribute("visibility", "hidden");
    dots.setAttribute("visibility", "hidden");
    tip.hidden = true;
  };
  const gradId = `lg${Math.random().toString(36).slice(2, 8)}`;
  const svg = s("svg", {
    class: "lg", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": title, onMouseleave: hide,
  },
  s("defs", null, series.filter((sr) => sr.area).map((sr) => s("linearGradient", { id: `${gradId}-${sr.name.replace(/\W/g, "")}`, x1: 0, x2: 0, y1: 0, y2: 1 },
    s("stop", { offset: "0%", "stop-color": sr.color, "stop-opacity": 0.28 }),
    s("stop", { offset: "100%", "stop-color": sr.color, "stop-opacity": 0 })))),
  s("g", { class: "lg-grid" }, yTicks.map((t) => s("g", null,
    s("line", { x1: m.l, x2: m.l + iw, y1: y(t), y2: y(t) }),
    s("text", { x: m.l - 8, y: y(t) + 4, "text-anchor": "end" }, percent ? `${Math.round(t * 100)}%` : t)))),
  s("g", { class: "lg-x" }, tickIdx.map((i) => s("text", { x: x(i), y: H - 8, "text-anchor": i === 0 ? "start" : i === n - 1 ? "end" : "middle" }, dayLabel(labels[i])))),
  series.filter((sr) => sr.area).map((sr) => {
    const p = pts(sr.values);
    if (p.length < 2) return null;
    const d = `${pathOf(sr.values)} L${p[p.length - 1][0].toFixed(1)},${m.t + ih} L${p[0][0].toFixed(1)},${m.t + ih} Z`;
    return s("path", { d, fill: `url(#${gradId}-${sr.name.replace(/\W/g, "")})`, stroke: "none" });
  }),
  series.map((sr) => s("path", {
    d: pathOf(sr.values), fill: "none", stroke: sr.color, "stroke-width": sr.width ?? 2.2,
    "stroke-dasharray": sr.dash ?? null, "stroke-linejoin": "round", "stroke-linecap": "round", "vector-effect": "non-scaling-stroke",
  })),
  n <= 31 ? series.filter((sr) => !sr.dash).map((sr) => pts(sr.values).map(([px, py]) => s("circle", {
    cx: px, cy: py, r: 2.6, fill: sr.color, "vector-effect": "non-scaling-stroke",
  }))) : null,
  cross, dots,
  labels.map((_, i) => s("rect", {
    x: x(i) - iw / Math.max(n - 1, 1) / 2, y: m.t, width: iw / Math.max(n - 1, 1), height: ih, fill: "transparent", onMouseenter: () => show(i),
  })));
  return h("div", { class: "lg-wrap" },
    h("div", { class: "lg-legend" }, series.map((sr) => h("span", null, h("i", { class: sr.dash ? "dash" : "", style: { background: sr.color, borderColor: sr.color } }), sr.name))),
    h("div", { class: "lg-box" }, svg, tip),
    h("details", { class: "lg-table" }, h("summary", null, "View as table"),
      h("div", { class: "overflow" }, h("table", { class: "data" },
        h("thead", null, h("tr", null, h("th", null, xName), series.map((sr) => h("th", null, sr.name)))),
        h("tbody", null, labels.map((l, i) => h("tr", null, h("td", null, dayLabel(l)), series.map((sr) => h("td", null, fmt(sr.values[i]))))))))));
}

function spark(values, color) {
  const pts = values.map((v, i) => [i, v]).filter(([, v]) => v !== null && v !== undefined);
  if (pts.length < 2) return h("span", { class: "muted small" }, pts.length ? pct(pts[0][1]) : "–");
  const W = 96, H = 28, n = values.length - 1 || 1;
  const d = pts.map(([i, v], k) => `${k ? "L" : "M"}${((i / n) * W).toFixed(1)},${(H - 3 - v * (H - 6)).toFixed(1)}`).join(" ");
  return s("svg", { class: "spark", viewBox: `0 0 ${W} ${H}`, width: W, height: H, "aria-hidden": "true" },
    s("path", { d, fill: "none", stroke: color, "stroke-width": 1.8, "stroke-linecap": "round", "stroke-linejoin": "round" }));
}

function kpi(ic, tone, label, value, note) {
  return h("div", { class: "card kpi" },
    h("div", { class: `kpi-ico ${tone}` }, icon(ic)),
    h("div", { class: "kpi-label" }, label),
    h("div", { class: "kpi-value" }, value),
    note ? h("div", { class: "kpi-note" }, note) : null);
}

function meter(v) {
  const tone = v === null ? "" : v >= 0.75 ? "good" : v >= 0.5 ? "mid" : "low";
  return h("div", { class: `meter ${tone}` }, h("span", { style: { width: `${Math.round((v ?? 0) * 100)}%` } }));
}

async function practiseTopic(subjectId, topic) {
  const rnd = await api.post(`/api/learning/subjects/${subjectId}/rounds?topics=${encodeURIComponent(topic)}`);
  window.location.hash = `#/learning?round=${rnd.id}`;
}

export default function progress(root) {
  const st = { days: savedRange(), mode: "daily", hidden: new Set(), data: null };

  async function load() {
    try {
      const data = await api.get(`/api/progress/overview?days=${st.days}&tz=${-new Date().getTimezoneOffset()}`);
      for (const sr of data.series.subjects) colourOf(sr.name);  // fixed colour order: alphabetical
      st.data = data;
      paint();
    } catch (e) {
      render(root, errorLine(errorText(e)));
    }
  }

  const setRange = (d) => {
    st.days = d;
    try {
      window.localStorage.setItem(STORE, String(d));
    } catch {
      /* only a convenience */
    }
    load();
  };

  function header(d) {
    return h("div", { class: "prog-head" },
      h("div", null,
        h("h2", null, "Your performance"),
        h("p", { class: "muted small" }, `Based on ${plural(d.totals.answered, "answer")} in My Learning${d.totals.quizzes ? ` and ${plural(d.totals.quizzes, "quiz")}`.replace("quizs", "quizzes") : ""}.`)),
      h("div", { class: "seg range-seg", role: "tablist", "aria-label": "Period" }, RANGES.map(([v, l]) => h("button", {
        role: "tab", class: st.days === v ? "active" : "", "aria-selected": String(st.days === v), onClick: () => setRange(v),
      }, l))));
  }

  function empty() {
    return h("section", { class: "card prog-empty" },
      h("div", { class: "prog-empty-ico" }, icon("trend")),
      h("h2", null, "Your progress starts with your first answers"),
      h("p", { class: "muted" }, "Practise any subject in My Learning. Every answer shows up here: your accuracy over time, each subject and topic, and what to focus on next."),
      h("a", { class: "btn primary", href: "#/learning" }, icon("play"), " Start practising"));
  }

  function paint() {
    const d = st.data;
    if (!d.totals.answered && !d.totals.quizzes) {
      render(root, h("div", { class: "stack" }, header(d), empty()));
      return;
    }
    const t = d.totals;
    const unit = d.granularity === "week" ? "week" : "day";
    const subjects = d.series.subjects.filter((sr) => !st.hidden.has(sr.id));
    const accSeries = [
      st.mode === "daily"
        ? { name: "All subjects", color: "var(--brand)", values: d.series.overall, width: 3, area: true }
        : { name: "Running average", color: "var(--brand)", values: d.series.running, width: 3, area: true },
      ...subjects.map((sr) => ({ name: sr.name, color: colourOf(sr.name), values: sr.values, width: 1.8, dash: "5 4" })),
    ];
    render(root, h("div", { class: "stack prog" },
      header(d),
      h("div", { class: "kpi-grid" },
        kpi("target", "blue", "Accuracy", pct(t.accuracy_in_range ?? t.accuracy), `${pct(t.accuracy)} all time`),
        kpi("check", "green", "Questions answered", t.answered_in_range, `${t.answered} all time · ${plural(t.rounds, "round")}`),
        kpi("flame", "orange", "Study streak", plural(t.streak, "day"), `${plural(t.study_days, "study day")} in total`),
        kpi("file", "purple", "Quiz average", t.quiz_average === null ? "–" : pct(t.quiz_average), t.quizzes ? `${plural(t.quizzes, "quiz").replace("quizs", "quizzes")} taken` : "Quizzes from your teachers' folders")),
      h("section", { class: "card" },
        h("div", { class: "card-head" },
          h("div", null, h("h2", null, "Accuracy over time"),
            h("p", { class: "muted small" }, st.mode === "daily" ? `Share of right answers each ${unit}, all subjects together and per subject.` : "Your overall accuracy so far at the end of each " + unit + ".")),
          h("div", { class: "seg range-seg" }, [["daily", `Per ${unit}`], ["running", "Running average"]].map(([k, l]) => h("button", {
            class: st.mode === k ? "active" : "", onClick: () => { st.mode = k; paint(); },
          }, l)))),
        d.series.subjects.length > 1
          ? h("div", { class: "row subj-toggles" }, d.series.subjects.map((sr) => h("button", {
              class: `subj-toggle ${st.hidden.has(sr.id) ? "off" : ""}`, style: { "--c": colourOf(sr.name) }, "aria-pressed": String(!st.hidden.has(sr.id)),
              onClick: () => { if (st.hidden.has(sr.id)) st.hidden.delete(sr.id); else st.hidden.add(sr.id); paint(); },
            }, h("i", null), sr.name)))
          : null,
        lineGraph(d.labels, accSeries, { title: "Accuracy over time", xName: unit === "week" ? "Week of" : "Day" })),
      h("div", { class: "grid cols-wide-narrow" },
        h("section", { class: "card" },
          h("h2", null, "Questions answered"),
          h("p", { class: "muted small", style: { marginTop: -6 } }, `How much you practised each ${unit}.`),
          lineGraph(d.labels, [{ name: "Answers", color: "var(--series-3)", values: d.series.answered, width: 2.4, area: true }],
            { percent: false, height: 260, width: 560, title: "Questions answered over time", xName: unit === "week" ? "Week of" : "Day" })),
        h("section", { class: "card" },
          h("h2", null, "Focus next"),
          d.focus.length
            ? h("ul", { class: "focus-list" }, d.focus.map((f) => h("li", null,
                h("div", null, h("b", null, f.topic), h("div", { class: "muted small" }, `${f.subject} · ${plural(f.answered, "answer")}`)),
                h("span", { class: "focus-pct low-text" }, pct(f.accuracy)),
                h("button", {
                  class: "btn small", onClick: () => practiseTopic(d.subjects.find((x) => x.name === f.subject)?.id, f.topic),
                }, "Practise"))))
            : h("p", { class: "empty" }, "Answer at least 3 questions on a topic to see where to focus."))),
      d.subjects.length
        ? h("section", { class: "card" },
            h("h2", null, "Subjects"),
            h("div", { class: "overflow" }, h("table", { class: "subj-table" },
              h("thead", null, h("tr", null, ["Subject", "Accuracy", "Trend", "Answered", "Change (7 days)", "Strongest", "Needs work", ""].map((x) => h("th", null, x)))),
              h("tbody", null, d.subjects.map((sb) => h("tr", null,
                h("td", null, h("div", { class: "row nowrap" }, subjectBadge(sb.name), h("div", null, h("b", null, sb.name), h("div", { class: "muted small" }, `last practised ${lastSeen(sb.last_practised)}`)))),
                h("td", null, h("div", { class: "acc-cell" }, h("b", null, pct(sb.accuracy)), meter(sb.accuracy))),
                h("td", null, spark(sb.spark, colourOf(sb.name))),
                h("td", null, `${sb.answered}`, h("div", { class: "muted small" }, plural(sb.rounds, "round"))),
                h("td", null, sb.change === null ? h("span", { class: "muted small" }, "–")
                  : h("span", { class: sb.change >= 0 ? "delta-up" : "delta-down" }, `${sb.change >= 0 ? "▲" : "▼"} ${Math.abs(Math.round(sb.change * 100))} pts`)),
                h("td", null, sb.strongest.length ? sb.strongest.slice(0, 2).map((x) => h("span", { class: "badge ok" }, x)) : h("span", { class: "muted small" }, "–")),
                h("td", null, sb.weakest.length ? sb.weakest.slice(0, 2).map((x) => h("span", { class: "badge danger" }, x)) : h("span", { class: "muted small" }, "–")),
                h("td", null, h("a", { class: "btn small", href: `#/learning?subject=${sb.id}` }, "Details"))))))))
        : null,
      h("div", { class: "grid cols-2" },
        h("section", { class: "card" },
          h("h2", null, "Strongest topics"),
          d.strong.length
            ? h("ul", { class: "topic-list" }, d.strong.map((x) => h("li", null,
                h("span", { class: "topic-name" }, x.topic, h("span", { class: "muted small" }, ` · ${x.subject}`)),
                meter(x.accuracy), h("span", { class: "topic-val" }, pct(x.accuracy)))))
            : h("p", { class: "empty" }, "Keep practising to find your strengths.")),
        h("section", { class: "card" },
          h("h2", null, "Recent activity"),
          d.activity.length
            ? h("ul", { class: "list" }, d.activity.map((a) => {
                const p = a.total ? a.score / a.total : null;
                return h("li", { class: "list-row" },
                  h("span", { class: `ico ${p === null ? "" : p >= 0.75 ? "green" : p >= 0.5 ? "orange" : "red"}` }, icon(a.kind === "quiz" ? "file" : "target")),
                  h("div", { class: "body" }, h("div", { class: "title" }, a.title), h("div", { class: "muted small" }, timeAgo(a.at))),
                  h("b", null, `${a.score}/${a.total}`),
                  h("a", { class: "btn small", href: a.kind === "quiz" ? `#/subjects?attempt=${a.id}` : `#/learning?round=${a.id}` }, "Review"));
              }))
            : h("p", { class: "empty" }, "Nothing yet."))),
      d.roadmaps.length
        ? h("section", { class: "card" },
            h("h2", null, "Roadmaps"),
            h("ul", { class: "roadmap-progress" }, d.roadmaps.map((r) => h("li", null,
              h("a", { href: `#/goals?roadmap=${r.id}` }, h("b", null, r.goal)),
              h("span", { class: "muted small" }, r.status === "completed" ? "Completed" : `${r.subject} · week ${r.week} of ${r.weeks}`),
              h("div", { class: "progress" }, h("span", { style: { width: `${r.percent * 100}%` } })),
              h("b", null, pct(r.percent))))))
        : null));
  }

  render(root, skeleton({ cards: 3, stats: true }));
  load();
}
