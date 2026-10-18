import { api, errorText } from "../api.js";
import { h, render } from "../dom.js";
import { errorLine, skeleton, toast } from "../ui.js";

export default function escalations(root) {
  let rows = null;
  const drafts = {};

  async function load() {
    try {
      rows = await api.get("/api/teacher/escalations");
      paint();
    } catch (e) {
      render(root, errorLine(errorText(e)));
    }
  }

  async function answer(id) {
    await api.post(`/api/teacher/escalations/${id}/answer`, { response: drafts[id] });
    delete drafts[id];
    await load();
    toast("Reply sent. The student will see it in Mentora.");
  }

  function paint() {
    const open = rows.filter((r) => r.status === "open");
    const done = rows.filter((r) => r.status !== "open");
    render(root, h(
      "div", { class: "stack" },
      h("section", { class: "card" },
        h("h2", null, `Waiting for you (${open.length})`),
        open.length === 0 ? h("p", { class: "empty" }, "Nothing waiting for you.") : null,
        h("ul", { class: "list" }, open.map((e) => {
          const send = h("button", { class: "btn primary small mt", disabled: !drafts[e.id]?.trim(), onClick: () => answer(e.id) }, "Send reply");
          return h("li", null,
            h("div", { class: "row" },
              h("span", { class: `badge ${e.reason === "distress" ? "danger" : "warn"}` }, e.reason.replace(/_/g, " ")),
              h("span", { class: "muted" }, "student ", h("code", null, e.learner), ` · ${new Date(e.created_at).toLocaleString()}`)),
            e.message ? h("p", null, `“${e.message}”`) : null,
            e.reason === "distress"
              ? h("p", { class: "error" }, "Possible distress: consider contacting the student directly and pointing them to the counselling service.")
              : null,
            h("textarea", {
              rows: "2", placeholder: "Reply to the student…", value: drafts[e.id] ?? "", "data-key": `reply-${e.id}`,
              onInput: (ev) => { drafts[e.id] = ev.target.value; send.disabled = !drafts[e.id].trim(); },
            }),
            send);
        }))),
      done.length > 0
        ? h("section", { class: "card" },
            h("h2", null, "Answered"),
            h("ul", { class: "list" }, done.map((e) => h("li", null,
              h("span", { class: "muted" }, `${e.reason.replace(/_/g, " ")} · `, h("code", null, e.learner), ":"),
              ` ${e.teacher_response ?? ""}`))))
        : null,
    ));
  }

  render(root, skeleton({ cards: 2 }));
  load();
}
