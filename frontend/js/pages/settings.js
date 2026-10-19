import { api, errorText } from "../api.js";
import { h, icon, render } from "../dom.js";
import { saveTheme, storedTheme } from "../theme.js";
import { toast } from "../ui.js";

function appearance() {
  const section = h("section", { class: "card" });
  const paint = () => {
    const theme = storedTheme();
    render(section,
      h("h2", null, "Appearance"),
      h("div", { class: "tabs", role: "radiogroup", "aria-label": "Theme" }, ["system", "light", "dark"].map((t) => h(
        "button", {
          class: theme === t ? "active" : "", role: "radio", "aria-checked": String(theme === t),
          onClick: () => saveTheme(t),
        }, t[0].toUpperCase() + t.slice(1)))));
  };
  window.addEventListener("mentora-theme", paint);
  paint();
  return [section, () => window.removeEventListener("mentora-theme", paint)];
}

function rules() {
  const section = h("section", { class: "card" });
  const st = { rows: null, name: "", kind: "agent", value: "", weekLte: "", graded: "", error: null };

  async function reload() {
    st.rows = await api.get("/api/teacher/rules");
    paint();
  }

  async function add(e) {
    e.preventDefault();
    st.error = null;
    const when = {};
    if (st.weekLte) when.week_lte = Number(st.weekLte);
    if (st.graded) when.graded = st.graded === "yes";
    try {
      await api.post("/api/teacher/rules", { name: st.name, rule: { forbid: { [st.kind]: st.value.trim() }, when } });
      Object.assign(st, { name: "", value: "", weekLte: "", graded: "" });
      await reload();
      toast("Rule added. It applies from the next tutor turn.");
    } catch (err) {
      st.error = errorText(err);
      paint();
    }
  }

  async function remove(id) {
    await api.del(`/api/teacher/rules/${id}`);
    await reload();
    toast("Rule removed");
  }

  const field = (key, props) => h("input", {
    type: "text", value: st[key], "data-key": key, ...props, onInput: (e) => { st[key] = e.target.value; },
  });

  function paint() {
    render(section,
      h("h2", null, "Tutor rules"),
      h("p", { class: "muted", style: { marginTop: -6 } },
        "Rules you add here are applied by the safety filter on every turn, on top of the built-in rules."),
      st.rows && st.rows.length === 0 ? h("p", { class: "empty" }, "No rules yet.") : null,
      h("ul", { class: "list" }, (st.rows ?? []).map((r) => h(
        "li", { class: "list-row" },
        h("div", { class: "body" }, h("b", null, r.name), h("div", { class: "muted small" }, JSON.stringify(r.rule))),
        h("button", { class: "btn small danger", onClick: () => remove(r.id) }, "Remove")))),
      h("form", { class: "list mt", onSubmit: add },
        field("name", { placeholder: "Rule name, e.g. No peer suggestions in week 1", required: true }),
        h("div", { class: "row" },
          h("span", null, "Never use"),
          h("select", { style: { width: "auto" }, onChange: (e) => { st.kind = e.target.value; } },
            ["agent", "move", "style", "action"].map((k) => h("option", { value: k, selected: st.kind === k }, k))),
          field("value", { placeholder: "e.g. PeerBroker, worked_example or Directive", required: true, style: { flex: 1 } })),
        h("div", { class: "row" },
          h("span", null, "only when course week ≤"),
          field("weekLte", { inputmode: "numeric", style: { width: 70 }, placeholder: "any" }),
          h("span", null, "and the item is graded:"),
          h("select", { style: { width: "auto" }, onChange: (e) => { st.graded = e.target.value; } },
            [["", "either"], ["yes", "yes"], ["no", "no"]].map(([v, l]) => h("option", { value: v, selected: st.graded === v }, l)))),
        h("div", null, h("button", { class: "btn primary", type: "submit" }, "Add rule")),
        st.error ? h("p", { class: "error" }, st.error) : null));
  }

  paint();
  reload().catch((e) => { st.error = errorText(e); paint(); });
  return section;
}

function privacy() {
  const section = h("section", { class: "card" });
  let notes = null;

  async function reload() {
    try {
      notes = await api.get("/api/me/memory");
    } catch {
      notes = [];
    }
    paint();
  }

  async function forget(id) {
    await api.del(`/api/me/memory/${id}`);
    toast("Deleted. The tutor will no longer use that note.");
    reload();
  }

  async function forgetAll() {
    if (!window.confirm("Delete everything Mentora remembers about you?")) return;
    try {
      await api.del("/api/me/memory");
      toast("Done. Mentora no longer remembers anything about you.");
      reload();
    } catch (e) {
      toast(errorText(e), "error");
    }
  }

  function paint() {
    render(section,
      h("h2", null, "Privacy"),
      h("p", { class: "muted" },
        "Mentora stores your activity under a pseudonym, not your name or LMS id. Below are the short notes the AI tutor "
        + "remembers to help you in later sessions; delete any of them, or all at once. Old notes are deleted "
        + "automatically after the retention period."),
      h("h3", null, "What Mentora remembers about you"),
      notes === null ? h("p", { class: "muted" }, "Loading…")
        : notes.length === 0 ? h("p", { class: "empty" }, "Nothing yet.")
          : h("ul", { class: "list" }, notes.map((n) => h("li", { class: "list-row" },
              h("div", { class: "body" }, n.text),
              h("button", { class: "btn small danger", onClick: () => forget(n.id) }, icon("trash"), " Delete")))),
      h("div", { class: "row", style: { marginTop: 12 } },
        h("a", { class: "btn", href: "/api/me/export", download: true }, icon("download"), " Download my data"),
        h("button", { class: "btn danger", onClick: forgetAll }, icon("trash"), " Delete all my memory")),
      h("p", { class: "muted small" },
        "The download is a JSON file with your sessions, goals, remembered notes, messages to your teacher and activity log."));
  }

  paint();
  reload();
  return section;
}

const REPLIES = {
  offline: "Offline templates (no AI model)",
  local: "AI model running on this computer (live, streamed replies)",
  hosted: "Claude AI model (live, streamed replies)",
};

export default function settings(root, { me }) {
  const [look, stop] = appearance();
  const about = h("section", { class: "card" });
  render(root, h("div", { class: "stack" },
    look,
    me.role === "teacher" ? rules() : null,
    me.role === "learner" ? privacy() : null,
    about));
  api.get("/api/me").then((m) => render(about,
    h("h2", null, "About this installation"),
    h("table", { class: "data" }, h("tbody", null,
      h("tr", null, h("th", null, "Signed in as"),
        h("td", null, `${m.name} (${m.role}, via ${m.via === "lti" ? "Moodle" : "development sign-in"})`)),
      h("tr", null, h("th", null, "Tutor mode"),
        h("td", null, m.mode === "static" ? "Static (study control: fixed rules, no memory)" : "Adaptive")),
      h("tr", null, h("th", null, "Replies"), h("td", null, REPLIES[m.llm_backend] ?? m.llm_backend)))))).catch(() => about.remove());
  return stop;
}
