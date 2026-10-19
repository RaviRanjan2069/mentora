// Subjects: teachers' folders ("Java by Dr. Ravi Singh") with study material, quizzes and
// analysis. One route per role; the view comes from the hash: ?folder=&tab=, ?quiz=, ?attempt=, ?edit=.
import { api, errorText, pct, timeAgo } from "../api.js";
import { h, hashParam, icon, plural, render } from "../dom.js";
import { photoOf } from "../people.js";
import { errorLine, openDrawer, skeleton, toast } from "../ui.js";
import { practiceSection, questionBank } from "./bank.js";
import { editQuiz, percent, quizResult, takeQuiz } from "./quiz.js";

const HUES = [221, 262, 160, 24, 340, 190, 45, 290];
export const hue = (name) => HUES[[...name].reduce((a, c) => a + c.charCodeAt(0), 0) % HUES.length];

export function fmtSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function subjectBadge(name, big = false) {
  return h("span", { class: `subject-badge ${big ? "big" : ""}`, style: { "--h": hue(name) } }, name.slice(0, 1).toUpperCase());
}

export default function subjects(root, { me }) {
  const base = me.role === "teacher" ? "#/teacher/subjects" : "#/subjects";
  const go = (params) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== null && v !== undefined)).toString();
    window.location.hash = q ? `${base}?${q}` : base;
  };
  if (me.via !== "account") {
    render(root, h("section", { class: "card" }, h("h2", null, "Subjects"),
      h("p", { class: "muted" }, "Subjects need a Mentora account. Sign out and create one.")));
    return undefined;
  }
  const quiz = hashParam("quiz");
  const attempt = hashParam("attempt");
  const edit = hashParam("edit");
  const folder = hashParam("folder");
  if (attempt) return quizResult(root, attempt, go, me);
  if (quiz && me.role === "learner") return takeQuiz(root, quiz, go);
  if (edit && me.role === "teacher") return editQuiz(root, { quizId: edit, folderId: folder }, go);
  if (folder) return folderPage(root, me, Number(folder), hashParam("tab"), go);
  return browse(root, me, go);
}

// --- all subjects -----------------------------------------------------------------------------

function folderCard(f, me, go, onEnroll) {
  const open = () => go({ folder: f.id });
  const canOpen = f.mine || f.enrolled;
  return h("article", { class: `folder-card ${canOpen ? "clickable" : ""}`, onClick: canOpen ? open : null },
    h("div", { class: "folder-top" },
      subjectBadge(f.subject),
      h("div", { class: "folder-title" },
        h("b", null, f.subject),
        h("div", { class: "person small-person" }, photoOf(f.teacher, "sm"), h("span", null, `by ${f.teacher.name}`))),
      f.mine ? h("span", { class: "badge brand" }, "Your folder") : f.enrolled ? h("span", { class: "badge ok" }, "Enrolled") : null),
    f.about ? h("p", { class: "folder-about" }, f.about) : null,
    h("div", { class: "folder-stats" },
      h("span", null, icon("file"), plural(f.resources, "material")),
      h("span", null, icon("target"), plural(f.quizzes, "quiz").replace("quizs", "quizzes")),
      h("span", null, icon("users"), plural(f.students, "student"))),
    me.role === "learner" && !f.enrolled
      ? h("button", { class: "btn primary small", onClick: (e) => { e.stopPropagation(); onEnroll(f); } }, "Enrol")
      : canOpen ? h("button", { class: "btn small", onClick: (e) => { e.stopPropagation(); open(); } }, "Open", icon("arrow")) : null);
}

