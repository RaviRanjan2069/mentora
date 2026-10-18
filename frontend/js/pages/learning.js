import { actionLabel, api, errorText, pct } from "../api.js";
import { h, icon, render } from "../dom.js";
import { errorLine, skeleton, toast } from "../ui.js";

export default function learning(root) {
  let data = null;
  let memory = null;

  async function load() {
    try {
      [data, memory] = await Promise.all([api.get("/api/me/dashboard"), api.get("/api/me/memory")]);
      paint();
    } catch (e) {
      render(root, errorLine(errorText(e)));
    }
  }

  async function forget(id) {
    await api.del(`/api/me/memory/${id}`);
    memory = await api.get("/api/me/memory");
    paint();
    toast("Deleted. The tutor will no longer use that note.");
  }

  function paint() {
    const active = data.goals.filter((g) => g.status === "active");
    const past = data.goals.filter((g) => g.status !== "active");
    render(root, h(
      "div", { class: "stack" },
      data.teacher_replies.length > 0
        ? h("section", { class: "card" },
            h("h2", null, "Messages from your teacher"),
            h("ul", { class: "list" }, data.teacher_replies.map((r) => h(
              "li", { class: "list-row" },
              h("span", { class: "ico" }, icon("chat")),
              h("div", { class: "body" },
                r.question ? h("div", { class: "muted" }, `You wrote: “${r.question}”`) : null,
                h("div", null, r.response))))))
        : null,

      h("div", { class: "grid cols-2" },
        h("section", { class: "card" },
          h("h2", null, "Goals and plan"),
          active.length === 0 ? h("p", { class: "empty" }, "No active goal. Start a session with the tutor to set one.") : null,
          h("ul", { class: "list" }, active.map((g) => h(
            "li", null,
            h("div", { class: "title" }, h("b", null, g.text)),
            h("div", { class: "row muted" },
              h("span", null, `Plan progress ${pct(g.progress)}`),
              g.smart_score !== null ? h("span", null, `· goal clarity ${pct(g.smart_score)}`) : null),
            h("div", { class: "progress", style: { margin: "6px 0" } }, h("span", { style: { width: `${g.progress * 100}%` } })),
            h("ul", { class: "muted", style: { paddingLeft: 18, margin: 0 } }, g.steps.map((s) => h(
              "li", null, `${s.done ? "✓ " : ""}${s.concept ? `Master ${s.concept.replace(/_/g, " ")}` : s.text}`)))))),
          past.length > 0
            ? h("details", null,
                h("summary", null, `Earlier goals (${past.length})`),
                h("ul", { class: "muted" }, past.map((g) => h("li", null, `${g.text} (${g.status})`))))
            : null),
        h("section", { class: "card" },
          h("h2", null, "What Mentora remembers about you"),
          h("p", { class: "muted", style: { marginTop: -6 } }, "Short notes that help the tutor in later sessions. You can delete any of them."),
          memory.length === 0 ? h("p", { class: "empty" }, "Nothing yet.") : null,
          h("ul", { class: "list" }, memory.map((m) => h(
            "li", { class: "list-row" },
            h("div", { class: "body" }, m.text),
            h("button", { class: "btn small danger", onClick: () => forget(m.id) }, icon("trash"), " Delete")))))),

      h("section", { class: "card" },
        h("h2", null, "Recent tutor suggestions"),
        data.recent_tutor_messages.length === 0 ? h("p", { class: "empty" }, "None yet.") : null,
        h("ul", { class: "list" }, data.recent_tutor_messages.slice(0, 10).map((t) => h(
          "li", null,
          h("span", { class: "chip" }, actionLabel(t.action)),
          h("div", { style: { marginTop: 4 } }, t.reply?.split("\n\nWhy this suggestion:")[0]),
          t.why ? h("div", { class: "muted small" }, t.why) : null)))),
    ));
  }

  render(root, skeleton({ cards: 3 }));
  load();
}
