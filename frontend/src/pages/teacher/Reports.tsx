import { Policy } from "../../api";
import Icon from "../../icons";
import { useLoad } from "../../session";

export default function Reports() {
  const [policies] = useLoad<Policy[]>("/api/teacher/policies");
  const withReport = (policies ?? []).filter((p) => typeof p.metrics.report_markdown === "string");
  return (
    <div className="stack">
      <section className="card">
        <h2>Class report</h2>
        <p className="muted">One row per student (pseudonymous): sessions, answers, quiz average, mean mastery, dropout estimate and open escalations.</p>
        <a className="btn primary" href="/api/teacher/reports/class.csv" download><Icon name="file" /> Download CSV</a>
      </section>
      <section className="card">
        <h2>Policy evaluation reports</h2>
        {withReport.length === 0 && <p className="empty">No policy has been evaluated yet. Run training on the Model Training page.</p>}
        {withReport.map((p) => (
          <details key={p.version}>
            <summary>{p.version} ({p.status})</summary>
            <pre className="report">{p.metrics.report_markdown as string}</pre>
          </details>
        ))}
      </section>
    </div>
  );
}
