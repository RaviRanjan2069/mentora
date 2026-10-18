import { api, ApiError, errorText } from "../api.js";
import { h, icon, logo, render } from "../dom.js";

const FEATURES = [
  ["target", "Set a goal, plan the steps, then practise with feedback"],
  ["bot", "A tutor that explains why it suggests each next step"],
  ["book", "Answers grounded in your course notes, with sources"],
  ["shield", "Pseudonymous by design; you can see and delete what it remembers"],
];

export default function login(root, { onSignedIn }) {
  const state = { name: "", role: "learner", code: "", error: null, busy: false };

  async function submit(e) {
    e.preventDefault();
    state.error = null;
    state.busy = true;
    paint();
    try {
      await api.post("/api/dev/login", {
        role: state.role,
        name: state.name.trim() || "Demo learner",
        ...(state.role === "teacher" && state.code ? { access_code: state.code } : {}),
      });
      window.location.hash = state.role === "teacher" ? "#/teacher" : "#/";
      onSignedIn();
      return;
    } catch (err) {
      state.error = err instanceof ApiError && err.status === 404
        ? "Development sign-in is turned off. Open Mentora from your Moodle course."
        : err instanceof ApiError && err.status === 403
          ? "That teacher access code is not right."
          : errorText(err);
    }
    state.busy = false;
    paint();
  }

  function paint() {
    render(root, h(
      "div", { class: "login-wrap" },
      h("section", { class: "login-art" },
        h("div", { class: "brand" }, logo(),
          h("div", null, h("b", null, "Mentora"), h("small", null, "Self-learning strategy tutor"))),
        h("div", null,
          h("h2", null, "Learn how you learn: plan, practise, reflect."),
          h("p", null, "Mentora helps you set goals, work through course material with an AI tutor, and look back on what worked."),
          h("ul", null, FEATURES.map(([name, text]) => h("li", null, icon(name), text)))),
        h("p", { class: "foot small" }, "Part of your course in Moodle.")),
      h("section", { class: "login-form" },
        h("form", { class: "card", onSubmit: submit },
          h("h2", { style: { fontSize: 20, marginBottom: 4 } }, "Sign in"),
          h("p", { class: "muted", style: { marginTop: 0 } },
            "Students and teachers normally open Mentora from the Moodle course page. For local testing you can sign in here."),
          h("label", { style: { display: "block", marginBottom: 14 } },
            h("span", { class: "muted" }, "Your name"),
            h("input", {
              type: "text", value: state.name, placeholder: "e.g. Asha", maxlength: "60", autofocus: true,
              "data-key": "name", onInput: (e) => { state.name = e.target.value; },
            })),
          h("span", { class: "muted" }, "I am a"),
          h("div", { class: "role-pick", role: "radiogroup", "aria-label": "Role" },
            [["learner", "user", "Student"], ["teacher", "users", "Teacher"]].map(([r, name, label]) => h(
              "label", { class: state.role === r ? "on" : "" },
              h("input", {
                type: "radio", name: "role", checked: state.role === r,
                onChange: () => { state.role = r; paint(); },
              }),
              icon(name), " ", label))),
          state.role === "teacher"
            ? h("label", { style: { display: "block", marginBottom: 14 } },
                h("span", { class: "muted" }, "Teacher access code (if this demo uses one)"),
                h("input", {
                  type: "password", value: state.code, autocomplete: "off", maxlength: "200",
                  "data-key": "code", onInput: (e) => { state.code = e.target.value; },
                }))
            : null,
          h("button", {
            class: "btn primary", type: "submit", disabled: state.busy,
            style: { width: "100%", justifyContent: "center", padding: "10px 14px" },
          }, state.busy ? "Signing in…" : "Sign in"),
          state.error ? h("p", { class: "error" }, state.error) : null)),
    ));
  }

  paint();
  root.querySelector('[data-key="name"]')?.focus();
}