function browse(root, me, go) {
  const st = { rows: null, q: "", newSubject: "", about: "", busy: false };

  async function load() {
    try {
      st.rows = await api.get("/api/subjects");
      paint();
    } catch (e) {
      render(root, errorLine(errorText(e)));
    }
  }

  async function enroll(f) {
    try {
      await api.post(`/api/folders/${f.id}/enroll`);
      toast(`You joined ${f.subject} by ${f.teacher.name}.`);
      go({ folder: f.id });
    } catch (e) {
      toast(errorText(e), "error");
    }
  }

  async function create(e) {
    e.preventDefault();
    st.busy = true;
    paint();
    try {
      const f = await api.post("/api/folders", { subject: st.newSubject, about: st.about });
      toast(`Your ${f.subject} folder is ready. Add material and quizzes.`);
      go({ folder: f.id });
    } catch (err) {
      toast(errorText(err), "error");
      st.busy = false;
      paint();
    }
  }

  function paint() {
    const needle = st.q.trim().toLowerCase();
    const all = st.rows.flatMap((s) => s.folders);
    const mine = all.filter((f) => f.mine || f.enrolled);
    const shown = st.rows
      .map((s) => ({
        ...s,
        folders: s.folders.filter((f) => !needle || s.name.toLowerCase().includes(needle) || f.teacher.name.toLowerCase().includes(needle)),
      }))
      .filter((s) => !needle || s.name.toLowerCase().includes(needle) || s.folders.length);
    const teacher = me.role === "teacher";
    render(root, h("div", { class: "stack" },
      teacher
        ? h("section", { class: "card" },
            h("h2", null, "Start teaching a subject"),
            h("p", { class: "muted", style: { marginTop: -6 } },
              "Pick a subject or type a new one. You get your own folder for it, where you add material and quizzes."),
            h("form", { class: "row", onSubmit: create },
              h("input", {
                type: "text", list: "subject-names", value: st.newSubject, "data-key": "newSubject", required: true, maxlength: "60",
                placeholder: "Subject, e.g. Java", style: { flex: "1 1 200px" }, onInput: (e) => { st.newSubject = e.target.value; },
              }),
              h("datalist", { id: "subject-names" }, st.rows.map((s) => h("option", { value: s.name }))),
              h("input", {
                type: "text", value: st.about, "data-key": "about", maxlength: "300", placeholder: "One line about your course (optional)",
                style: { flex: "2 1 260px" }, onInput: (e) => { st.about = e.target.value; },
              }),
              h("button", { class: "btn primary", type: "submit", disabled: st.busy }, icon("folder"), " Create folder")))
        : null,
      mine.length
        ? h("section", null,
            h("h2", { class: "section-title" }, teacher ? "Your folders" : "Your subjects"),
            h("div", { class: "folder-grid" }, mine.map((f) => folderCard(f, me, go, enroll))))
        : !teacher
          ? h("section", { class: "card hello-card" }, icon("sparkle"),
              h("div", null, h("b", null, "Choose what to study"),
                h("p", { class: "muted", style: { margin: "4px 0 0" } }, "Pick a subject below, then the teacher whose material you like. Enrolling is free and you can leave any time.")))
          : null,
      h("section", null,
        h("div", { class: "row", style: { marginBottom: 10 } },
          h("h2", { class: "section-title", style: { margin: 0 } }, "All subjects"),
          h("div", { class: "spacer" }),
          h("input", {
            type: "search", value: st.q, "data-key": "q", placeholder: "Find a subject or teacher", style: { maxWidth: 260 },
            onInput: (e) => { st.q = e.target.value; paint(); },
          })),
        shown.length === 0 ? h("p", { class: "empty" }, "Nothing matches your search.") : null,
        h("div", { class: "stack" }, shown.filter((s) => s.folders.length).map((s) => h("section", { class: "card subject-block" },
          h("div", { class: "row" }, subjectBadge(s.name, true),
            h("div", null, h("h3", { style: { margin: 0 } }, s.name),
              h("div", { class: "muted small" }, plural(s.folders.length, "teacher")))),
          h("div", { class: "folder-grid", style: { marginTop: 14 } }, s.folders.map((f) => folderCard(f, me, go, enroll)))))),
        shown.some((s) => !s.folders.length)
          ? h("div", { style: { marginTop: 18 } },
              h("h3", { class: "section-title muted" }, "Waiting for a teacher"),
              h("div", { class: "subject-chips" }, shown.filter((s) => !s.folders.length).map((s) => h("span", { class: "subject-chip" },
                subjectBadge(s.name), h("span", null, s.name, h("small", null, teacher ? "Be the first to teach it" : "No teacher yet"))))))
          : null)));
  }

  render(root, skeleton({ cards: 3 }));
  load();
}

