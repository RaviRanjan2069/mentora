import { api, errorText, uploadFile } from "../api.js";
import { h, icon, plural, render } from "../dom.js";
import { errorLine, toast } from "../ui.js";

function materials() {
  const section = h("section", { class: "card" });
  const st = { rows: null, busy: false, result: null, error: null };

  async function reload() {
    st.rows = await api.get("/api/teacher/materials");
    paint();
  }

  async function onFile(e) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    Object.assign(st, { busy: true, error: null, result: null });
    paint();
    try {
      st.result = await uploadFile("/api/teacher/materials", f);
      toast(`Added ${plural(st.result.passages, "passage")} from ${st.result.source}`);
      await reload();
    } catch (err) {
      st.error = errorText(err);
    } finally {
      st.busy = false;
      paint();
    }
  }

  async function remove(source) {
    if (!window.confirm(`Remove all passages from ${source}? The tutor will stop citing it.`)) return;
    await api.del(`/api/teacher/materials/${encodeURIComponent(source)}`);
    await reload();
    toast(`Removed ${source}`);
  }

  function paint() {
    const r = st.result;
    render(section,
      h("div", { class: "row between" },
        h("h2", { style: { margin: 0 } }, "Course material"),
        h("label", { class: `btn primary ${st.busy ? "disabled" : ""}` },
          icon("upload"), ` ${st.busy ? "Uploading…" : "Upload file"}`,
          h("input", { type: "file", accept: ".md,.txt,.pdf,.pptx,.yaml,.yml", disabled: st.busy, hidden: true, onChange: onFile }))),
      h("p", { class: "muted" },
        "Markdown, text, PDF, PowerPoint or an FAQ YAML file, up to 20 MB. The tutor answers only from this material."),
      st.error ? h("p", { class: "error" }, st.error) : null,
      r
        ? h("div", { class: "banner" },
            `Added ${plural(r.passages, "passage")} from `, h("b", null, r.source), ".",
            r.quarantined.length > 0
              ? [` ${r.quarantined.length} passage(s) looked like instructions to the AI and were left out:`,
                  h("ul", null, r.quarantined.map((q) => h("li", { class: "small" }, q.text)))]
              : null)
        : null,
      st.rows && st.rows.length === 0 ? h("p", { class: "empty" }, "No material yet.") : null,
      h("ul", { class: "list" }, (st.rows ?? []).map((m) => h(
        "li", { class: "list-row" },
        h("span", { class: "ico orange" }, icon("file")),
        h("div", { class: "body" },
          h("div", { class: "title" }, m.source),
          h("div", { class: "muted" }, `${m.passages} passages${m.week ? ` · week ${m.week}` : ""}`)),
        h("button", { class: "btn small danger", onClick: () => remove(m.source) }, icon("trash"), " Remove")))));
  }

  paint();
  reload().catch((e) => { st.error = errorText(e); paint(); });
  return section;
}

function memoryQueue() {
  const section = h("section", { class: "card" });
  let rows = null;

  async function reload() {
    rows = await api.get("/api/teacher/memory-queue");
    paint();
  }

  async function review(id, approve) {
    await api.post(`/api/teacher/memory-queue/${id}`, { approve });
    await reload();
    toast(approve ? "Note approved for the course" : "Note rejected");
  }

  function paint() {
    render(section,
      h("h2", null, "Course-memory review"),
      h("p", { class: "muted" }, "Notes proposed for every learner in the course. None is used until you approve it."),
      rows && rows.length === 0 ? h("p", { class: "empty" }, "Nothing to review.") : null,
      h("ul", { class: "list" }, (rows ?? []).map((r) => h(
        "li", { class: "list-row" },
        h("div", { class: "body" }, r.text),
        h("button", { class: "btn small primary", onClick: () => review(r.id, true) }, "Approve"),
        h("button", { class: "btn small danger", onClick: () => review(r.id, false) }, "Reject")))));
  }

  paint();
  reload().catch((e) => render(section, h("h2", null, "Course-memory review"), errorLine(errorText(e))));
  return section;
}

const PAGE = 25;

function items() {
  const section = h("section", { class: "card overflow" });
  const st = { rows: null, q: "", concept: "", page: 0 };

  function paint() {
    const rows = st.rows ?? [];
    const concepts = [...new Set(rows.flatMap((i) => i.concepts))].sort();
    const needle = st.q.trim().toLowerCase();
    const shown = rows.filter((i) =>
      (!st.concept || i.concepts.includes(st.concept))
      && (!needle || i.text.toLowerCase().includes(needle) || (i.external_id ?? "").includes(needle)));
    const pages = Math.max(1, Math.ceil(shown.length / PAGE));
    st.page = Math.min(st.page, pages - 1);
    const slice = shown.slice(st.page * PAGE, st.page * PAGE + PAGE);
    render(section,
      h("div", { class: "row between" },
        h("h2", { style: { margin: 0 } },
          `Practice questions (${shown.length}${shown.length !== rows.length ? ` of ${rows.length}` : ""})`),
        h("div", { class: "row" },
          h("input", {
            type: "search", placeholder: "Search questions or ids", value: st.q, "data-key": "q",
            "aria-label": "Search questions", style: { width: 220 },
            onInput: (e) => { st.q = e.target.value; st.page = 0; paint(); },
          }),
          h("select", {
            "aria-label": "Filter by concept", style: { width: "auto" },
            onChange: (e) => { st.concept = e.target.value; st.page = 0; paint(); },
          },
          h("option", { value: "" }, "All concepts"),
          concepts.map((c) => h("option", { value: c, selected: st.concept === c }, c.replace(/_/g, " ")))))),
      h("p", { class: "muted" },
        "Includes the generated question bank (data/sample/question_bank.yaml): every answer key there was computed by "
        + "running the question's code."),
      h("table", { class: "data" },
        h("thead", null, h("tr", null, ["Id", "Question", "Type", "Answer key", "Concepts"].map((x) => h("th", null, x)))),
        h("tbody", null, slice.map((i) => h(
          "tr", null,
          h("td", { class: "muted" }, i.external_id ?? i.id),
          h("td", null, h("pre", { style: { margin: 0, whiteSpace: "pre-wrap", font: "inherit", maxWidth: 460 } }, i.text)),
          h("td", null, i.item_type, i.graded ? h("span", { class: "badge warn" }, "graded") : null),
          h("td", null, h("code", null, i.answer_key ?? "–")),
          h("td", { class: "muted" }, i.concepts.join(", ")))))),
      shown.length === 0 ? h("p", { class: "empty" }, "No questions match.") : null,
      pages > 1
        ? h("div", { class: "row mt", style: { justifyContent: "flex-end" } },
            h("button", { class: "btn small", disabled: st.page === 0, onClick: () => { st.page -= 1; paint(); } }, "Previous"),
            h("span", { class: "muted" }, `Page ${st.page + 1} of ${pages}`),
            h("button", { class: "btn small", disabled: st.page + 1 >= pages, onClick: () => { st.page += 1; paint(); } }, "Next"))
        : null);
  }

  paint();
  api.get("/api/teacher/items").then((rows) => { st.rows = rows; paint(); })
    .catch((e) => render(section, errorLine(errorText(e))));
  return section;
}

export default function content(root) {
  render(root, h("div", { class: "stack" }, materials(), memoryQueue(), items()));
}
