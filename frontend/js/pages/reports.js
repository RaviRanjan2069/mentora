import { api } from "../api.js";
import { h, icon, render } from "../dom.js";

export default function reports(root) {
  const evaluations = h("section", { class: "card" }, h("h2", null, "Policy evaluation reports"));
  render(root, h(
    "div", { class: "stack" },
    h("section", { class: "card" },
      h("h2", null, "Class report"),
      h("p", { class: "muted" },
        "One row per student (pseudonymous): sessions, answers, quiz average, mean mastery, dropout estimate and open escalations."),
      h("a", { class: "btn primary", href: "/api/teacher/reports/class.csv", download: true }, icon("file"), " Download CSV")),
    evaluations,
  ));
  api.get("/api/teacher/policies").then((policies) => {
    const withReport = policies.filter((p) => typeof p.metrics.report_markdown === "string");
    render(evaluations,
      h("h2", null, "Policy evaluation reports"),
      withReport.length === 0
        ? h("p", { class: "empty" }, "No policy has been evaluated yet. Run training on the Model Training page.")
        : null,
      withReport.map((p) => h("details", null,
        h("summary", null, `${p.version} (${p.status})`),
        h("pre", { class: "report" }, p.metrics.report_markdown))));
  }).catch(() => undefined);
}
