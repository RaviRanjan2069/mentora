// Help & support: a help-desk form for problems and complaints. Each request is emailed to the
// Mentora support inbox (reply-to the user) and confirmed to the user.
import { api, errorText } from "../api.js";
import { h, icon, render } from "../dom.js";
import { copyText, errorLine, toast } from "../ui.js";

const PLACES = ["Home", "Subjects", "AI Tutor", "My Learning", "Goals & Plans", "Progress", "My Teachers", "Quizzes", "Profile or account", "Teacher pages", "Somewhere else"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const LIMIT = 5000;

function when(iso) {
  const d = new Date(iso);
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}, ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export default function support(root) {
  const blank = { category: "", priority: "normal", page: "", subject: "", message: "" };
  const st = { data: null, ...blank, busy: false, error: null, sent: null };

  async function load() {
    try {
      st.data = await api.get("/api/support");
      paint();
    } catch (e) {
      render(root, errorLine(errorText(e)));
    }
  }

  async function remove(t) {
    const note = t.status === "open" ? " It is still open, so the Mentora team will no longer be able to mark it as resolved." : "";
    if (!window.confirm(`Delete ${t.number} “${t.subject}”?${note} This cannot be undone.`)) return;
    try {
      await api.del(`/api/support/${t.number}`);
      st.data = await api.get("/api/support");
      if (st.sent?.number === t.number) st.sent = null;
      toast(`${t.number} deleted.`);
      paint();
    } catch (e) {
      toast(errorText(e), "error");
    }
  }

  async function reopen(t) {
    if (!window.confirm(`Reopen ${t.number}? The Mentora team will be told it is not fixed yet.`)) return;
    try {
      await api.post(`/api/support/${t.number}/reopen`);
      st.data = await api.get("/api/support");
      toast(`${t.number} reopened. The team has been emailed.`);
      paint();
    } catch (e) {
      toast(errorText(e), "error");
    }
  }

  async function submit(e) {
    e.preventDefault();
    st.error = null;
    if (!st.category) {
      st.error = "Choose a topic.";
      paint();
      return;
    }
    st.busy = true;
    paint();
    try {
      const t = await api.post("/api/support", {
        category: st.category, priority: st.priority, page: st.page, subject: st.subject, message: st.message,
      });
      Object.assign(st, blank, { sent: t });
      st.data = await api.get("/api/support");
      toast(`Request ${t.number} sent.`);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      st.error = errorText(err);
    }
    st.busy = false;
    paint();
  }

  const select = (key, options, placeholder, label) => h("label", { class: "field" }, h("span", null, label),
    h("select", { required: key === "category", onChange: (e) => { st[key] = e.target.value; } },
      placeholder ? h("option", { value: "", selected: !st[key] }, placeholder) : null,
      options.map(([v, l]) => h("option", { value: v, selected: st[key] === v }, l))));

  function form() {
    const d = st.data;
    return h("form", { class: "card desk-form", onSubmit: submit },
      h("div", { class: "desk-form-head" }, h("h2", null, "New request"),
        h("span", { class: "muted small" }, "Fields marked * are required")),
      h("div", { class: "desk-grid" },
        select("category", Object.entries(d.categories), "Choose a topic", "Topic *"),
        select("priority", [["normal", "Normal"], ["high", "High – it stops me from studying"]], null, "Priority"),
        select("page", PLACES.map((p) => [p, p]), "Not sure / not needed", "Where in Mentora")),
      h("label", { class: "field" }, h("span", null, "Subject *"),
        h("input", {
          type: "text", value: st.subject, "data-key": "subject", required: true, minlength: "4", maxlength: "200",
          placeholder: "A short summary, e.g. Question 4 in the Java round has the wrong answer",
          onInput: (e) => { st.subject = e.target.value; },
        })),
      h("label", { class: "field" }, h("span", null, "Description *"),
        h("textarea", {
          rows: "7", value: st.message, "data-key": "message", required: true, minlength: "10", maxlength: String(LIMIT),
          placeholder: "What were you doing, what did you expect, and what happened instead? Include the question text or the steps if you can.",
          onInput: (e) => {
            st.message = e.target.value;
            const c = root.querySelector("[data-count]");
            if (c) c.textContent = `${st.message.length} / ${LIMIT}`;
          },
        }),
        h("span", { class: "desk-count muted small", "data-count": "" }, `${st.message.length} / ${LIMIT}`)),
      st.error ? h("p", { class: "error", role: "alert" }, st.error) : null,
      h("div", { class: "desk-form-foot" },
        h("span", { class: "muted small" }, "We reply to ", h("b", null, d.your_email), ". Please do not include passwords."),
        h("button", { class: "btn primary", type: "submit", disabled: st.busy }, st.busy ? "Sending…" : "Submit request")));
  }

  function requests() {
    const d = st.data;
    return h("section", { class: "card" },
      h("h2", null, "Your requests"),
      d.tickets.length === 0
        ? h("p", { class: "empty" }, "You have not sent any requests yet.")
        : h("div", { class: "overflow" }, h("table", { class: "data desk-table" },
            h("thead", null, h("tr", null, ["Reference", "Subject", "Topic", "Priority", "Submitted", "Status"].map((x) => h("th", null, x)))),
            h("tbody", null, d.tickets.map((t) => h("tr", null,
              h("td", { class: "mono" }, t.number),
              h("td", null, h("div", { class: "desk-subject" }, t.subject), h("div", { class: "muted small ellipsis" }, t.message),
                t.status === "resolved" && t.resolution
                  ? h("div", { class: "desk-resolution" }, h("b", null, `Resolved ${when(t.resolved_at)}: `), t.resolution)
                  : t.reopened ? h("div", { class: "muted small" }, "Reopened – the team has been told.") : null),
              h("td", null, t.category_label),
              h("td", null, t.priority === "high" ? h("span", { class: "badge danger" }, "High") : h("span", { class: "muted" }, "Normal")),
              h("td", { class: "muted nowrap" }, when(t.created_at)),
              h("td", { class: "desk-status" }, h("span", { class: `badge ${t.status === "open" ? "warn" : "ok"}` }, t.status === "open" ? "Open" : "Resolved"),
                t.status === "resolved"
                  ? h("button", { class: "text-btn small", title: "Not fixed? Tell the team", onClick: () => reopen(t) }, "Reopen")
                  : null,
                h("button", { class: "text-btn small desk-delete", title: "Remove this request from your list", onClick: () => remove(t) }, "Delete"))))))));
  }

  function paint() {
    const d = st.data;
    const open = d.tickets.filter((t) => t.status === "open").length;
    render(root, h("div", { class: "desk" },
      h("div", { class: "desk-facts" },
        h("div", null, h("span", null, "Email"), h("a", { href: `mailto:${d.email}` }, d.email)),
        h("div", null, h("span", null, "Typical reply"), h("b", null, "Within 2 working days")),
        h("div", null, h("span", null, "Your open requests"), h("b", null, String(open)))),
      st.sent
        ? h("div", { class: "desk-confirm", role: "status" },
            h("b", null, `Request ${st.sent.number} received.`),
            ` We have emailed a confirmation to ${d.your_email}. Our team will reply there.`)
        : null,
      h("div", { class: "desk-body" },
        h("div", { class: "desk-main" }, form()),
        h("aside", { class: "desk-side" },
          h("section", { class: "card" },
            h("h2", null, "Contact"),
            h("p", { class: "muted small", style: { margin: "0 0 6px" } }, "Prefer email? Write to us directly:"),
            h("p", { class: "desk-mail" }, d.email),
            h("div", { class: "row" },
              h("a", { class: "btn small", href: `mailto:${d.email}?subject=${encodeURIComponent("Mentora support")}` }, "Open email"),
              h("button", { class: "btn small", onClick: () => copyText(d.email) }, icon("copy"), " Copy"))),
          h("section", { class: "card" },
            h("h2", null, "Before you send"),
            h("ul", { class: "desk-tips" },
              h("li", null, "Reload the page with Ctrl + F5; many display problems go away."),
              h("li", null, "For a wrong question, copy the question and the answer shown."),
              h("li", null, "For sign-in problems, use Forgot password on the sign-in page first."),
              h("li", null, "Mention your reference (MEN-…) if you write again."))))),
      requests()));
  }

  render(root, h("p", { class: "muted" }, "Loading…"));
  load();
}
