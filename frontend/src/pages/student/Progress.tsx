import { Dashboard, Home, pct } from "../../api";
import CalibrationChart from "../../components/CalibrationChart";
import { Heatmap, PhaseBars } from "../../components/Charts";
import MasteryBars from "../../components/MasteryBars";
import { Skeleton } from "../../components/ui";
import { useLoad } from "../../session";

export default function Progress() {
  const [data] = useLoad<Dashboard>("/api/me/dashboard");
  const [home] = useLoad<Home>("/api/me/home");
  if (!data || !home) return <Skeleton cards={3} />;
  return (
    <div className="stack">
      <section className="card">
        <h2>Study activity</h2>
        <Heatmap days={home.calendar} />
      </section>
      <div className="grid cols-2">
        <section className="card">
          <h2>Self-regulated learning by phase</h2>
          <PhaseBars rows={[
            { label: "Forethought", value: home.srl.forethought, color: "var(--series-1)" },
            { label: "Performance", value: home.srl.performance, color: "var(--series-2)" },
            { label: "Self-reflection", value: home.srl.reflection, color: "var(--series-3)" },
          ]} />
          <ul className="muted" style={{ paddingLeft: 18 }}>
            <li><b>Forethought</b>: how often you set a goal at the start, and how specific your goals are.</li>
            <li><b>Performance</b>: how closely your confidence matches your results, and your recent accuracy.</li>
            <li><b>Self-reflection</b>: how often you look back on a session, and whether you say what happened, why, and what you'll change.</li>
          </ul>
        </section>
        <section className="card">
          <h2>Confidence vs results</h2>
          <p className="muted" style={{ marginTop: -6 }}>
            Calibration error {pct(data.calibration_error)} (lower means your confidence matches your results more closely).
          </p>
          <CalibrationChart points={data.calibration_points} />
        </section>
      </div>
      <section className="card">
        <h2>Estimated mastery by concept</h2>
        <p className="muted" style={{ marginTop: -6 }}>An estimate from your practice answers. Faint bars are concepts you have not practised yet.</p>
        <MasteryBars rows={data.mastery} />
      </section>
    </div>
  );
}