// --- one folder -------------------------------------------------------------------------------

function folderPage(root, me, folderId, tab, go) {
  const teacher = me.role === "teacher";
  const tabs = teacher
    ? [["materials", "Materials", "file"], ["quizzes", "Quizzes", "target"], ["bank", "Question bank", "layers"], ["students", "Students", "users"], ["analysis", "Analysis", "bars"]]
    : [["materials", "Materials", "file"], ["quizzes", "Quizzes", "target"], ["results", "My results", "trend"]];
  const current = tabs.some(([k]) => k === tab) ? tab : "materials";
  const st = { folder: null, editAbout: false, about: "" };
  const body = h("div");

  async function load() {
    try {
      st.folder = await api.get(`/api/folders/${folderId}`);
      if (!st.folder.mine && !st.folder.enrolled) {
        paintLocked();
        return;
      }
      paint();
      const views = { materials, quizzes, bank: questionBank, students, analysis, results };
      views[current](body, st.folder, me, go, refresh);
    } catch (e) {
      render(root, errorLine(errorText(e)));
    }
  }

  async function refresh() {
    try {
      st.folder = await api.get(`/api/folders/${folderId}`);
      paint();
    } catch {
      /* the counts are only a summary */
    }
  }

  function paintLocked() {
    const f = st.folder;
    render(root, h("div", { class: "stack" }, header(f),
      h("section", { class: "card" },
        teacher
          ? h("p", { class: "muted" }, "This is another teacher's folder.")
          : [h("p", null, "Enrol to see the material and take the quizzes."),
            h("button", {
              class: "btn primary", onClick: async () => {
                await api.post(`/api/folders/${f.id}/enroll`);
                toast(`You joined ${f.subject} by ${f.teacher.name}.`);
                load();
              },
            }, "Enrol")])));
  }

  async function saveAbout() {
    try {
      st.folder = await api.post(`/api/folders/${folderId}`, { about: st.about });
      st.editAbout = false;
      paint();
    } catch (e) {
      toast(errorText(e), "error");
    }
  }

  async function removeFolder() {
    const f = st.folder;
    if (!window.confirm(`Delete your ${f.subject} folder? All its material, quizzes and results are deleted for good.`)) return;
    await api.del(`/api/folders/${f.id}`);
    toast("Folder deleted.");
    go({});
  }

  async function leave() {
    const f = st.folder;
    if (!window.confirm(`Leave ${f.subject} by ${f.teacher.name}? Your quiz results are kept if you come back.`)) return;
    await api.del(`/api/folders/${f.id}/enroll`);
    toast("You left the folder.");
    go({});
  }

  function header(f) {
    return h("section", { class: "card folder-head", style: { "--h": hue(f.subject) } },
      h("button", { class: "link-btn inline", onClick: () => go({}) }, "← All subjects"),
      h("div", { class: "folder-head-main" },
        subjectBadge(f.subject, true),
        h("div", { style: { flex: 1, minWidth: 0 } },
          h("h2", null, f.subject, h("span", { class: "by" }, ` by ${f.teacher.name}`)),
          st.editAbout
            ? h("div", { class: "row" },
                h("input", { type: "text", value: st.about, "data-key": "aboutEdit", maxlength: "1000", style: { flex: 1 }, onInput: (e) => { st.about = e.target.value; } }),
                h("button", { class: "btn small primary", onClick: saveAbout }, "Save"),
                h("button", { class: "btn small", onClick: () => { st.editAbout = false; paint(); } }, "Cancel"))
            : h("p", { class: "muted", style: { margin: "4px 0 0" } }, f.about || (f.mine ? "Add a line about your course." : "")),
          h("div", { class: "folder-stats", style: { marginTop: 10 } },
            h("span", null, icon("file"), plural(f.resources, "material")),
            h("span", null, icon("target"), plural(f.quizzes, "quiz").replace("quizs", "quizzes")),
            h("span", null, icon("users"), plural(f.students, "student")))),
        h("div", { class: "folder-actions" },
          photoOf(f.teacher),
          f.mine
            ? h("div", { class: "row" },
                h("button", { class: "btn small", onClick: () => { st.editAbout = true; st.about = f.about; paint(); } }, icon("pen"), " Edit"),
                h("button", { class: "btn small danger", onClick: removeFolder }, "Delete"))
            : f.enrolled ? h("button", { class: "btn small", onClick: leave }, "Leave") : null)));
  }

  function paint() {
    const f = st.folder;
    render(root, h("div", { class: "stack" },
      header(f),
      h("div", { class: "tabs", role: "tablist" }, tabs.map(([k, label, ic]) => h("button", {
        role: "tab", class: k === current ? "active" : "", "aria-selected": String(k === current),
        onClick: () => go({ folder: f.id, tab: k }),
      }, icon(ic), " ", label))),
      body));
  }

  render(root, skeleton({ cards: 2 }));
  load();
}

