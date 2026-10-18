import { Home as HomeData, pct, timeAgo } from "../../api";
import { PhaseBars, Ring, StatCard } from "../../components/Charts";
import Icon, { IconName } from "../../icons";
import { Skeleton } from "../../components/ui";
import { useLoad } from "../../session";

const ACTIVITY_ICON: Record<string, [IconName, string]> = {
  quiz: ["check", "green"],
  practice: ["practice", ""],
  resource: ["book", "orange"],
  chat: ["chat", ""],
  session: ["clock", ""],
};

export default function Home() {
  const [data, , error] = useLoad<HomeData>("/api/me/home");
  if (error) return <p className="error">{error}</p>;
  if (!data) return <Skeleton stats cards={2} />;
  const s = data.stats;
  const delta = s.quiz_average !== null && s.quiz_average_previous !== null
    ? Math.round((s.quiz_average - s.quiz_average_previous) * 100) : null;

  return (
    <div className="stack">
      <div className="grid cols-4">
        <StatCard icon="flame" tone="orange" label="Study streak" value={`${s.streak_days} day${s.streak_days === 1 ? "" : "s"}`}
                  note="days in a row with a session" />
        <StatCard icon="check" tone="green" label="Topics mastered" value={`${s.topics_completed} / ${s.topics_total}`}
                  note="concepts in this course" />
        <StatCard icon="bars" label="Quiz average" value={pct(s.quiz_average)}
                  note={delta === null ? "this week" : (
                    <span className={delta >= 0 ? "delta-up" : "delta-down"}>
                      {delta >= 0 ? "+" : ""}{delta}% from last week
                    </span>)} />
        <StatCard icon="clock" label="Learning time" value={`${s.learning_hours_week.toFixed(1)} h`} note="this week" />
      </div>

      <div className="grid cols-wide-narrow">
        <section className="card">
          <h2>SRL progress</h2>
          {!data.srl.has_data ? (
            <p className="empty">Start a study session to see how you plan, practise and reflect.</p>
          ) : (
            <div className="row" style={{ gap: 24, alignItems: "center" }}>
              <Ring value={data.srl.overall} label="Overall self-regulated learning" />
              <div style={{ flex: 1, minWidth: 220 }}>
                <PhaseBars rows={[
                  { label: "Forethought", value: data.srl.forethought, color: "var(--series-1)" },
                  { label: "Performance", value: data.srl.performance, color: "var(--series-2)" },
                  { label: "Self-reflection", value: data.srl.reflection, color: "var(--series-3)" },
                ]} />
                <div className="row" style={{ justifyContent: "flex-end" }}>
                  <a href="#/progress" className="link-btn">View detailed analysis →</a>
                </div>
              </div>
            </div>
          )}
          <details>
            <summary>How are these calculated?</summary>
            <p className="muted">
              Forethought: how often you set a goal, and how specific your goals are. Performance: how
              well your confidence matches your results, and your recent accuracy. Self-reflection: how
              often you look back on a session, and how much your reflections cover (what happened, why,
              and what you'll change).
            </p>
          </details>
        </section>

        <section className="card">
          <h2>Current learning strategy</h2>
          {data.strategy ? (
            <div className="hint-card">
              <Icon name="bulb" />
              <div>
                <h3 style={{ color: "var(--brand)" }}>{data.strategy.title}</h3>
                <p className="muted" style={{ marginTop: 0 }}>{data.strategy.description} {data.strategy.why}</p>
                <a className="btn soft small" href="#/tutor">Continue with the tutor</a>
              </div>
            </div>
          ) : (
            <p className="empty">Your tutor will suggest a strategy once you start a session.</p>
          )}
        </section>
      </div>

      <div className="grid cols-wide-narrow">
        <section className="card">
          <h2>Recent activity</h2>
          {data.activity.length === 0 && <p className="empty">Nothing yet.</p>}
          <ul className="list">
            {data.activity.map((a, i) => {
              const [icon, tone] = ACTIVITY_ICON[a.kind] ?? ["activity", ""];
              return (
                <li key={i} className="list-row">
                  <span className={`ico ${tone}`}><Icon name={icon} /></span>
                  <div className="body"><div className="title">{a.text}</div><div className="muted">{timeAgo(a.at)}</div></div>
                </li>
              );
            })}
          </ul>
        </section>

        <section className="card">
          <h2>Recommended next steps</h2>
          {data.next_steps.length === 0 && <p className="empty">You've covered everything that is open to you right now.</p>}
          <ul className="list">
            {data.next_steps.map((n) => (
              <li key={n.concept} className="list-row">
                <span className={`ico ${n.kind === "practice" ? "green" : "orange"}`}>
                  <Icon name={n.kind === "practice" ? "practice" : "book"} />
                </span>
                <div className="body"><div className="title">{n.title}</div><div className="muted">{n.detail}</div></div>
                <a className="arrow-btn" aria-label={n.title}
                   href={n.kind === "practice" ? `#/practice?concept=${n.concept}` : `#/resources?concept=${n.concept}`}>
                  <Icon name="arrow" />
                </a>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
