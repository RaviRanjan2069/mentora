import { api, errorText, pct, timeAgo } from "../api.js";
import { phaseBars, ring, SRL_ROWS, statCard } from "../charts.js";
import { h, icon, plural, render } from "../dom.js";
import { errorLine, skeleton } from "../ui.js";

const ACTIVITY_ICON = {
  quiz: ["check", "green"],
  practice: ["practice", ""],
  resource: ["book", "orange"],
  chat: ["chat", ""],
  session: ["clock", ""],
};

export default function home(root) {
  render(root, skeleton({ stats: true, cards: 2 }));
  api.get("/api/me/home").then((data) => render(root, view(data))).catch((e) => render(root, errorLine(errorText(e))));
}

function view(data) {
  const s = data.stats;
  const delta = s.quiz_average !== null && s.quiz_average_previous !== null
    ? Math.round((s.quiz_average - s.quiz_average_previous) * 100) : null;
  return h(
    "div", { class: "stack" },
    h("div", { class: "grid cols-4" },
      statCard({ icon: "flame", tone: "orange", label: "Study streak", value: plural(s.streak_days, "day"), note: "days in a row with a session" }),
      statCard({ icon: "check", tone: "green", label: "Topics mastered", value: `${s.topics_completed} / ${s.topics_total}`, note: "concepts in this course" }),
      statCard({
        icon: "bars", label: "Quiz average", value: pct(s.quiz_average),
        note: delta === null ? "this week"
          : h("span", { class: delta >= 0 ? "delta-up" : "delta-down" }, `${delta >= 0 ? "+" : ""}${delta}% from last week`),
      }),
      statCard({ icon: "clock", label: "Learning time", value: `${s.learning_hours_week.toFixed(1)} h`, note: "this week" })),

    h("div", { class: "grid cols-wide-narrow" },
      h("section", { class: "card" },
        h("h2", null, "SRL progress"),
        !data.srl.has_data
          ? h("p", { class: "empty" }, "Start a study session to see how you plan, practise and reflect.")
          : h("div", { class: "row", style: { gap: 24, alignItems: "center" } },
              ring(data.srl.overall, "Overall self-regulated learning"),
              h("div", { style: { flex: 1, minWidth: 220 } },
                phaseBars(SRL_ROWS(data.srl)),
                h("div", { class: "row", style: { justifyContent: "flex-end" } },
                  h("a", { href: "#/progress", class: "link-btn" }, "View detailed analysis →")))),
        h("details", null,
          h("summary", null, "How are these calculated?"),
          h("p", { class: "muted" },
            "Forethought: how often you set a goal, and how specific your goals are. Performance: how well your "
            + "confidence matches your results, and your recent accuracy. Self-reflection: how often you look back "
            + "on a session, and how much your reflections cover (what happened, why, and what you'll change)."))),
      h("section", { class: "card" },
        h("h2", null, "Current learning strategy"),
        data.strategy
          ? h("div", { class: "hint-card" }, icon("bulb"),
              h("div", null,
                h("h3", { style: { color: "var(--brand)" } }, data.strategy.title),
                h("p", { class: "muted", style: { marginTop: 0 } }, `${data.strategy.description} ${data.strategy.why}`),
                h("a", { class: "btn soft small", href: "#/tutor" }, "Continue with the tutor")))
          : h("p", { class: "empty" }, "Your tutor will suggest a strategy once you start a session."))),

    h("div", { class: "grid cols-wide-narrow" },
      h("section", { class: "card" },
        h("h2", null, "Recent activity"),
        data.activity.length === 0 ? h("p", { class: "empty" }, "Nothing yet.") : null,
        h("ul", { class: "list" }, data.activity.map((a) => {
          const [name, tone] = ACTIVITY_ICON[a.kind] ?? ["activity", ""];
          return h("li", { class: "list-row" },
            h("span", { class: `ico ${tone}` }, icon(name)),
            h("div", { class: "body" }, h("div", { class: "title" }, a.text), h("div", { class: "muted" }, timeAgo(a.at))));
        }))),
      h("section", { class: "card" },
        h("h2", null, "Recommended next steps"),
        data.next_steps.length === 0 ? h("p", { class: "empty" }, "You've covered everything that is open to you right now.") : null,
        h("ul", { class: "list" }, data.next_steps.map((n) => h(
          "li", { class: "list-row" },
          h("span", { class: `ico ${n.kind === "practice" ? "green" : "orange"}` }, icon(n.kind === "practice" ? "practice" : "book")),
          h("div", { class: "body" }, h("div", { class: "title" }, n.title), h("div", { class: "muted" }, n.detail)),
          h("a", {
            class: "arrow-btn", "aria-label": n.title,
            href: n.kind === "practice" ? `#/practice?concept=${n.concept}` : `#/resources?concept=${n.concept}`,
          }, icon("arrow"))))))),
  );
}
