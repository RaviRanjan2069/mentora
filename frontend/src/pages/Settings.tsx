import { FormEvent, useEffect, useState } from "react";
import { api, Me, Rule } from "../api";
import { saveTheme, storedTheme } from "../App";
import { useToast } from "../components/ui";
import Icon from "../icons";
import { useLoad } from "../session";

function Appearance() {
  const [theme, setTheme] = useState(storedTheme);
  useEffect(() => {
    const sync = () => setTheme(storedTheme());
    window.addEventListener("mentora-theme", sync);
    return () => window.removeEventListener("mentora-theme", sync);
  }, []);
  function choose(t: string) {
    setTheme(t);
    saveTheme(t);
  }
  return (
    <section className="card">
      <h2>Appearance</h2>
      <div className="tabs" role="radiogroup" aria-label="Theme">
        {["system", "light", "dark"].map((t) => (
          <button key={t} className={theme === t ? "active" : ""} onClick={() => choose(t)}
                  role="radio" aria-checked={theme === t}>{t[0].toUpperCase() + t.slice(1)}</button>
        ))}
      </div>
    </section>
  );
}

function Rules() {
  const toast = useToast();
  const [rows, reload] = useLoad<Rule[]>("/api/teacher/rules");
  const [name, setName] = useState("");
  const [kind, setKind] = useState("agent");
  const [value, setValue] = useState("");
  const [weekLte, setWeekLte] = useState("");
  const [graded, setGraded] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function add(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const when: Record<string, unknown> = {};
    if (weekLte) when.week_lte = Number(weekLte);
    if (graded) when.graded = graded === "yes";
    try {
      await api.post("/api/teacher/rules", { name, rule: { forbid: { [kind]: value.trim() }, when } });
      setName(""); setValue(""); setWeekLte(""); setGraded("");
      reload();
      toast("Rule added. It applies from the next tutor turn.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <section className="card">
      <h2>Tutor rules</h2>
      <p className="muted" style={{ marginTop: -6 }}>Rules you add here are applied by the safety filter on every turn, on top of the built-in rules.</p>
      {rows && rows.length === 0 && <p className="empty">No rules yet.</p>}
      <ul className="list">
        {rows?.map((r) => (
          <li key={r.id} className="list-row">
            <div className="body"><b>{r.name}</b><div className="muted small">{JSON.stringify(r.rule)}</div></div>
            <button className="btn small danger" onClick={() => api.del(`/api/teacher/rules/${r.id}`).then(() => { reload(); toast("Rule removed"); })}>Remove</button>
          </li>
        ))}
      </ul>
      <form onSubmit={add} className="list mt">
        <input type="text" placeholder="Rule name, e.g. No peer suggestions in week 1" value={name}
               onChange={(e) => setName(e.target.value)} required />
        <div className="row">
          <span>Never use</span>
          <select value={kind} onChange={(e) => setKind(e.target.value)} style={{ width: "auto" }}>
            <option value="agent">agent</option><option value="move">move</option>
            <option value="style">style</option><option value="action">action</option>
          </select>
          <input type="text" placeholder="e.g. PeerBroker, worked_example or Directive" value={value}
                 onChange={(e) => setValue(e.target.value)} required style={{ flex: 1 }} />
        </div>
        <div className="row">
          <span>only when course week ≤</span>
          <input type="text" inputMode="numeric" value={weekLte} onChange={(e) => setWeekLte(e.target.value)}
                 style={{ width: 70 }} placeholder="any" />
          <span>and the item is graded:</span>
          <select value={graded} onChange={(e) => setGraded(e.target.value)} style={{ width: "auto" }}>
            <option value="">either</option><option value="yes">yes</option><option value="no">no</option>
          </select>
        </div>
        <div><button className="btn primary" type="submit">Add rule</button></div>
        {error && <p className="error">{error}</p>}
      </form>
    </section>
  );
}

export default function Settings({ role }: { role: "learner" | "teacher" }) {
  const [me] = useLoad<Me>("/api/me");
  const toast = useToast();
  async function forgetAll() {
    if (!window.confirm("Delete everything Mentora remembers about you?")) return;
    try {
      await api.del("/api/me/memory");
      toast("Done. Mentora no longer remembers anything about you.");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  }
  return (
    <div className="stack">
      <Appearance />
      {role === "teacher" && <Rules />}
      {role === "learner" && (
        <section className="card">
          <h2>Privacy</h2>
          <p className="muted">
            Mentora stores your activity under a pseudonym, not your name or LMS id. Notes the tutor
            remembers are listed on My Learning, where you can delete them one by one, or all at once here.
            Old notes are deleted automatically after the retention period.
          </p>
          <div className="row">
            <a className="btn" href="/api/me/export" download><Icon name="download" /> Download my data</a>
            <button className="btn danger" onClick={() => void forgetAll()}><Icon name="trash" /> Delete all my memory</button>
          </div>
          <p className="muted small">The download is a JSON file with your sessions, goals, remembered notes, messages to your teacher and activity log.</p>
        </section>
      )}
      {me && (
        <section className="card">
          <h2>About this installation</h2>
          <table className="data">
            <tbody>
              <tr><th>Signed in as</th><td>{me.name} ({me.role}, via {me.via === "lti" ? "Moodle" : "development sign-in"})</td></tr>
              <tr><th>Tutor mode</th><td>{me.mode === "static" ? "Static (study control: fixed rules, no memory)" : "Adaptive"}</td></tr>
              <tr><th>Replies</th><td>{({
                offline: "Offline templates (no AI model)",
                local: "AI model running on this computer (live, streamed replies)",
                hosted: "Claude AI model (live, streamed replies)",
              } as Record<string, string>)[me.llm_backend] ?? me.llm_backend}</td></tr>
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
