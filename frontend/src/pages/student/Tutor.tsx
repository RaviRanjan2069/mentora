import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import { actionLabel } from "../../api";
import RichText from "../../components/RichText";
import { Modal, useToast } from "../../components/ui";
import Icon, { IconName } from "../../icons";
import { ChatMessage, useSession } from "../../session";

const QUICK = [
  ["Explain again", "Can you explain that again?"],
  ["Give a hint", "Can I get a hint?"],
  ["Show similar example", "Can you show me a similar example?"],
  ["Give a practice question", "Give me a practice question"],
] as const;

const STARTERS: [IconName, string, string, string][] = [
  ["target", "Plan a study session", "Set a goal for today", "My goal today is to understand for loops and finish two exercises"],
  ["bulb", "Explain a concept", "Ask about anything in the notes", "Can you explain how range() works?"],
  ["practice", "Quiz me", "A practice question on this week", "Give me a practice question"],
  ["pen", "Look back", "Reflect on how it went", "Looking back, what should I change in how I study?"],
];

const SOURCE_NOTE: Record<string, string> = {
  course: "From your course notes",
  general: "General knowledge, not from your course notes: check important facts",
  unverified: "Uses your course notes, but some details could not be checked against them",
};

const PHASE: Record<string, string> = {
  forethought: "Forethought (planning)",
  performance: "Performance (working)",
  reflection: "Self-reflection",
};

const REFLECT: [string, string, string][] = [
  ["went", "What did you get done?", "Compare it with the goal you set."],
  ["why", "What was hard, and why?", "Was it the topic, your approach, time or focus?"],
  ["next", "What will you do differently next time?", "One concrete change is enough."],
];

function Message({ m }: { m: ChatMessage }) {
  if (m.from === "system") return <div className="system-line">{m.text}</div>;
  const time = m.at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return (
    <div className={`msg ${m.from} ${m.turn?.escalated ? "escalated" : ""}`}>
      <div className="who">{m.from === "tutor" ? <Icon name="bot" /> : <Icon name="user" />}</div>
      <div style={{ minWidth: 0, maxWidth: "78%" }}>
        <div className="bubble" style={{ maxWidth: "100%" }}>
          <RichText text={m.text} />
          {m.streaming && <span className="caret" aria-hidden />}
          {m.turn?.answer_source && SOURCE_NOTE[m.turn.answer_source] && (
            <div className={`source-note ${m.turn.answer_source}`}>{SOURCE_NOTE[m.turn.answer_source]}</div>
          )}
          {m.turn?.why && (
            <div className="why"><b>Why this suggestion?</b> {m.turn.why.replace(/^Why this suggestion:\s*/, "")}</div>
          )}
        </div>
        <div className="time" style={{ textAlign: m.from === "learner" ? "right" : "left" }}>
          {time}{m.turn && <> · <span title="What the tutor chose to do">{m.turn.action === "WAIT" ? "Answer" : actionLabel(m.turn.action)}</span></>}
        </div>
      </div>
    </div>
  );
}

/** Guided end-of-session reflection: the answers go to the tutor as one message, then the session ends. */
function ReflectDialog({ onClose }: { onClose: () => void }) {
  const s = useSession();
  const toast = useToast();
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const filled = REFLECT.filter(([k]) => answers[k]?.trim()).length;

  async function finish(withReflection: boolean) {
    if (withReflection) {
      const text = REFLECT.filter(([k]) => answers[k]?.trim())
        .map(([k, q]) => `${q} ${answers[k].trim()}`).join("\n");
      await s.send(text);
    }
    await s.end();
    toast(withReflection ? "Session ended. Your reflection is saved." : "Session ended.");
    onClose();
  }

  return (
    <Modal title="Before you finish: look back" onClose={onClose}>
      <p className="muted" style={{ marginTop: 0 }}>
        A short reflection helps you remember what worked. It also counts towards your self-reflection
        score on the Home page. Answer any of these, or skip.
      </p>
      {REFLECT.map(([k, q, hint]) => (
        <div key={k} className="reflect-q">
          <label htmlFor={`r-${k}`}>{q}</label>
          <div className="muted">{hint}</div>
          <textarea id={`r-${k}`} rows={2} value={answers[k] ?? ""} maxLength={1000}
                    onChange={(e) => setAnswers({ ...answers, [k]: e.target.value })} />
        </div>
      ))}
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button className="btn" onClick={() => void finish(false)} disabled={s.busy}>Skip and end</button>
        <button className="btn primary" onClick={() => void finish(true)} disabled={s.busy || filled === 0}>
          Save reflection and end
        </button>
      </div>
    </Modal>
  );
}

