// Home: a calm, full-width overview of the student's week, written from their real numbers,
// with a short product tour for newcomers. Editorial layout: type and rules, few boxes.
import { api, errorText, pct, timeAgo } from "../api.js";
import { h, icon, logo, plural, render, s } from "../dom.js";
import { errorLine, toast } from "../ui.js";
import { colourOf, lineGraph } from "./progress.js";

const SCENE_MS = 6500;
const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

// --- the product tour (HTML/CSS animation, follows the theme) ------------------------------------

const SCENES = [
  {
    label: "Ask the tutor",
    build: () => h("div", { class: "scene scene-chat" },
      h("div", { class: "s-bubble user" }, "What is a Python tuple?"),
      h("div", { class: "s-bot" }, h("span", { class: "s-avatar" }, logo()),
        h("div", { class: "s-answer" },
          h("div", { class: "s-line w90" }), h("div", { class: "s-line w75" }),
          h("div", { class: "s-code" }, h("span", null, "point = (3, 4)"), h("span", null, "point[0] = 5  # error")),
          h("div", { class: "s-line w60" })))),
  },
  {
    label: "Practise",
    build: () => h("div", { class: "scene scene-quiz" },
      h("div", { class: "s-qhead" }, h("span", { class: "s-chip" }, "Java · Collections"), h("span", { class: "s-score" }, "4 of 10")),
      h("div", { class: "s-question" }, "Which collection keeps keys sorted?"),
      ["HashMap", "TreeMap", "ArrayList", "HashSet"].map((o, i) => h("div", { class: `s-opt ${i === 1 ? "pick" : ""}`, style: { "--d": `${0.25 + i * 0.15}s` } },
        h("b", null, "ABCD"[i]), h("span", null, o), i === 1 ? h("i", { class: "s-tick" }, icon("check")) : null)),
      h("div", { class: "s-feedback" }, h("b", null, "Correct. "), "TreeMap is ordered by key.")),
  },
  {
    label: "Track progress",
    build: () => h("div", { class: "scene scene-chart" },
      h("div", { class: "s-kpis" },
        h("div", null, h("small", null, "Accuracy"), h("b", { class: "s-count", "data-to": "82" }, "0"), "%"),
        h("div", null, h("small", null, "Answered"), h("b", { class: "s-count", "data-to": "240" }, "0")),
        h("div", null, h("small", null, "Streak"), h("b", { class: "s-count", "data-to": "6" }, "0"), " days")),
      s("svg", { class: "s-graph", viewBox: "0 0 320 120", "aria-hidden": "true" },
        [30, 60, 90].map((y) => s("line", { x1: 0, x2: 320, y1: y, y2: y, class: "s-grid" })),
        s("path", { class: "s-area", d: "M0,100 L40,92 L80,95 L120,70 L160,74 L200,52 L240,46 L280,30 L320,24 L320,120 L0,120 Z" }),
        s("path", { class: "s-path", d: "M0,100 L40,92 L80,95 L120,70 L160,74 L200,52 L240,46 L280,30 L320,24" }),
        s("circle", { class: "s-dot", cx: 320, cy: 24, r: 5 }))),
  },
  {
    label: "Follow a plan",
    build: () => h("div", { class: "scene scene-road" },
      h("div", { class: "s-roadhead" }, h("b", null, "Learn Java from basic to advanced"), h("span", { class: "s-pct" }, h("span", { class: "s-count", "data-to": "38" }, "0"), "%")),
      h("div", { class: "s-bar" }, h("span", null)),
      ["Java fundamentals", "Control statements", "Arrays and strings", "Classes and objects", "Inheritance"].map((w, i) => h("div", {
        class: `s-week ${i < 3 ? "done" : i === 3 ? "now" : ""}`, style: { "--d": `${0.3 + i * 0.35}s` },
      }, h("span", { class: "s-wk" }, i < 3 ? icon("check") : `W${i + 1}`), h("span", null, w), i === 3 ? h("em", null, "This week") : null))),
  },
];

