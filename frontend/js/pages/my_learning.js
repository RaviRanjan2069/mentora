// My Learning: practise any subject in rounds of 10 questions that adapt to your weak topics,
// and follow your progress per subject and topic. Views: overview, ?subject=, ?round=.
import { api, errorText, pct, timeAgo } from "../api.js";
import { hBars, lineChart, statCard } from "../charts.js";
import { h, hashParam, icon, plural, render } from "../dom.js";
import { errorLine, skeleton, toast } from "../ui.js";
import { hue, subjectBadge } from "./subjects.js";

const LABELS = {
  strong: ["ok", "Strong"],
  learning: ["", "Learning"],
  weak: ["danger", "Needs work"],
  new: ["", "Not tried"],
};

const go = (params) => {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== null && v !== undefined)).toString();
  window.location.hash = q ? `#/learning?${q}` : "#/learning";
};

async function startRound(subjectId) {
  try {
    const r = await api.post(`/api/learning/subjects/${subjectId}/rounds`);
    go({ round: r.id });
  } catch (e) {
    toast(errorText(e), "error");
  }
}

function accuracyRing(value, size = 64) {
  const v = value ?? 0;
  const tone = value === null || value === undefined ? "none" : v >= 0.75 ? "good" : v >= 0.5 ? "mid" : "low";
  return h("div", { class: `mini-ring ${tone}`, style: { "--p": Math.round(v * 100), width: `${size}px`, height: `${size}px` } },
    h("span", null, value === null || value === undefined ? "–" : `${Math.round(v * 100)}%`));
}

export default function myLearning(root, { me }) {
  if (me.via !== "account") {
    render(root, h("section", { class: "card" }, h("h2", null, "My Learning"),
      h("p", { class: "muted" }, "Practice needs a Mentora account. Sign out and create one.")));
    return undefined;
  }
  const round = hashParam("round");
  if (round) return practiceRound(root, Number(round));
  const subject = hashParam("subject");
  if (subject) return subjectPage(root, Number(subject));
  return overview(root);
}

// --- overview ---------------------------------------------------------------------------------

function overview(root) {
  async function load() {
    try {
      const [subjects, progress] = await Promise.all([api.get("/api/learning/subjects"), api.get("/api/learning/progress")]);
      paint(subjects, progress);
    } catch (e) {
      render(root, errorLine(errorText(e)));
    }
  }

  function card(s) {
    return h("article", { class: "learn-card", style: { "--h": hue(s.name) } },
      h("div", { class: "learn-card-top" },
        subjectBadge(s.name, true),
        h("div", { class: "learn-card-title" },
          h("b", null, s.name),
          h("span", { class: "muted small" }, `${s.questions} questions · ${s.topics} topics`)),
        accuracyRing(s.answered ? s.accuracy : null)),
      s.answered
        ? h("div", { class: "learn-card-facts" },
            h("span", null, icon("check"), `${s.answered} answered`),
            h("span", null, icon("activity"), plural(s.rounds, "round")),
            s.last_practiced ? h("span", null, icon("clock"), timeAgo(s.last_practiced)) : null)
        : h("p", { class: "muted small", style: { margin: 0 } }, "Not practised yet. Your first round mixes all topics."),
      s.weakest && s.answered
        ? h("div", { class: "learn-focus" }, h("span", { class: "muted small" }, "Focus next: "), h("span", { class: "badge danger" }, s.weakest))
        : null,
      h("div", { class: "row" },
        h("button", { class: "btn primary small", onClick: () => (s.open_round ? go({ round: s.open_round }) : startRound(s.id)) },
          icon("play"), s.open_round ? " Continue round" : " Practise 10 questions"),
        s.answered ? h("button", { class: "btn small", onClick: () => go({ subject: s.id }) }, icon("bars"), " Progress") : null));
  }

  function paint(subjects, p) {
    const practised = p.subjects.filter((s) => s.answered > 0);
    const timeline = p.timeline.slice(-20);
    render(root, h("div", { class: "stack" },
      h("div", { class: "grid cols-4" },
        statCard({ icon: "check", label: "Questions answered", value: p.answered }),
        statCard({ icon: "target", tone: "green", label: "Overall accuracy", value: pct(p.accuracy) }),
        statCard({ icon: "activity", label: "Practice rounds", value: p.rounds }),
        statCard({ icon: "book", tone: "orange", label: "Subjects practised", value: `${practised.length} of ${subjects.length}` })),
      p.answered
        ? h("div", { class: "grid cols-2" },
            h("section", { class: "card" }, h("h2", null, "Subject-wise performance"),
              hBars(practised.map((s) => ({ label: s.name, value: s.accuracy ?? 0, note: `${s.answered} answers` })))),
            h("section", { class: "card" }, h("h2", null, "Improvement over time"),
              h("p", { class: "muted small", style: { marginTop: -6 } }, "Score of each round (last 20)"),
              lineChart(timeline.map((_, i) => `${p.timeline.length - timeline.length + i + 1}`),
                [{ name: "Round score", color: "var(--series-1)", values: timeline.map((t) => t.accuracy) }],
                { label: "Score of each practice round", xName: "Round" })))
        : h("section", { class: "card hello-card" }, icon("sparkle"),
            h("div", null, h("b", null, "Pick a subject to start"),
              h("p", { class: "muted", style: { margin: "4px 0 0" } },
                "Each round has 10 questions. Mentora notices the topics you miss most and gives you more of them next time, so practice goes where it helps."))),
      practised.some((s) => s.strengths.length || s.weaknesses.length)
        ? h("section", { class: "card" }, h("h2", null, "Strengths and weaknesses"),
            h("div", { class: "sw-grid" }, practised.map((s) => h("div", { class: "sw-row" },
              h("b", null, s.name),
              h("div", { class: "row" }, s.strengths.slice(0, 3).map((t) => h("span", { class: "badge ok" }, t)),
                s.weaknesses.slice(0, 3).map((t) => h("span", { class: "badge danger" }, t)),
                !s.strengths.length && !s.weaknesses.length ? h("span", { class: "muted small" }, "Answer a few more questions to see this.") : null),
              s.improvement !== null
                ? h("span", { class: `small ${s.improvement >= 0 ? "delta-up" : "delta-down"}` },
                    `${s.improvement >= 0 ? "▲" : "▼"} ${Math.abs(Math.round(s.improvement * 100))} points since your first rounds`)
                : null))))
        : null,
      h("section", null,
        h("h2", { class: "section-title" }, "Subjects"),
        h("div", { class: "learn-grid" }, subjects.map(card)))));
  }

  render(root, skeleton({ cards: 3, stats: true }));
  load();
}

