import { api, errorText, pct, timeAgo } from "../api.js";
import { heatmap, masteryBars, phaseBars, SRL_ROWS } from "../charts.js";
import { h, icon, plural, render } from "../dom.js";
import { errorLine, openDrawer, skeleton } from "../ui.js";

function studentPanel(row) {
  openDrawer(`Student ${row.learner}`, (close) => {
    const body = h("div", null,
      h("div", { class: "row" },
        row.at_risk ? h("span", { class: "badge danger" }, "At risk") : h("span", { class: "badge ok" }, "On track"),
        row.simulated ? h("span", { class: "badge" }, "Simulated demo learner") : null,
        h("span", { class: "muted" }, `Last active ${row.last_active ? timeAgo(row.last_active) : "never"}`)),
      h("div", { class: "mt" }, skeleton({ cards: 2 })));
    api.get(`/api/teacher/students/${encodeURIComponent(row.id)}`).then((d) => {
      body.lastChild.replaceWith(
        h("section", null, h("div", { class: "mini-stats" },
          h("div", null, h("b", null, d.sessions), h("span", null, "sessions")),
          h("div", null, h("b", null, pct(row.quiz_average)), h("span", null, `quiz average (${row.answers} answers)`)),
          h("div", null, h("b", null, pct(row.dropout_risk)), h("span", null, "dropout estimate")))),
        h("section", null, h("h3", null, "Activity, last 12 weeks"), heatmap(d.calendar)),
        h("section", null, h("h3", null, "Self-regulated learning"),
          d.srl.has_data ? phaseBars(SRL_ROWS(d.srl)) : h("p", { class: "empty" }, "No sessions with enough data yet.")),
        h("section", null, h("h3", null, "Goals"),
          d.goals.length === 0 ? h("p", { class: "empty" }, "No goals set.") : null,
          h("ul", { class: "list" }, d.goals.map((g) => h(
            "li", { class: "list-row" },
            h("span", { class: `ico ${g.status === "attained" ? "green" : g.status === "abandoned" ? "red" : ""}` }, icon("target")),
            h("div", { class: "body" },
              h("div", { class: "title" }, g.text),
              h("div", { class: "muted" },
                `${g.status}${g.smart_score !== null ? ` · clarity ${pct(g.smart_score)}` : ""} · ${timeAgo(g.created_at)}`)))))),
        h("section", null, h("h3", null, "Recent activity"),
          h("ul", { class: "list" }, d.activity.map((a) => h(
            "li", { class: "row between" }, h("span", null, a.text), h("span", { class: "muted" }, timeAgo(a.at)))))),
        h("section", null, h("h3", null, "Estimated mastery"), masteryBars(d.mastery)),
        row.open_escalations > 0
          ? h("a", { class: "btn primary mt", href: "#/teacher/escalations", onClick: close },
              icon("alert"), ` ${plural(row.open_escalations, "open escalation")}`)
          : null);
    }).catch((e) => body.lastChild.replaceWith(errorLine(errorText(e))));
    return body;
  });
}

export default function students(root) {
  const st = { rows: null, filter: "all", q: "" };

  function paint() {
    const shown = st.rows.filter((r) =>
      (st.filter === "risk" ? r.at_risk : st.filter === "real" ? !r.simulated : true)
      && (!st.q.trim() || r.learner.toLowerCase().includes(st.q.trim().toLowerCase())));
    render(root, h(
      "section", { class: "card overflow" },
      h("div", { class: "row between" },
        h("h2", { style: { margin: 0 } }, `Students (${shown.length})`),
        h("div", { class: "row" },
          h("input", {
            type: "search", placeholder: "Find a student id", value: st.q, "data-key": "q",
            "aria-label": "Find a student", style: { width: 200 },
            onInput: (e) => { st.q = e.target.value; paint(); },
          }),
          h("div", { class: "tabs", role: "tablist", style: { margin: 0 } },
            [["all", "All"], ["risk", "At risk"], ["real", "Real only"]].map(([f, l]) => h(
              "button", {
                role: "tab", "aria-selected": String(st.filter === f), class: st.filter === f ? "active" : "",
                onClick: () => { st.filter = f; paint(); },
              }, l))))),
      h("p", { class: "muted" },
        "Students appear under pseudonyms. Select a row for details. “At risk” means a dropout estimate of 50% or more, "
        + "accuracy under 40% over at least five answers, or an open wellbeing escalation."),
      h("table", { class: "data" },
        h("thead", null, h("tr", null,
          ["Student", "Sessions", "Last active", "Mean mastery", "Quiz average", "Answers", "Dropout estimate", "Status"]
            .map((x) => h("th", null, x)))),
        h("tbody", null, shown.map((r) => h(
          "tr", {
            class: "clickable", tabindex: "0", onClick: () => studentPanel(r),
            onKeydown: (e) => { if (e.key === "Enter") studentPanel(r); },
          },
          h("td", null, h("code", null, r.learner), r.simulated ? h("span", { class: "muted small" }, " (simulated)") : null),
          h("td", null, r.sessions),
          h("td", { class: "muted" }, r.last_active ? timeAgo(r.last_active) : "never"),
          h("td", null, pct(r.mean_mastery)),
          h("td", null, pct(r.quiz_average)),
          h("td", null, r.answers),
          h("td", null, pct(r.dropout_risk)),
          h("td", null,
            r.at_risk ? h("span", { class: "badge danger" }, "At risk") : h("span", { class: "badge" }, "OK"),
            r.open_escalations > 0
              ? h("span", { class: "small", style: { color: "var(--danger)" } }, ` ${r.open_escalations} open`) : null))))),
    ));
  }

  render(root, skeleton({ cards: 1 }));
  api.get("/api/teacher/students").then((rows) => { st.rows = rows; paint(); })
    .catch((e) => render(root, errorLine(errorText(e))));
}
