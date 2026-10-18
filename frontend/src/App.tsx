import { ReactNode, useCallback, useEffect, useState } from "react";
import { api, Dashboard, Escalation, Me, timeAgo } from "./api";
import CommandPalette, { PaletteEntry } from "./components/CommandPalette";
import { Popover, ToastProvider } from "./components/ui";
import Icon, { IconName, Logo } from "./icons";
import Login from "./pages/Login";
import { SessionProvider, useLoad, useSession } from "./session";
import Home from "./pages/student/Home";
import Tutor from "./pages/student/Tutor";
import MyLearning from "./pages/student/MyLearning";
import Practice from "./pages/student/Practice";
import Resources from "./pages/student/Resources";
import Progress from "./pages/student/Progress";
import Settings from "./pages/Settings";
import Overview from "./pages/teacher/Overview";
import Escalations from "./pages/teacher/Escalations";
import Students from "./pages/teacher/Students";
import Analytics from "./pages/teacher/Analytics";
import Content from "./pages/teacher/Content";
import Training from "./pages/teacher/Training";
import Reports from "./pages/teacher/Reports";

function useHashRoute(): string {
  const read = () => window.location.hash.replace(/^#/, "").split("?")[0] || "/";
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const onChange = () => setRoute(read());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export function applyTheme(theme: string | null) {
  if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
}

export function storedTheme(): string {
  try { return localStorage.getItem("mentora-theme") ?? "system"; } catch { return "system"; }
}

export function saveTheme(theme: string) {
  try { localStorage.setItem("mentora-theme", theme); } catch { /* storage unavailable */ }
  applyTheme(theme);
  window.dispatchEvent(new Event("mentora-theme"));
}

interface Page { path: string; label: string; icon: IconName; title: string; sub: string; render: () => ReactNode }

const STUDENT: Page[] = [
  { path: "/", label: "Home", icon: "home", title: "", sub: "", render: () => <Home /> },
  { path: "/tutor", label: "AI Tutor", icon: "bot", title: "AI Tutor", sub: "Plan · Learn · Reflect · Improve", render: () => <Tutor /> },
  { path: "/learning", label: "My Learning", icon: "book", title: "My Learning", sub: "Your goals, plans, tutor suggestions and what Mentora remembers", render: () => <MyLearning /> },
  { path: "/practice", label: "Practice", icon: "practice", title: "Practice Questions", sub: "Test your understanding and get feedback", render: () => <Practice /> },
  { path: "/resources", label: "Resources", icon: "folder", title: "Resources", sub: "Course material, by week", render: () => <Resources /> },
  { path: "/progress", label: "Progress", icon: "trend", title: "Progress", sub: "Mastery by concept and how well your confidence matches your results", render: () => <Progress /> },
  { path: "/settings", label: "Settings", icon: "settings", title: "Settings", sub: "Appearance, privacy and your data", render: () => <Settings role="learner" /> },
];

const TEACHER: Page[] = [
  { path: "/teacher", label: "Teacher Console", icon: "layers", title: "Teacher Console", sub: "Monitor student progress and manage the AI tutor", render: () => <Overview /> },
  { path: "/teacher/escalations", label: "Escalations", icon: "alert", title: "Escalations", sub: "Messages the tutor passed to you", render: () => <Escalations /> },
  { path: "/teacher/students", label: "Students", icon: "users", title: "Students", sub: "Progress and risk, per student (pseudonymous)", render: () => <Students /> },
  { path: "/teacher/analytics", label: "Learning Analytics", icon: "bars", title: "Learning Analytics", sub: "Every tutor decision and why it was made", render: () => <Analytics /> },
  { path: "/teacher/content", label: "Content Management", icon: "folder", title: "Content Management", sub: "Course material, quiz items and course-memory review", render: () => <Content /> },
  { path: "/teacher/training", label: "Model Training", icon: "cpu", title: "Model Training", sub: "Learner models and tutor policies (nothing changes without your approval)", render: () => <Training /> },
  { path: "/teacher/reports", label: "Reports", icon: "file", title: "Reports", sub: "Exports and policy evaluation reports", render: () => <Reports /> },
  { path: "/teacher/settings", label: "Settings", icon: "settings", title: "Settings", sub: "Tutor rules and system information", render: () => <Settings role="teacher" /> },
];

function greeting(name: string): string {
  const h = new Date().getHours();
  return `${h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening"}, ${name}`;
}

function Notifications({ role, open, close }: { role: Me["role"]; open: Escalation[]; close: () => void }) {
  const [dash] = useLoad<Dashboard>(role === "learner" ? "/api/me/dashboard" : null);
  const go = (hash: string) => { window.location.hash = hash; close(); };
  if (role === "teacher") {
    return (
      <>
        <div className="popover-head">Waiting for you</div>
        {open.length === 0 && <p className="empty" style={{ padding: "0 14px" }}>Nothing waiting for you.</p>}
        {open.slice(0, 5).map((e) => (
          <button key={e.id} className="popover-item" onClick={() => go("#/teacher/escalations")}>
            <span className={`badge ${e.reason === "distress" ? "danger" : "warn"}`}>{e.reason.replace(/_/g, " ")}</span>
            <span className="ellipsis">{e.message ?? "No message"}</span>
            <span className="muted small">{timeAgo(e.created_at)}</span>
          </button>
        ))}
        <button className="popover-foot" onClick={() => go("#/teacher/escalations")}>Open escalations →</button>
      </>
    );
  }
  const replies = dash?.teacher_replies ?? [];
  return (
    <>
      <div className="popover-head">Messages from your teacher</div>
      {!dash && <p className="muted" style={{ padding: "0 14px" }}>Loading…</p>}
      {dash && replies.length === 0 && <p className="empty" style={{ padding: "0 14px" }}>No messages yet.</p>}
      {replies.slice(0, 5).map((r) => (
        <button key={r.id} className="popover-item" onClick={() => go("#/learning")}>
          <Icon name="chat" />
          <span className="ellipsis">{r.response}</span>
          {r.at && <span className="muted small">{timeAgo(r.at)}</span>}
        </button>
      ))}
      <button className="popover-foot" onClick={() => go("#/learning")}>See all in My Learning →</button>
    </>
  );
}

function AccountMenu({ me, close, onSignOut, openPalette }: {
  me: Me; close: () => void; onSignOut: () => void; openPalette: () => void;
}) {
  const [theme, setTheme] = useState(storedTheme);
  const pick = (t: string) => { setTheme(t); saveTheme(t); };
  return (
    <>
      <div className="popover-head">
        <div><b>{me.name}</b></div>
        <div className="muted small">{me.role === "teacher" ? "Teacher" : "Student"} · {me.via === "lti" ? "signed in from Moodle" : "development sign-in"}</div>
      </div>
      <div className="seg" role="radiogroup" aria-label="Theme">
        {([["system", "sliders", "Auto"], ["light", "sun", "Light"], ["dark", "moon", "Dark"]] as const).map(([t, icon, label]) => (
          <button key={t} role="radio" aria-checked={theme === t} className={theme === t ? "active" : ""} onClick={() => pick(t)}>
            <Icon name={icon} /> {label}
          </button>
        ))}
      </div>
      <button className="popover-item" onClick={() => { close(); openPalette(); }}>
        <Icon name="search" /> <span>Search and jump</span> <kbd>Ctrl K</kbd>
      </button>
      <button className="popover-item" onClick={() => { close(); window.location.hash = me.role === "teacher" ? "#/teacher/settings" : "#/settings"; }}>
        <Icon name="settings" /> <span>Settings</span>
      </button>
      <button className="popover-item danger" onClick={() => { close(); onSignOut(); }}>
        <Icon name="logout" /> <span>Sign out</span>
      </button>
    </>
  );
}

const NOTICE_KEY = "mentora-demo-notice-dismissed";

/** Says that replies are templates (never hidden by default); closable per browser. */
function DemoNotice({ role }: { role: Me["role"] }) {
  const [hidden, setHidden] = useState(() => {
    try { return localStorage.getItem(NOTICE_KEY) === "1"; } catch { return false; }
  });
  if (hidden) return null;
  const close = () => {
    setHidden(true);
    try { localStorage.setItem(NOTICE_KEY, "1"); } catch { /* storage unavailable */ }
  };
  return (
    <div className="notice" role="note">
      <span className="notice-tag">Demo mode</span>
      <span className="notice-text">
        {role === "teacher"
          ? <>Tutor replies are fixed templates. For AI replies, add <code>ANTHROPIC_API_KEY=…</code> to <code>.env</code> and restart the server.</>
          : "Tutor replies are fixed templates for now, not an AI model. Everything else works as normal."}
      </span>
      <button className="notice-close" onClick={close} aria-label="Hide this notice"><Icon name="x" /></button>
    </div>
  );
}

function Shell({ me, onSignOut, ask }: { me: Me; onSignOut: () => void; ask?: (q: string) => void }) {
  const route = useHashRoute();
  const pages = me.role === "teacher" ? TEACHER : STUDENT;
  const page = pages.find((p) => p.path === route) ?? pages[0];
  const [menuOpen, setMenuOpen] = useState(false);
  const [palette, setPalette] = useState(false);
  const [escalations] = useLoad<Escalation[]>(me.role === "teacher" ? `/api/teacher/escalations?status=open&r=${route}` : null);
  const openEsc = (escalations ?? []).filter((e) => e.status === "open");
  const [home] = useLoad<{ teacher_replies: number }>(me.role === "learner" ? "/api/me/home" : null);
  const bell = me.role === "teacher" ? openEsc.length : home?.teacher_replies ?? 0;

  useEffect(() => { setMenuOpen(false); window.scrollTo({ top: 0 }); }, [route]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((p) => !p); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const entries: PaletteEntry[] = pages.map((p) => ({
    label: p.label, icon: p.icon, hint: p.sub || undefined, run: () => { window.location.hash = `#${p.path}`; },
  }));

  return (
    <div className={`shell ${menuOpen ? "menu-open" : ""}`}>
      <aside className="sidebar" aria-label="Main navigation">
        <div className="brand">
          <Logo /><div><b>Mentora</b><small>Self-learning strategy tutor</small></div>
          <button className="icon-btn mobile-only" style={{ marginLeft: "auto" }} onClick={() => setMenuOpen(false)} aria-label="Close menu">
            <Icon name="x" />
          </button>
        </div>
        <button className="search-btn" onClick={() => setPalette(true)}>
          <Icon name="search" /> <span>Search</span> <kbd>Ctrl K</kbd>
        </button>
        <nav className="nav">
          {pages.map((p) => (
            <a key={p.path} href={`#${p.path}`} className={`nav-item ${p === page ? "active" : ""}`}
               aria-current={p === page ? "page" : undefined}>
              <Icon name={p.icon} />
              {p.label}
              {p.path === "/teacher/escalations" && openEsc.length > 0 && <span className="count">{openEsc.length}</span>}
            </a>
          ))}
        </nav>
        <div className="grow" />
        {me.role === "learner" && (
          <a className="sidebar-cta" href="#/tutor">
            <Icon name="sparkle" />
            <div><b>Study with the tutor</b><small>Plan a session, then practise and reflect</small></div>
          </a>
        )}
        <button className="nav-item plain" onClick={onSignOut}><Icon name="logout" /> Sign out</button>
      </aside>
      {menuOpen && <div className="scrim" onClick={() => setMenuOpen(false)} aria-hidden />}

      <div className="main">
        <header className="topbar">
          <button className="icon-btn mobile-only" onClick={() => setMenuOpen(true)} aria-label="Open menu" aria-expanded={menuOpen}>
            <Icon name="menu" />
          </button>
          <div className="topbar-title">
            <h1>{page.title || greeting(me.name)}</h1>
            <div className="sub">{page.sub || "Here's your learning progress and recommendations."}</div>
          </div>
          <div className="spacer" />
          <Popover label={me.role === "teacher" ? "Escalations waiting" : "Messages from your teacher"} badge={bell} button={<Icon name="bell" />}>
            {(close) => <Notifications role={me.role} open={openEsc} close={close} />}
          </Popover>
          <Popover label="Account menu" button={
            <span className="avatar"><span className="circle">{me.name.slice(0, 1).toUpperCase()}</span>
              <span className="avatar-name">{me.role === "teacher" ? "Teacher" : "Student"}</span></span>
          }>
            {(close) => <AccountMenu me={me} close={close} onSignOut={onSignOut} openPalette={() => setPalette(true)} />}
          </Popover>
        </header>
        <main className="content" key={page.path}>
          {(me.llm_backend === "offline" || me.llm_backend === "fake") && <DemoNotice role={me.role} />}
          <div className="page-enter">{page.render()}</div>
        </main>
      </div>
      {palette && <CommandPalette pages={entries} onClose={() => setPalette(false)} ask={ask} />}
    </div>
  );
}

function LearnerShell({ me, onSignOut }: { me: Me; onSignOut: () => void }) {
  const s = useSession();
  const ask = (q: string) => { window.location.hash = "#/tutor"; void s.send(q); };
  return <Shell me={me} onSignOut={onSignOut} ask={ask} />;
}

export default function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const refresh = useCallback(() => {
    api.get<Me>("/api/me").then(setMe).catch(() => setMe(null));
  }, []);
  useEffect(() => {
    applyTheme(storedTheme());
    refresh();
  }, [refresh]);

  if (me === undefined) return <div className="boot"><Logo /></div>;
  if (me === null) return <ToastProvider><Login onSignedIn={refresh} /></ToastProvider>;
  const signOut = () => { api.post("/api/logout").then(() => { window.location.hash = ""; refresh(); }); };
  return (
    <ToastProvider>
      {me.role === "learner"
        ? <SessionProvider><LearnerShell me={me} onSignOut={signOut} /></SessionProvider>
        : <Shell me={me} onSignOut={signOut} />}
    </ToastProvider>
  );
}
