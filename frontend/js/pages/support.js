// Customer support: raise a complaint about anything in Mentora, or write to the support inbox.
import { api, errorText, timeAgo } from "../api.js";
import { h, icon, render } from "../dom.js";
import { copyText, errorLine, toast } from "../ui.js";

const PLACES = ["", "Home", "Subjects", "AI Tutor", "My Learning", "Goals & Plans", "Progress", "My Teachers", "Profile or account", "Quizzes", "Teacher pages", "Somewhere else"];

export default function support(root) {
  const st = { data: null, category: "", subject: "", message: "", page: "", busy: false, error: null, sent: null };

  async function load() {
    try {
      st.data = await api.get("/api/support");
      paint();
    } catch (e) {
      render(root, errorLine(errorText(e)));
    }
  }

  async function submit(e) {
    e.preventDefault();
    st.error = null;
    if (!st.category) {
      st.error = "Choose what the problem is about.";
      paint();
      return;
    }
    st.busy = true;
    paint();
    try {
      const t = await api.post("/api/support", { category: st.category, subject: st.subject, message: st.message, page: st.page });
      Object.assign(st, { sent: t, category: "", subject: "", message: "", page: "" });
      st.data = await api.get("/api/support");
      toast(`Complaint ${t.number} sent.`);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      st.error = errorText(err);
    }
    st.busy = false;
    paint();
  }

  function form() {
    const d = st.data;
    return h("form", { class: "card support-form", onSubmit: submit },
      h("h2", null, "Raise a complaint"),
      h("p", { class: "muted page-intro" },
        "Tell us what went wrong: a bug, a wrong question, a problem with your account, an AI tutor answer or anything else. ",
        "Your complaint goes to the Mentora team by email, and we reply to ", h("b", null, st.data.your_email), "."),
      h("div", { class: "field" }, h("span", null, "What is it about?"),
        h("div", { class: "topic-pick" }, Object.entries(d.categories).map(([k, label]) => h("label", { class: `pick ${st.category === k ? "on" : ""}` },
          h("input", { type: "radio", name: "category", value: k, checked: st.category === k, onChange: () => { st.category = k; paint(); } }),
          h("span", null, label))))),
      h("div", { class: "field-row" },
        h("label", { class: "field" }, h("span", null, "Title"),
          h("input", { type: "text", value: st.subject, "data-key": "subject", required: true, minlength: "4", maxlength: "200",
            placeholder: "e.g. Quiz question 4 has the wrong answer", onInput: (e) => { st.subject = e.target.value; } })),
        h("label", { class: "field" }, h("span", null, "Where in Mentora? (optional)"),
          h("select", { onChange: (e) => { st.page = e.target.value; } },
            PLACES.map((p) => h("option", { value: p, selected: st.page === p }, p || "Choose a page"))))),
      h("label", { class: "field" }, h("span", null, "What happened?"),
        h("textarea", { rows: "6", value: st.message, "data-key": "message", required: true, minlength: "10", maxlength: "5000",
          placeholder: "What did you do, what did you expect, and what happened instead?", onInput: (e) => { st.message = e.target.value; } })),
      st.error ? h("p", { class: "error", role: "alert" }, st.error) : null,
      h("div", { class: "row" },
        h("button", { class: "btn primary", type: "submit", disabled: st.busy }, icon("send"), st.busy ? " Sending…" : " Send complaint"),
        h("span", { class: "muted small" }, "Please do not include passwords.")));
  }

  function paint() {
    const d = st.data;
    render(root, h("div", { class: "support" },
      h("div", { class: "support-main" },
        st.sent
          ? h("div", { class: "notice support-done", role: "status" }, h("span", { class: "notice-tag" }, st.sent.number),
              h("span", { class: "notice-text" }, `Thank you. We received “${st.sent.subject}” and sent a confirmation to ${st.data.your_email}. We will reply by email.`))
          : null,
        form(),
        h("section", { class: "card" },
          h("h2", null, `Your complaints (${d.tickets.length})`),
          d.tickets.length === 0
            ? h("p", { class: "empty" }, "You have not raised any complaints.")
            : h("table", { class: "data support-table" },
                h("thead", null, h("tr", null, ["Number", "Title", "About", "Sent", "Status"].map((x) => h("th", null, x)))),
                h("tbody", null, d.tickets.map((t) => h("tr", null,
                  h("td", { class: "mono" }, t.number),
                  h("td", null, h("b", null, t.subject), h("div", { class: "muted small ellipsis" }, t.message)),
                  h("td", null, t.category_label),
                  h("td", { class: "muted" }, timeAgo(t.created_at)),
                  h("td", null, h("span", { class: `badge ${t.status === "open" ? "warn" : "ok"}` }, t.status === "open" ? "Open" : "Resolved")))))))),
      h("aside", { class: "support-side" },
        h("section", { class: "card" },
          h("h2", null, "Email us"),
          h("p", null, "You can also write to the Mentora team directly:"),
          h("p", { class: "support-email" }, h("a", { href: `mailto:${d.email}?subject=${encodeURIComponent("Mentora complaint")}` }, d.email)),
          h("div", { class: "row" },
            h("a", { class: "btn small", href: `mailto:${d.email}?subject=${encodeURIComponent("Mentora complaint")}` }, icon("send"), " Open email"),
            h("button", { class: "btn small", onClick: () => copyText(d.email) }, icon("copy"), " Copy address"))),
        h("section", { class: "card" },
          h("h2", null, "What happens next"),
          h("ol", { class: "support-steps" },
            h("li", null, "You get a confirmation email with your complaint number."),
            h("li", null, "The Mentora team looks into it and replies by email."),
            h("li", null, "Mention your complaint number if you write again."))))));
  }

  render(root, h("p", { class: "muted" }, "Loading…"));
  load();
}
