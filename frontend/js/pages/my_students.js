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
  const st = { requests: null, roster: null, busy: false, code: null };

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

  function codeCard() {
    const shareText = `Join my class on Mentora: sign in at ${window.location.origin}/app/, open My Teachers and enter the code ${st.code}.`;
    return h("section", { class: "card" },
      h("h2", null, "Your class code"),
      st.code
        ? [h("div", { class: "row" },
            h("span", { class: "class-code" }, st.code),
            h("button", { class: "btn small", onClick: () => copyText(st.code) }, icon("copy"), " Copy code"),
            h("button", { class: "btn small", onClick: () => copyText(shareText) }, icon("send"), " Copy invite message")),
          h("p", { class: "muted", style: { marginBottom: 0 } },
            "This is your permanent class code. Students enter it on their My Teachers page, and each one arrives here ",
            "as a request for you to accept.")]
        : h("p", { class: "muted", style: { marginBottom: 0 } }, "Class codes are for teachers with a Mentora account."));
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
