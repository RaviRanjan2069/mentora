import { api, errorText, pct, timeAgo } from "../api.js";
import { hBars, lineChart, statCard } from "../charts.js";
import { h, render } from "../dom.js";
import { errorLine, skeleton } from "../ui.js";

export function systemStatus() {
  const section = h("section", { class: "card" }, h("h2", null, "System status"), h("p", { class: "muted" }, "Checking…"));
  api.get("/api/teacher/status").then((rows) => render(section,
    h("h2", null, "System status"),
    h("ul", { class: "list" }, rows.map((r) => h(
      "li", { class: "list-row" },
      h("span", { class: `status-dot ${r.state}`, "aria-hidden": "true" }),
      h("div", { class: "body" }, h("div", { class: "title" }, r.name), h("div", { class: "muted" }, r.detail)),
      h("span", { class: "muted small" }, r.state)))))).catch((e) => render(section, h("h2", null, "System status"), errorLine(errorText(e))));
  return section;
}

export default function overview(root) {
  render(root, skeleton({ stats: true, cards: 2 }));
  api.get("/api/teacher/overview").then((data) => {
    const st = data.stats;
    render(root, h(
      "div", { class: "stack" },
      st.simulated_students > 0
        ? h("div", { class: "notice", role: "note" },
            h("span", { class: "notice-tag" }, "Demo data"),
            h("span", { class: "notice-text" },
              `${st.simulated_students} of ${st.total_students} students are simulated (ids starting “sim_”). `
              + "Their data fills the charts until real students use Mentora."))
        : null,
      h("div", { class: "grid cols-4" },
        statCard({ icon: "users", label: "Total students", value: st.total_students }),
        statCard({
          icon: "activity", tone: "green", label: "Active this week", value: st.active_week,
          note: st.total_students ? `${pct(st.active_week / st.total_students)} of the class` : null,
        }),
        statCard({ icon: "target", tone: "orange", label: "Average score", value: pct(st.average_score), note: "Correct answers, all practice" }),
        statCard({ icon: "alert", tone: "red", label: "At-risk students", value: st.at_risk, note: h("a", { href: "#/teacher/students" }, "See who") })),
      h("div", { class: "grid cols-wide-narrow" },
        h("section", { class: "card" },
          h("h2", null, "Class progress by week"),
          lineChart(data.weekly.map((w) => `Wk ${w.week}`), [
            { name: "Average score", color: "var(--series-1)", values: data.weekly.map((w) => w.average_score) },
            { name: "Goal completion", color: "var(--series-2)", values: data.weekly.map((w) => w.goal_completion) },
          ])),
        h("section", { class: "card" },
          h("h2", null, "Topic-wise performance"),
          hBars(data.topics.map((t) => ({ label: t.concept, value: t.accuracy, note: `${t.answers} answers` }))))),
      h("div", { class: "grid cols-wide-narrow" },
        h("section", { class: "card overflow" },
          h("h2", null, "Recent student activity"),
          data.activity.length === 0
            ? h("p", { class: "empty" }, "No activity yet.")
            : h("table", { class: "data" },
                h("thead", null, h("tr", null, h("th", null, "Student"), h("th", null, "Activity"), h("th", null, "When"))),
                h("tbody", null, data.activity.map((a) => h("tr", null,
                  h("td", null, h("code", null, a.learner)), h("td", null, a.activity), h("td", { class: "muted" }, timeAgo(a.at))))))),
        systemStatus()),
    ));
  }).catch((e) => render(root, errorLine(errorText(e))));
}
