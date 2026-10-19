// Goals & Plans: turn a goal ("Learn Java from basic to advanced") into a week-by-week roadmap,
// follow it, and see how Mentora adapts it.
import { api, errorText, pct, timeAgo } from "../api.js";
import { h, hashParam, icon, plural, render } from "../dom.js";
import { errorLine, skeleton, toast } from "../ui.js";
import { hue, subjectBadge } from "./subjects.js";

const STAGE_TONE = { Basics: "basics", Intermediate: "inter", Advanced: "adv", Project: "proj" };
const KIND = {
  study: ["book", "Study"],
  practice: ["target", "Practice"],
  exercise: ["file", "Exercise"],
  project: ["layers", "Project"],
  checkpoint: ["check", "Checkpoint"],
  review: ["alert", "Review"],
};
const AUTO = new Set(["practice", "checkpoint", "review"]);
const fmtDate = (d) => new Date(d).toLocaleDateString(undefined, { day: "numeric", month: "short" });
const go = (params) => {
  const q = new URLSearchParams(params).toString();
  window.location.hash = q ? `#/goals?${q}` : "#/goals";
};

export default function goals(root, ctx) {
  if (ctx.me.via !== "account") {
    render(root, h("section", { class: "card" }, h("h2", null, "Goals & Plans"),
      h("p", { class: "muted" }, "Roadmaps need a Mentora account. Sign out and create one.")));
    return undefined;
  }
  const id = hashParam("roadmap");
  if (id) return roadmapPage(root, Number(id));
  return overview(root, ctx);
}

const aiWarning = () => h("div", { class: "notice", role: "note", style: { marginTop: 12 } }, h("span", { class: "notice-tag" }, "AI plan"),
  h("span", { class: "notice-text" }, "Written by the AI tutor model, not by a teacher. It can contain mistakes: check the topics with a teacher or a good book before relying on it."));

function stageBar(weeks) {
  const counts = {};
  for (const w of weeks) counts[w.stage] = (counts[w.stage] ?? 0) + 1;
  return h("div", { class: "stage-bar" }, Object.entries(counts).map(([stage, n]) => h("div", {
    class: `stage ${STAGE_TONE[stage] ?? ""}`, style: { flex: n },
  }, h("b", null, stage), h("span", null, plural(n, "week")))));
}

// --- overview: goal search, my roadmaps, tutor goals ----------------------------------------