// --- one subject ------------------------------------------------------------------------------

function subjectPage(root, subjectId) {
  async function load() {
    try {
      paint(await api.get(`/api/learning/subjects/${subjectId}`));
    } catch (e) {
      render(root, errorLine(errorText(e)));
    }
  }

  function topicRow(t) {
    const [tone, text] = LABELS[t.label] ?? ["", t.label];
    const v = t.accuracy ?? 0;
    return h("li", null,
      h("span", { class: "topic-name" }, t.topic),
      h("div", { class: `meter ${t.accuracy === null ? "" : v >= 0.75 ? "good" : v >= 0.5 ? "mid" : "low"}` }, h("span", { style: { width: `${Math.round(v * 100)}%` } })),
      h("span", { class: "topic-val" }, pct(t.accuracy)),
      h("span", { class: `badge ${tone}` }, text),
      h("span", { class: "muted small" }, t.answered ? `${t.right}/${t.answered}` : ""));
  }

  function paint(d) {
    render(root, h("div", { class: "stack" },
      h("section", { class: "card folder-head", style: { "--h": hue(d.name) } },
        h("button", { class: "link-btn inline", onClick: () => go({}) }, "← My Learning"),
        h("div", { class: "folder-head-main" },
          subjectBadge(d.name, true),
          h("div", { style: { flex: 1, minWidth: 0 } },
            h("h2", null, d.name),
            h("div", { class: "folder-stats", style: { marginTop: 8 } },
              h("span", null, icon("check"), `${d.answered} answered`),
              h("span", null, icon("activity"), plural(d.rounds, "round")),
              h("span", null, icon("file"), `${d.questions} questions in the bank`),
              d.improvement !== null
                ? h("span", { class: d.improvement >= 0 ? "delta-up" : "delta-down" },
                    `${d.improvement >= 0 ? "▲" : "▼"} ${Math.abs(Math.round(d.improvement * 100))} points`)
                : null)),
          h("div", { class: "folder-actions" },
            accuracyRing(d.accuracy, 76),
            h("button", { class: "btn primary", onClick: () => (d.open_round ? go({ round: d.open_round }) : startRound(d.id)) },
              icon("play"), d.open_round ? " Continue round" : " Practise 10 questions")))),
      h("div", { class: "grid cols-2" },
        h("section", { class: "card" }, h("h2", null, "Strengths"),
          d.strengths.length ? h("div", { class: "row" }, d.strengths.map((t) => h("span", { class: "badge ok" }, t)))
            : h("p", { class: "muted small" }, "Topics where you score 75% or more (after at least 3 answers) appear here.")),
        h("section", { class: "card" }, h("h2", null, "Needs work"),
          d.weaknesses.length ? h("div", { class: "row" }, d.weaknesses.map((t) => h("span", { class: "badge danger" }, t)))
            : h("p", { class: "muted small" }, "Topics below 60% appear here. Your next rounds give you more of them."))),
      h("section", { class: "card" }, h("h2", null, "Topics"),
        h("ul", { class: "topic-list wide" }, d.topics.map(topicRow))),
      d.trend.length
        ? h("section", { class: "card" }, h("h2", null, "Your rounds"),
            lineChart(d.trend.map((_, i) => `${i + 1}`), [{ name: "Round score", color: `hsl(${hue(d.name)} 70% 50%)`, values: d.trend.map((t) => t.accuracy) }],
              { label: `Score of each ${d.name} round`, xName: "Round" }),
            h("ul", { class: "list", style: { marginTop: 12 } }, d.trend.slice(-5).reverse().map((t) => h("li", { class: "list-row" },
              h("span", { class: `ico ${t.accuracy >= 0.75 ? "green" : t.accuracy >= 0.5 ? "orange" : "red"}` }, icon("check")),
              h("div", { class: "body" }, h("div", { class: "title" }, `${t.score} / ${t.total} (${pct(t.accuracy)})`),
                h("div", { class: "muted small" }, timeAgo(t.at))),
              h("button", { class: "btn small", onClick: () => go({ round: t.round_id }) }, "Review")))))
        : null));
  }

  render(root, skeleton({ cards: 3 }));
  load();
}

