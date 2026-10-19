// Home: a hero with an animated product tour (a video-like player built from live HTML, so it
// is sharp, light and follows the theme) and a dashboard of the student's real numbers.
import { api, errorText, pct, timeAgo } from "../api.js";
import { h, icon, logo, plural, render, s } from "../dom.js";
import { errorLine, skeleton, toast } from "../ui.js";
import { colourOf, lineGraph } from "./progress.js";
import { subjectBadge } from "./subjects.js";

const SCENE_MS = 6000;
const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

// --- the animated tour -------------------------------------------------------------------------

const SCENES = [
  {
    label: "Ask the AI tutor",
    build: () => h("div", { class: "scene scene-chat" },
      h("div", { class: "s-bubble user" }, "What is a Python tuple?"),
      h("div", { class: "s-bot" }, h("span", { class: "s-avatar" }, logo()),
        h("div", { class: "s-answer" },
          h("div", { class: "s-line w90" }), h("div", { class: "s-line w75" }),
          h("div", { class: "s-code" }, h("span", null, "point = (3, 4)"), h("span", null, "point[0] = 5  # error")),
          h("div", { class: "s-line w60" })))),
  },
  {
    label: "Practise with instant feedback",
    build: () => h("div", { class: "scene scene-quiz" },
      h("div", { class: "s-qhead" }, h("span", { class: "s-chip" }, "Java · Collections"), h("span", { class: "s-score" }, "Question 4 of 10")),
      h("div", { class: "s-question" }, "Which collection keeps keys sorted?"),
      ["HashMap", "TreeMap", "ArrayList", "HashSet"].map((o, i) => h("div", { class: `s-opt ${i === 1 ? "pick" : ""}`, style: { "--d": `${0.25 + i * 0.15}s` } },
        h("b", null, "ABCD"[i]), h("span", null, o), i === 1 ? h("i", { class: "s-tick" }, icon("check")) : null)),
      h("div", { class: "s-feedback" }, h("b", null, "Correct! "), "TreeMap is a red-black tree ordered by key.")),
  },
  {
    label: "See your real progress",
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
    label: "Follow your roadmap",
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
  const bars = h("div", { class: "tour-bars" });
  const caption = h("div", { class: "tour-caption" });
  const playBtn = h("button", { class: "tour-play", "aria-label": "Pause" });

  function countUp(root) {
    for (const el of root.querySelectorAll(".s-count")) {
      const to = Number(el.dataset.to);
      const t0 = performance.now();
      const step = (t) => {
        const k = Math.min(1, (t - t0) / 1400);
        el.textContent = String(Math.round(to * (1 - (1 - k) ** 3)));
        if (k < 1 && el.isConnected) requestAnimationFrame(step);
      };
      if (reducedMotion()) el.textContent = String(to);
      else requestAnimationFrame(step);
    }
  }

  function paintBars() {
    render(bars, SCENES.map((sc, i) => h("button", {
      class: `tour-bar ${i < index ? "past" : i === index ? "now" : ""} ${playing ? "" : "paused"}`,
      "aria-label": `Show: ${sc.label}`, "aria-current": i === index ? "step" : null,
      onClick: () => { if (!playing) toggle(); go(i); },
    }, h("span", { style: { animationDuration: `${SCENE_MS}ms` } }))));
  }

  function show() {
    const scene = SCENES[index].build();
    render(stage, scene);
    render(caption, h("b", null, `${index + 1}/${SCENES.length}`), " ", SCENES[index].label);
    paintBars();
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
    paintBars();
  }

  playBtn.addEventListener("click", toggle);
  render(playBtn, icon(playing ? "pause" : "play"));
  const root = h("div", { class: `tour ${playing ? "" : "paused"}`, role: "region", "aria-label": "Mentora product tour" },
    h("div", { class: "tour-chrome" }, h("i"), h("i"), h("i"), h("span", null, "mentora.app"), playBtn),
    bars, stage, caption);
  show();
  schedule(SCENE_MS);
  return { el: root, stop: () => window.clearTimeout(timer) };
}

// --- dashboard -----------------------------------------------------------------------------------

function greetingWord() {
  const hour = new Date().getHours();
  return hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
}

function kpi(ic, tone, label, value, note) {
  return h("div", { class: "card kpi" },
    h("div", { class: `kpi-ico ${tone}` }, icon(ic)),
    h("div", { class: "kpi-label" }, label),
    h("div", { class: "kpi-value" }, value),
    note ? h("div", { class: "kpi-note" }, note) : null);
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
  for (const s0 of d.subjects.filter((x) => x.open_round)) {
    steps.push({ ic: "play", tone: "blue", title: `Finish your ${s0.name} round`, note: "Pick up where you left off", run: () => { window.location.hash = `#/learning?round=${s0.open_round}`; } });
  }
  const road = d.roadmaps.find((r) => r.status === "active");
  if (road) {
    steps.push({ ic: "target", tone: "purple", title: `Week ${road.progress.current_week}: ${road.current_title ?? road.goal}`, note: `${road.subject} roadmap · ${pct(road.progress.percent)} done`, run: () => { window.location.hash = `#/goals?roadmap=${road.id}`; } });
  }
  for (const q of d.quizzes.slice(0, 2)) {
    steps.push({ ic: "file", tone: "orange", title: `Quiz: ${q.title}`, note: `${q.subject} by ${q.teacher} · ${plural(q.questions, "question")}`, run: () => { window.location.hash = `#/subjects?quiz=${q.id}`; } });
  }
  const weak = d.progress.focus[0];
  if (weak) {
    const sub = d.progress.subjects.find((x) => x.name === weak.subject);
    steps.push({ ic: "alert", tone: "red", title: `Strengthen ${weak.topic}`, note: `${weak.subject} · ${pct(weak.accuracy)} right so far`, run: () => startRound(sub?.id, weak.topic) });
  }
  return steps.slice(0, 5);
}

function gettingStarted() {
  const items = [
    ["layers", "Choose a subject to practise", "Rounds of 10 questions that adapt to you", "#/learning"],
    ["target", "Set a learning goal", "Get a week-by-week roadmap", "#/goals"],
    ["bot", "Ask the AI tutor anything", "Concepts, code and exam doubts", "#/tutor"],
    ["users", "Join your teacher's class", "Enter their 10-digit class code", "#/teachers"],
  ];
  return h("section", { class: "card" },
    h("h2", null, "Get started in 4 steps"),
    h("ol", { class: "start-steps" }, items.map(([ic, title, note, href], i) => h("li", null,
      h("a", { href }, h("span", { class: "step-n" }, i + 1), h("span", { class: "step-ico" }, icon(ic)),
        h("div", null, h("b", null, title), h("span", { class: "muted small" }, note)), icon("arrow"))))));
}

export default function home(root, { me }) {
  let stopTour = () => undefined;

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
      render(dash, errorLine(errorText(e)));
    }
  }

  const first = (me.name || "there").split(" ")[0];
  const t = tour();
  stopTour = t.stop;
  const dash = h("div", { class: "stack" }, skeleton({ cards: 3, stats: true }));

  function paint(d) {
    const p = d.progress;
    const tot = p.totals;
    const road = d.roadmaps.find((r) => r.status === "active");
    const thisWeek = p.series.answered.slice(-7).reduce((a, b) => a + b, 0);
    const practised = d.subjects.filter((x) => x.answered > 0);
    const steps = nextSteps(d);
    const isNew = !tot.answered && !d.roadmaps.length && !tot.quizzes;
    render(dash,
      h("div", { class: "kpi-grid" },
        kpi("target", "blue", "Accuracy · 14 days", pct(tot.accuracy_in_range), tot.accuracy === null ? "Answer a few questions to start" : `${pct(tot.accuracy)} all time`),
        kpi("check", "green", "Answered this week", thisWeek, `${tot.answered} in total`),
        kpi("flame", "orange", "Study streak", plural(tot.streak, "day"), tot.streak ? "Keep it going today" : "Practise today to start one"),
        kpi("layers", "purple", "Roadmap", road ? pct(road.progress.percent) : "–", road ? `${road.subject} · week ${road.progress.current_week} of ${road.progress.weeks_total}` : "Set a goal to get a plan")),
      isNew ? gettingStarted() : null,
      !isNew
        ? h("div", { class: "grid cols-wide-narrow" },
            h("section", { class: "card" },
              h("div", { class: "card-head" },
                h("div", null, h("h2", null, "Your accuracy, last 14 days"), h("p", { class: "muted small" }, "Share of right answers each day across all subjects.")),
                h("a", { class: "btn small", href: "#/progress" }, "Full progress", icon("arrow"))),
              lineGraph(p.labels, [{ name: "Accuracy", color: "var(--cat-1)", values: p.series.overall, width: 2.6, area: true }],
                { height: 230, width: 640, title: "Accuracy over the last 14 days" })),
            h("section", { class: "card" },
              h("h2", null, "Up next"),
              steps.length
                ? h("ul", { class: "next-list" }, steps.map((st) => h("li", null,
                    h("button", { onClick: st.run },
                      h("span", { class: `kpi-ico ${st.tone}` }, icon(st.ic)),
                      h("div", null, h("b", null, st.title), h("span", { class: "muted small" }, st.note)),
                      icon("arrow")))))
                : h("p", { class: "empty" }, "All caught up. Start a new round in My Learning.")))
        : null,
      h("section", null,
        h("div", { class: "row", style: { marginBottom: 10 } },
          h("h2", { class: "section-title", style: { margin: 0 } }, practised.length ? "Your subjects" : "Subjects you can practise"),
          h("div", { class: "spacer" }),
          h("a", { class: "btn small", href: "#/learning" }, "All subjects", icon("arrow"))),
        h("div", { class: "home-subjects" }, (practised.length ? practised : d.subjects.slice(0, 4)).slice(0, 4).map((sb) => {
          const prog = p.subjects.find((x) => x.id === sb.id);
          return h("article", { class: "home-subject" },
            h("div", { class: "row nowrap" }, subjectBadge(sb.name),
              h("div", { style: { minWidth: 0, flex: 1 } }, h("b", null, sb.name),
                h("div", { class: "muted small" }, sb.answered ? `${sb.answered} answered · ${plural(sb.rounds, "round")}` : `${sb.questions} questions · ${sb.topics} topics`)),
              sb.answered ? h("b", { class: "home-pct" }, pct(sb.accuracy)) : null),
            sb.answered
              ? h("div", { class: "home-meter" }, h("span", { style: { width: `${Math.round((sb.accuracy ?? 0) * 100)}%`, background: colourOf(sb.name) } }))
              : null,
            prog?.weakest?.length ? h("div", { class: "muted small" }, "Focus: ", h("span", { class: "badge danger" }, prog.weakest[0])) : null,
            h("button", { class: "btn small primary", onClick: () => (sb.open_round ? (window.location.hash = `#/learning?round=${sb.open_round}`) : startRound(sb.id)) },
              icon("play"), sb.open_round ? " Continue" : " Practise 10"));
        }))),
      d.quizzes.length
        ? h("section", { class: "card" },
            h("h2", null, "Quizzes from your teachers"),
            h("ul", { class: "list" }, d.quizzes.map((q) => h("li", { class: "list-row" },
              h("span", { class: "ico" }, icon("file")),
              h("div", { class: "body" }, h("div", { class: "title" }, q.title),
                h("div", { class: "muted small" }, `${q.subject} by ${q.teacher} · ${plural(q.questions, "question")}${q.time_limit_min ? ` · ${q.time_limit_min} min` : ""}`)),
              h("a", { class: "btn small primary", href: `#/subjects?quiz=${q.id}` }, "Start")))))
        : null,
      p.activity.length
        ? h("section", { class: "card" },
            h("h2", null, "Recent activity"),
            h("ul", { class: "list" }, p.activity.slice(0, 4).map((a) => h("li", { class: "list-row" },
              h("span", { class: "ico" }, icon(a.kind === "quiz" ? "file" : "target")),
              h("div", { class: "body" }, h("div", { class: "title" }, a.title), h("div", { class: "muted small" }, timeAgo(a.at))),
              h("b", null, `${a.score}/${a.total}`)))))
        : null);
  }

  render(root, h("div", { class: "stack home" },
    h("section", { class: "home-hero" },
      h("div", { class: "hero-copy" },
        h("span", { class: "hero-kicker" }, icon("sparkle"), ` ${greetingWord()}, ${first}`),
        h("h2", null, "Learn smarter with Mentora"),
        h("p", null, "Practise any subject with questions that adapt to you, follow a week-by-week roadmap, and ask your AI tutor whenever you are stuck."),
        h("div", { class: "row hero-cta" },
          h("a", { class: "btn hero-primary", href: "#/learning" }, icon("play"), " Start practising"),
          h("a", { class: "btn hero-ghost", href: "#/tutor" }, icon("bot"), " Ask the AI tutor"),
          h("a", { class: "btn hero-ghost", href: "#/goals" }, icon("target"), " Set a goal"))),
      t.el),
    dash));
  load();
  return () => stopTour();
}