function overview(root, ctx) {
  const st = { catalog: null, list: null, goal: "", level: "beginner", pace: "steady", busy: false, preview: null, error: null };

  async function load() {
    try {
      [st.catalog, st.list] = await Promise.all([api.get("/api/roadmaps/catalog"), api.get("/api/roadmaps")]);
      paint();
    } catch (e) {
      render(root, errorLine(errorText(e)));
    }
  }

  async function build(e) {
    e?.preventDefault();
    if (!st.goal.trim()) return;
    st.busy = true;
    st.error = null;
    st.preview = null;
    paint();
    try {
      st.preview = await api.post("/api/roadmaps/preview", { goal: st.goal, level: st.level, pace: st.pace });
    } catch (err) {
      st.error = errorText(err);
    }
    st.busy = false;
    paint();
  }

  async function start() {
    st.busy = true;
    paint();
    try {
      const r = await api.post("/api/roadmaps", { goal: st.goal, level: st.level, pace: st.pace });
      toast("Your roadmap is ready. Week 1 starts today.");
      go({ roadmap: r.id });
    } catch (err) {
      toast(errorText(err), "error");
      st.busy = false;
      paint();
    }
  }

  const seg = (key, options) => h("div", { class: "seg goal-seg" }, Object.entries(options).map(([k, label]) => h("button", {
    type: "button", class: st[key] === k ? "active" : "", onClick: () => { st[key] = k; if (st.preview) build(); else paint(); },
  }, label)));

  function previewCard(p) {
    return h("section", { class: "card roadmap-preview", style: { "--h": hue(p.subject) } },
      h("div", { class: "row" },
        subjectBadge(p.subject, true),
        h("div", { style: { flex: 1, minWidth: 0 } },
          h("h2", { style: { margin: 0 } }, p.goal),
          h("div", { class: "muted small" },
            `${p.subject} · ${plural(p.weeks.length, "week")} · ${p.weeks.reduce((n, w) => n + w.tasks.length, 0)} tasks`,
            p.source === "ai" ? " · written by the AI tutor model" : " · Mentora roadmap")),
        h("button", { class: "btn primary", disabled: st.busy, onClick: start }, icon("play"), " Start this roadmap")),
      p.source === "ai" ? aiWarning() : null,
      stageBar(p.weeks),
      h("ol", { class: "week-preview" }, p.weeks.map((w) => h("li", null,
        h("span", { class: `wk ${STAGE_TONE[w.stage] ?? ""}` }, `W${w.n}`),
        h("div", null, h("b", null, w.title), h("div", { class: "muted small" }, w.topics.join(" · ")))))));
  }

  function card(r) {
    const p = r.progress;
    return h("article", { class: "roadmap-card", style: { "--h": hue(r.subject) }, onClick: () => go({ roadmap: r.id }) },
      h("div", { class: "row" }, subjectBadge(r.subject),
        h("div", { style: { flex: 1, minWidth: 0 } }, h("b", { class: "ellipsis" }, r.goal), h("div", { class: "muted small" }, r.subject)),
        r.status === "completed" ? h("span", { class: "badge ok" }, "Completed")
          : r.status === "archived" ? h("span", { class: "badge" }, "Archived")
            : p.behind > 0 ? h("span", { class: "badge warn" }, `${p.behind} wk behind`) : h("span", { class: "badge ok" }, "On track")),
      h("div", { class: "progress" }, h("span", { style: { width: `${p.percent * 100}%` } })),
      h("div", { class: "muted small" }, `${pct(p.percent)} done · week ${p.current_week} of ${p.weeks_total}`,
        r.current_title && r.status === "active" ? `: ${r.current_title}` : ""),
      r.adaptations ? h("div", { class: "small adapt-hint" }, icon("activity"), ` Adapted ${plural(r.adaptations, "time")} to your results`) : null);
  }

  function paint() {
    const c = st.catalog;
    render(root, h("div", { class: "stack" },
      h("section", { class: "card goal-hero" },
        h("h2", null, "What do you want to learn?"),
        h("p", { class: "muted", style: { marginTop: -4 } }, "Describe your goal and Mentora builds a week-by-week roadmap from the basics to advanced topics and a project, then adapts it to your practice results."),
        h("form", { class: "goal-search", onSubmit: build },
          icon("search"),
          h("input", {
            type: "search", value: st.goal, "data-key": "goal", maxlength: "200", "aria-label": "Your learning goal",
            placeholder: "e.g. How to learn Java from basic to advanced", onInput: (e) => { st.goal = e.target.value; },
          }),
          h("button", { class: "btn primary", type: "submit", disabled: st.busy }, st.busy ? "Building…" : "Build my roadmap")),
        st.busy ? h("p", { class: "muted small", style: { margin: "0 0 8px" } }, "Ready-made roadmaps appear at once; for other goals the AI tutor model writes one, which can take up to a minute.") : null,
        h("div", { class: "row goal-examples" }, h("span", { class: "muted small" }, "Try:"),
          c.examples.map((x) => h("button", { type: "button", class: "chip-btn", onClick: () => { st.goal = x; build(); } }, x))),
        h("div", { class: "goal-options" },
          h("div", null, h("span", { class: "muted small" }, "Your level"), seg("level", c.levels)),
          h("div", null, h("span", { class: "muted small" }, "Pace"), seg("pace", c.paces))),
        h("p", { class: "muted small", style: { margin: "10px 0 0" } },
          `Ready-made roadmaps: ${c.subjects.join(", ")}. Other goals are planned by the AI tutor when it is online.`),
        st.error ? h("p", { class: "error", role: "alert" }, st.error) : null),
      st.preview ? previewCard(st.preview) : null,
      st.list.length
        ? h("section", null, h("h2", { class: "section-title" }, "My roadmaps"),
            h("div", { class: "roadmap-grid" }, st.list.map(card)))
        : null));
  }

  render(root, skeleton({ cards: 2 }));
  load();
}

