import { api, errorText, pct } from "../api.js";
import { calibrationChart, heatmap, masteryBars, phaseBars, SRL_ROWS } from "../charts.js";
import { h, render } from "../dom.js";
import { errorLine, skeleton } from "../ui.js";

export default function progress(root) {
  render(root, skeleton({ cards: 3 }));
  Promise.all([api.get("/api/me/dashboard"), api.get("/api/me/home")])
    .then(([data, home]) => render(root, h(
      "div", { class: "stack" },
      h("section", { class: "card" }, h("h2", null, "Study activity"), heatmap(home.calendar)),
      h("div", { class: "grid cols-2" },
        h("section", { class: "card" },
          h("h2", null, "Self-regulated learning by phase"),
          phaseBars(SRL_ROWS(home.srl)),
          h("ul", { class: "muted", style: { paddingLeft: 18 } },
            h("li", null, h("b", null, "Forethought"), ": how often you set a goal at the start, and how specific your goals are."),
            h("li", null, h("b", null, "Performance"), ": how closely your confidence matches your results, and your recent accuracy."),
            h("li", null, h("b", null, "Self-reflection"),
              ": how often you look back on a session, and whether you say what happened, why, and what you'll change."))),
        h("section", { class: "card" },
          h("h2", null, "Confidence vs results"),
          h("p", { class: "muted", style: { marginTop: -6 } },
            `Calibration error ${pct(data.calibration_error)} (lower means your confidence matches your results more closely).`),
          calibrationChart(data.calibration_points))),
      h("section", { class: "card" },
        h("h2", null, "Estimated mastery by concept"),
        h("p", { class: "muted", style: { marginTop: -6 } },
          "An estimate from your practice answers. Faint bars are concepts you have not practised yet."),
        masteryBars(data.mastery)),
    )))
    .catch((e) => render(root, errorLine(errorText(e))));
}