// --- materials ----------------------------------------------------------------------------------

const KIND_ICON = { file: "file", link: "send", note: "book" };

function materials(root, folder, me, go, changed) {
  const st = { rows: null, add: "file", title: "", description: "", url: "", text: "", file: null, busy: false, open: new Set(), storage: null };

  async function load() {
    try {
      [st.rows, st.storage] = await Promise.all([
        api.get(`/api/folders/${folder.id}/resources`),
        folder.mine ? api.get("/api/teacher/storage") : Promise.resolve(null),
      ]);
      paint();
    } catch (e) {
      render(root, errorLine(errorText(e)));
    }
  }

  async function add(e) {
    e.preventDefault();
    st.busy = true;
    paint();
    try {
      if (st.add === "file") {
        if (!st.file) throw new Error("Choose a file first.");
        if (st.storage && st.file.size > st.storage.file_max) {
          throw new Error(`Files can be up to ${fmtSize(st.storage.file_max)}. Upload bigger material to Google Drive and add a link.`);
        }
        const fd = new FormData();
        fd.append("file", st.file);
        fd.append("title", st.title);
        fd.append("description", st.description);
        const resp = await fetch(`/api/folders/${folder.id}/files`, { method: "POST", body: fd, credentials: "same-origin" });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(typeof data.detail === "string" ? data.detail : "The upload failed.");
      } else {
        await api.post(`/api/folders/${folder.id}/resources`, {
          kind: st.add, title: st.title, description: st.description,
          url: st.add === "link" ? st.url : null, text: st.add === "note" ? st.text : null,
        });
      }
      toast("Added. Your students can see it now.");
      Object.assign(st, { title: "", description: "", url: "", text: "", file: null });
      await load();
      changed();
    } catch (err) {
      toast(errorText(err), "error");
    }
    st.busy = false;
    paint();
  }

  async function remove(r) {
    if (!window.confirm(`Delete “${r.title}”?`)) return;
    await api.del(`/api/resources/${r.id}`);
    await load();
    changed();
  }

  function addForm() {
    const s = st.storage;
    const usedPct = s ? Math.min(100, (s.used / s.total) * 100) : 0;
    return h("section", { class: "card" },
      h("h2", null, "Add material"),
      h("div", { class: "seg add-seg" }, [["file", "Upload a file", "upload"], ["link", "Add a link", "send"], ["note", "Write a note", "pen"]].map(([k, l, ic]) => h("button", {
        type: "button", class: st.add === k ? "active" : "", onClick: () => { st.add = k; paint(); },
      }, icon(ic), l))),
      h("form", { onSubmit: add },
        st.add === "file"
          ? h("label", { class: "drop" },
              h("input", {
                type: "file", accept: ".pdf,.ppt,.pptx,.doc,.docx,.xls,.xlsx,.zip,.png,.jpg,.jpeg,.txt,.md,.csv,.py,.java,.sql,.c,.cpp,.ipynb",
                onChange: (e) => { st.file = e.target.files?.[0] ?? null; if (st.file && !st.title) st.title = st.file.name.replace(/\.[^.]+$/, ""); paint(); },
              }),
              icon("upload"),
              h("span", null, st.file ? `${st.file.name} (${fmtSize(st.file.size)})` : "Choose a PDF, slides, document, notes or code"),
              s ? h("span", { class: "muted small" }, `Up to ${fmtSize(s.file_max)} per file`) : null)
          : null,
        h("div", { class: "field-row" },
          h("label", { class: "field" }, h("span", null, "Title"),
            h("input", { type: "text", value: st.title, "data-key": "rtitle", required: true, maxlength: "200", onInput: (e) => { st.title = e.target.value; } })),
          st.add === "link"
            ? h("label", { class: "field" }, h("span", null, "Web address"),
                h("input", { type: "url", value: st.url, "data-key": "rurl", required: true, placeholder: "https://…", onInput: (e) => { st.url = e.target.value; } }))
            : h("label", { class: "field" }, h("span", null, "Short description (optional)"),
                h("input", { type: "text", value: st.description, "data-key": "rdesc", maxlength: "1000", onInput: (e) => { st.description = e.target.value; } }))),
        st.add === "note"
          ? h("label", { class: "field" }, h("span", null, "Note"),
              h("textarea", { rows: "6", value: st.text, "data-key": "rtext", required: true, maxlength: "50000", onInput: (e) => { st.text = e.target.value; } }))
          : null,
        h("div", { class: "row" },
          h("button", { class: "btn primary", type: "submit", disabled: st.busy }, st.busy ? "Adding…" : "Add"),
          h("div", { class: "spacer" }),
          s ? h("div", { class: "storage" },
                h("div", { class: "progress" }, h("span", { style: { width: `${usedPct}%` } })),
                h("span", { class: "muted small" }, `Mentora file storage: ${fmtSize(s.used)} of ${fmtSize(s.total)} used`))
            : null)));
  }

  function row(r) {
    const open = st.open.has(r.id);
    const meta = [r.kind === "file" ? `${r.file_name} · ${fmtSize(r.size)}` : r.kind === "link" ? new URL(r.url).host : "Note", timeAgo(r.created_at)];
    let action;
    if (r.kind === "file") action = h("a", { class: "btn small", href: `/api/resources/${r.id}/file`, target: "_blank", rel: "noopener" }, icon("download"), " Open");
    else if (r.kind === "link") action = h("a", { class: "btn small", href: r.url, target: "_blank", rel: "noopener noreferrer" }, "Open link", icon("arrow"));
    else action = h("button", { class: "btn small", onClick: () => { if (open) st.open.delete(r.id); else st.open.add(r.id); paint(); } }, open ? "Hide" : "Read");
    return h("li", { class: "resource" },
      h("div", { class: "list-row" },
        h("span", { class: `ico kind-${r.kind}` }, icon(KIND_ICON[r.kind])),
        h("div", { class: "body" },
          h("div", { class: "title" }, r.title),
          r.description ? h("div", { class: "small" }, r.description) : null,
          h("div", { class: "muted small" }, meta.join(" · "))),
        action,
        folder.mine ? h("button", { class: "icon-btn", "aria-label": "Delete", onClick: () => remove(r) }, icon("trash")) : null),
      open ? h("div", { class: "note-text" }, r.text) : null);
  }

  function paint() {
    render(root, h("div", { class: "stack" },
      folder.mine ? addForm() : null,
      h("section", { class: "card" },
        h("h2", null, `Material (${st.rows.length})`),
        st.rows.length === 0
          ? h("p", { class: "empty" }, folder.mine ? "Nothing yet. Upload notes or slides, add a link, or write a note." : "Your teacher has not added material yet.")
          : h("ul", { class: "list" }, st.rows.map(row)))));
  }

  render(root, skeleton({ cards: 1 }));
  load();
}

