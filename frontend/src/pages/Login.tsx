import { FormEvent, useState } from "react";
import { api, ApiError } from "../api";
import Icon, { IconName, Logo } from "../icons";

const FEATURES: [IconName, string][] = [
  ["target", "Set a goal, plan the steps, then practise with feedback"],
  ["bot", "A tutor that explains why it suggests each next step"],
  ["book", "Answers grounded in your course notes, with sources"],
  ["shield", "Pseudonymous by design; you can see and delete what it remembers"],
];

export default function Login({ onSignedIn }: { onSignedIn: () => void }) {
  const [name, setName] = useState("");
  const [role, setRole] = useState<"learner" | "teacher">("learner");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.post("/api/dev/login", {
        role,
        name: name.trim() || "Demo learner",
        ...(role === "teacher" && code ? { access_code: code } : {}),
      });
      window.location.hash = role === "teacher" ? "#/teacher" : "#/";
      onSignedIn();
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 404
          ? "Development sign-in is turned off. Open Mentora from your Moodle course."
          : err instanceof ApiError && err.status === 403
            ? "That teacher access code is not right."
            : String(err),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <section className="login-art">
        <div className="brand"><Logo /><div><b>Mentora</b><small>Self-learning strategy tutor</small></div></div>
        <div>
          <h2>Learn how you learn: plan, practise, reflect.</h2>
          <p>Mentora helps you set goals, work through course material with an AI tutor, and look back on what worked.</p>
          <ul>{FEATURES.map(([icon, text]) => <li key={text}><Icon name={icon} />{text}</li>)}</ul>
        </div>
        <p className="foot small">Part of your course in Moodle.</p>
      </section>

      <section className="login-form">
        <form className="card" onSubmit={submit}>
          <h2 style={{ fontSize: 20, marginBottom: 4 }}>Sign in</h2>
          <p className="muted" style={{ marginTop: 0 }}>
            Students and teachers normally open Mentora from the Moodle course page. For local
            testing you can sign in here.
          </p>
          <label style={{ display: "block", marginBottom: 14 }}>
            <span className="muted">Your name</span>
            <input type="text" value={name} onChange={(e) => setName(e.target.value)}
                   placeholder="e.g. Asha" maxLength={60} autoFocus />
          </label>
          <span className="muted">I am a</span>
          <div className="role-pick" role="radiogroup" aria-label="Role">
            {([["learner", "user", "Student"], ["teacher", "users", "Teacher"]] as const).map(([r, icon, label]) => (
              <label key={r} className={role === r ? "on" : ""}>
                <input type="radio" name="role" checked={role === r} onChange={() => setRole(r)} />
                <Icon name={icon} /> {label}
              </label>
            ))}
          </div>
          {role === "teacher" && (
            <label style={{ display: "block", marginBottom: 14 }}>
              <span className="muted">Teacher access code (if this demo uses one)</span>
              <input type="password" value={code} onChange={(e) => setCode(e.target.value)}
                     autoComplete="off" maxLength={200} />
            </label>
          )}
          <button className="btn primary" type="submit" disabled={busy} style={{ width: "100%", justifyContent: "center", padding: "10px 14px" }}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
          {error && <p className="error">{error}</p>}
        </form>
      </section>
    </div>
  );
}
