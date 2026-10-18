import { actionLabel, Decision } from "../../api";
import { HBars } from "../../components/Charts";
import { Skeleton } from "../../components/ui";
import { useLoad } from "../../session";

export default function Analytics() {
  const [rows] = useLoad<Decision[]>("/api/teacher/decisions?limit=200");
  if (!rows) return <Skeleton cards={2} />;
  const counts = new Map<string, number>();
  for (const d of rows) {
    const agent = d.action.split(".")[0];
    counts.set(agent, (counts.get(agent) ?? 0) + 1);
  }
  const mix = [...counts.entries()].sort((a, b) => b[1] - a[1])
    .map(([label, n]) => ({ label, value: n / rows.length, note: `${n} decisions` }));
  const filtered = rows.filter((d) => Object.keys(d.removed).length > 0).length;
  const escalated = rows.filter((d) => d.escalated).length;

  return (
    <div className="stack">
      <div className="grid cols-2">
        <section className="card">
          <h2>Which agents the tutor used</h2>
          <p className="muted" style={{ marginTop: -6 }}>Share of the last {rows.length} decisions.</p>
          <HBars rows={mix} />
        </section>
        <section className="card">
          <h2>Safety filter</h2>
          <table className="data">
            <tbody>
              <tr><th>Decisions where the filter removed options</th><td>{filtered} of {rows.length}</td></tr>
              <tr><th>Escalated to you</th><td>{escalated}</td></tr>
              <tr><th>Policies in use</th><td>{[...new Set(rows.map((d) => d.policy_version))].join(", ") || "–"}</td></tr>
            </tbody>
          </table>
          <p className="muted">Every action is chosen by the policy from the actions the safety filter allows; the language model only phrases it.</p>
        </section>
      </div>
      <section className="card overflow">
        <h2>Recent tutor decisions</h2>
        <table className="data">
          <thead>
            <tr><th>When</th><th>Student</th><th>Action</th><th>Why the policy chose it</th><th>Filtered out</th><th>Probability</th></tr>
          </thead>
          <tbody>
            {rows.slice(0, 100).map((d, i) => (
              <tr key={i}>
                <td className="muted">{new Date(d.at).toLocaleString()}</td>
                <td><code>{d.learner}</code></td>
                <td>{actionLabel(d.action)}{d.escalated && <span className="badge danger"> escalated</span>}</td>
                <td>{d.reason}{d.why && <div className="muted small">{d.why}</div>}</td>
                <td>
                  {Object.keys(d.removed).length === 0 ? <span className="muted">nothing</span>
                    : Object.entries(d.removed).map(([k, v]) => <div key={k}>{k}: {v.length}</div>)}
                  <div className="muted small">{d.feasible_count} allowed</div>
                </td>
                <td>{d.propensity.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
