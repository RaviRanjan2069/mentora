import { FormEvent, useEffect, useMemo, useState } from "react";
import { Concept, FullTurn, Item, parseItem, pct } from "../../api";
import RichText from "../../components/RichText";
import { Skeleton } from "../../components/ui";
import Icon from "../../icons";
import { useLoad, useSession } from "../../session";

function queryParam(name: string): string | null {
  const q = window.location.hash.split("?")[1];
  return q ? new URLSearchParams(q).get(name) : null;
}

type Result = { response: string; correct: boolean | null; confidence: number };

const ROUND_SIZES = [5, 10, 20];

/** A random round: questions not yet seen in this browser session first. */
function pickRound(pool: Item[], size: number, seen: Set<number>): Item[] {
  const shuffled = [...pool].sort(() => Math.random() - 0.5);
  const fresh = shuffled.filter((i) => !seen.has(i.id));
  return [...fresh, ...shuffled.filter((i) => seen.has(i.id))].slice(0, size);
}

export default function Practice() {
  const s = useSession();
  const [concepts] = useLoad<Concept[]>("/api/concepts");
  const [items] = useLoad<Item[]>("/api/items");
  const [topic, setTopic] = useState<string | null>(queryParam("concept"));
  const [started, setStarted] = useState(false);
  const [index, setIndex] = useState(0);
  const [results, setResults] = useState<Record<number, Result>>({});
  const [answer, setAnswer] = useState("");
  const [confidence, setConfidence] = useState(50);
  const [shownAt, setShownAt] = useState(Date.now());
  const [tutorNote, setTutorNote] = useState<FullTurn | null>(null);
  const [hint, setHint] = useState<FullTurn | null>(null);
  const [finished, setFinished] = useState(false);
  const [roundSize, setRoundSize] = useState(10);
  const [set, setRound] = useState<Item[]>([]);
  const [seen] = useState(() => new Set<number>());

  const withItems = useMemo(() => (concepts ?? []).filter((c) => c.item_ids.length > 0), [concepts]);
  useEffect(() => {
    if (!topic && withItems.length) setTopic(withItems[0].key);
  }, [topic, withItems]);
  const concept = withItems.find((c) => c.key === topic) ?? null;
  const pool = useMemo(() => {
    const ids = new Set(concept?.item_ids ?? []);
    return (items ?? []).filter((i) => ids.has(i.id));
  }, [items, concept]);
  const item = set[index] ?? null;
  const parsed = item ? parseItem(item.text) : null;
  const names = Object.fromEntries((concepts ?? []).map((c) => [c.key, c]));

  async function open(i: number, round: Item[] = set, fresh = false) {
    const it = round[i];
    if (!it) return;
    seen.add(it.id);
    setIndex(i);
    setAnswer(fresh ? "" : results[it.id]?.response ?? "");
    setHint(null);
    setShownAt(Date.now());
    setTutorNote(await s.present(it));
  }

  async function start() {
    const round = pickRound(pool, roundSize, seen);
    setRound(round);
    setResults({});
    setFinished(false);
    await s.quiz(round.map((i) => i.id));
    setStarted(true);
    await open(0, round, true);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!item || !answer.trim()) return;
    const t = await s.answer(item, answer.trim(), confidence / 100, Math.round((Date.now() - shownAt) / 1000));
    if (t) {
      setResults((r) => ({ ...r, [item.id]: { response: answer.trim(), correct: t.correct, confidence: confidence / 100 } }));
      setTutorNote(t);
    }
  }

  async function askHint() {
    setHint(await s.send("Can I get a hint?"));
  }

  if (!concepts || !items) return <Skeleton cards={2} />;
  const done = set.filter((i) => results[i.id]?.correct).length;

  return (
    <div className="grid cols-main-side">
      <section className="card">
        {started && finished ? (
          <Summary set={set} results={results} topic={concept?.name ?? ""}
                   onRetry={() => void start()} onReview={(i) => { setFinished(false); void open(i); }}
                   onAsk={(msg) => { window.location.hash = "#/tutor"; void s.send(msg); }}
                   onPick={() => { setStarted(false); setFinished(false); }} />
        ) : !started || !item || !parsed ? (
          <>
            <h2>Choose a topic</h2>
            <div className="row" style={{ marginBottom: 14 }}>
              <select value={topic ?? ""} onChange={(e) => { setTopic(e.target.value); setStarted(false); }}
                      style={{ maxWidth: 360 }} aria-label="Topic">
                {withItems.map((c) => (
                  <option key={c.key} value={c.key}>{c.name} ({c.item_ids.length} question{c.item_ids.length === 1 ? "" : "s"})</option>
                ))}
              </select>
              <select value={roundSize} onChange={(e) => setRoundSize(Number(e.target.value))}
                      style={{ width: "auto" }} aria-label="Questions per round">
                {ROUND_SIZES.map((n) => <option key={n} value={n}>{n} questions</option>)}
              </select>
              <button className="btn primary" onClick={() => void start()} disabled={!pool.length || s.busy}>
                <Icon name="play" /> Start practice
              </button>
            </div>
            <p className="muted">
              Each round picks {Math.min(roundSize, pool.length)} random questions from the {pool.length} on this
              topic, new ones first. You'll rate how sure you are before each answer: it helps you notice what
              you really know. Graded questions get hints only, never answers.
            </p>
          </>
        ) : (
          <form onSubmit={submit}>
            <div className="row between">
              <h2 style={{ margin: 0 }}>Question {index + 1} of {set.length}</h2>
              <span className="muted">Topic: {concept?.name}</span>
            </div>
            {item.graded && <span className="badge warn" style={{ marginTop: 8, display: "inline-block" }}>Graded: hints only</span>}
            <p style={{ marginTop: 14 }}>{parsed.stem}</p>
            {parsed.code && <div className="question-code">{parsed.code}</div>}
            {parsed.options.length > 0 ? (
              <div role="radiogroup" aria-label="Options">
                {parsed.options.map((o) => (
                  <label key={o.key} className={`option ${answer === o.key ? "selected" : ""}`}>
                    <input type="radio" name="opt" checked={answer === o.key} onChange={() => setAnswer(o.key)} />
                    <span><b>{o.key}.</b> {o.label}</span>
                  </label>
                ))}
              </div>
            ) : (
              <input type="text" value={answer} onChange={(e) => setAnswer(e.target.value)} placeholder="Your answer"
                     aria-label="Your answer" style={{ maxWidth: 360 }} />
            )}
            <label style={{ display: "block", margin: "16px 0", maxWidth: 360 }}>
              How sure are you? <b>{confidence}%</b>
              <input type="range" min={0} max={100} step={5} value={confidence}
                     onChange={(e) => setConfidence(Number(e.target.value))} style={{ width: "100%" }} />
            </label>
            <div className="row">
              <button className="btn primary" type="submit" disabled={s.busy || !answer.trim()}>Submit answer</button>
              {results[item.id]?.correct === true && <span className="feedback-ok">Correct</span>}
              {results[item.id]?.correct === false && <span className="feedback-bad">Not yet, have another go</span>}
              <div className="spacer" />
              {Object.keys(results).length > 0 && set.every((i) => results[i.id]) && (
                <button type="button" className="btn soft" onClick={() => setFinished(true)}>
                  See results <Icon name="arrow" />
                </button>
              )}
              {index + 1 < set.length && (
                <button type="button" className="btn" onClick={() => void open(index + 1)} disabled={s.busy}>
                  Next question <Icon name="arrow" />
                </button>
              )}
            </div>
            {tutorNote?.reply && (
              <div className="card mt" style={{ background: "var(--surface-2)", boxShadow: "none" }}>
                <div className="muted" style={{ marginBottom: 4 }}>Your tutor</div>
                <div style={{ whiteSpace: "pre-wrap" }}><RichText text={tutorNote.reply} /></div>
                {tutorNote.why && <div className="muted small" style={{ marginTop: 6 }}>{tutorNote.why}</div>}
              </div>
            )}
          </form>
        )}
        {s.error && <p className="error">{s.error}</p>}
      </section>

      <aside className="stack">
        {started && set.length > 0 && (
          <section className="card">
            <h2>Question navigator</h2>
            <div className="navigator">
              {set.map((it, i) => {
                const r = results[it.id];
                const cls = i === index ? "current" : r?.correct ? "right" : r ? "wrong" : "";
                return <button key={it.id} className={cls} onClick={() => void open(i)} aria-label={`Question ${i + 1}`}>{i + 1}</button>;
              })}
            </div>
            <p className="muted" style={{ marginTop: 10 }}>{done} of {set.length} correct</p>
          </section>
        )}
        {started && (
          <section className="card">
            <div className="hint-card">
              <Icon name="bulb" />
              <div style={{ flex: 1 }}>
                <h3>Hint</h3>
                {hint?.reply ? <p style={{ margin: 0, whiteSpace: "pre-wrap" }}><RichText text={hint.reply} /></p>
                  : <p className="muted" style={{ margin: 0 }}>Stuck? Ask for the smallest useful nudge.</p>}
                <button className="btn soft small mt" onClick={() => void askHint()} disabled={s.busy}>Get a hint</button>
              </div>
            </div>
          </section>
        )}
        {concept && (
          <section className="card">
            <h2>Related concepts</h2>
            <ul className="list">
              {[concept.key, ...concept.prereqs].map((k) => names[k]).filter(Boolean).map((c) => (
                <li key={c.key} className="list-row">
                  <span className="ico"><Icon name="target" /></span>
                  <div className="body">
                    <div className="title">{c.name}</div>
                    <div className="muted">{c.practised ? `Estimated mastery ${pct(c.mastery)}` : "Not practised yet"}</div>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}
      </aside>
    </div>
  );
}

function Summary({ set, results, topic, onRetry, onReview, onAsk, onPick }: {
  set: Item[]; results: Record<number, Result>; topic: string;
  onRetry: () => void; onReview: (i: number) => void; onAsk: (msg: string) => void; onPick: () => void;
}) {
  const answered = set.filter((i) => results[i.id]);
  const right = answered.filter((i) => results[i.id].correct).length;
  const score = answered.length ? right / answered.length : 0;
  const meanConf = answered.length
    ? answered.reduce((a, i) => a + results[i.id].confidence, 0) / answered.length : 0;
  const gap = meanConf - score;
  const wrong = set.map((it, i) => [it, i] as const).filter(([it]) => results[it.id] && !results[it.id].correct);
  return (
    <div>
      <h2>Results: {topic}</h2>
      <div className="score-hero">
        <div><div className="big">{right}/{answered.length}</div><div className="muted">correct</div></div>
        <div style={{ flex: 1, minWidth: 220 }}>
          <div className="row between muted"><span>Your average confidence</span><b>{pct(meanConf)}</b></div>
          <div className="progress" style={{ margin: "4px 0 10px" }}><span style={{ width: `${meanConf * 100}%`, background: "var(--series-2)" }} /></div>
          <div className="row between muted"><span>Your accuracy</span><b>{pct(score)}</b></div>
          <div className="progress" style={{ marginTop: 4 }}><span style={{ width: `${score * 100}%` }} /></div>
        </div>
      </div>
      <p className="muted">
        {Math.abs(gap) < 0.15
          ? "Your confidence was close to your results: you judged what you knew well."
          : gap > 0
            ? "You were more confident than your results. Before answering, try explaining the idea to yourself in one sentence."
            : "You knew more than you thought. It is worth trusting your reasoning a little more."}
      </p>
      <ul className="list result-list mt">
        {set.map((it, i) => {
          const r = results[it.id];
          return (
            <li key={it.id}>
              <span className={`mark ${r?.correct ? "ok" : "bad"}`}>{r?.correct ? "✓" : "✗"}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div>{parseItem(it.text).stem}</div>
                <div className="muted small">Your answer: {r?.response ?? "–"} · {pct(r?.confidence)} sure</div>
              </div>
              <button className="btn small" onClick={() => onReview(i)}>Review</button>
            </li>
          );
        })}
      </ul>
      <div className="row mt">
        <button className="btn primary" onClick={onRetry}><Icon name="play" /> Try again</button>
        {wrong.length > 0 && (
          <button className="btn soft" onClick={() => onAsk(`I got ${wrong.length} question(s) on ${topic} wrong. Can you explain the idea again?`)}>
            <Icon name="bot" /> Go over my mistakes with the tutor
          </button>
        )}
        <button className="btn" onClick={onPick}>Pick another topic</button>
      </div>
    </div>
  );
}