function tour() {
  let index = 0;
  let playing = !reducedMotion();
  let timer = 0;
  let started = 0;
  let remaining = SCENE_MS;
  const stage = h("div", { class: "tour-stage" });
  const tabs = h("div", { class: "tour-tabs", role: "tablist" });
  const playBtn = h("button", { class: "tour-play", "aria-label": "Pause" });

  function countUp(root) {
    for (const el of root.querySelectorAll(".s-count")) {
      const to = Number(el.dataset.to);
      if (reducedMotion()) {
        el.textContent = String(to);
        continue;
      }
      const t0 = performance.now();
      const step = (t) => {
        const k = Math.min(1, (t - t0) / 1400);
        el.textContent = String(Math.round(to * (1 - (1 - k) ** 3)));
        if (k < 1 && el.isConnected) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    }
  }

  function paintTabs() {
    render(tabs, SCENES.map((sc, i) => h("button", {
      role: "tab", class: `tour-tab ${i < index ? "past" : i === index ? "now" : ""} ${playing ? "" : "paused"}`,
      "aria-selected": String(i === index), onClick: () => { if (!playing) toggle(); go(i); },
    }, h("span", { class: "tour-tab-label" }, `${String(i + 1).padStart(2, "0")} ${sc.label}`),
    h("span", { class: "tour-tab-bar" }, h("i", { style: { animationDuration: `${SCENE_MS}ms` } })))));
  }

  function show() {
    const scene = SCENES[index].build();
    render(stage, scene);
    paintTabs();
    countUp(scene);
  }

  function schedule(ms) {
    window.clearTimeout(timer);
    started = Date.now();
    remaining = ms;
    if (playing) timer = window.setTimeout(() => go((index + 1) % SCENES.length), ms);
  }

  function go(i) {
    index = i;
    show();
    schedule(SCENE_MS);
  }

  function toggle() {
    playing = !playing;
    if (playing) schedule(remaining);
    else {
      window.clearTimeout(timer);
      remaining = Math.max(500, remaining - (Date.now() - started));
    }
    playBtn.setAttribute("aria-label", playing ? "Pause" : "Play");
    render(playBtn, icon(playing ? "pause" : "play"));
    root.classList.toggle("paused", !playing);
    paintTabs();
  }

  playBtn.addEventListener("click", toggle);
  render(playBtn, icon(playing ? "pause" : "play"));
  const root = h("div", { class: `tour ${playing ? "" : "paused"}`, role: "region", "aria-label": "How Mentora works" },
    h("div", { class: "tour-top" }, tabs, playBtn),
    stage);
  show();
  schedule(SCENE_MS);
  return { el: root, stop: () => window.clearTimeout(timer) };
}

// --- helpers --------------------------------------------------------------------------------------

function greetingWord() {
  const hour = new Date().getHours();
  return hour < 5 ? "Good evening" : hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
}

function today() {
  const d = new Date();
  return `${DAYS[d.getDay()]}, ${d.getDate()} ${MONTHS[d.getMonth()]}`;
}

/** This week vs the week before, from the 14 daily buckets. */
function weeks(p) {
  const n = p.series.answered.length;
  const sum = (from, to) => {
    let answered = 0;
    let right = 0;
    for (let i = Math.max(0, from); i < to; i += 1) {
      const a = p.series.answered[i] ?? 0;
      answered += a;
      right += Math.round((p.series.overall[i] ?? 0) * a);
    }
    return { answered, acc: answered ? right / answered : null };
  };
  return { now: sum(n - 7, n), before: sum(n - 14, n - 7) };
}

function change(nowV, beforeV, unit) {
  if (nowV === null || beforeV === null || beforeV === undefined) return null;
  const diff = unit === "%" ? Math.round((nowV - beforeV) * 100) : nowV - beforeV;
  if (diff === 0) return h("span", { class: "chg flat" }, "same as last week");
  return h("span", { class: `chg ${diff > 0 ? "up" : "down"}` }, `${diff > 0 ? "+" : "−"}${Math.abs(diff)}${unit === "%" ? " pts" : ""} vs last week`);
}

function summary(d, w) {
  const tot = d.progress.totals;
  if (!tot.answered) return "You have not practised yet. Pick a subject below and answer your first 10 questions; this page fills in as you go.";
  const parts = [];
  if (w.now.answered) {
    parts.push(`This week you answered ${plural(w.now.answered, "question")}`);
    if (w.now.acc !== null) parts[0] += ` and got ${pct(w.now.acc)} right`;
    if (w.before.answered) parts[0] += w.now.answered >= w.before.answered ? `, more than the ${w.before.answered} the week before` : `, fewer than the ${w.before.answered} the week before`;
    parts[0] += ".";
  } else {
    parts.push("You have not practised this week yet.");
  }
  const best = [...d.progress.subjects].sort((a, b) => (b.accuracy ?? 0) - (a.accuracy ?? 0))[0];
  if (best) parts.push(`${best.name} is your strongest subject at ${pct(best.accuracy)}.`);
  const weak = d.progress.focus[0];
  if (weak) parts.push(`${weak.topic} (${weak.subject}) needs the most work.`);
  return parts.join(" ");
}

async function startRound(subjectId, topics) {
  try {
    const q = topics ? `?topics=${encodeURIComponent(topics)}` : "";
    const r = await api.post(`/api/learning/subjects/${subjectId}/rounds${q}`);
    window.location.hash = `#/learning?round=${r.id}`;
  } catch (e) {
    toast(errorText(e), "error");
  }
}

function nextSteps(d) {
  const steps = [];
  for (const sb of d.subjects.filter((x) => x.open_round)) {
    steps.push({ title: `Finish your ${sb.name} round`, note: "You left it part-way", href: `#/learning?round=${sb.open_round}` });
  }
  const road = d.roadmaps.find((r) => r.status === "active");
  if (road) steps.push({ title: `Week ${road.progress.current_week} of your ${road.subject} plan`, note: road.current_title ?? road.goal, href: `#/goals?roadmap=${road.id}` });
  for (const q of d.quizzes.slice(0, 2)) steps.push({ title: `Take “${q.title}”`, note: `${q.subject} · ${q.teacher}`, href: `#/subjects?quiz=${q.id}` });
  const weak = d.progress.focus[0];
  if (weak) {
    const sb = d.progress.subjects.find((x) => x.name === weak.subject);
    steps.push({ title: `Practise ${weak.topic}`, note: `${weak.subject} · ${pct(weak.accuracy)} right so far`, run: () => startRound(sb?.id, weak.topic) });
  }
  if (!road) steps.push({ title: "Set a learning goal", note: "Get a week-by-week plan", href: "#/goals" });
  return steps.slice(0, 5);
}

// --- the page ------------------------------------------------------------------------------------

export default function home(root, { me }) {
  const first = (me.name || "there").split(" ")[0];
  const t = tour();
  const body = h("div", { class: "home-body" }, h("p", { class: "muted" }, "Loading your week…"));

  async function load() {
    try {
      const [progress, subjects, roadmaps, quizzes] = await Promise.all([
        api.get(`/api/progress/overview?days=14&tz=${-new Date().getTimezoneOffset()}`),
        api.get("/api/learning/subjects"),
        api.get("/api/roadmaps").catch(() => []),
        api.get("/api/me/quizzes/pending").catch(() => []),
      ]);
      for (const sr of progress.series.subjects) colourOf(sr.name);
      paint({ progress, subjects, roadmaps, quizzes });
    } catch (e) {
      render(body, errorLine(errorText(e)));
    }
  }

  function paint(d) {
    const p = d.progress;
    const tot = p.totals;
    const w = weeks(p);
    const road = d.roadmaps.find((r) => r.status === "active");
    const steps = nextSteps(d);
    const rows = d.subjects.filter((x) => x.answered > 0);
    const others = d.subjects.filter((x) => !x.answered);
    render(summaryEl, summary(d, w));
    render(body,
      h("section", { class: "home-band" },
        h("div", { class: "home-week" },
          h("h3", { class: "eyebrow" }, "This week"),
          h("div", { class: "figures" },
            h("div", { class: "figure" }, h("span", { class: "fig-label" }, "Accuracy"), h("span", { class: "fig-value" }, pct(w.now.acc)), change(w.now.acc, w.before.acc, "%")),
            h("div", { class: "figure" }, h("span", { class: "fig-label" }, "Questions"), h("span", { class: "fig-value" }, w.now.answered), change(w.now.answered, w.before.answered, "")),
            h("div", { class: "figure" }, h("span", { class: "fig-label" }, "Streak"), h("span", { class: "fig-value" }, tot.streak, h("small", null, tot.streak === 1 ? " day" : " days")), h("span", { class: "chg flat" }, `${tot.study_days} study days in all`)),
            h("div", { class: "figure" }, h("span", { class: "fig-label" }, "Plan"), h("span", { class: "fig-value" }, road ? pct(road.progress.percent) : "—"),
              h("span", { class: "chg flat" }, road ? `${road.subject}, week ${road.progress.current_week} of ${road.progress.weeks_total}` : h("a", { href: "#/goals" }, "Set a goal")))),
          tot.answered
            ? h("div", { class: "home-chart" },
                h("div", { class: "chart-cap" }, h("span", null, "Daily accuracy, last 14 days"), h("a", { href: "#/progress" }, "All progress →")),
                lineGraph(p.labels, [{ name: "Accuracy", color: "var(--cat-1)", values: p.series.overall, width: 2.4, area: true }],
                  { height: 210, width: 760, title: "Daily accuracy over the last 14 days" }))
            : null),
        h("aside", { class: "home-next" },
          h("h3", { class: "eyebrow" }, "Up next"),
          steps.length
            ? h("ol", { class: "next-steps" }, steps.map((st) => h("li", null,
                st.href
                  ? h("a", { href: st.href }, h("b", null, st.title), h("span", null, st.note))
                  : h("button", { onClick: st.run }, h("b", null, st.title), h("span", null, st.note)))))
            : h("p", { class: "muted" }, "Nothing waiting. Start a round whenever you like."))),
      h("section", { class: "home-section" },
        h("div", { class: "section-head" }, h("h3", { class: "eyebrow" }, "Subjects"), h("a", { href: "#/learning" }, "Open My Learning →")),
        rows.length
          ? h("table", { class: "home-table" },
              h("thead", null, h("tr", null, ["Subject", "Accuracy", "", "Answered", "Last 7 days", "Focus on", ""].map((x) => h("th", null, x)))),
              h("tbody", null, rows.map((sb) => {
                const prog = p.subjects.find((x) => x.id === sb.id);
                return h("tr", null,
                  h("td", null, h("span", { class: "dot", style: { background: colourOf(sb.name) } }), h("b", null, sb.name)),
                  h("td", { class: "num" }, pct(sb.accuracy)),
                  h("td", { class: "barcell" }, h("span", { class: "thin-bar" }, h("i", { style: { width: `${Math.round((sb.accuracy ?? 0) * 100)}%`, background: colourOf(sb.name) } }))),
                  h("td", { class: "num" }, sb.answered),
                  h("td", null, prog?.change === null || prog?.change === undefined ? h("span", { class: "muted" }, "—")
                    : h("span", { class: `chg ${prog.change >= 0 ? "up" : "down"}` }, `${prog.change >= 0 ? "+" : "−"}${Math.abs(Math.round(prog.change * 100))} pts`)),
                  h("td", { class: "muted" }, prog?.weakest?.[0] ?? "—"),
                  h("td", { class: "act" }, h("button", { class: "text-btn", onClick: () => (sb.open_round ? (window.location.hash = `#/learning?round=${sb.open_round}`) : startRound(sb.id)) },
                    sb.open_round ? "Continue" : "Practise")));
              })))
          : null,
        others.length
          ? h("p", { class: "muted more-subjects" }, rows.length ? "Not started yet: " : "Pick a subject to begin: ",
              others.map((sb, i) => [i ? ", " : "", h("button", { class: "text-btn", onClick: () => startRound(sb.id) }, sb.name)]))
          : null),
      h("section", { class: "home-band lower" },
        h("div", { class: "home-tour" },
          h("div", { class: "section-head" }, h("h3", { class: "eyebrow" }, "How Mentora works"), h("span", { class: "muted small" }, "A one-minute tour")),
          t.el),
        h("div", { class: "home-side" },
          d.quizzes.length
            ? h("div", null, h("h3", { class: "eyebrow" }, "From your teachers"),
                h("ul", { class: "plain-list" }, d.quizzes.map((q) => h("li", null,
                  h("a", { href: `#/subjects?quiz=${q.id}` }, q.title),
                  h("span", { class: "muted small" }, `${q.subject} · ${q.teacher} · ${plural(q.questions, "question")}`)))))
            : null,
          h("div", null, h("h3", { class: "eyebrow" }, "Recent"),
            p.activity.length
              ? h("ul", { class: "plain-list" }, p.activity.slice(0, 5).map((a) => h("li", null,
                  h("span", null, a.title, h("b", { class: "score" }, ` ${a.score}/${a.total}`)),
                  h("span", { class: "muted small" }, timeAgo(a.at)))))
              : h("p", { class: "muted" }, "Your rounds and quizzes will appear here.")))));
  }

  const summaryEl = h("p", { class: "home-summary" }, " ");
  render(root, h("div", { class: "home" },
    h("header", { class: "home-head" },
      h("div", { class: "home-date" }, today()),
      h("h2", { class: "home-greeting" }, `${greetingWord()}, ${first}.`),
      summaryEl,
      h("div", { class: "home-actions" },
        h("a", { class: "btn primary", href: "#/learning" }, "Practise"),
        h("a", { class: "btn", href: "#/tutor" }, "Ask the tutor"),
        h("a", { class: "btn", href: "#/goals" }, "Goals & plans"))),
    body));
  load();
  return () => t.stop();
}
