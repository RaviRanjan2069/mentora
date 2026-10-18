import { useState } from "react";
import { api, Policy } from "../../api";
import Icon from "../../icons";
import { useToast } from "../../components/ui";
import { useLoad } from "../../session";

interface Models {
  mastery_model: string;
  kt_models: string[];
  tactic_hmm: boolean;
  report: Record<string, unknown> | null;
}

function PolicyCard({ p, reload }: { p: Policy; reload: () => void }) {
  const [note, setNote] = useState("");
  const toast = useToast();
  const decide = (approve: boolean) =>
    api.post(`/api/teacher/policies/${p.version}/decision`, { approve, note: note || (approve ? "Approved" : "Rejected") })
      .then(() => { setNote(""); reload(); toast(approve ? `${p.version} is now active` : `${p.version} rejected`); });
  return (
    <section className="card">
      <div className="row">
        <h2 style={{ margin: 0 }}>{p.version}</h2>
        <span className={`badge ${p.status === "active" ? "ok" : p.status === "candidate" ? "warn" : ""}`}>{p.status}</span>
        <span className="muted">{p.type} · {new Date(p.created_at).toLocaleDateString()}</span>
      </div>
      {p.reasons && <pre className="report">{p.reasons}</pre>}
      {typeof p.metrics.report_markdown === "string" && (
        <details open={p.status === "candidate"}>
          <summary>Off-policy evaluation and fairness report</summary>
          <pre className="report">{p.metrics.report_markdown}</pre>
        </details>
      )}
      {p.status === "candidate" && (
        <div className="list mt">
          <textarea rows={2} placeholder="Your reasons (stored with the decision)" value={note} onChange={(e) => setNote(e.target.value)} />
          <div className="row">
            <button className="btn primary" onClick={() => void decide(true)}>Approve and activate</button>
            <button className="btn danger" onClick={() => void decide(false)}>Reject</button>
          </div>
        </div>
      )}
    </section>
  );
}

export default function Training() {
  const [models] = useLoad<Models>("/api/teacher/models");
  const [policies, reload] = useLoad<Policy[]>("/api/teacher/policies");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<{ status: string; version: string | null; reasons: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function train() {
    setRunning(true); setError(null); setResult(null);
    try {
      setResult(await api.post("/api/teacher/policies/train"));
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="stack">
      <div className="grid cols-2">
        <section className="card">
          <h2>Learner models</h2>
          {models && (
            <table className="data">
              <tbody>
                <tr><th>Mastery model</th><td>{models.mastery_model}</td></tr>
                <tr><th>Trained knowledge-tracing files</th><td>{models.kt_models.length ? models.kt_models.join(", ") : "none (using the fallback estimate)"}</td></tr>
                <tr><th>Study-tactic model</th><td>{models.tactic_hmm ? "trained" : "not trained"}</td></tr>
              </tbody>
            </table>
          )}
          {models?.report && (
            <details><summary>Training report</summary><pre className="report">{JSON.stringify(models.report, null, 2)}</pre></details>
          )}
        </section>
        <section className="card">
          <h2>Tutor policy training</h2>
          <p className="muted">
            Trains a new policy offline from logged sessions and checks it with off-policy evaluation and a fairness
            audit. A new policy is only ever a candidate: it does nothing until you approve it below.
          </p>
          <button className="btn primary" onClick={() => void train()} disabled={running}>
            <Icon name="cpu" /> {running ? "Training… (this can take a minute)" : "Run training now"}
          </button>
          {error && <p className="error">{error}</p>}
          {result && (
            <div className="banner mt">
              Result: <b>{result.status}</b>{result.version && <> · {result.version}</>}
              <pre className="report">{result.reasons}</pre>
            </div>
          )}
        </section>
      </div>
      {policies?.map((p) => <PolicyCard key={p.version} p={p} reload={reload} />)}
    </div>
  );
}
