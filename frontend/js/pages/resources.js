import { api, errorText } from "../api.js";
import { h, hashParam, icon, render } from "../dom.js";
import { errorLine, skeleton } from "../ui.js";

export default function resources(root) {
  const st = { rows: null, open: hashParam("id"), concept: hashParam("concept"), q: "", hits: null };

  function toggle(id) {
    st.open = st.open === id ? null : id;
    if (st.open) api.post(`/api/resources/${id}/view`).catch(() => undefined);
    paint();
  }

  async function search(e) {
    e.preventDefault();
    if (st.q.trim().length < 2) return;
    const r = await api.get(`/api/rag/search?q=${encodeURIComponent(st.q.trim())}`);
    st.hits = r.hits;
    paint();
  }

  function weeks() {
    const by = new Map();
    for (const r of st.rows) {
      if (st.concept && !r.concepts.includes(st.concept)) continue;
      const k = r.week ? `Week ${r.week}` : "General";
      by.set(k, [...(by.get(k) ?? []), r]);
    }
    return [...by.entries()];
  }

  function paint() {
    render(root, h(
      "div", { class: "stack" },
      h("section", { class: "card" },
        h("form", { class: "row", onSubmit: search },
          h("input", {
            type: "search", value: st.q, "data-key": "q", style: { flex: 1 }, "aria-label": "Search course material",
            placeholder: "Search the course material, e.g. Does range(10) include 10?",
            onInput: (e) => { st.q = e.target.value; },
          }),
          h("button", { class: "btn primary", type: "submit" }, "Search")),
        st.hits
          ? h("ul", { class: "list mt" },
              st.hits.length === 0 ? h("li", { class: "empty" }, "No passages found.") : null,
              st.hits.map((hit) => h(
                "li", { class: "list-row" },
                h("span", { class: "ico" }, icon("file")),
                h("div", { class: "body" },
                  h("div", { class: "title" }, hit.section, " ", h("span", { class: "muted" }, `· week ${hit.week ?? "–"}`)),
                  h("div", { class: "muted" }, hit.text)))))
          : null),
      st.concept
        ? h("p", { class: "muted" }, "Showing material for one concept. ", h("a", { href: "#/resources" }, "Show everything"))
        : null,
      weeks().map(([week, list]) => h(
        "section", { class: "card" },
        h("h2", null, week),
        h("ul", { class: "list" }, list.map((r) => h(
          "li", { id: `passage-${r.id}` },
          h("div", { class: "list-row" },
            h("span", { class: "ico orange" }, icon("book")),
            h("div", { class: "body" },
              h("div", { class: "title" }, r.section ?? r.id),
              h("div", { class: "muted" }, `${r.source?.split("#")[0] ?? ""}${r.concepts.length ? ` · ${r.concepts.join(", ")}` : ""}`)),
            h("button", { class: "btn small", "aria-expanded": String(st.open === r.id), onClick: () => toggle(r.id) },
              icon("eye"), ` ${st.open === r.id ? "Close" : "Read"}`)),
          st.open === r.id ? h("p", { style: { whiteSpace: "pre-wrap", margin: "10px 0 0 46px" } }, r.text) : null))))),
    ));
  }

  render(root, skeleton({ cards: 3 }));
  api.get("/api/resources")
    .then((rows) => {
      st.rows = rows;
      paint();
      // A citation link opens its passage: bring it into view.
      if (st.open) root.querySelector(`#passage-${CSS.escape(st.open)}`)?.scrollIntoView({ block: "center" });
    })
    .catch((e) => render(root, errorLine(errorText(e))));
}
