import { useState } from "react";
import { api, Escalation } from "../../api";
import { Skeleton, useToast } from "../../components/ui";
import { useLoad } from "../../session";

export default function Escalations() {
  const [rows, reload] = useLoad<Escalation[]>("/api/teacher/escalations");
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const toast = useToast();
  if (!rows) return <Skeleton cards={2} />;
  const open = rows.filter((r) => r.status === "open");
  const done = rows.filter((r) => r.status !== "open");
  const answer = async (id: number) => {
    await api.post(`/api/teacher/escalations/${id}/answer`, { response: drafts[id] });
    reload();
    toast("Reply sent. The student will see it in Mentora.");
  };
  return (
    <div className="stack">
      <section className="card">
        <h2>Waiting for you ({open.length})</h2>
        {open.length === 0 && <p className="empty">Nothing waiting for you.</p>}
        <ul className="list">
          {open.map((e) => (
            <li key={e.id}>
              <div className="row">
                <span className={`badge ${e.reason === "distress" ? "danger" : "warn"}`}>{e.reason.replace(/_/g, " ")}</span>
                <span className="muted">student <code>{e.learner}</code> · {new Date(e.created_at).toLocaleString()}</span>
              </div>
              {e.message && <p>“{e.message}”</p>}
              {e.reason === "distress" && (
                <p className="error">Possible distress: consider contacting the student directly and pointing them to the counselling service.</p>
              )}
              <textarea rows={2} placeholder="Reply to the student…" value={drafts[e.id] ?? ""}
                        onChange={(ev) => setDrafts({ ...drafts, [e.id]: ev.target.value })} />
              <button className="btn primary small mt" disabled={!drafts[e.id]?.trim()} onClick={() => void answer(e.id)}>
                Send reply
              </button>
            </li>
          ))}
        </ul>
      </section>
      {done.length > 0 && (
        <section className="card">
          <h2>Answered</h2>
          <ul className="list">
            {done.map((e) => (
              <li key={e.id}>
                <span className="muted">{e.reason.replace(/_/g, " ")} · <code>{e.learner}</code>:</span> {e.teacher_response}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
