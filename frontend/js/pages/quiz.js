// Quizzes inside a subject folder: students take them and see results; teachers write them.
import { api, errorText, timeAgo } from "../api.js";
import { h, icon, plural, render } from "../dom.js";
import { photoOf } from "../people.js";
import { errorLine, skeleton, toast } from "../ui.js";

export const KINDS = [
  ["single", "One right answer"],
  ["multiple", "Several right answers"],
  ["true_false", "True / false"],
  ["short", "Short typed answer"],
];

export const percent = (score, max) => (max ? Math.round((score / max) * 100) : 0);
const fmtPoints = (n) => (Number.isInteger(n) ? String(n) : n.toFixed(1));
const store = (key) => `mentora-quiz-${key}`;

function loadAnswers(attemptId) {
  try {
    return JSON.parse(window.sessionStorage.getItem(store(attemptId)) || "{}");
  } catch {
    return {};
  }
}

function saveAnswers(attemptId, answers) {
  try {
    window.sessionStorage.setItem(store(attemptId), JSON.stringify(answers));
  } catch {
    /* only a convenience */
  }
}

function clock(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function answered(v) {
  return !(v === undefined || v === null || v === "" || (Array.isArray(v) && v.length === 0));
}

// --- taking a quiz (students) ---------------------------------------------------------------

export function takeQuiz(root, quizId, go) {
  const st = { quiz: null, attempt: null, deadline: null, answers: {}, busy: false, left: null };
  let timer = 0;

  async function load() {
    try {
      st.quiz = await api.get(`/api/quizzes/${quizId}`);
      if (st.quiz.open_attempt) await start();
      else paint();
    } catch (e) {
      render(root, errorLine(errorText(e)));
    }
  }

  async function start() {
    st.busy = true;
    try {
      const r = await api.post(`/api/quizzes/${quizId}/start`);
      st.attempt = r.attempt_id;
      st.deadline = r.deadline ? new Date(r.deadline).getTime() : null;
      st.answers = loadAnswers(st.attempt);
      tick();
      window.clearInterval(timer);
      if (st.deadline) timer = window.setInterval(tick, 1000);
    } catch (e) {
      toast(errorText(e), "error");
    }
    st.busy = false;
    paint();
  }

  function tick() {
    if (!st.deadline) return;
    st.left = st.deadline - Date.now();
    const el = root.querySelector("[data-timer]");
    if (el) {
      el.textContent = clock(st.left);
      el.classList.toggle("low", st.left < 60_000);
    }
    if (st.left <= 0 && !st.busy) {
      window.clearInterval(timer);
      toast("Time is up. Your answers were submitted.");
      submit(true);
    }
  }

  async function submit(auto = false) {
    const missing = st.quiz.questions.filter((q) => !answered(st.answers[q.id])).length;
    if (!auto && missing > 0 && !window.confirm(`${plural(missing, "question")} not answered. Submit anyway?`)) return;
    st.busy = true;
    paint();
    try {
      const r = await api.post(`/api/attempts/${st.attempt}/submit`, { answers: st.answers });
      window.clearInterval(timer);
      try {
        window.sessionStorage.removeItem(store(st.attempt));
      } catch {
        /* ignore */
      }
      go({ attempt: r.id });
    } catch (e) {
      toast(errorText(e), "error");
      st.busy = false;
      paint();
    }
  }

  // Typing does not redraw the page (the input keeps focus), so the counter updates on its own.
  function showCount() {
    const done = st.quiz.questions.filter((x) => answered(st.answers[x.id])).length;
    const el = root.querySelector("[data-count]");
    if (el) el.textContent = `${done} of ${st.quiz.questions.length} answered`;
    const bar = root.querySelector("[data-bar]");
    if (bar) bar.style.width = `${(done / st.quiz.questions.length) * 100}%`;
  }

  const set = (qid, value) => {
    st.answers[qid] = value;
    saveAnswers(st.attempt, st.answers);
    paint();
  };

  function question(q, i) {
    const value = st.answers[q.id];
    let body;
    if (q.kind === "short") {
      body = h("input", {
        type: "text", value: value ?? "", "data-key": `a-${q.id}`, maxlength: "300", placeholder: "Type your answer",
        onInput: (e) => { st.answers[q.id] = e.target.value; saveAnswers(st.attempt, st.answers); showCount(); },
      });
    } else {
      const multi = q.kind === "multiple";
      const picked = multi ? (Array.isArray(value) ? value : []) : value;
      body = h("div", { role: multi ? "group" : "radiogroup" }, q.options.map((o, oi) => {
        const on = multi ? picked.includes(oi) : picked === oi;
        return h("label", { class: `option ${on ? "selected" : ""}` },
          h("input", {
            type: multi ? "checkbox" : "radio", name: `q-${q.id}`, checked: on,
            onChange: () => set(q.id, multi ? (on ? picked.filter((x) => x !== oi) : [...picked, oi].sort()) : oi),
          }),
          h("span", null, o));
      }));
    }
    return h("section", { class: "card quiz-q" },
      h("div", { class: "row quiz-q-head" },
        h("span", { class: "quiz-num" }, i + 1),
        h("span", { class: "muted small" }, `${fmtPoints(q.points)} ${q.points === 1 ? "point" : "points"}`,
          q.kind === "multiple" ? " · choose all that apply" : "", q.topic ? ` · ${q.topic}` : "")),
      h("p", { class: "quiz-text" }, q.text),
      body);
  }

  function paint() {
    const q = st.quiz;
    if (!st.attempt) {
      const best = q.attempts.reduce((b, a) => Math.max(b, percent(a.score, a.max_score)), -1);
      render(root, h("div", { class: "stack narrow" },
        h("button", { class: "link-btn inline", onClick: () => go({ folder: q.folder_id, tab: "quizzes" }) }, "← Back to the folder"),
        h("section", { class: "card" },
          h("h2", null, q.title),
          q.description ? h("p", { class: "muted pre" }, q.description) : null,
          h("div", { class: "quiz-facts" },
            h("span", null, icon("file"), plural(q.question_count, "question")),
            h("span", null, icon("target"), `${fmtPoints(q.total_points)} points`),
            h("span", null, icon("clock"), q.time_limit_min ? `${q.time_limit_min} minutes` : "No time limit"),
            h("span", null, icon("activity"), `${q.attempts_left} of ${plural(q.max_attempts, "attempt")} left`)),
          best >= 0 ? h("p", null, "Your best score so far: ", h("b", null, `${best}%`)) : null,
          q.time_limit_min ? h("p", { class: "muted small" }, "The timer starts when you press Start and keeps running if you leave the page.") : null,
          h("div", { class: "row" },
            q.attempts_left > 0
              ? h("button", { class: "btn primary", disabled: st.busy, onClick: start }, icon("play"), q.attempts.length ? " Try again" : " Start the quiz")
              : h("span", { class: "badge" }, "No attempts left"))),
        q.attempts.length
          ? h("section", { class: "card" }, h("h2", null, "Your attempts"),
              h("ul", { class: "list" }, q.attempts.map((a, i) => h("li", { class: "list-row" },
                h("div", { class: "body" }, h("div", { class: "title" }, `Attempt ${i + 1}: ${percent(a.score, a.max_score)}%`),
                  h("div", { class: "muted small" }, `${fmtPoints(a.score)} / ${fmtPoints(a.max_score)} · ${timeAgo(a.submitted_at)}${a.late ? " · late" : ""}`)),
                h("button", { class: "btn small", onClick: () => go({ attempt: a.id }) }, "See answers")))))
          : null));
      return;
    }
    const done = q.questions.filter((x) => answered(st.answers[x.id])).length;
    render(root, h("div", { class: "stack narrow" },
      h("div", { class: "card quiz-bar" },
        h("div", null, h("b", null, q.title), h("div", { class: "muted small", "data-count": "" }, `${done} of ${q.questions.length} answered`)),
        h("div", { class: "spacer" }),
        st.deadline ? h("span", { class: "quiz-timer", "data-timer": "" }, clock(st.left ?? 0)) : null,
        h("button", { class: "btn primary", disabled: st.busy, onClick: () => submit(false) }, st.busy ? "Submitting…" : "Submit")),
      h("div", { class: "progress" }, h("span", { "data-bar": "", style: { width: `${(done / q.questions.length) * 100}%` } })),
      q.questions.map(question),
      h("div", { class: "row" }, h("div", { class: "spacer" }),
        h("button", { class: "btn primary", disabled: st.busy, onClick: () => submit(false) }, "Submit answers"))));
    tick();
  }

  render(root, skeleton({ cards: 2 }));
  load();
  return () => window.clearInterval(timer);
}

// --- a submitted attempt -------------------------------------------------------------------

function shownAnswer(q, value) {
  if (!answered(value)) return "No answer";
  if (q.kind === "short") return String(value);
  const picks = Array.isArray(value) ? value : [value];
  return picks.map((i) => q.options[i] ?? "?").join(", ");
}

export function quizResult(root, attemptId, go, me) {
  async function load() {
    try {
      const r = await api.get(`/api/attempts/${attemptId}`);
      const quiz = await api.get(`/api/quizzes/${r.quiz_id}`).catch(() => null);
      paint(r, quiz);
    } catch (e) {
      render(root, errorLine(errorText(e)));
    }
  }

  function paint(r, quiz) {
    const pc = percent(r.score, r.max_score);
    const right = r.questions.filter((q) => q.correct).length;
    const back = quiz ? () => go({ folder: quiz.folder_id, tab: me.role === "teacher" ? "analysis" : "results" }) : () => go({});
    render(root, h("div", { class: "stack narrow" },
      h("button", { class: "link-btn inline", onClick: back }, "← Back to the folder"),
      h("section", { class: "card" },
        h("div", { class: "score-hero" },
          h("div", { class: `score-ring ${pc >= 75 ? "good" : pc >= 50 ? "mid" : "low"}`, style: { "--p": pc } }, h("span", null, `${pc}%`)),
          h("div", null,
            h("h2", { style: { margin: 0 } }, r.quiz_title),
            me.role === "teacher" && r.student
              ? h("div", { class: "person", style: { margin: "8px 0" } }, photoOf(r.student),
                  h("div", null, h("div", { class: "who-name" }, r.student.name), h("div", { class: "muted small" }, `@${r.student.username}`)))
              : null,
            h("p", { class: "muted", style: { margin: "6px 0 0" } },
              `${fmtPoints(r.score)} of ${fmtPoints(r.max_score)} points · ${right} of ${r.questions.length} right · ${timeAgo(r.submitted_at)}`),
            r.late ? h("span", { class: "badge warn" }, "Submitted after the time limit") : null))),
      h("section", { class: "card" },
        h("h2", null, "Answers"),
        r.show_answers ? null : h("p", { class: "muted" }, "Your teacher shows the right answers later."),
        h("ol", { class: "result-list review" }, r.questions.map((q, i) => h("li", null,
          h("span", { class: `mark ${q.correct ? "ok" : "bad"}` }, q.correct ? "✓" : "✗"),
          h("div", { class: "body" },
            h("div", { class: "quiz-text" }, `${i + 1}. ${q.text}`),
            h("div", { class: "small" }, h("span", { class: "muted" }, "Your answer: "), shownAnswer(q, q.given)),
            r.show_answers && !q.correct
              ? h("div", { class: "small ok-text" }, h("span", { class: "muted" }, "Right answer: "),
                  q.kind === "short" ? q.answer.join(" / ") : q.answer.map((a) => q.options[a]).join(", "))
              : null,
            h("div", { class: "muted small" }, `${fmtPoints(q.earned)} / ${fmtPoints(q.points)}${q.topic ? ` · ${q.topic}` : ""}`))))))));
  }

  render(root, skeleton({ cards: 2 }));
  load();
}

// --- writing a quiz (teachers) -------------------------------------------------------------

let uid = 0;
const blank = (kind = "single") => ({
  key: `n${++uid}`, kind, text: "", topic: "", points: 1,
  options: kind === "single" || kind === "multiple" ? ["", ""] : [], answer: kind === "true_false" ? [0] : [], accepted: "",
});

function fromServer(q) {
  return {
    key: `s${++uid}`, id: q.id, kind: q.kind, text: q.text, topic: q.topic || "", points: q.points,
    options: q.kind === "true_false" || q.kind === "short" ? [] : [...q.options],
    answer: q.kind === "short" ? [] : [...q.answer],
    accepted: q.kind === "short" ? q.answer.join(", ") : "",
  };
}

function toServer(q) {
  return {
    id: q.id, kind: q.kind, text: q.text, topic: q.topic, points: Number(q.points) || 1,
    options: q.options,
    answer: q.kind === "short" ? q.accepted.split(",").map((a) => a.trim()).filter(Boolean) : q.answer,
  };
}

export function editQuiz(root, { quizId, folderId }, go) {
  const st = {
    loading: quizId !== "new", busy: false, error: null, taken: 0,
    title: "", description: "", time: "", attempts: 1, show: true, published: false, questions: [blank()],
    folder: Number(folderId) || null,
  };

  async function load() {
    try {
      const q = await api.get(`/api/quizzes/${quizId}`);
      Object.assign(st, {
        loading: false, title: q.title, description: q.description, time: q.time_limit_min ?? "",
        attempts: q.max_attempts, show: q.show_answers, published: q.published, taken: q.taken_by || 0,
        questions: q.questions.map(fromServer), folder: q.folder_id,
      });
      paint();
    } catch (e) {
      render(root, errorLine(errorText(e)));
    }
  }

  async function save(publish) {
    st.error = null;
    st.busy = true;
    paint();
    const body = {
      title: st.title, description: st.description, questions: st.questions.map(toServer),
      time_limit_min: st.time === "" ? null : Number(st.time), max_attempts: Number(st.attempts) || 1,
      show_answers: st.show, published: publish ?? st.published,
    };
    try {
      if (quizId === "new") await api.post(`/api/folders/${st.folder}/quizzes`, body);
      else await api.post(`/api/quizzes/${quizId}`, body);
      toast(body.published ? "Quiz saved and published. Your students can take it now." : "Quiz saved as a draft.");
      go({ folder: st.folder, tab: "quizzes" });
    } catch (e) {
      st.error = errorText(e);
      st.busy = false;
      paint();
    }
  }

  const move = (i, d) => {
    const qs = st.questions;
    if (i + d < 0 || i + d >= qs.length) return;
    [qs[i], qs[i + d]] = [qs[i + d], qs[i]];
    paint();
  };

  function questionEditor(q, i) {
    const k = q.key;
    const choice = q.kind === "single" || q.kind === "multiple";
    const setKind = (kind) => {
      const fresh = blank(kind);
      Object.assign(q, { kind, options: choice && (kind === "single" || kind === "multiple") ? q.options : fresh.options, answer: fresh.answer });
      paint();
    };
    let answers;
    if (choice) {
      answers = h("div", { class: "stack-s" },
        h("div", { class: "muted small" }, q.kind === "single" ? "Options (select the right one)" : "Options (tick every right one)"),
        q.options.map((o, oi) => h("div", { class: "opt-edit" },
          h("input", {
            type: q.kind === "single" ? "radio" : "checkbox", name: `right-${k}`, checked: q.answer.includes(oi),
            "aria-label": `Option ${oi + 1} is right`,
            onChange: (e) => {
              if (q.kind === "single") q.answer = [oi];
              else q.answer = e.target.checked ? [...q.answer, oi].sort() : q.answer.filter((x) => x !== oi);
              paint();
            },
          }),
          h("input", {
            type: "text", value: o, placeholder: `Option ${oi + 1}`, "data-key": `${k}-o${oi}`, maxlength: "500",
            onInput: (e) => { q.options[oi] = e.target.value; },
          }),
          q.options.length > 2
            ? h("button", {
                class: "icon-btn", type: "button", "aria-label": "Remove option",
                onClick: () => {
                  q.options.splice(oi, 1);
                  q.answer = q.answer.filter((x) => x !== oi).map((x) => (x > oi ? x - 1 : x));
                  paint();
                },
              }, icon("x"))
            : null)),
        q.options.length < 8
          ? h("button", { class: "btn small", type: "button", onClick: () => { q.options.push(""); paint(); } }, "+ Add option")
          : null);
    } else if (q.kind === "true_false") {
      answers = h("div", { class: "row" }, h("span", { class: "muted small" }, "Right answer:"),
        ["True", "False"].map((label, oi) => h("label", { class: `option inline ${q.answer[0] === oi ? "selected" : ""}` },
          h("input", { type: "radio", name: `right-${k}`, checked: q.answer[0] === oi, onChange: () => { q.answer = [oi]; paint(); } }),
          h("span", null, label))));
    } else {
      answers = h("label", { class: "field" }, h("span", null, "Accepted answers (separate with commas; capitals and punctuation are ignored)"),
        h("input", {
          type: "text", value: q.accepted, "data-key": `${k}-acc`, placeholder: "e.g. extends", maxlength: "600",
          onInput: (e) => { q.accepted = e.target.value; },
        }));
    }
    return h("section", { class: "card quiz-q" },
      h("div", { class: "row quiz-q-head" },
        h("span", { class: "quiz-num" }, i + 1),
        h("select", { "aria-label": "Question type", onChange: (e) => setKind(e.target.value) },
          KINDS.map(([v, l]) => h("option", { value: v, selected: q.kind === v }, l))),
        h("div", { class: "spacer" }),
        h("button", { class: "icon-btn", type: "button", "aria-label": "Move up", disabled: i === 0, onClick: () => move(i, -1) }, "↑"),
        h("button", { class: "icon-btn", type: "button", "aria-label": "Move down", disabled: i === st.questions.length - 1, onClick: () => move(i, 1) }, "↓"),
        h("button", {
          class: "icon-btn", type: "button", "aria-label": "Delete question", disabled: st.questions.length === 1,
          onClick: () => { st.questions.splice(i, 1); paint(); },
        }, icon("trash"))),
      h("label", { class: "field" }, h("span", null, "Question"),
        h("textarea", {
          rows: "2", value: q.text, "data-key": `${k}-t`, maxlength: "2000", placeholder: "Write the question",
          onInput: (e) => { q.text = e.target.value; },
        })),
      answers,
      h("div", { class: "field-row", style: { marginTop: 10 } },
        h("label", { class: "field" }, h("span", null, "Topic (for strengths and weaknesses)"),
          h("input", { type: "text", value: q.topic, "data-key": `${k}-topic`, maxlength: "60", placeholder: "e.g. Inheritance", onInput: (e) => { q.topic = e.target.value; } })),
        h("label", { class: "field" }, h("span", null, "Points"),
          h("input", { type: "number", min: "0.5", max: "100", step: "0.5", value: q.points, "data-key": `${k}-pts`, onInput: (e) => { q.points = e.target.value; } }))));
  }

  function paint() {
    if (st.loading) return;
    render(root, h("div", { class: "stack narrow" },
      h("button", { class: "link-btn inline", onClick: () => go({ folder: st.folder, tab: "quizzes" }) }, "← Back to the folder"),
      st.taken > 0
        ? h("div", { class: "notice", role: "note" }, h("span", { class: "notice-tag" }, "Note"),
            h("span", { class: "notice-text" }, `${plural(st.taken, "student")} took this quiz, so its questions cannot change. You can still rename it, change the settings or hide it.`))
        : null,
      h("section", { class: "card" },
        h("h2", null, quizId === "new" ? "New quiz" : "Edit quiz"),
        h("label", { class: "field" }, h("span", null, "Title"),
          h("input", { type: "text", value: st.title, "data-key": "title", maxlength: "200", placeholder: "e.g. Unit 1: Classes and objects", onInput: (e) => { st.title = e.target.value; } })),
        h("label", { class: "field" }, h("span", null, "Instructions (optional)"),
          h("textarea", { rows: "2", value: st.description, "data-key": "desc", maxlength: "2000", onInput: (e) => { st.description = e.target.value; } })),
        h("div", { class: "field-row" },
          h("label", { class: "field" }, h("span", null, "Time limit in minutes (empty: none)"),
            h("input", { type: "number", min: "1", max: "600", value: st.time, "data-key": "time", onInput: (e) => { st.time = e.target.value; } })),
          h("label", { class: "field" }, h("span", null, "Attempts allowed"),
            h("input", { type: "number", min: "1", max: "20", value: st.attempts, "data-key": "attempts", onInput: (e) => { st.attempts = e.target.value; } }))),
        h("label", { class: "check-line" },
          h("input", { type: "checkbox", checked: st.show, onChange: (e) => { st.show = e.target.checked; } }),
          h("span", null, "Show students the right answers after they submit"))),
      st.questions.map(questionEditor),
      h("div", { class: "row" }, h("span", { class: "muted small" }, "Add a question:"),
        KINDS.map(([v, l]) => h("button", { class: "btn small", type: "button", onClick: () => { st.questions.push(blank(v)); paint(); } }, `+ ${l}`))),
      st.error ? h("p", { class: "error", role: "alert" }, st.error) : null,
      h("div", { class: "card quiz-bar" },
        h("span", { class: "muted small" }, `${plural(st.questions.length, "question")} · ${st.published ? "published" : "draft"}`),
        h("div", { class: "spacer" }),
        h("button", { class: "btn", disabled: st.busy, onClick: () => save(st.published ? null : false) }, st.published ? "Save" : "Save draft"),
        st.published
          ? h("button", { class: "btn", disabled: st.busy, onClick: () => save(false) }, "Hide from students")
          : h("button", { class: "btn primary", disabled: st.busy, onClick: () => save(true) }, "Save and publish"))));
  }

  if (quizId === "new") paint();
  else {
    render(root, skeleton({ cards: 2 }));
    load();
  }
}
