import { api, errorText } from "../api.js";
import { h, icon, render } from "../dom.js";
import { toast } from "../ui.js";

function policyCard(p, reload) {
  let note = "";
  const decide = (approve) =>
    api.post(`/api/teacher/policies/${p.version}/decision`, { approve, note: note || (approve ? "Approved" : "Rejected") })
      .then(() => { reload(); toast(approve ? `${p.version} is now active` : `${p.version} rejected`); })
      .catch((e) => toast(errorText(e), "error"));
  const report = typeof p.metrics.report_markdown === "string" ? p.metrics.report_markdown : null;
  return h(
    "section", { class: "card" },
    h("div", { class: "row" },
      h("h2", { style: { margin: 0 } }, p.version),
      h("span", { class: `badge ${p.status === "active" ? "ok" : p.status === "candidate" ? "warn" : ""}` }, p.status),
      h("span", { class: "muted" }, `${p.type} · ${new Date(p.created_at).toLocaleDateString()}`)),
    p.reasons ? h("pre", { class: "report" }, p.reasons) : null,
    report
      ? h("details", { open: p.status === "candidate" },
          h("summary", null, "Off-policy evaluation and fairness report"),
          h("pre", { class: "report" }, report))
      : null,
    p.status === "candidate"
      ? h("div", { class: "list mt" },
          h("textarea", {
            rows: "2", placeholder: "Your reasons (stored with the decision)",
            onInput: (e) => { note = e.target.value; },
          }),
          h("div", { class: "row" },
            h("button", { class: "btn primary", onClick: () => decide(true) }, "Approve and activate"),
            h("button", { class: "btn danger", onClick: () => decide(false) }, "Reject")))
      : null,
  );
}

export default function training(root) {
  const st = { models: null, policies: null, running: false, result: null, error: null };
  const top = h("div", { class: "grid cols-2" });
  const policyList = h("div", { class: "stack" });

  async function reload() {
    st.policies = await api.get("/api/teacher/policies");
    render(policyList, st.policies.map((p) => policyCard(p, reload)));
  }

  async function train() {
    Object.assign(st, { running: true, error: null, result: null });
    paint();
    try {
      st.result = await api.post("/api/teacher/policies/train");
      await reload();
    } catch (err) {
      st.error = errorText(err);
    } finally {
      st.running = false;
      paint();
    }
  }

  function paint() {
    const m = st.models;
    render(top,
      h("section", { class: "card" },
        h("h2", null, "Learner models"),
        m
          ? h("table", { class: "data" }, h("tbody", null,
              h("tr", null, h("th", null, "Mastery model"), h("td", null, m.mastery_model)),
              h("tr", null, h("th", null, "Trained knowledge-tracing files"),
                h("td", null, m.kt_models.length ? m.kt_models.join(", ") : "none (using the fallback estimate)")),
              h("tr", null, h("th", null, "Study-tactic model"), h("td", null, m.tactic_hmm ? "trained" : "not trained"))))
          : null,
        m?.report
          ? h("details", null, h("summary", null, "Training report"), h("pre", { class: "report" }, JSON.stringify(m.report, null, 2)))
          : null),
      h("section", { class: "card" },
        h("h2", null, "Tutor policy training"),
        h("p", { class: "muted" },
          "Trains a new policy offline from logged sessions and checks it with off-policy evaluation and a fairness audit. "
          + "A new policy is only ever a candidate: it does nothing until you approve it below."),
        h("button", { class: "btn primary", disabled: st.running, onClick: train },
          icon("cpu"), ` ${st.running ? "Training… (this can take a minute)" : "Run training now"}`),
        st.error ? h("p", { class: "error" }, st.error) : null,
        st.result
          ? h("div", { class: "banner mt" },
              "Result: ", h("b", null, st.result.status), st.result.version ? ` · ${st.result.version}` : null,
              h("pre", { class: "report" }, st.result.reasons))
          : null));
  }

  render(root, h("div", { class: "stack" }, top, policyList));
  paint();
  api.get("/api/teacher/models").then((m) => { st.models = m; paint(); }).catch(() => undefined);
  reload().catch((e) => toast(errorText(e), "error"));
}