// --- quizzes --------------------------------------------------------------------------------------

function quizzes(root, folder, me, go, changed) {
  const st = { rows: null };

  async function load() {
    try {
      st.rows = await api.get(`/api/folders/${folder.id}/quizzes`);
      paint();
    } catch (e) {
      render(root, errorLine(errorText(e)));
    }
  }

  async function remove(q) {
    if (!window.confirm(`Delete the quiz “${q.title}” and all its results?`)) return;
    await api.del(`/api/quizzes/${q.id}`);
    await load();
    changed();
  }

  function facts(q) {
    return [plural(q.question_count, "question"), `${q.total_points} points`, q.time_limit_min ? `${q.time_limit_min} min` : "no time limit"].join(" · ");
  }

  function row(q) {
    if (folder.mine) {
      return h("li", { class: "list-row" },
        h("span", { class: "ico" }, icon("target")),
        h("div", { class: "body" },
          h("div", { class: "title" }, q.title, " ", q.published ? h("span", { class: "badge ok" }, "Published") : h("span", { class: "badge" }, "Draft")),
          h("div", { class: "muted small" }, `${facts(q)} · taken by ${plural(q.taken_by ?? 0, "student")}`)),
        h("button", { class: "btn small", onClick: () => go({ folder: folder.id, edit: q.id }) }, icon("pen"), " Edit"),
        h("button", { class: "btn small", onClick: () => go({ folder: folder.id, tab: "analysis" }) }, icon("bars"), " Results"),
        h("button", { class: "icon-btn", "aria-label": "Delete", onClick: () => remove(q) }, icon("trash")));
    }
    const best = q.attempts.reduce((b, a) => Math.max(b, percent(a.score, a.max_score)), -1);
    const label = q.open_attempt ? "Continue" : q.attempts.length === 0 ? "Start" : q.attempts_left > 0 ? "Try again" : "Review";
    return h("li", { class: "list-row" },
      h("span", { class: `ico ${best >= 75 ? "green" : best >= 0 ? "orange" : ""}` }, icon(best >= 0 ? "check" : "target")),
      h("div", { class: "body" },
        h("div", { class: "title" }, q.title),
        h("div", { class: "muted small" }, facts(q),
          best >= 0 ? ` · best ${best}%` : "", ` · ${q.attempts_left} of ${plural(q.max_attempts, "attempt")} left`)),
      h("button", { class: `btn small ${label === "Review" ? "" : "primary"}`, onClick: () => go({ quiz: q.id }) }, label));
  }

  function paint() {
    render(root, h("section", { class: "card" },
      h("div", { class: "row", style: { marginBottom: 6 } },
        h("h2", { style: { margin: 0 } }, `Quizzes (${st.rows.length})`),
        h("div", { class: "spacer" }),
        folder.mine ? h("button", { class: "btn primary small", onClick: () => go({ folder: folder.id, edit: "new" }) }, "+ New quiz") : null),
      st.rows.length === 0
        ? h("p", { class: "empty" }, folder.mine ? "No quizzes yet. Create one: questions can have one or several right answers, true/false, or a short typed answer." : "No quizzes yet.")
        : h("ul", { class: "list" }, st.rows.map(row))));
  }

  render(root, skeleton({ cards: 1 }));
  load();
}