// --- one roadmap -------------------------------------------------------------------------------

function roadmapPage(root, id) {
  const st = { r: null, open: new Set(), busy: false };

  async function load(first = false) {
    try {
      st.r = await api.get(`/api/roadmaps/${id}`);
      if (first) st.open.add(st.r.progress.current_week);
      for (const note of st.r.new_adaptations) toast(`Plan updated: ${note}`);
      paint();
    } catch (e) {
      render(root, errorLine(errorText(e)));
    }
  }

  async function tick(task, done) {
    try {
      st.r = await api.post(`/api/roadmaps/${id}/tasks/${encodeURIComponent(task.id)}`, { done });
      for (const note of st.r.new_adaptations) toast(`Plan updated: ${note}`);
      if (st.r.status === "completed") toast("Roadmap completed. Well done!");
      paint();
    } catch (e) {
      toast(errorText(e), "error");
    }
  }

  async function practise(task) {
    try {
      const rnd = await api.post(`/api/learning/subjects/${st.r.subject_id}/rounds?topics=${encodeURIComponent(task.topics.join(","))}`);
      window.location.hash = `#/learning?round=${rnd.id}`;
    } catch (e) {
      toast(errorText(e), "error");
    }
  }

  async function setStatus(status) {
    st.r = await api.post(`/api/roadmaps/${id}/status`, { status });
    toast(status === "archived" ? "Roadmap archived." : "Roadmap active again.");
    paint();
  }

  async function remove() {
    if (!window.confirm("Delete this roadmap and its progress?")) return;
    await api.del(`/api/roadmaps/${id}`);
    go({});
  }

  function taskRow(t) {
    const [ic, label] = KIND[t.kind] ?? ["file", t.kind];
    const auto = AUTO.has(t.kind);
    const progress = auto && t.target
      ? h("div", { class: "task-progress" },
          h("div", { class: "progress" }, h("span", { style: { width: `${Math.min(100, ((t.answered ?? 0) / t.target) * 100)}%` } })),
          h("span", { class: "muted small" }, `${t.answered ?? 0}/${t.target} answered${t.answered ? ` · ${pct((t.right ?? 0) / t.answered)} right` : ""} · need ${pct(t.pass)}`))
      : null;
    return h("li", { class: `task ${t.done ? "done" : ""} ${t.optional ? "optional" : ""} ${t.added ? "added" : ""}` },
      h("input", {
        type: "checkbox", checked: t.done, "aria-label": `Mark "${t.text}" done`,
        onChange: (e) => tick(t, e.target.checked), disabled: st.r.status === "archived",
      }),
      h("span", { class: `task-ico k-${t.kind}` }, icon(ic)),
      h("div", { class: "task-body" },
        h("div", null, h("span", { class: "task-kind" }, label), t.optional ? h("span", { class: "badge" }, "Optional") : null,
          t.added ? h("span", { class: "badge warn" }, "Added for you") : null, t.done && t.auto ? h("span", { class: "badge ok" }, "Done in practice") : null),
        h("div", { class: "task-text" }, t.text),
        progress),
      auto && !t.done && st.r.subject_id && st.r.status === "active"
        ? h("button", { class: "btn small primary", onClick: () => practise(t) }, icon("play"), " Practise")
        : null);
  }

  function weekCard(w) {
    const p = st.r.progress;
    const start = new Date(new Date(st.r.start_date).getTime() + (w.n - 1) * 7 * 86400000);
    const end = new Date(start.getTime() + 6 * 86400000);
    const req = w.tasks.filter((t) => !t.optional);
    const done = w.tasks.every((t) => t.done || t.optional);
    const current = w.n === p.current_week && st.r.status === "active";
    const open = st.open.has(w.n);
    return h("li", { class: `week ${done ? "done" : ""} ${current ? "current" : ""}` },
      h("button", {
        class: "week-head", "aria-expanded": String(open),
        onClick: () => { if (open) st.open.delete(w.n); else st.open.add(w.n); paint(); },
      },
      h("span", { class: `wk ${STAGE_TONE[w.stage] ?? ""}` }, done ? icon("check") : `W${w.n}`),
      h("div", { class: "week-title" }, h("b", null, w.title),
        h("span", { class: "muted small" }, `Week ${w.n} · ${w.stage} · ${fmtDate(start)} - ${fmtDate(end)} · ${req.filter((t) => t.done).length}/${req.length} tasks`)),
      current ? h("span", { class: "badge brand" }, "This week") : null,
      h("span", { class: `week-caret ${open ? "open" : ""}`, "aria-hidden": "true" }, "›")),
      open ? h("ul", { class: "tasks" }, w.tasks.map(taskRow)) : null);
  }

  function paint() {
    const r = st.r;
    const p = r.progress;
    render(root, h("div", { class: "stack narrow-wide" },
      h("section", { class: "card folder-head", style: { "--h": hue(r.subject) } },
        h("button", { class: "link-btn inline", onClick: () => go({}) }, "← Goals & Plans"),
        h("div", { class: "folder-head-main" },
          subjectBadge(r.subject, true),
          h("div", { style: { flex: 1, minWidth: 0 } },
            h("h2", null, r.goal),
            h("div", { class: "folder-stats", style: { marginTop: 8 } },
              h("span", null, icon("layers"), `${r.subject}${r.source === "ai" ? " (AI-written plan)" : ""}`),
              h("span", null, icon("clock"), `Week ${p.current_week} of ${p.weeks_total}`),
              h("span", null, icon("check"), `${p.tasks_done}/${p.tasks_total} tasks`),
              h("span", null, icon("target"), `Finish by ${fmtDate(p.finish_by)}`),
              r.status === "completed" ? h("span", { class: "delta-up" }, "Completed")
                : p.behind > 0 ? h("span", { class: "delta-down" }, `${p.behind} weeks behind`) : h("span", { class: "delta-up" }, "On track"))),
          h("div", { class: "folder-actions" },
            h("div", { class: `mini-ring ${p.percent >= 0.75 ? "good" : p.percent >= 0.4 ? "mid" : "low"}`, style: { "--p": Math.round(p.percent * 100), width: "76px", height: "76px" } },
              h("span", null, pct(p.percent))),
            h("div", { class: "row" },
              h("button", { class: "btn small", onClick: () => setStatus(r.status === "archived" ? "active" : "archived") }, r.status === "archived" ? "Restore" : "Archive"),
              h("button", { class: "btn small danger", onClick: remove }, "Delete")))),
        r.source === "ai" ? aiWarning() : null,
        stageBar(r.weeks),
        r.teachers.length
          ? h("div", { class: "row", style: { marginTop: 10 } }, h("span", { class: "muted small" }, "Material from teachers:"),
              r.teachers.map((t) => h("a", { class: "chip-btn", href: `#/subjects?folder=${t.folder_id}` }, `${r.subject} by ${t.name}`)))
          : null),
      r.adaptations.length
        ? h("details", { class: "card adapt-log", open: r.new_adaptations.length > 0 },
            h("summary", null, icon("activity"), ` Mentora adapted your plan ${plural(r.adaptations.length, "time")}`),
            h("ul", null, [...r.adaptations].reverse().map((a) => h("li", null, h("span", null, a.text), h("span", { class: "muted small" }, ` · ${timeAgo(a.at)}`)))))
        : h("p", { class: "muted small", style: { margin: 0 } },
            "Practise in My Learning as you go: Mentora ticks practice tasks for you, adds reviews for topics you miss, and makes weeks optional when you already know them."),
      h("ol", { class: "weeks" }, r.weeks.map(weekCard))));
  }

  render(root, skeleton({ cards: 3 }));
  load(true);
}
