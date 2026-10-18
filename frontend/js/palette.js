// Ctrl+K / Cmd+K: jump to a page, search the course material, or (students) ask the tutor.
import { api } from "./api.js";
import { h, icon, render } from "./dom.js";

/** pages: [{label, hint?, icon, run}]; ask(q) for students. Returns close(). */
export function openPalette(pages, ask) {
  let q = "";
  let hits = [];
  let active = 0;
  let timer = 0;

  const list = h("ul", { class: "palette-list", id: "palette-list", role: "listbox" });
  const input = h("input", {
    placeholder: "Go to a page, search course notes…", "aria-label": "Search", role: "combobox",
    "aria-expanded": "true", "aria-controls": "palette-list",
  });
  const root = h(
    "div",
    { class: "overlay top", onMousedown: (e) => { if (e.target === e.currentTarget) close(); } },
    h("div", { class: "palette", role: "dialog", "aria-modal": "true", "aria-label": "Search and jump" },
      h("div", { class: "palette-input" }, icon("search"), input, h("kbd", null, "Esc")),
      list,
      h("div", { class: "palette-foot muted small" },
        "↑ ↓ to move · Enter to open · type 3+ letters to search the course notes")),
  );

  function entries() {
    const needle = q.trim().toLowerCase();
    const out = pages.filter((p) => !needle || p.label.toLowerCase().includes(needle));
    if (ask && needle.length >= 3) {
      out.push({ label: `Ask the tutor: “${q.trim()}”`, icon: "bot", run: () => ask(q.trim()) });
    }
    for (const hit of hits) {
      out.push({
        label: hit.section ?? hit.id, hint: hit.text.slice(0, 90), icon: "book",
        run: () => { window.location.hash = `#/resources?id=${hit.id}`; },
      });
    }
    return out;
  }

  function choose(e) {
    close();
    e.run();
  }

  function paint() {
    const items = entries();
    active = Math.min(active, Math.max(items.length - 1, 0));
    render(list,
      items.length === 0 ? h("li", { class: "empty", style: { padding: "10px 14px" } }, "No matches.") : null,
      items.map((e, i) => h(
        "li", {
          role: "option", "aria-selected": String(i === active), class: i === active ? "active" : "",
          onMouseenter: () => { active = i; paint(); },
          onMousedown: (ev) => { ev.preventDefault(); choose(e); },
        },
        icon(e.icon),
        h("div", { style: { minWidth: 0 } },
          h("div", { class: "title" }, e.label),
          e.hint ? h("div", { class: "muted small ellipsis" }, e.hint) : null),
      )));
  }

  function search() {
    window.clearTimeout(timer);
    const query = q.trim();
    if (query.length < 3) {
      hits = [];
      paint();
      return;
    }
    timer = window.setTimeout(() => {
      api.get(`/api/rag/search?q=${encodeURIComponent(query)}`)
        .then((r) => { hits = r.hits.slice(0, 4); })
        .catch(() => { hits = []; })
        .finally(() => { active = 0; paint(); });
    }, 250);
  }

  input.addEventListener("input", () => {
    q = input.value;
    active = 0;
    paint();
    search();
  });
  input.addEventListener("keydown", (ev) => {
    const items = entries();
    if (ev.key === "ArrowDown") {
      ev.preventDefault();
      active = Math.min(active + 1, items.length - 1);
      paint();
    } else if (ev.key === "ArrowUp") {
      ev.preventDefault();
      active = Math.max(active - 1, 0);
      paint();
    } else if (ev.key === "Enter" && items[active]) {
      ev.preventDefault();
      choose(items[active]);
    } else if (ev.key === "Escape") {
      close();
    }
  });

  function close() {
    window.clearTimeout(timer);
    root.remove();
  }

  document.body.appendChild(root);
  paint();
  input.focus();
  return close;
}
