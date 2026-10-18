import { Overview as Data, pct, StatusRow, timeAgo } from "../../api";
import { HBars, LineChart, StatCard } from "../../components/Charts";
import { Skeleton } from "../../components/ui";
import { useLoad } from "../../session";

export function SystemStatus() {
  const [rows] = useLoad<StatusRow[]>("/api/teacher/status");
  return (
    <section className="card">
      <h2>System status</h2>
      {!rows && <p className="muted">Checking…</p>}
      <ul className="list">
        {rows?.map((r) => (
          <li key={r.name} className="list-row">
            <span className={`status-dot ${r.state}`} aria-hidden />
            <div className="body">
              <div className="title">{r.name}</div>
              <div className="muted">{r.detail}</div>
            </div>
            <span className="muted small">{r.state}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function Overview() {
  const [data, , error] = useLoad<Data>("/api/teacher/overview");
  if (error) return <p className="error">{error}</p>;
  if (!data) return <Skeleton stats cards={2} />;
  const st = data.stats;
  return (
    <div className="stack">
      {st.simulated_students > 0 && (
        <div className="notice" role="note">
          <span className="notice-tag">Demo data</span>
          <span className="notice-text">
            {st.simulated_students} of {st.total_students} students are simulated (ids starting “sim_”). Their
            data fills the charts until real students use Mentora.
          </span>
        </div>
      )}
      <div className="grid cols-4">
        <StatCard icon="users" label="Total students" value={st.total_students} />
        <StatCard icon="activity" tone="green" label="Active this week" value={st.active_week}
                  note={st.total_students ? `${pct(st.active_week / st.total_students)} of the class` : undefined} />
        <StatCard icon="target" tone="orange" label="Average score" value={pct(st.average_score)} note="Correct answers, all practice" />
        <StatCard icon="alert" tone="red" label="At-risk students" value={st.at_risk} note={<a href="#/teacher/students">See who</a>} />
      </div>

      <div className="grid cols-wide-narrow">
        <section className="card">
          <h2>Class progress by week</h2>
          <LineChart
            labels={data.weekly.map((w) => `Wk ${w.week}`)}
            series={[
              { name: "Average score", color: "var(--series-1)", values: data.weekly.map((w) => w.average_score) },
              { name: "Goal completion", color: "var(--series-2)", values: data.weekly.map((w) => w.goal_completion) },
            ]}
          />
        </section>
        <section className="card">
          <h2>Topic-wise performance</h2>
          <HBars rows={data.topics.map((t) => ({ label: t.concept, value: t.accuracy, note: `${t.answers} answers` }))} />
        </section>
      </div>

      <div className="grid cols-wide-narrow">
        <section className="card overflow">
          <h2>Recent student activity</h2>
          {data.activity.length === 0 && <p className="empty">No activity yet.</p>}
          {data.activity.length > 0 && (
            <table className="data">
              <thead><tr><th>Student</th><th>Activity</th><th>When</th></tr></thead>
              <tbody>
                {data.activity.map((a, i) => (
                  <tr key={i}><td><code>{a.learner}</code></td><td>{a.activity}</td><td className="muted">{timeAgo(a.at)}</td></tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
        <SystemStatus />
      </div>
    </div>
  );
}
