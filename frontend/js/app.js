// Mentora web app: sign-in, the shell (sidebar, topbar, notifications, account menu) and
// hash routing between pages. Plain ES modules; no build step.
import { api, timeAgo } from "./api.js";
import { h, icon, logo, render } from "./dom.js";
import { openPalette } from "./palette.js";
import { loadSession, resetSession, send } from "./session.js";
import { applyTheme, saveTheme, storedTheme } from "./theme.js";
import { popover } from "./ui.js";
import login from "./pages/login.js";
import home from "./pages/home.js";
import tutor from "./pages/tutor.js";
import learning from "./pages/learning.js";
import practice from "./pages/practice.js";
import resources from "./pages/resources.js";
import progress from "./pages/progress.js";
import settings from "./pages/settings.js";
import overview from "./pages/overview.js";
import escalations from "./pages/escalations.js";
import students from "./pages/students.js";
import analytics from "./pages/analytics.js";
import content from "./pages/content.js";
import training from "./pages/training.js";
import reports from "./pages/reports.js";

const STUDENT = [
  { path: "/", label: "Home", icon: "home", title: "", sub: "", page: home },
  { path: "/tutor", label: "AI Tutor", icon: "bot", title: "AI Tutor", sub: "Plan · Learn · Reflect · Improve", page: tutor },
  { path: "/learning", label: "My Learning", icon: "book", title: "My Learning", sub: "Your goals, plans, tutor suggestions and what Mentora remembers", page: learning },
  { path: "/practice", label: "Practice", icon: "practice", title: "Practice Questions", sub: "Test your understanding and get feedback", page: practice },
  { path: "/resources", label: "Resources", icon: "folder", title: "Resources", sub: "Course material, by week", page: resources },
  { path: "/progress", label: "Progress", icon: "trend", title: "Progress", sub: "Mastery by concept and how well your confidence matches your results", page: progress },
  { path: "/settings", label: "Settings", icon: "settings", title: "Settings", sub: "Appearance, privacy and your data", page: settings },
];

const TEACHER = [
  { path: "/teacher", label: "Teacher Console", icon: "layers", title: "Teacher Console", sub: "Monitor student progress and manage the AI tutor", page: overview },
  { path: "/teacher/escalations", label: "Escalations", icon: "alert", title: "Escalations", sub: "Messages the tutor passed to you", page: escalations },
  { path: "/teacher/students", label: "Students", icon: "users", title: "Students", sub: "Progress and risk, per student (pseudonymous)", page: students },
  { path: "/teacher/analytics", label: "Learning Analytics", icon: "bars", title: "Learning Analytics", sub: "Every tutor decision and why it was made", page: analytics },
  { path: "/teacher/content", label: "Content Management", icon: "folder", title: "Content Management", sub: "Course material, quiz items and course-memory review", page: content },
  { path: "/teacher/training", label: "Model Training", icon: "cpu", title: "Model Training", sub: "Learner models and tutor policies (nothing changes without your approval)", page: training },
  { path: "/teacher/reports", label: "Reports", icon: "file", title: "Reports", sub: "Exports and policy evaluation reports", page: reports },
  { path: "/teacher/settings", label: "Settings", icon: "settings", title: "Settings", sub: "Tutor rules and system information", page: settings },
];

