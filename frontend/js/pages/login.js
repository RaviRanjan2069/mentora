// Sign in, create an account, forgotten password, reset (from the email link), verify email.
import { api, ApiError, errorText } from "../api.js";
import { h, hashParam, icon, logo, render } from "../dom.js";
import { GENDERS } from "../people.js";
import { toast } from "../ui.js";

const FEATURES = [
  ["target", "Goals and plans", "Set a goal, plan the steps, then practise with feedback."],
  ["bot", "An AI tutor", "Explains why it suggests each next step."],
  ["book", "Grounded answers", "Built on your course notes, with sources."],
  ["shield", "Private by design", "Learning data under a pseudonym; delete your account any time."],
];

/** 0-4: length and variety of characters. */
function strength(pw) {
  let score = 0;
  if (pw.length >= 8) score += 1;
  if (pw.length >= 12) score += 1;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score += 1;
  if (/\d/.test(pw) && /[^A-Za-z0-9]/.test(pw)) score += 1;
  return Math.min(score, 4);
}
const STRENGTH = [["Too weak", "var(--danger)"], ["Weak", "var(--danger)"], ["Fair", "#d97706"], ["Good", "var(--series-1)"], ["Strong", "var(--ok)"]];

function passwordField(st, key, label, { onInput, autocomplete = "current-password", meter = false } = {}) {
  const input = h("input", {
    type: st[`show_${key}`] ? "text" : "password", value: st[key], "data-key": key, autocomplete, maxlength: "128",
    required: true,
    onInput: (e) => {
      st[key] = e.target.value;
      onInput?.(e);
    },
  });
  const level = strength(st[key]);
  return h("label", { class: "field" },
    h("span", null, label),
    h("div", { class: "pw-wrap" }, input,
      h("button", {
        type: "button", "aria-label": st[`show_${key}`] ? "Hide password" : "Show password",
        onClick: () => {
          st[`show_${key}`] = !st[`show_${key}`];
          input.type = st[`show_${key}`] ? "text" : "password";
          input.nextSibling.textContent = st[`show_${key}`] ? "Hide" : "Show";
          input.focus();
        },
      }, st[`show_${key}`] ? "Hide" : "Show")),
    meter
      ? [h("div", { class: "strength", "aria-hidden": "true" },
          h("span", { "data-meter": key, style: { width: `${(level / 4) * 100}%`, background: STRENGTH[level][1] } })),
        h("div", { class: "hint", "data-meter-label": key }, st[key] ? STRENGTH[level][0] : "At least 8 characters; longer is better.")]
      : null);
}

function updateMeter(root, key, value) {
  const level = strength(value);
  const bar = root.querySelector(`[data-meter="${key}"]`);
  const label = root.querySelector(`[data-meter-label="${key}"]`);
  if (bar) {
    bar.style.width = `${(level / 4) * 100}%`;
    bar.style.background = STRENGTH[level][1];
  }
  if (label) label.textContent = value ? STRENGTH[level][0] : "At least 8 characters; longer is better.";
}

