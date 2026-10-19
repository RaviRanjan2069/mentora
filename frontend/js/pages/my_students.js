// Teachers: requests from students (accept / decline) and the class roster.
import { api, errorText, timeAgo } from "../api.js";
import { h, icon, render } from "../dom.js";
import { photoOf } from "../people.js";
import { copyText, errorLine, skeleton, toast } from "../ui.js";
import { openStudent } from "./students.js";

export default function myStudents(root, { me }) {
  if (me.via !== "account") {
    render(root, h("section", { class: "card" }, h("h2", null, "My Students"),
      h("p", { class: "muted" }, "Students join teachers who have a Mentora account. You signed in another way, so you see every student on the Students page.")));
    return undefined;
  }
  const st = { requests: null, roster: null, busy: false, code: null, draft: "", editing: false };

  async function load() {
    try {
      let codeRow;
      [st.requests, st.roster, codeRow] = await Promise.all([
        api.get("/api/teacher/requests"), api.get("/api/teacher/my-students"), api.get("/api/teacher/class-code"),
      ]);
      st.code = codeRow.code;
      paint();
    } catch (e) {
      render(root, errorLine(errorText(e)));
    }
  }

  async function decide(link, accept) {
    st.busy = true;
    paint();
    try {
      await api.post(`/api/teacher/requests/${link.id}`, { accept });
      toast(accept ? `${link.person.name} is now in your class.` : `Request from ${link.person.name} declined.`);
      await load();
    } catch (e) {
      toast(errorText(e), "error");
    }
    st.busy = false;
    paint();
  }

  async function remove(link) {
    if (!window.confirm(`Remove ${link.person.name} from your class? They can ask again later.`)) return;
    await api.del(`/api/teacher/my-students/${link.id}`);
    await load();
  }

  async function saveCode(e) {
    e.preventDefault();
    st.busy = true;
    paint();
    try {
      const r = await fetch("/api/teacher/class-code", {
        method: "PUT", credentials: "same-origin", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: st.draft }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Could not save the code.");
      const changed = st.code && st.code !== data.code;
      st.code = data.code;
      st.editing = false;
      toast(changed ? `Your class code is now ${data.code}. The old code no longer works.` : `Your class code is ${data.code}.`);
    } catch (err) {
      toast(errorText(err), "error");
    }
    st.busy = false;
    paint();
  }

  async function removeCode() {
    if (!window.confirm(`Remove the class code ${st.code}? Students will no longer be able to use it.`)) return;
    await api.del("/api/teacher/class-code");
    st.code = null;
    paint();
  }

  function codeCard() {
    const shareText = `Join my class on Mentora: sign in at ${window.location.origin}/app/, open My Teachers and enter the code ${st.code}.`;
    const form = h("form", { class: "row", onSubmit: saveCode },
      h("input", {
        type: "text", value: st.draft, "data-key": "code", placeholder: "e.g. RAO-PYTHON", maxlength: "20",
        autocomplete: "off", spellcheck: "false", style: { maxWidth: 240, textTransform: "uppercase" },
        onInput: (e) => { st.draft = e.target.value; },
      }),
      h("button", { class: "btn primary", type: "submit", disabled: st.busy }, st.code ? "Save new code" : "Create code"),
      st.code ? h("button", { type: "button", class: "btn", onClick: () => { st.editing = false; paint(); } }, "Cancel") : null);
    return h("section", { class: "card" },
      h("h2", null, "Your class code"),
      st.code && !st.editing
        ? [h("div", { class: "row" },
            h("span", { class: "class-code" }, st.code),
            h("button", { class: "btn small", onClick: () => copyText(st.code) }, icon("copy"), " Copy code"),
            h("button", { class: "btn small", onClick: () => copyText(shareText) }, icon("send"), " Copy invite message"),
            h("button", { class: "btn small", onClick: () => { st.editing = true; st.draft = st.code; paint(); } }, icon("pen"), " Change"),
            h("button", { class: "btn small danger", onClick: removeCode }, "Remove")),
          h("p", { class: "muted", style: { marginBottom: 0 } },
            "Students enter this code on their My Teachers page. Each one arrives here as a request for you to accept. ",
            "The code stays the same until you change it.")]
        : [h("p", { class: "muted", style: { marginTop: -6 } },
            "Choose a permanent code for your class (4-20 letters, digits or hyphens). Share it with your students; ",
            "their requests appear below for you to accept."),
          form]);
  }

  const who = (l) => h("div", { class: "person" }, photoOf(l.person),
    h("div", null, h("div", { class: "who-name" }, l.person.name),
      h("div", { class: "muted" }, `@${l.person.username}${l.email_verified === false ? " · email not confirmed" : ""}`)));

  function paint() {
    render(root, h(
      "div", { class: "stack" },
      me.email_verified === false
        ? h("div", { class: "notice", role: "note" }, h("span", { class: "notice-tag" }, "Email"),
            h("span", { class: "notice-text" }, "Confirm your email address (open the link we sent you) before accepting students."))
        : null,
      codeCard(),
      h("section", { class: "card" },
        h("h2", null, `Requests to join your class (${st.requests.length})`),
        h("p", { class: "muted", style: { marginTop: -6 } },
          `Students find you by your class code${st.code ? ` (${st.code})` : ""} or your user id: @${me.username}.`),
        st.requests.length === 0 ? h("p", { class: "empty" }, "No requests waiting.") : null,
        h("ul", { class: "list" }, st.requests.map((l) => h(
          "li", { class: "list-row" },
          who(l), h("div", { class: "spacer" }),
          h("span", { class: "muted small" }, timeAgo(l.created_at)),
          h("button", { class: "btn primary small", disabled: st.busy, onClick: () => decide(l, true) }, icon("check"), " Accept"),
          h("button", { class: "btn small", disabled: st.busy, onClick: () => decide(l, false) }, "Decline"))))),
      h("section", { class: "card" },
        h("h2", null, `My students (${st.roster.length})`),
        st.roster.length === 0 ? h("p", { class: "empty" }, "No students yet. Share your class code (or user id) with your class.") : null,
        h("ul", { class: "list" }, st.roster.map((l) => h(
          "li", { class: "list-row" },
          who(l), h("div", { class: "spacer" }),
          h("span", { class: "muted small" }, `joined ${timeAgo(l.decided_at ?? l.created_at)}`),
          l.learner_id
            ? h("button", { class: "btn small", onClick: () => openStudent(l.learner_id, l.person) }, icon("eye"), " Progress")
            : null,
          h("button", { class: "btn small danger", onClick: () => remove(l) }, "Remove"))))),
    ));
  }

  render(root, skeleton({ cards: 2 }));
  load();
  return undefined;
}