// --- students (teacher) ---------------------------------------------------------------------------

function students(root, folder, me, go, changed) {
  const st = { rows: null };

  async function load() {
    try {
      st.rows = await api.get(`/api/folders/${folder.id}/students`);
      paint();
    } catch (e) {
      render(root, errorLine(errorText(e)));
    }
  }

  async function remove(r) {
    if (!window.confirm(`Remove ${r.student.name} from this folder? Their results are kept if they enrol again.`)) return;
    await api.del(`/api/folders/${folder.id}/students/${encodeURIComponent(r.student.username)}`);
    await load();
    changed();
  }

  function paint() {
    render(root, h("section", { class: "card" },
      h("h2", null, `Enrolled students (${st.rows.length})`),
      st.rows.length === 0
        ? h("p", { class: "empty" }, "Nobody has enrolled yet. Students find your folder under Subjects.")
        : h("ul", { class: "list" }, st.rows.map((r) => h("li", { class: "list-row" },
            h("div", { class: "person", style: { flex: 1 } }, photoOf(r.student),
              h("div", null, h("div", { class: "who-name" }, r.student.name), h("div", { class: "muted small" }, `@${r.student.username} · enrolled ${timeAgo(r.enrolled_at)}`))),
            h("button", { class: "btn small danger", onClick: () => remove(r) }, "Remove"))))));
  }

  render(root, skeleton({ cards: 1 }));
  load();
}

