import { ChangeEvent, useEffect, useMemo, useState } from "react";
import { api, uploadFile } from "../../api";
import Icon from "../../icons";
import { useToast } from "../../components/ui";
import { useLoad } from "../../session";

interface Material { source: string; passages: number; week: number | null }
interface TeacherItem {
  id: number; external_id: string | null; text: string; item_type: string;
  graded: boolean; answer_key: string | null; concepts: string[];
}
interface UploadResult { source: string; passages: number; quarantined: { text: string }[] }

function Materials() {
  const [rows, reload] = useLoad<Material[]>("/api/teacher/materials");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();

  async function onFile(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    setBusy(true); setError(null); setResult(null);
    try {
      const r = await uploadFile<UploadResult>("/api/teacher/materials", f);
      setResult(r);
      reload();
      toast(`Added ${r.passages} passage${r.passages === 1 ? "" : "s"} from ${r.source}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(source: string) {
    if (!window.confirm(`Remove all passages from ${source}? The tutor will stop citing it.`)) return;
    await api.del(`/api/teacher/materials/${encodeURIComponent(source)}`);
    reload();
    toast(`Removed ${source}`);
  }

  return (
    <section className="card">
      <div className="row between">
        <h2 style={{ margin: 0 }}>Course material</h2>
        <label className={`btn primary ${busy ? "disabled" : ""}`}>
          <Icon name="upload" /> {busy ? "Uploading…" : "Upload file"}
          <input type="file" accept=".md,.txt,.pdf,.pptx,.yaml,.yml" onChange={onFile} disabled={busy} hidden />
        </label>
      </div>
      <p className="muted">Markdown, text, PDF, PowerPoint or an FAQ YAML file, up to 20 MB. The tutor answers only from this material.</p>
      {error && <p className="error">{error}</p>}
      {result && (
        <div className="banner">
          Added {result.passages} passage{result.passages === 1 ? "" : "s"} from <b>{result.source}</b>.
          {result.quarantined.length > 0 && (
            <> {result.quarantined.length} passage(s) looked like instructions to the AI and were left out:
              <ul>{result.quarantined.map((q, i) => <li key={i} className="small">{q.text}</li>)}</ul></>
          )}
        </div>
      )}
      {rows && rows.length === 0 && <p className="empty">No material yet.</p>}
      <ul className="list">
        {rows?.map((r) => (
          <li key={r.source} className="list-row">
            <span className="ico orange"><Icon name="file" /></span>
            <div className="body">
              <div className="title">{r.source}</div>
              <div className="muted">{r.passages} passages{r.week ? ` · week ${r.week}` : ""}</div>
            </div>
            <button className="btn small danger" onClick={() => void remove(r.source)}><Icon name="trash" /> Remove</button>
          </li>
        ))}
      </ul>
    </section>
  );
}

const PAGE = 25;

function Items() {
  const [rows] = useLoad<TeacherItem[]>("/api/teacher/items");
  const [q, setQ] = useState("");
  const [concept, setConcept] = useState("");
  const [page, setPage] = useState(0);
  const concepts = useMemo(() => [...new Set((rows ?? []).flatMap((i) => i.concepts))].sort(), [rows]);
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (rows ?? []).filter((i) =>
      (!concept || i.concepts.includes(concept))
      && (!needle || i.text.toLowerCase().includes(needle) || (i.external_id ?? "").includes(needle)));
  }, [rows, q, concept]);
  useEffect(() => setPage(0), [q, concept]);
  const pages = Math.max(1, Math.ceil(shown.length / PAGE));
  const slice = shown.slice(page * PAGE, page * PAGE + PAGE);
  return (
    <section className="card overflow">
      <div className="row between">
        <h2 style={{ margin: 0 }}>Practice questions ({shown.length}{shown.length !== rows?.length ? ` of ${rows?.length}` : ""})</h2>
        <div className="row">
          <input type="search" placeholder="Search questions or ids" value={q} onChange={(e) => setQ(e.target.value)}
                 aria-label="Search questions" style={{ width: 220 }} />
          <select value={concept} onChange={(e) => setConcept(e.target.value)} aria-label="Filter by concept" style={{ width: "auto" }}>
            <option value="">All concepts</option>
            {concepts.map((c) => <option key={c} value={c}>{c.replace(/_/g, " ")}</option>)}
          </select>
        </div>
      </div>
      <p className="muted">
        Includes the generated question bank (data/sample/question_bank.yaml): every answer key there was
        computed by running the question's code.
      </p>
      <table className="data">
        <thead><tr><th>Id</th><th>Question</th><th>Type</th><th>Answer key</th><th>Concepts</th></tr></thead>
        <tbody>
          {slice.map((i) => (
            <tr key={i.id}>
              <td className="muted">{i.external_id ?? i.id}</td>
              <td><pre style={{ margin: 0, whiteSpace: "pre-wrap", font: "inherit", maxWidth: 460 }}>{i.text}</pre></td>
              <td>{i.item_type}{i.graded && <span className="badge warn">graded</span>}</td>
              <td><code>{i.answer_key ?? "–"}</code></td>
              <td className="muted">{i.concepts.join(", ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {shown.length === 0 && <p className="empty">No questions match.</p>}
      {pages > 1 && (
        <div className="row mt" style={{ justifyContent: "flex-end" }}>
          <button className="btn small" onClick={() => setPage((p) => p - 1)} disabled={page === 0}>Previous</button>
          <span className="muted">Page {page + 1} of {pages}</span>
          <button className="btn small" onClick={() => setPage((p) => p + 1)} disabled={page + 1 >= pages}>Next</button>
        </div>
      )}
    </section>
  );
}

function MemoryQueue() {
  const [rows, reload] = useLoad<{ id: number; text: string; created_at: string }[]>("/api/teacher/memory-queue");
  const toast = useToast();
  const review = (id: number, approve: boolean) => api.post(`/api/teacher/memory-queue/${id}`, { approve })
    .then(() => { reload(); toast(approve ? "Note approved for the course" : "Note rejected"); });
  return (
    <section className="card">
      <h2>Course-memory review</h2>
      <p className="muted">Notes proposed for every learner in the course. None is used until you approve it.</p>
      {rows && rows.length === 0 && <p className="empty">Nothing to review.</p>}
      <ul className="list">
        {rows?.map((r) => (
          <li key={r.id} className="list-row">
            <div className="body">{r.text}</div>
            <button className="btn small primary" onClick={() => void review(r.id, true)}>Approve</button>
            <button className="btn small danger" onClick={() => void review(r.id, false)}>Reject</button>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function Content() {
  return (
    <div className="stack">
      <Materials />
      <MemoryQueue />
      <Items />
    </div>
  );
}
