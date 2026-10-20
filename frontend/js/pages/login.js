// Sign in, create an account, forgotten password, reset (from the email link), verify email.
import { api, ApiError, errorText } from "../api.js";
import { h, hashParam, icon, logo, render, s } from "../dom.js";
import { saveTheme, storedTheme } from "../theme.js";
import { GENDERS } from "../people.js";
import { openModal, toast } from "../ui.js";

const FEATURES = [
  ["target", "Practice that adapts", "Rounds of 10 questions that come back to the topics you miss."],
  ["layers", "A plan for every goal", "Week-by-week roadmaps from the basics to a final project."],
  ["bot", "Help when you are stuck", "Ask the AI tutor, or your teacher, about anything you study."],
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
    onKeyup: (e) => caps(e),
    onKeydown: (e) => caps(e),
    onBlur: () => { warn.hidden = true; },
  });
  const warn = h("span", { class: "caps-warn", hidden: true, role: "status" }, icon("alert"), " Caps Lock is on");
  const caps = (e) => { warn.hidden = !(e.getModifierState && e.getModifierState("CapsLock")); };
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
    warn,
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
    gender: "prefer_not_to_say", accept: false, remember: true, status: null, userCheck: null, devName: "", devRole: "learner", devCode: "",
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
      await api.post("/api/auth/login", { login: st.login.trim(), password: st.password, remember: st.remember });
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
        h("button", { type: "button", class: "btn small", onClick: () => suggestCode(true) }, "Another code")),
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
  }, st.busy ? [h("span", { class: "spinner", "aria-hidden": "true" }), ` ${busyLabel}`] : label);

  const errorBox = () => (st.error ? h("div", { class: "auth-alert", role: "alert" }, icon("alert"), h("span", null, st.error)) : null);

  function signinForm() {
    return h("form", { onSubmit: signIn },
      text("login", "User id or email", { autocomplete: "username", required: true, maxlength: "254", autofocus: true }),
      passwordField(st, "password", "Password"),
      h("div", { class: "auth-row" },
        h("label", { class: "check-line keep" },
          h("input", { type: "checkbox", checked: st.remember, onChange: (e) => { st.remember = e.target.checked; } }),
          h("span", null, "Keep me signed in")),
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

  function preview() {
    return h("aside", { class: "auth-preview", "aria-hidden": "true" },
      h("div", { class: "pv-head" }, h("span", { class: "pv-date" }, "This week"), h("span", { class: "pv-dots" }, h("i"), h("i"), h("i"))),
      h("div", { class: "pv-figs" },
        h("div", null, h("small", null, "Accuracy"), h("b", null, "77%"), h("em", null, "+20 pts")),
        h("div", null, h("small", null, "Questions"), h("b", null, "90"), h("em", null, "+10")),
        h("div", null, h("small", null, "Streak"), h("b", null, "5"), h("em", { class: "flat" }, "days"))),
      s("svg", { class: "pv-graph", viewBox: "0 0 300 90", preserveAspectRatio: "none" },
        [22, 45, 68].map((y) => s("line", { x1: 0, x2: 300, y1: y, y2: y, class: "pv-grid" })),
        s("path", { class: "pv-area", d: "M0,70 L38,62 L75,66 L112,48 L150,52 L188,36 L225,30 L262,22 L300,18 L300,90 L0,90 Z" }),
        s("path", { class: "pv-line", d: "M0,70 L38,62 L75,66 L112,48 L150,52 L188,36 L225,30 L262,22 L300,18" })),
      h("ol", { class: "pv-next" },
        h("li", null, h("b", null, "Finish your Python round"), h("span", null, "4 of 10 answered")),
        h("li", null, h("b", null, "Week 3 of your Java plan"), h("span", null, "Arrays and strings")),
        h("li", null, h("b", null, "Practise Exceptions"), h("span", null, "40% right so far"))),
      h("p", { class: "pv-caption" }, "Your home page after you sign in: real numbers from your practice."));
  }

  function statusDot() {
    const up = st.status;
    const [tone, text] = up === null ? ["", "Checking service…"] : up ? ["ok", "All systems operational"] : ["warn", "Some services are slow right now"];
    return h("span", { class: `auth-status-dot ${tone}` }, h("i"), text);
  }

  function themeSwitch() {
    const cur = storedTheme();
    return h("span", { class: "auth-theme", role: "radiogroup", "aria-label": "Theme" },
      [["system", "Auto"], ["light", "Light"], ["dark", "Dark"]].map(([v, l]) => h("button", {
        type: "button", role: "radio", "aria-checked": String(cur === v), class: cur === v ? "on" : "",
        onClick: () => { saveTheme(v); paint(); },
      }, l)));
  }

  const info = (title, paras) => openModal(title, () => h("div", { class: "legal" }, paras.map((x) => h("p", null, x))));
  const privacy = () => info("Privacy", [
    "Mentora stores your name, user id, email, gender and photo to run your account. Your learning activity is kept under a pseudonym, not your name.",
    "Your teachers see your results only after you join their class. The AI tutor never sees your email or password.",
    "You can download your data and delete your account and all your learning data at any time from Profile and Settings.",
    "This is a demo service for learning: please do not enter sensitive information.",
  ]);
  const terms = () => info("Terms of use", [
    "Mentora is a learning tool offered as is, for study and teaching. Use it honestly: do not try to break it, misuse other people's accounts or upload harmful material.",
    "Practice questions and AI tutor answers can contain mistakes. Check important facts with your teacher or course material.",
    "Teachers are responsible for the material and quizzes they publish in their folders.",
  ]);
  const help = () => info("Help", [
    "Forgot your password? Use Forgot password on the Sign in tab; we email you a reset link.",
    "Did not get our email? Check your spam folder, then use Resend on your profile after signing in.",
    `Anything else: write to ${st.options.support_email || "the Mentora team"}. Signed-in users can also use Help & support in the menu.`,
  ]);

  function paint() {
    const [title, sub] = TITLES[st.mode];
    const body = { signin: signinForm, signup: signupForm, forgot: forgotForm, reset: resetForm, verify: verifyView }[st.mode]();
    render(root, h("div", { class: "auth-page" },
      h("header", { class: "auth-brand" },
        h("span", { class: "auth-logo" }, logo()),
        h("span", { class: "auth-name" }, "Mentora")),
      h("p", { class: "auth-tagline" }, "Practise, plan and track your learning, with your teachers."),
      h("div", { class: "auth-body" },
        h("main", { class: "card auth-card" },
          st.mode === "signin" || st.mode === "signup"
            ? h("div", { class: "auth-switch", role: "tablist" },
                [["signin", "Sign in"], ["signup", "Create account"]].map(([m, l]) => h(
                  "button", { type: "button", role: "tab", "aria-selected": String(st.mode === m), class: st.mode === m ? "active" : "", onClick: () => go(m) }, l)))
            : null,
          h("h1", { class: "auth-title" }, title),
          sub ? h("p", { class: "muted", style: { marginTop: 0 } }, sub) : null,
          body,
          st.mode === "signin" ? devForm() : null),
        preview()),
      h("ul", { class: "auth-points" }, FEATURES.map(([, head, text]) => h("li", null, h("b", null, head), h("span", null, text)))),
      h("footer", { class: "auth-footer" },
        h("div", { class: "auth-footer-left" },
          h("span", null, `© ${new Date().getFullYear()} Mentora`),
          statusDot()),
        h("nav", { class: "auth-links", "aria-label": "About Mentora" },
          h("button", { type: "button", class: "link-btn inline", onClick: privacy }, "Privacy"),
          h("button", { type: "button", class: "link-btn inline", onClick: terms }, "Terms"),
          h("button", { type: "button", class: "link-btn inline", onClick: help }, "Help"),
          themeSwitch()))));
    if (st.mode === "signup") setHint();
  }

  api.get("/api/auth/options").then((o) => { st.options = o; paint(); }).catch(() => undefined);
  fetch("/health").then((r) => r.json()).then((h0) => { st.status = h0.status === "ok" && h0.database === "ok"; paint(); })
    .catch(() => { st.status = false; paint(); });
  paint();
  if (st.mode === "verify") {
    api.post("/api/auth/verify", { token: hashParam("token") ?? "" })
      .then((r) => { st.done = `Thank you! The email for ${r.username} is confirmed.`; })
      .catch((e) => { st.error = errorText(e); })
      .finally(paint);
  }
}