export default function login(root, { onSignedIn, mode: initialMode = "signin" }) {
  const st = {
    mode: initialMode, busy: false, error: null, done: null, options: { dev_login: false, email: false, teacher_signup: true },
    login: "", password: "", role: "learner", name: "", username: "", email: "", password2: "",
    gender: "prefer_not_to_say", accept: false, userCheck: null, devName: "", devRole: "learner", devCode: "",
    classCode: "",
  };
  let checkTimer = 0;

  const go = (mode) => {
    Object.assign(st, { mode, error: null, done: null, password: "", password2: "" });
    paint();
  };

  async function run(fn) {
    st.error = null;
    st.busy = true;
    paint();
    try {
      await fn();
    } catch (e) {
      st.error = errorText(e);
    }
    st.busy = false;
    paint();
  }

  const signIn = (e) => {
    e.preventDefault();
    run(async () => {
      await api.post("/api/auth/login", { login: st.login.trim(), password: st.password });
      window.location.hash = "#/";
      onSignedIn();
    });
  };

  const signUp = (e) => {
    e.preventDefault();
    if (st.password !== st.password2) {
      st.error = "The two passwords are not the same.";
      paint();
      return;
    }
    run(async () => {
      const r = await api.post("/api/auth/signup", {
        role: st.role, username: st.username.trim(), email: st.email.trim(), password: st.password,
        name: st.name.trim(), gender: st.gender, class_code: st.role === "teacher" ? st.classCode : "",
        accept_privacy: st.accept,
      }).catch((err) => {
        if (st.role === "teacher" && /class code/.test(errorText(err))) suggestCode(true);
        throw err;
      });
      if (r.class_code) toast(`Welcome! Your permanent class code is ${r.class_code}.`);
      if (r.verification_sent) toast(`We sent a confirmation link to ${st.email.trim()}.`);
      window.location.hash = st.role === "teacher" ? "#/teacher" : "#/";
      onSignedIn();
    });
  };

  async function suggestCode(again = false) {
    if (st.classCode && !again) return;
    try {
      st.classCode = (await api.get("/api/auth/class-code-suggestion")).code;
    } catch {
      st.classCode = "";  // the server picks one at sign-up
    }
    paint();
  }

  function classCodeField() {
    return h("div", { class: "field class-code-field" },
      h("span", null, "Your class code"),
      h("div", { class: "class-code-pick" },
        h("span", { class: "class-code", "data-class-code": "" }, st.classCode || "…"),
        h("button", { type: "button", class: "btn small", onClick: () => suggestCode(true) }, icon("sparkle"), " Another code")),
      h("div", { class: "hint" },
        "Your students type this code to ask to join your class. It becomes permanent when you create your account."));
  }

  const forgot = (e) => {
    e.preventDefault();
    run(async () => {
      await api.post("/api/auth/forgot", { email: st.email.trim() });
      st.done = "If an account uses that email, we have sent it a link to choose a new password. "
        + "It works for one hour. Check your spam folder if you do not see it.";
    });
  };

  const reset = (e) => {
    e.preventDefault();
    if (st.password !== st.password2) {
      st.error = "The two passwords are not the same.";
      paint();
      return;
    }
    run(async () => {
      await api.post("/api/auth/reset", { token: hashParam("token") ?? "", password: st.password });
      toast("Your password is changed and you are signed in.");
      window.location.hash = "#/";
      onSignedIn();
    });
  };

  const devSignIn = (e) => {
    e.preventDefault();
    run(async () => {
      try {
        await api.post("/api/dev/login", {
          role: st.devRole, name: st.devName.trim() || "Demo learner",
          ...(st.devRole === "teacher" && st.devCode ? { access_code: st.devCode } : {}),
        });
      } catch (err) {
        if (err instanceof ApiError && err.status === 403) throw new Error("That teacher access code is not right.");
        throw err;
      }
      window.location.hash = st.devRole === "teacher" ? "#/teacher" : "#/";
      onSignedIn();
    });
  };

  function checkUsername() {
    window.clearTimeout(checkTimer);
    const value = st.username.trim();
    if (value.length < 3) {
      st.userCheck = null;
      setHint();
      return;
    }
    checkTimer = window.setTimeout(async () => {
      try {
        const r = await api.get(`/api/auth/username-available?username=${encodeURIComponent(value)}`);
        if (value === st.username.trim()) st.userCheck = r;
      } catch {
        st.userCheck = null;
      }
      setHint();
    }, 350);
  }

  function setHint() {
    const el = root.querySelector("[data-user-hint]");
    if (!el) return;
    const c = st.userCheck;
    el.className = `hint ${c ? (c.available ? "ok" : "bad") : ""}`;
    el.textContent = c ? (c.available ? "✓ This user id is available. It is permanent." : c.reason)
      : "Your permanent user id: 3-30 letters, digits, dots or underscores.";
  }

  const text = (key, label, props = {}) => h("label", { class: "field" },
    h("span", null, label),
    h("input", { type: "text", value: st[key], "data-key": key, onInput: (e) => { st[key] = e.target.value; }, ...props }));

  const submit = (label, busyLabel) => h("button", {
    class: "btn primary", type: "submit", disabled: st.busy,
    style: { width: "100%", justifyContent: "center", padding: "11px 14px" },
  }, st.busy ? busyLabel : label);

  const errorBox = () => (st.error ? h("p", { class: "error", role: "alert" }, st.error) : null);

  function signinForm() {
    return h("form", { onSubmit: signIn },
      text("login", "User id or email", { autocomplete: "username", required: true, maxlength: "254", autofocus: true }),
      passwordField(st, "password", "Password"),
      h("div", { class: "row between", style: { margin: "-4px 0 14px" } },
        h("span"),
        h("button", { type: "button", class: "link-btn inline", onClick: () => go("forgot") }, "Forgot password?")),
      submit("Sign in", "Signing in…"),
      errorBox());
  }

  function signupForm() {
    return h("form", { onSubmit: signUp },
      h("span", { class: "muted", style: { fontSize: 13 } }, "I am a"),
      h("div", { class: "role-pick", role: "radiogroup", "aria-label": "Role" },
        [["learner", "user", "Student"], ["teacher", "users", "Teacher"]].map(([r, name, label]) => h(
          "label", { class: st.role === r ? "on" : "" },
          h("input", { type: "radio", name: "role", checked: st.role === r, onChange: () => { st.role = r; if (r === "teacher") suggestCode(); paint(); } }),
          icon(name), " ", label))),
      text("name", "Full name", { autocomplete: "name", required: true, maxlength: "80" }),
      h("label", { class: "field" },
        h("span", null, "User id"),
        h("input", {
          type: "text", value: st.username, "data-key": "username", autocomplete: "username", required: true,
          maxlength: "30", spellcheck: "false", autocapitalize: "none",
          onInput: (e) => { st.username = e.target.value; checkUsername(); },
        }),
        h("div", { class: "hint", "data-user-hint": "" })),
      h("label", { class: "field" },
        h("span", null, "Email"),
        h("input", {
          type: "email", value: st.email, "data-key": "email", autocomplete: "email", required: true, maxlength: "254",
          onInput: (e) => { st.email = e.target.value; },
        }),
        h("div", { class: "hint" }, st.options.email ? "We will send you a link to confirm it." : "Used to sign in and to reset your password.")),
      h("div", { class: "field-row" },
        passwordField(st, "password", "Password", {
          autocomplete: "new-password", meter: true, onInput: (e) => updateMeter(root, "password", e.target.value),
        }),
        passwordField(st, "password2", "Confirm password", { autocomplete: "new-password" })),
      h("label", { class: "field" },
        h("span", null, "Gender"),
        h("select", { onChange: (e) => { st.gender = e.target.value; } },
          GENDERS.map(([v, l]) => h("option", { value: v, selected: st.gender === v }, l)))),
      st.role === "teacher" ? classCodeField() : null,
      h("label", { class: "check-line" },
        h("input", { type: "checkbox", checked: st.accept, onChange: (e) => { st.accept = e.target.checked; } }),
        h("span", null,
          "I understand that Mentora stores my name, user id, email, gender and photo to run my account, ",
          "keeps my learning activity under a pseudonym, and that I can delete my account and data at any time. ",
          "This is a demo service: please do not enter sensitive information.")),
      submit("Create account", "Creating your account…"),
      errorBox());
  }

  function forgotForm() {
    if (st.done) {
      return h("div", { class: "auth-status" }, icon("check"), h("p", null, st.done),
        h("button", { type: "button", class: "btn", onClick: () => go("signin") }, "Back to sign in"));
    }
    return h("form", { onSubmit: forgot },
      h("p", { class: "muted", style: { marginTop: 0 } }, "Enter your account's email and we will send you a link to choose a new password."),
      h("label", { class: "field" }, h("span", null, "Email"),
        h("input", {
          type: "email", value: st.email, "data-key": "email", autocomplete: "email", required: true, autofocus: true,
          onInput: (e) => { st.email = e.target.value; },
        })),
      submit("Send reset link", "Sending…"),
      errorBox(),
      h("div", { class: "auth-foot" }, h("button", { type: "button", class: "link-btn inline", onClick: () => go("signin") }, "Back to sign in")));
  }

  function resetForm() {
    return h("form", { onSubmit: reset },
      h("p", { class: "muted", style: { marginTop: 0 } }, "Choose a new password. Other devices will be signed out."),
      passwordField(st, "password", "New password", {
        autocomplete: "new-password", meter: true, onInput: (e) => updateMeter(root, "password", e.target.value),
      }),
      passwordField(st, "password2", "Confirm new password", { autocomplete: "new-password" }),
      submit("Save new password", "Saving…"),
      errorBox());
  }

  function verifyView() {
    if (st.done) {
      return h("div", { class: "auth-status" }, icon("check"),
        h("p", null, st.done),
        h("button", { type: "button", class: "btn primary", onClick: () => { window.location.hash = "#/"; onSignedIn(); } }, "Continue"));
    }
    return h("div", { class: "auth-status" },
      st.error ? [icon("alert"), h("p", { class: "error" }, st.error),
        h("button", { type: "button", class: "btn", onClick: () => { window.location.hash = "#/"; onSignedIn(); } }, "Go to Mentora")]
        : h("p", { class: "muted" }, "Confirming your email…"));
  }

  function devForm() {
    if (!st.options.dev_login) return null;
    return h("details", { class: "mt" },
      h("summary", { class: "muted small" }, "Quick demo sign-in (no account)"),
      h("form", { class: "mt", onSubmit: devSignIn },
        h("div", { class: "field-row" },
          h("input", { type: "text", placeholder: "Your name", value: st.devName, "data-key": "devName", onInput: (e) => { st.devName = e.target.value; } }),
          h("select", { onChange: (e) => { st.devRole = e.target.value; paint(); } },
            [["learner", "Student"], ["teacher", "Teacher"]].map(([v, l]) => h("option", { value: v, selected: st.devRole === v }, l)))),
        st.devRole === "teacher"
          ? h("input", { type: "password", class: "mt", placeholder: "Teacher access code", value: st.devCode, "data-key": "devCode", onInput: (e) => { st.devCode = e.target.value; } })
          : null,
        h("button", { class: "btn mt", type: "submit", disabled: st.busy }, "Continue without an account")));
  }

  const TITLES = {
    signin: ["Welcome back", "Sign in to continue learning."],
    signup: ["Create your account", "One account for the tutor, practice and your progress."],
    forgot: ["Forgot your password?", ""],
    reset: ["Choose a new password", ""],
    verify: ["Confirm your email", ""],
  };

  function paint() {
    const [title, sub] = TITLES[st.mode];
    const body = { signin: signinForm, signup: signupForm, forgot: forgotForm, reset: resetForm, verify: verifyView }[st.mode]();
    render(root, h(
      "div", { class: "login-wrap" },
      h("section", { class: "login-art" },
        h("div", { class: "hero-brand" }, h("span", { class: "hero-logo" }, logo()),
          h("div", null, h("b", null, "Mentora"), h("small", null, "Self-learning strategy tutor"))),
        h("div", { class: "hero-main" },
          h("span", { class: "hero-pill" }, icon("sparkle"), "For students and teachers"),
          h("h2", null, "Learn how you learn: ", h("span", { class: "hero-accent" }, "plan, practise, reflect.")),
          h("p", { class: "hero-lead" }, "Mentora helps you set goals, work through course material with an AI tutor, and look back on what worked."),
          h("ul", { class: "hero-features" }, FEATURES.map(([name, head, text]) => h("li", null,
            h("span", { class: "hero-ico" }, icon(name)),
            h("div", null, h("b", null, head), h("span", null, text)))))),
        h("p", { class: "foot" }, "Students join their teacher with a 10-digit class code.")),
      h("section", { class: "login-form" },
        h("div", { class: "card auth-card" },
          st.mode === "signin" || st.mode === "signup"
            ? h("div", { class: "auth-switch", role: "tablist" },
                [["signin", "Sign in"], ["signup", "Create account"]].map(([m, l]) => h(
                  "button", { type: "button", role: "tab", "aria-selected": String(st.mode === m), class: st.mode === m ? "active" : "", onClick: () => go(m) }, l)))
            : null,
          h("h2", null, title),
          sub ? h("p", { class: "muted", style: { marginTop: 0 } }, sub) : null,
          body,
          st.mode === "signin" ? devForm() : null)),
    ));
    if (st.mode === "signup") setHint();
  }

  api.get("/api/auth/options").then((o) => { st.options = o; paint(); }).catch(() => undefined);
  paint();
  if (st.mode === "verify") {
    api.post("/api/auth/verify", { token: hashParam("token") ?? "" })
      .then((r) => { st.done = `Thank you! The email for ${r.username} is confirmed.`; })
      .catch((e) => { st.error = errorText(e); })
      .finally(paint);
  }
}