export default function Tutor() {
  const s = useSession();
  const [text, setText] = useState("");
  const [reflecting, setReflecting] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [s.messages, s.busy]);
  useEffect(() => {
    const el = box.current;
    if (el) { el.style.height = "auto"; el.style.height = `${Math.min(el.scrollHeight, 160)}px`; }
  }, [text]);

  const sendText = (body: string) => {
    if (!body.trim() || s.busy) return;
    setText("");
    void s.send(body.trim());
  };
  const submit = (e: FormEvent) => { e.preventDefault(); sendText(text); };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); sendText(text); }
  };
  const chatting = s.messages.some((m) => m.from !== "system");

  return (
    <div className="grid cols-main-side">
      <section className="card chat" aria-label="Tutor chat">
        <div className="row between" style={{ marginBottom: 10 }}>
          <span className="muted row" style={{ gap: 6 }}>
            <span className={`status-dot ${s.sessionId ? "" : "empty"}`} aria-hidden />
            {s.sessionId ? "Session in progress" : "No session yet"}
          </span>
          {s.sessionId
            ? <button className="btn small" onClick={() => setReflecting(true)} disabled={s.busy}>End session</button>
            : <button className="btn primary small" onClick={() => void s.start()} disabled={s.busy}>
                <Icon name="play" /> Start a study session
              </button>}
        </div>
        <div className="messages" aria-live="polite">
          {!chatting && !s.busy && (
            <div className="welcome">
              <div className="orb"><Icon name="sparkle" /></div>
              <h3>What would you like to work on?</h3>
              <p className="muted" style={{ margin: 0 }}>
                The tutor helps you plan, practise and reflect. Pick a starting point or type your own question.
              </p>
              <div className="starters">
                {STARTERS.map(([icon, title, sub, msg]) => (
                  <button key={title} className="starter" onClick={() => sendText(msg)} disabled={s.busy}>
                    <Icon name={icon} />
                    <div><b>{title}</b><span>{sub}</span></div>
                  </button>
                ))}
              </div>
            </div>
          )}
          {s.messages.map((m, i) => <Message key={i} m={m} />)}
          {s.busy && !s.messages.some((m) => m.streaming) && (
            <div className="msg tutor" aria-label="The tutor is replying">
              <div className="who"><Icon name="bot" /></div>
              <div className="typing"><i /><i /><i /></div>
            </div>
          )}
          <div ref={endRef} />
        </div>
        {s.error && <p className="error">{s.error}</p>}
        {chatting && (
          <div className="quick" aria-label="Quick requests">
            {QUICK.map(([label, msg]) => (
              <button key={label} className="chip-btn" disabled={s.busy} onClick={() => sendText(msg)}>{label}</button>
            ))}
          </div>
        )}
        <form className="composer" onSubmit={submit}>
          <textarea ref={box} rows={1} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey}
                    maxLength={4000} placeholder="Type your message…" aria-label="Message" />
          <button className="send-btn" type="submit" disabled={s.busy || !text.trim()} aria-label="Send">
            <Icon name="send" />
          </button>
        </form>
        <div className="composer-hint">Enter to send · Shift+Enter for a new line · Ctrl+K to search the notes</div>
      </section>

      <aside className="stack">
        <section className="card">
          <h2>Current learning context</h2>
          <div className="context-item"><div className="k">Topic</div><div>{s.context.topic ?? "Not set yet"}</div></div>
          <div className="context-item p2"><div className="k">SRL phase</div><div>{PHASE[s.context.phase] ?? "–"}</div></div>
          <div className="context-item p3"><div className="k">Suggested strategy</div><div>{s.context.strategy ?? "–"}</div></div>
        </section>
        <section className="card">
          <h2>Related resources</h2>
          {s.context.sources.length === 0 && <p className="empty">Course passages the tutor uses appear here.</p>}
          <ul className="list">
            {s.context.sources.map((r) => (
              <li key={r.id} className="list-row">
                <span className="ico"><Icon name="file" /></span>
                <div className="body">
                  <div className="title">{r.section ?? r.id}</div>
                  <div className="muted">{r.week ? `Week ${r.week} notes` : "Course notes"}</div>
                </div>
                <a className="arrow-btn" href={`#/resources?id=${r.id}`} aria-label={`Open ${r.section ?? r.id}`}>
                  <Icon name="arrow" />
                </a>
              </li>
            ))}
          </ul>
        </section>
      </aside>
      {reflecting && <ReflectDialog onClose={() => setReflecting(false)} />}
    </div>
  );
}
