import { useMemo, useState } from "react";
import { pct, StudentDetail, StudentRow, timeAgo } from "../../api";
import { Heatmap, PhaseBars } from "../../components/Charts";
import MasteryBars from "../../components/MasteryBars";
import { Drawer, Skeleton } from "../../components/ui";
import Icon from "../../icons";
import { useLoad } from "../../session";

type Filter = "all" | "risk" | "real";

function StudentPanel({ row, onClose }: { row: StudentRow; onClose: () => void }) {
  const [d, , error] = useLoad<StudentDetail>(`/api/teacher/students/${encodeURIComponent(row.id)}`);
  return (
    <Drawer title={`Student ${row.learner}`} onClose={onClose}>
      <div className="row">
        {row.at_risk ? <span className="badge danger">At risk</span> : <span className="badge ok">On track</span>}
        {row.simulated && <span className="badge">Simulated demo learner</span>}
        <span className="muted">Last active {row.last_active ? timeAgo(row.last_active) : "never"}</span>
      </div>
      {error && <p className="error">{error}</p>}
      {!d && !error && <div className="mt"><Skeleton cards={2} /></div>}
      {d && (
        <>
          <section>
            <div className="mini-stats">
              <div><b>{d.sessions}</b><span>sessions</span></div>
              <div><b>{pct(row.quiz_average)}</b><span>quiz average ({row.answers} answers)</span></div>
              <div><b>{pct(row.dropout_risk)}</b><span>dropout estimate</span></div>
            </div>
          </section>
          <section>
            <h3>Activity, last 12 weeks</h3>
            <Heatmap days={d.calendar} />
          </section>
          <section>
            <h3>Self-regulated learning</h3>
            {d.srl.has_data ? (
              <PhaseBars rows={[
                { label: "Forethought", value: d.srl.forethought, color: "var(--series-1)" },
                { label: "Performance", value: d.srl.performance, color: "var(--series-2)" },
                { label: "Self-reflection", value: d.srl.reflection, color: "var(--series-3)" },
              ]} />
            ) : <p className="empty">No sessions with enough data yet.</p>}
          </section>
          <section>
            <h3>Goals</h3>
            {d.goals.length === 0 && <p className="empty">No goals set.</p>}
            <ul className="list">
              {d.goals.map((g, i) => (
                <li key={i} className="list-row">
                  <span className={`ico ${g.status === "attained" ? "green" : g.status === "abandoned" ? "red" : ""}`}><Icon name="target" /></span>
                  <div className="body">
                    <div className="title">{g.text}</div>
                    <div className="muted">{g.status}{g.smart_score !== null ? ` · clarity ${pct(g.smart_score)}` : ""} · {timeAgo(g.created_at)}</div>
                  </div>
                </li>
              ))}
            </ul>
          </section>
          <section>
            <h3>Recent activity</h3>
            <ul className="list">
              {d.activity.map((a, i) => (
                <li key={i} className="row between"><span>{a.text}</span><span className="muted">{timeAgo(a.at)}</span></li>
              ))}
            </ul>
          </section>
          <section>
            <h3>Estimated mastery</h3>
            <MasteryBars rows={d.mastery} />
          </section>
          {row.open_escalations > 0 && (
            <a className="btn primary mt" href="#/teacher/escalations">
              <Icon name="alert" /> {row.open_escalations} open escalation{row.open_escalations === 1 ? "" : "s"}
            </a>
          )}
        </>
      )}
    </Drawer>
  );
}

export default function Students() {
  const [rows] = useLoad<StudentRow[]>("/api/teacher/students");
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<StudentRow | null>(null);
  const shown = useMemo(() => (rows ?? []).filter((r) =>
    (filter === "risk" ? r.at_risk : filter === "real" ? !r.simulated : true)
    && (!q.trim() || r.learner.toLowerCase().includes(q.trim().toLowerCase()))), [rows, filter, q]);
  if (!rows) return <Skeleton cards={1} />;
  return (
    <section className="card overflow">
      <div className="row between">
        <h2 style={{ margin: 0 }}>Students ({shown.length})</h2>
        <div className="row">
          <input type="search" placeholder="Find a student id" value={q} onChange={(e) => setQ(e.target.value)}
                 aria-label="Find a student" style={{ width: 200 }} />
          <div className="tabs" role="tablist" style={{ margin: 0 }}>
            {([["all", "All"], ["risk", "At risk"], ["real", "Real only"]] as [Filter, string][]).map(([f, l]) => (
              <button key={f} role="tab" aria-selected={filter === f} className={filter === f ? "active" : ""}
                      onClick={() => setFilter(f)}>{l}</button>
            ))}
          </div>
        </div>
      </div>
      <p className="muted">
        Students appear under pseudonyms. Select a row for details. “At risk” means a dropout estimate of 50% or
        more, accuracy under 40% over at least five answers, or an open wellbeing escalation.
      </p>
      <table className="data">
        <thead>
          <tr><th>Student</th><th>Sessions</th><th>Last active</th><th>Mean mastery</th><th>Quiz average</th><th>Answers</th><th>Dropout estimate</th><th>Status</th></tr>
        </thead>
        <tbody>
          {shown.map((r) => (
            <tr key={r.id} className="clickable" tabIndex={0} onClick={() => setSelected(r)}
                onKeyDown={(e) => { if (e.key === "Enter") setSelected(r); }}>
              <td><code>{r.learner}</code>{r.simulated && <span className="muted small"> (simulated)</span>}</td>
              <td>{r.sessions}</td>
              <td className="muted">{r.last_active ? timeAgo(r.last_active) : "never"}</td>
              <td>{pct(r.mean_mastery)}</td>
              <td>{pct(r.quiz_average)}</td>
              <td>{r.answers}</td>
              <td>{pct(r.dropout_risk)}</td>
              <td>
                {r.at_risk ? <span className="badge danger">At risk</span> : <span className="badge">OK</span>}
                {r.open_escalations > 0 && <span className="small" style={{ color: "var(--danger)" }}> {r.open_escalations} open</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {selected && <StudentPanel row={selected} onClose={() => setSelected(null)} />}
    </section>
  );
}