// --- analysis (teacher) and my results (student) ------------------------------------------------

function bar(value) {
  const v = value ?? 0;
  const tone = v >= 0.75 ? "good" : v >= 0.5 ? "mid" : "low";
  return h("div", { class: `meter ${tone}` }, h("span", { style: { width: `${Math.round(v * 100)}%` } }));
}

function topicList(topics) {
  if (!topics.length) return h("p", { class: "empty" }, "No answers yet. Add a topic to each question to see strengths and weaknesses.");
  return h("ul", { class: "topic-list" }, topics.map((t) => h("li", null,
    h("span", { class: "topic-name" }, t.topic),
    bar(t.accuracy),
    h("span", { class: "topic-val" }, pct(t.accuracy)),
    h("span", { class: "muted small" }, plural(t.answers, "answer")))));
}

const chips = (items, tone) => (items.length
  ? h("div", { class: "row" }, items.map((t) => h("span", { class: `badge ${tone}` }, t)))
  : h("span", { class: "muted small" }, "–"));

function statCard(ic, label, value, tone = "") {
  return h("div", { class: "card stat" }, h("span", { class: `ico ${tone}` }, icon(ic)),
    h("div", null, h("div", { class: "label" }, label), h("div", { class: "value" }, value)));
}

function analysis(root, folder, me, go) {
  async function load() {
    try {
      paint(await api.get(`/api/folders/${folder.id}/analysis`));
    } catch (e) {
      render(root, errorLine(errorText(e)));
    }
  }

  function studentDrawer(r) {
    openDrawer(r.student?.name ?? "Student", (close) => h("div", { class: "stack" },
      h("div", { class: "person" }, photoOf(r.student, "big"),
        h("div", null, h("div", { class: "who-name" }, r.student?.name), h("div", { class: "muted small" }, `@${r.student?.username}`))),
      h("div", { class: "mini-stats" },
        h("div", null, h("b", null, r.quizzes_taken), h("span", null, "quizzes taken")),
        h("div", null, h("b", null, pct(r.average)), h("span", null, "average (best tries)"))),
      h("div", null, h("h3", null, "Strengths"), chips(r.strengths, "ok")),
      h("div", null, h("h3", null, "Needs work"), chips(r.weaknesses, "danger")),
      h("div", null, h("h3", null, "By topic"), topicList(r.topics)),
      h("div", null, h("h3", null, "Recent attempts"),
        r.recent.length
          ? h("ul", { class: "list" }, r.recent.map((a) => h("li", { class: "list-row" },
              h("div", { class: "body" }, `${percent(a.score, a.max_score)}% (${a.score} / ${a.max_score})`),
              h("button", { class: "btn small", onClick: () => { close(); go({ attempt: a.attempt_id }); } }, "See answers"))))
          : h("p", { class: "empty" }, "No quizzes taken yet."))));
  }

  function paint(d) {
    const taken = d.students.filter((s) => s.average !== null);
    const avg = taken.length ? taken.reduce((a, s) => a + s.average, 0) / taken.length : null;
    const needHelp = taken.filter((s) => s.average < 0.5).length;
    render(root, h("div", { class: "stack" },
      h("div", { class: "grid cols-4" },
        statCard("users", "Students enrolled", d.students.length),
        statCard("target", "Quizzes", d.quizzes.length),
        statCard("trend", "Class average", pct(avg), "green"),
        statCard("alert", "Below 50%", needHelp, needHelp ? "red" : "")),
      h("div", { class: "grid cols-2" },
        h("section", { class: "card" }, h("h2", null, "Class topics (weakest first)"), topicList(d.topics)),
        h("section", { class: "card" }, h("h2", null, "Quizzes"),
          d.quizzes.length === 0 ? h("p", { class: "empty" }, "No quizzes yet.") : null,
          h("ul", { class: "list" }, d.quizzes.map((q) => h("li", { class: "quiz-stat" },
            h("details", null,
              h("summary", null,
                h("div", { class: "row" },
                  h("b", null, q.title), q.published ? null : h("span", { class: "badge" }, "Draft"),
                  h("div", { class: "spacer" }),
                  h("span", { class: "muted small" }, `${plural(q.students, "student")} · avg ${pct(q.average)} · high ${pct(q.highest)} · low ${pct(q.lowest)}`)),
                bar(q.average)),
              h("ol", { class: "q-acc" }, q.questions.map((x) => h("li", null,
                h("span", { class: "q-acc-text" }, x.text, x.topic ? h("span", { class: "muted small" }, ` · ${x.topic}`) : null),
                bar(x.accuracy), h("span", { class: "topic-val" }, pct(x.accuracy))))))))))),
      h("section", { class: "card" },
        h("h2", null, "Students (lowest average first)"),
        d.students.length === 0 ? h("p", { class: "empty" }, "Nobody has enrolled yet.") : null,
        d.students.length
          ? h("div", { class: "overflow" }, h("table", null,
              h("thead", null, h("tr", null, ["Student", "Quizzes", "Average", "Strengths", "Needs work", "Last activity"].map((t) => h("th", null, t)))),
              h("tbody", null, d.students.map((r) => h("tr", {
                class: "clickable", tabindex: "0", onClick: () => studentDrawer(r), onKeydown: (e) => { if (e.key === "Enter") studentDrawer(r); },
              },
                h("td", null, h("div", { class: "person" }, photoOf(r.student),
                  h("div", null, h("div", { class: "who-name" }, r.student?.name), h("div", { class: "muted small" }, `@${r.student?.username}`)))),
                h("td", null, r.quizzes_taken),
                h("td", null, r.average === null ? "–" : h("div", { class: "row nowrap" }, bar(r.average), pct(r.average))),
                h("td", null, chips(r.strengths.slice(0, 3), "ok")),
                h("td", null, chips(r.weaknesses.slice(0, 3), "danger")),
                h("td", { class: "muted" }, r.last_activity ? timeAgo(r.last_activity) : "never"))))))
          : null),
      practiceSlot));
    practiceSection(folder).then((el) => render(practiceSlot, el)).catch(() => render(practiceSlot));
  }

  const practiceSlot = h("div");
  render(root, skeleton({ cards: 2, stats: true }));
  load();
}