const NOTICE_KEY = "mentora-demo-notice-dismissed";
const app = document.getElementById("root");
const route = () => window.location.hash.replace(/^#/, "").split("?")[0] || "/";

function greeting(name) {
  const hour = new Date().getHours();
  return `${hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening"}, ${name}`;
}

/** Says that replies are templates (never hidden by default); closable per browser. */
function demoNotice(role) {
  try {
    if (localStorage.getItem(NOTICE_KEY) === "1") return null;
  } catch {
    /* storage unavailable */
  }
  const el = h("div", { class: "notice", role: "note" },
    h("span", { class: "notice-tag" }, "Demo mode"),
    h("span", { class: "notice-text" }, role === "teacher"
      ? ["Tutor replies are fixed templates. For AI replies, add ", h("code", null, "ANTHROPIC_API_KEY=…"),
          " to ", h("code", null, ".env"), " and restart the server."]
      : "Tutor replies are fixed templates for now, not an AI model. Everything else works as normal."),
    h("button", {
      class: "notice-close", "aria-label": "Hide this notice",
      onClick: () => {
        el.remove();
        try {
          localStorage.setItem(NOTICE_KEY, "1");
        } catch {
          /* storage unavailable */
        }
      },
    }, icon("x")));
  return el;
}

function notifications(me, openEsc, close) {
  const go = (hash) => {
    window.location.hash = hash;
    close();
  };
  if (me.role === "teacher") {
    return h("div", null,
      h("div", { class: "popover-head" }, "Waiting for you"),
      openEsc.length === 0 ? h("p", { class: "empty", style: { padding: "0 14px" } }, "Nothing waiting for you.") : null,
      openEsc.slice(0, 5).map((e) => h(
        "button", { class: "popover-item", onClick: () => go("#/teacher/escalations") },
        h("span", { class: `badge ${e.reason === "distress" ? "danger" : "warn"}` }, e.reason.replace(/_/g, " ")),
        h("span", { class: "ellipsis" }, e.message ?? "No message"),
        h("span", { class: "muted small" }, timeAgo(e.created_at)))),
      h("button", { class: "popover-foot", onClick: () => go("#/teacher/escalations") }, "Open escalations →"));
  }
  const box = h("div", null,
    h("div", { class: "popover-head" }, "Messages from your teacher"),
    h("p", { class: "muted", style: { padding: "0 14px" } }, "Loading…"));
  api.get("/api/me/dashboard").then((dash) => {
    const replies = dash.teacher_replies ?? [];
    render(box,
      h("div", { class: "popover-head" }, "Messages from your teacher"),
      replies.length === 0 ? h("p", { class: "empty", style: { padding: "0 14px" } }, "No messages yet.") : null,
      replies.slice(0, 5).map((r) => h(
        "button", { class: "popover-item", onClick: () => go("#/learning") },
        icon("chat"), h("span", { class: "ellipsis" }, r.response),
        r.at ? h("span", { class: "muted small" }, timeAgo(r.at)) : null)),
      h("button", { class: "popover-foot", onClick: () => go("#/learning") }, "See all in My Learning →"));
  }).catch(() => undefined);
  return box;
}

function accountMenu(me, close, signOut, palette) {
  const seg = h("div", { class: "seg", role: "radiogroup", "aria-label": "Theme" });
  const paintSeg = () => {
    const theme = storedTheme();
    render(seg, [["system", "sliders", "Auto"], ["light", "sun", "Light"], ["dark", "moon", "Dark"]].map(([t, name, label]) => h(
      "button", {
        role: "radio", "aria-checked": String(theme === t), class: theme === t ? "active" : "",
        onClick: () => { saveTheme(t); paintSeg(); },
      }, icon(name), ` ${label}`)));
  };
  paintSeg();
  return h("div", null,
    h("div", { class: "popover-head" },
      h("div", null, h("b", null, me.name)),
      h("div", { class: "muted small" },
        `${me.role === "teacher" ? "Teacher" : "Student"} · ${me.via === "lti" ? "signed in from Moodle" : "development sign-in"}`)),
    seg,
    h("button", { class: "popover-item", onClick: () => { close(); palette(); } },
      icon("search"), h("span", null, "Search and jump"), h("kbd", null, "Ctrl K")),
    h("button", {
      class: "popover-item",
      onClick: () => { close(); window.location.hash = me.role === "teacher" ? "#/teacher/settings" : "#/settings"; },
    }, icon("settings"), h("span", null, "Settings")),
    h("button", { class: "popover-item danger", onClick: () => { close(); signOut(); } },
      icon("logout"), h("span", null, "Sign out")));
}

function shell(me, signOut) {
  const pages = me.role === "teacher" ? TEACHER : STUDENT;
  const content = h("main", { class: "content" });
  const nav = h("nav", { class: "nav" });
  const title = h("div", { class: "topbar-title" });
  const bellSlot = h("div");
  const root = h("div", { class: "shell" });
  let cleanup = null;
  let openEsc = [];

  const ask = (q) => {
    window.location.hash = "#/tutor";
    send(q);
  };
  const palette = () => openPalette(pages.map((p) => ({
    label: p.label, icon: p.icon, hint: p.sub || undefined, run: () => { window.location.hash = `#${p.path}`; },
  })), me.role === "learner" ? ask : undefined);
  const setMenu = (open) => {
    root.classList.toggle("menu-open", open);
    scrim.hidden = !open;
  };
  const scrim = h("div", { class: "scrim", hidden: true, "aria-hidden": "true", onClick: () => setMenu(false) });

  function paintBell(count) {
    render(bellSlot, popover({
      label: me.role === "teacher" ? "Escalations waiting" : "Messages from your teacher",
      badge: count, button: icon("bell"), content: (close) => notifications(me, openEsc, close),
    }));
  }

  async function refreshCounts() {
    try {
      if (me.role === "teacher") {
        const rows = await api.get("/api/teacher/escalations?status=open");
        openEsc = rows.filter((e) => e.status === "open");
        paintBell(openEsc.length);
        paintNav();
      } else {
        const homeData = await api.get("/api/me/home");
        paintBell(homeData.teacher_replies ?? 0);
      }
    } catch {
      /* counts are optional */
    }
  }

  function paintNav() {
    const current = pages.find((p) => p.path === route()) ?? pages[0];
    render(nav, pages.map((p) => h(
      "a", { href: `#${p.path}`, class: `nav-item ${p === current ? "active" : ""}`, "aria-current": p === current ? "page" : null },
      icon(p.icon), p.label,
      p.path === "/teacher/escalations" && openEsc.length > 0 ? h("span", { class: "count" }, openEsc.length) : null)));
  }

  function show() {
    const page = pages.find((p) => p.path === route()) ?? pages[0];
    cleanup?.();
    cleanup = null;
    setMenu(false);
    window.scrollTo({ top: 0 });
    paintNav();
    render(title, h("h1", null, page.title || greeting(me.name)),
      h("div", { class: "sub" }, page.sub || "Here's your learning progress and recommendations."));
    const body = h("div", { class: "page-enter" });
    render(content, me.llm_backend === "offline" || me.llm_backend === "fake" ? demoNotice(me.role) : null, body);
    cleanup = page.page(body, { me, ask }) || null;
    refreshCounts();
  }

  render(root,
    h("aside", { class: "sidebar", "aria-label": "Main navigation" },
      h("div", { class: "brand" }, logo(),
        h("div", null, h("b", null, "Mentora"), h("small", null, "Self-learning strategy tutor")),
        h("button", { class: "icon-btn mobile-only", style: { marginLeft: "auto" }, "aria-label": "Close menu", onClick: () => setMenu(false) },
          icon("x"))),
      h("button", { class: "search-btn", onClick: palette }, icon("search"), h("span", null, "Search"), h("kbd", null, "Ctrl K")),
      nav,
      h("div", { class: "grow" }),
      me.role === "learner"
        ? h("a", { class: "sidebar-cta", href: "#/tutor" }, icon("sparkle"),
            h("div", null, h("b", null, "Study with the tutor"), h("small", null, "Plan a session, then practise and reflect")))
        : null,
      h("button", { class: "nav-item plain", onClick: signOut }, icon("logout"), " Sign out")),
    scrim,
    h("div", { class: "main" },
      h("header", { class: "topbar" },
        h("button", { class: "icon-btn mobile-only", "aria-label": "Open menu", onClick: () => setMenu(true) }, icon("menu")),
        title,
        h("div", { class: "spacer" }),
        bellSlot,
        popover({
          label: "Account menu",
          button: h("span", { class: "avatar" },
            h("span", { class: "circle" }, me.name.slice(0, 1).toUpperCase()),
            h("span", { class: "avatar-name" }, me.role === "teacher" ? "Teacher" : "Student")),
          content: (close) => accountMenu(me, close, signOut, palette),
        })),
      content));

  const onKey = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      palette();
    }
  };
  window.addEventListener("hashchange", show);
  window.addEventListener("keydown", onKey);
  render(app, root);
  paintBell(0);
  show();
  return () => {
    cleanup?.();
    window.removeEventListener("hashchange", show);
    window.removeEventListener("keydown", onKey);
  };
}

let stopShell = null;

async function boot() {
  stopShell?.();
  stopShell = null;
  let me = null;
  try {
    me = await api.get("/api/me");
  } catch {
    me = null;
  }
  if (!me) {
    resetSession();
    login(app, { onSignedIn: boot });
    return;
  }
  const signOut = () => api.post("/api/logout").then(() => {
    window.location.hash = "";
    boot();
  });
  if (me.role === "learner") loadSession();
  stopShell = shell(me, signOut);
}

applyTheme(storedTheme());
render(app, h("div", { class: "boot" }, logo()));
boot();
