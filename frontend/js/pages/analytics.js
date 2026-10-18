import { actionLabel, api, errorText } from "../api.js";
import { hBars } from "../charts.js";
import { h, render } from "../dom.js";
import { errorLine, skeleton } from "../ui.js";

export default function analytics(root) {
  render(root, skeleton({ cards: 2 }));
  api.get("/api/teacher/decisions?limit=200").then((rows) => {
    const counts = new Map();
    for (const d of rows) {
      const agent = d.action.split(".")[0];
      counts.set(agent, (counts.get(agent) ?? 0) + 1);
    }
    const mix = [...counts.entries()].sort((a, b) => b[1] - a[1])
      .map(([label, n]) => ({ label, value: n / rows.length, note: `${n} decisions` }));
    const filtered = rows.filter((d) => Object.keys(d.removed).length > 0).length;
    const escalated = rows.filter((d) => d.escalated).length;
    render(root, h(
      "div", { class: "stack" },
      h("div", { class: "grid cols-2" },
        h("section", { class: "card" },
          h("h2", null, "Which agents the tutor used"),
          h("p", { class: "muted", style: { marginTop: -6 } }, `Share of the last ${rows.length} decisions.`),
          hBars(mix)),
        h("section", { class: "card" },
          h("h2", null, "Safety filter"),
          h("table", { class: "data" }, h("tbody", null,
            h("tr", null, h("th", null, "Decisions where the filter removed options"), h("td", null, `${filtered} of ${rows.length}`)),
            h("tr", null, h("th", null, "Escalated to you"), h("td", null, escalated)),
            h("tr", null, h("th", null, "Policies in use"),
              h("td", null, [...new Set(rows.map((d) => d.policy_version))].join(", ") || "–")))),
          h("p", { class: "muted" },
            "Every action is chosen by the policy from the actions the safety filter allows; the language model only phrases it."))),
      h("section", { class: "card overflow" },
        h("h2", null, "Recent tutor decisions"),
        h("table", { class: "data" },
          h("thead", null, h("tr", null,
            ["When", "Student", "Action", "Why the policy chose it", "Filtered out", "Probability"].map((x) => h("th", null, x)))),
          h("tbody", null, rows.slice(0, 100).map((d) => h(
            "tr", null,
            h("td", { class: "muted" }, new Date(d.at).toLocaleString()),
            h("td", null, h("code", null, d.learner)),
            h("td", null, actionLabel(d.action), d.escalated ? h("span", { class: "badge danger" }, " escalated") : null),
            h("td", null, d.reason, d.why ? h("div", { class: "muted small" }, d.why) : null),
            h("td", null,
              Object.keys(d.removed).length === 0
                ? h("span", { class: "muted" }, "nothing")
                : Object.entries(d.removed).map(([k, v]) => h("div", null, `${k}: ${v.length}`)),
              h("div", { class: "muted small" }, `${d.feasible_count} allowed`)),
            h("td", null, d.propensity.toFixed(2))))))),
    ));
  }).catch((e) => render(root, errorLine(errorText(e))));
}