function results(root, folder, me, go) {
  async function load() {
    try {
      paint(await api.get(`/api/folders/${folder.id}/my-results`));
    } catch (e) {
      render(root, errorLine(errorText(e)));
    }
  }

  function paint(d) {
    render(root, h("div", { class: "stack" },
      h("div", { class: "grid cols-2" },
        statCard("target", "Quizzes taken", d.quizzes_taken),
        statCard("trend", "Your average (best tries)", pct(d.average), "green")),
      h("div", { class: "grid cols-2" },
        h("section", { class: "card" }, h("h2", null, "Strengths"), chips(d.strengths, "ok"),
          h("h2", { style: { marginTop: 18 } }, "Needs work"), chips(d.weaknesses, "danger")),
        h("section", { class: "card" }, h("h2", null, "By topic"), topicList(d.topics))),
      h("section", { class: "card" },
        h("h2", null, "Your attempts"),
        d.attempts.length === 0
          ? h("p", { class: "empty" }, "You have not taken a quiz here yet.", " ",
              h("button", { class: "link-btn inline", onClick: () => go({ folder: folder.id, tab: "quizzes" }) }, "See the quizzes"))
          : h("ul", { class: "list" }, d.attempts.map((a) => h("li", { class: "list-row" },
              h("span", { class: `ico ${percent(a.score, a.max_score) >= 75 ? "green" : "orange"}` }, icon("check")),
              h("div", { class: "body" }, h("div", { class: "title" }, a.quiz_title),
                h("div", { class: "muted small" }, `${percent(a.score, a.max_score)}% · ${a.score} / ${a.max_score} · ${timeAgo(a.submitted_at)}${a.late ? " · late" : ""}`)),
              h("button", { class: "btn small", onClick: () => go({ attempt: a.id }) }, "See answers")))))));
  }

  render(root, skeleton({ cards: 2 }));
  load();
}
