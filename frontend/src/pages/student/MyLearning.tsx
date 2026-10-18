import { actionLabel, api, Dashboard, MemoryItem, pct } from "../../api";
import Icon from "../../icons";
import { Skeleton, useToast } from "../../components/ui";
import { useLoad } from "../../session";

export default function MyLearning() {
  const [data, , error] = useLoad<Dashboard>("/api/me/dashboard");
  const [memory, reloadMemory] = useLoad<MemoryItem[]>("/api/me/memory");
  const toast = useToast();
  if (error) return <p className="error">{error}</p>;
  if (!data || !memory) return <Skeleton cards={3} />;
  const active = data.goals.filter((g) => g.status === "active");
  const past = data.goals.filter((g) => g.status !== "active");

  async function forget(id: number) {
    await api.del(`/api/me/memory/${id}`);
    reloadMemory();
    toast("Deleted. The tutor will no longer use that note.");
  }

  return (
    <div className="stack">
      {data.teacher_replies.length > 0 && (
        <section className="card">
          <h2>Messages from your teacher</h2>
          <ul className="list">
            {data.teacher_replies.map((r) => (
              <li key={r.id} className="list-row">
                <span className="ico"><Icon name="chat" /></span>
                <div className="body">
                  {r.question && <div className="muted">You wrote: “{r.question}”</div>}
                  <div>{r.response}</div>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="grid cols-2">
        <section className="card">
          <h2>Goals and plan</h2>
          {active.length === 0 && <p className="empty">No active goal. Start a session with the tutor to set one.</p>}
          <ul className="list">
            {active.map((g) => (
              <li key={g.id}>
                <div className="title"><b>{g.text}</b></div>
                <div className="row muted">
                  <span>Plan progress {pct(g.progress)}</span>
                  {g.smart_score !== null && <span>· goal clarity {pct(g.smart_score)}</span>}
                </div>
                <div className="progress" style={{ margin: "6px 0" }}><span style={{ width: `${g.progress * 100}%` }} /></div>
                <ul className="muted" style={{ paddingLeft: 18, margin: 0 }}>
                  {g.steps.map((s, i) => (
                    <li key={i}>{s.done ? "✓ " : ""}{s.concept ? `Master ${s.concept.replace(/_/g, " ")}` : s.text}</li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
          {past.length > 0 && (
            <details>
              <summary>Earlier goals ({past.length})</summary>
              <ul className="muted">{past.map((g) => <li key={g.id}>{g.text} ({g.status})</li>)}</ul>
            </details>
          )}
        </section>

        <section className="card">
          <h2>What Mentora remembers about you</h2>
          <p className="muted" style={{ marginTop: -6 }}>Short notes that help the tutor in later sessions. You can delete any of them.</p>
          {memory.length === 0 && <p className="empty">Nothing yet.</p>}
          <ul className="list">
            {memory.map((m) => (
              <li key={m.id} className="list-row">
                <div className="body">{m.text}</div>
                <button className="btn small danger" onClick={() => void forget(m.id)}><Icon name="trash" /> Delete</button>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <section className="card">
        <h2>Recent tutor suggestions</h2>
        {data.recent_tutor_messages.length === 0 && <p className="empty">None yet.</p>}
        <ul className="list">
          {data.recent_tutor_messages.slice(0, 10).map((t, i) => (
            <li key={i}>
              <span className="chip">{actionLabel(t.action)}</span>
              <div style={{ marginTop: 4 }}>{t.reply?.split("\n\nWhy this suggestion:")[0]}</div>
              {t.why && <div className="muted small">{t.why}</div>}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
