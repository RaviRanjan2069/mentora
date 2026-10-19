// Students: find a teacher by user id, send a request, see the answer, leave.
import { api, errorText, timeAgo } from "../api.js";
import { h, icon, render } from "../dom.js";
import { photoOf } from "../people.js";
import { errorLine, skeleton, toast } from "../ui.js";

const STATUS = {
  accepted: ["ok", "Your teacher"],
  pending: ["warn", "Waiting for an answer"],
  declined: ["", "Declined"],
};

export default function teachers(root, { me }) {
  if (me.via !== "account") {
    render(root, h("section", { class: "card" }, h("h2", null, "My Teachers"),
      h("p", { class: "muted" }, "Connecting with a teacher needs a Mentora account. Sign out and create one.")));
    return undefined;
  }
  const st = { links: null, q: "", hits: [], busy: false, code: "" };
  let timer = 0;

  async function load() {
    try {
      st.links = await api.get("/api/me/teachers");
      paint();
    } catch (e) {
      render(root, errorLine(errorText(e)));
    }
  }

  function search() {
    window.clearTimeout(timer);
    const q = st.q.trim();
    if (q.length < 2) {
      st.hits = [];
      paint();
      return;
    }
    timer = window.setTimeout(async () => {
      try {
        st.hits = await api.get(`/api/teachers/search?q=${encodeURIComponent(q)}`);
      } catch {
        st.hits = [];
      }
      paint();
    }, 300);
  }

  async function ask(username) {
    st.busy = true;
    paint();
    try {
      const link = await api.post("/api/me/teachers", { username });
      toast(`Request sent to ${link.person.name}.`);
      st.q = "";
      st.hits = [];
      st.links = await api.get("/api/me/teachers");
    } catch (e) {
      toast(errorText(e), "error");
    }
    st.busy = false;
    paint();
  }

  async function join(e) {
    e.preventDefault();
    if (!st.code.trim()) return;
    st.busy = true;
    paint();
    try {
      const link = await api.post("/api/me/teachers/join", { code: st.code.trim() });
      toast(`Request sent to ${link.person.name}. They will accept you into their class.`);
      st.code = "";
      st.links = await api.get("/api/me/teachers");
    } catch (err) {
      toast(errorText(err), "error");
    }
    st.busy = false;
    paint();
  }

  async function leave(link) {
    const verb = link.status === "pending" ? "Cancel your request to" : link.status === "accepted" ? "Leave" : "Remove";
    if (!window.confirm(`${verb} ${link.person.name}?`)) return;
    await api.del(`/api/me/teachers/${link.id}`);
    st.links = await api.get("/api/me/teachers");
    paint();
  }

  const connected = new Set();
  function paint() {
    connected.clear();
    for (const l of st.links) if (l.status !== "declined") connected.add(l.person.username);
    render(root, h(
      "div", { class: "stack" },
      me.email_verified === false
        ? h("div", { class: "notice", role: "note" }, h("span", { class: "notice-tag" }, "Email"),
            h("span", { class: "notice-text" }, "Confirm your email address first (open the link we sent you), then you can ask a teacher to add you."))
        : null,
      h("section", { class: "card" },
        h("h2", null, "Join with a class code"),
        h("p", { class: "muted", style: { marginTop: -6 } }, "Your teacher gives you a code, like RAO-PYTHON. They accept your request."),
        h("form", { class: "row", onSubmit: join },
          h("input", {
            type: "text", value: st.code, "data-key": "code", placeholder: "Class code", maxlength: "40",
            autocomplete: "off", spellcheck: "false", style: { maxWidth: 260, textTransform: "uppercase" },
            "aria-label": "Class code", onInput: (e) => { st.code = e.target.value; },
          }),
          h("button", { class: "btn primary", type: "submit", disabled: st.busy }, icon("send"), " Send request"))),
      h("section", { class: "card" },
        h("h2", null, "Or find your teacher by user id"),
        h("p", { class: "muted", style: { marginTop: -6 } }, "Type your teacher's user id. They will see your request and accept you into their class."),
        h("input", {
          type: "search", placeholder: "Teacher's user id, e.g. dr.rao", value: st.q, "data-key": "q",
          "aria-label": "Teacher's user id", autocomplete: "off", onInput: (e) => { st.q = e.target.value; search(); },
        }),
        st.q.trim().length >= 2 && st.hits.length === 0 ? h("p", { class: "empty" }, "No teacher with a user id starting like that.") : null,
        h("ul", { class: "list mt" }, st.hits.map((t) => h(
          "li", { class: "list-row" },
          h("div", { class: "person" }, photoOf(t), h("div", null, h("div", { class: "who-name" }, t.name), h("div", { class: "muted" }, `@${t.username}`))),
          h("div", { class: "spacer" }),
          connected.has(t.username)
            ? h("span", { class: "muted small" }, "Already requested")
            : h("button", { class: "btn primary small", disabled: st.busy, onClick: () => ask(t.username) }, icon("send"), " Send request"))))),
      h("section", { class: "card" },
        h("h2", null, "My teachers"),
        st.links.length === 0 ? h("p", { class: "empty" }, "You have not asked a teacher yet.") : null,
        h("ul", { class: "list" }, st.links.map((l) => {
          const [tone, label] = STATUS[l.status];
          return h("li", { class: "list-row" },
            h("div", { class: "person" }, photoOf(l.person),
              h("div", null, h("div", { class: "who-name" }, l.person.name),
                h("div", { class: "muted" }, `@${l.person.username} · asked ${timeAgo(l.created_at)}`))),
            h("div", { class: "spacer" }),
            h("span", { class: `badge ${tone}` }, label),
            h("button", { class: "btn small", onClick: () => leave(l) }, l.status === "pending" ? "Cancel" : l.status === "accepted" ? "Leave" : "Remove"));
        }))),
    ));
  }

  render(root, skeleton({ cards: 2 }));
  load();
  return () => window.clearTimeout(timer);
}