// --- a practice round ---------------------------------------------------------------------------

function practiceRound(root, roundId) {
  const st = { r: null, i: 0, busy: false, last: null };

  async function load() {
    try {
      st.r = await api.get(`/api/learning/rounds/${roundId}`);
      const firstOpen = st.r.questions.findIndex((q) => q.choice === null);
      st.i = st.r.finished_at ? st.r.questions.length : Math.max(0, firstOpen);
      paint();
    } catch (e) {
      render(root, errorLine(errorText(e)));
    }
  }

  async function choose(q, choice) {
    if (st.busy || q.choice !== null) return;
    st.busy = true;
    try {
      const res = await api.post(`/api/learning/rounds/${roundId}/answer`, { question_id: q.id, choice });
      Object.assign(q, { choice, correct: res.correct, answer: res.answer, explanation: res.explanation });
      st.r.score = res.score;
      if (res.finished) st.r.finished_at = new Date().toISOString();
    } catch (e) {
      toast(errorText(e), "error");
    }
    st.busy = false;
    paint();
  }

  async function finishEarly() {
    if (!window.confirm("End this round now? Only the questions you answered count.")) return;
    try {
      st.r = await api.post(`/api/learning/rounds/${roundId}/finish`);
      st.i = st.r.questions.length;
      paint();
    } catch (e) {
      toast(errorText(e), "error");
      go({});
    }
  }

  const onKey = (e) => {
    const q = st.r?.questions[st.i];
    if (!q || e.target.closest?.("input, textarea")) return;
    if (q.choice === null && /^[1-6]$/.test(e.key) && Number(e.key) <= q.options.length) choose(q, Number(e.key) - 1);
    else if (q.choice !== null && e.key === "Enter") next();
  };

  function next() {
    st.i += 1;
    paint();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function summary() {
    const r = st.r;
    const answered = r.questions.filter((q) => q.choice !== null);
    const right = answered.filter((q) => q.correct).length;
    const byTopic = {};
    for (const q of answered) {
      byTopic[q.topic] ??= [0, 0];
      byTopic[q.topic][0] += 1;
      byTopic[q.topic][1] += q.correct ? 1 : 0;
    }
    const pc = answered.length ? Math.round((right / answered.length) * 100) : 0;
    return h("div", { class: "stack narrow" },
      h("section", { class: "card" },
        h("div", { class: "score-hero" },
          h("div", { class: `score-ring ${pc >= 75 ? "good" : pc >= 50 ? "mid" : "low"}`, style: { "--p": pc } }, h("span", null, `${pc}%`)),
          h("div", null,
            h("h2", { style: { margin: 0 } }, `${r.subject}: ${right} of ${answered.length} right`),
            h("p", { class: "muted", style: { margin: "6px 0 0" } },
              pc >= 80 ? "Excellent! Your next round will stretch you on other topics." : pc >= 50 ? "Good work. Your next round focuses on the topics you missed." : "Keep going: your next round gives you more practice on these topics."))),
        h("div", { class: "row", style: { marginTop: 14 } },
          h("button", { class: "btn primary", onClick: () => startRound(r.subject_id) }, icon("play"), " Next round"),
          h("button", { class: "btn", onClick: () => go({ subject: r.subject_id }) }, icon("bars"), " See progress"),
          h("button", { class: "btn", onClick: () => go({}) }, "All subjects"))),
      h("section", { class: "card" }, h("h2", null, "This round by topic"),
        h("ul", { class: "topic-list" }, Object.entries(byTopic).map(([t, [n, ok]]) => h("li", null,
          h("span", { class: "topic-name" }, t),
          h("div", { class: `meter ${ok / n >= 0.75 ? "good" : ok / n >= 0.5 ? "mid" : "low"}` }, h("span", { style: { width: `${(ok / n) * 100}%` } })),
          h("span", { class: "topic-val" }, `${ok}/${n}`))))),
      h("section", { class: "card" }, h("h2", null, "Review"),
        h("ol", { class: "result-list review" }, answered.map((q) => h("li", null,
          h("span", { class: `mark ${q.correct ? "ok" : "bad"}` }, q.correct ? "✓" : "✗"),
          h("div", { class: "body" },
            h("div", { class: "quiz-text" }, q.text),
            h("div", { class: "small" }, h("span", { class: "muted" }, "Your answer: "), q.options[q.choice]),
            q.correct ? null : h("div", { class: "small ok-text" }, h("span", { class: "muted" }, "Right answer: "), q.options[q.answer]),
            q.explanation ? h("div", { class: "muted small" }, q.explanation) : null))))));
  }

  function paint() {
    const r = st.r;
    if (r.finished_at && st.i >= r.questions.length) {
      render(root, summary());
      return;
    }
    const q = r.questions[st.i];
    if (!q) {
      render(root, summary());
      return;
    }
    const answeredCount = r.questions.filter((x) => x.choice !== null).length;
    const done = q.choice !== null;
    render(root, h("div", { class: "stack narrow" },
      h("div", { class: "card quiz-bar" },
        h("div", null, h("b", null, r.subject),
          h("div", { class: "muted small" }, `Question ${st.i + 1} of ${r.questions.length} · ${r.score} right so far`)),
        h("div", { class: "spacer" }),
        h("button", { class: "btn small", onClick: finishEarly }, "End round")),
      h("div", { class: "progress" }, h("span", { style: { width: `${(answeredCount / r.questions.length) * 100}%` } })),
      st.i === 0 && r.focus.length && !done
        ? h("div", { class: "notice", role: "note" }, h("span", { class: "notice-tag" }, "Focus"),
            h("span", { class: "notice-text" }, `This round gives you extra practice on ${r.focus.join(", ")}.`))
        : null,
      h("section", { class: "card quiz-q practice-q" },
        h("div", { class: "row quiz-q-head" },
          h("span", { class: "quiz-num" }, st.i + 1),
          h("span", { class: "badge" }, q.topic),
          h("span", { class: `badge ${q.reason === "weak" || q.reason === "review" ? "warn" : ""}`, title: "Why Mentora chose this question" }, q.reason_text)),
        h("p", { class: "quiz-text" }, q.text),
        h("div", { class: "practice-options", role: "group", "aria-label": "Options" }, q.options.map((o, i) => {
          let state = "";
          if (done && i === q.answer) state = "right";
          else if (done && i === q.choice) state = "wrong";
          return h("button", {
            class: `practice-option ${state}`, disabled: done || st.busy, onClick: () => choose(q, i),
          }, h("span", { class: "opt-key" }, String.fromCharCode(65 + i)), h("span", null, o),
          state === "right" ? icon("check") : state === "wrong" ? icon("x") : null);
        })),
        done
          ? h("div", { class: `feedback ${q.correct ? "good" : "bad"}` },
              h("b", null, q.correct ? "Correct!" : "Not quite."),
              q.explanation ? h("p", null, q.explanation) : null)
          : h("p", { class: "muted small", style: { margin: "10px 0 0" } }, "Tip: press 1-4 to answer and Enter for the next question."),
        done
          ? h("div", { class: "row", style: { marginTop: 12 } }, h("div", { class: "spacer" }),
              h("button", { class: "btn primary", onClick: next, autofocus: true },
                st.i + 1 < r.questions.length ? "Next question" : "See results", icon("arrow")))
          : null)));
  }

  window.addEventListener("keydown", onKey);
  render(root, skeleton({ cards: 1 }));
  load();
  return () => window.removeEventListener("keydown", onKey);
}
