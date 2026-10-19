// Teachers: the question bank of a folder's subject (starter questions plus teachers' own),
// with add, edit, hide, delete and CSV upload. Shown as a tab of the folder page.
import { api, errorText, pct } from "../api.js";
import { h, icon, plural, render } from "../dom.js";
import { errorLine, openModal, skeleton, toast } from "../ui.js";

const PAGE = 25;
const TEMPLATE = "topic,question,option_a,option_b,option_c,option_d,answer,explanation,difficulty\n"
  + "Inheritance,Which keyword makes a class inherit from another?,implements,extends,inherits,super,B,class Dog extends Animal,1\n";
const DIFFICULTY = [[1, "Easy"], [2, "Medium"], [3, "Hard"]];

function download(name, text) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  const a = h("a", { href: url, download: name });
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function questionBank(root, folder) {
  const st = { data: null, topic: "", q: "", show: "all", limit: PAGE };

  async function load() {
    try {
      st.data = await api.get(`/api/bank/${folder.subject_id}`);
      paint();
    } catch (e) {
      render(root, errorLine(errorText(e)));
    }
  }

  function editor(q) {
    const f = q
      ? { topic: q.topic, text: q.text, options: [...q.options], answer: q.answer, explanation: q.explanation, difficulty: q.difficulty }
      : { topic: st.topic, text: "", options: ["", "", "", ""], answer: 0, explanation: "", difficulty: 2 };
    openModal(q ? "Edit question" : "New question", (close, body) => {
      let error = null;
      const paintForm = () => render(body, h("form", {
        onSubmit: async (e) => {
          e.preventDefault();
          try {
            const payload = { ...f, options: f.options.map((o) => o.trim()), difficulty: Number(f.difficulty) };
            if (q) await api.post(`/api/bank/questions/${q.id}`, payload);
            else await api.post(`/api/bank/${folder.subject_id}/questions`, payload);
            toast(q ? "Question saved." : "Question added. Students can get it in their next rounds.");
            close();
            load();
          } catch (err) {
            error = errorText(err);
            paintForm();
          }
        },
      },
      q?.starter ? h("p", { class: "muted small", style: { marginTop: 0 } }, "This is a Mentora starter question. Your fix applies for every teacher and student of this subject.") : null,
      h("div", { class: "field-row" },
        h("label", { class: "field" }, h("span", null, "Topic"),
          h("input", { type: "text", list: "bank-topics", value: f.topic, "data-key": "b-topic", required: true, maxlength: "60", onInput: (e) => { f.topic = e.target.value; } }),
          h("datalist", { id: "bank-topics" }, st.data.topics.map((t) => h("option", { value: t })))),
        h("label", { class: "field" }, h("span", null, "Difficulty"),
          h("select", { onChange: (e) => { f.difficulty = e.target.value; } },
            DIFFICULTY.map(([v, l]) => h("option", { value: v, selected: Number(f.difficulty) === v }, l))))),
      h("label", { class: "field" }, h("span", null, "Question"),
        h("textarea", { rows: "3", value: f.text, "data-key": "b-text", required: true, maxlength: "2000", onInput: (e) => { f.text = e.target.value; } })),
      h("div", { class: "muted small", style: { marginBottom: 6 } }, "Options (select the right one). Students see them in a shuffled order."),
      h("div", { class: "stack-s" }, f.options.map((o, i) => h("div", { class: "opt-edit" },
        h("input", { type: "radio", name: "bank-right", checked: f.answer === i, "aria-label": `Option ${i + 1} is right`, onChange: () => { f.answer = i; } }),
        h("input", { type: "text", value: o, "data-key": `b-o${i}`, placeholder: `Option ${String.fromCharCode(65 + i)}`, maxlength: "300", onInput: (e) => { f.options[i] = e.target.value; } }),
        f.options.length > 2
          ? h("button", {
              class: "icon-btn", type: "button", "aria-label": "Remove option",
              onClick: () => { f.options.splice(i, 1); f.answer = f.answer === i ? 0 : f.answer > i ? f.answer - 1 : f.answer; paintForm(); },
            }, icon("x"))
          : null))),
      f.options.length < 6
        ? h("button", { class: "btn small", type: "button", style: { marginTop: 8 }, onClick: () => { f.options.push(""); paintForm(); } }, "+ Add option")
        : null,
      h("label", { class: "field", style: { marginTop: 12 } }, h("span", null, "Explanation shown after answering (optional)"),
        h("textarea", { rows: "2", value: f.explanation, "data-key": "b-expl", maxlength: "2000", onInput: (e) => { f.explanation = e.target.value; } })),
      error ? h("p", { class: "error", role: "alert" }, error) : null,
      h("div", { class: "row" }, h("div", { class: "spacer" }),
        h("button", { class: "btn", type: "button", onClick: close }, "Cancel"),
        h("button", { class: "btn primary", type: "submit" }, q ? "Save" : "Add question"))));
      paintForm();
    }, { wide: true });
  }

  async function upload(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    try {
      const resp = await fetch(`/api/bank/${folder.subject_id}/import`, { method: "POST", body: fd, credentials: "same-origin" });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(typeof data.detail === "string" ? data.detail : "The upload failed.");
      toast(`${plural(data.added, "question")} added.`);
      if (data.problems.length) {
        openModal("Some rows were skipped", () => h("div", null,
          h("p", null, `${plural(data.added, "question")} added. Fix these rows and upload them again:`),
          h("ul", { class: "small" }, data.problems.map((p) => h("li", null, p)))));
      }
      load();
    } catch (err) {
      toast(errorText(err), "error");
    }
  }

  async function toggleHidden(q) {
    await api.post(`/api/bank/questions/${q.id}/hidden`, { hidden: !q.hidden });
    toast(q.hidden ? "Students can get this question again." : "Hidden: students will not get this question.");
    load();
  }

  async function remove(q) {
    if (!window.confirm("Delete this question? Past results keep their topic but the question is gone.")) return;
    await api.del(`/api/bank/questions/${q.id}`);
    load();
  }

  function row(q) {
    const flagged = q.answered >= 5 && q.right_rate !== null && q.right_rate < 0.3;
    const who = q.starter ? `Mentora starter question${q.edited ? " (edited)" : ""}` : q.mine ? "Written by you" : `By ${q.author ?? "another teacher"}`;
    return h("li", { class: `bank-q ${q.hidden ? "is-hidden" : ""}` },
      h("div", { class: "row" },
        h("span", { class: "badge" }, q.topic),
        h("span", { class: "muted small" }, `${DIFFICULTY[q.difficulty - 1]?.[1] ?? ""} · ${who}`),
        q.hidden ? h("span", { class: "badge warn" }, "Hidden") : null,
        h("div", { class: "spacer" }),
        h("span", { class: `small ${flagged ? "error-text" : "muted"}`, title: "Students answering it right" },
          q.answered ? `${pct(q.right_rate)} right · ${q.answered} answers` : "Not answered yet")),
      h("div", { class: "bank-text" }, q.text),
      h("ol", { class: "bank-options" }, q.options.map((o, i) => h("li", { class: i === q.answer ? "right" : "" }, o, i === q.answer ? icon("check") : null))),
      q.explanation ? h("div", { class: "muted small" }, q.explanation) : null,
      flagged ? h("div", { class: "small error-text" }, "Most students miss this one. Check that the marked answer is right.") : null,
      h("div", { class: "row", style: { marginTop: 6 } },
        q.starter || q.mine ? h("button", { class: "btn small", onClick: () => editor(q) }, icon("pen"), " Edit") : null,
        q.starter || q.mine ? h("button", { class: "btn small", onClick: () => toggleHidden(q) }, q.hidden ? "Show to students" : "Hide") : null,
        q.mine ? h("button", { class: "btn small danger", onClick: () => remove(q) }, "Delete") : null));
  }

  function paint() {
    const d = st.data;
    const needle = st.q.trim().toLowerCase();
    const rows = d.questions.filter((q) => (!st.topic || q.topic === st.topic)
      && (st.show === "all" || (st.show === "mine" && q.mine) || (st.show === "starter" && q.starter) || (st.show === "hidden" && q.hidden))
      && (!needle || q.text.toLowerCase().includes(needle) || q.options.some((o) => o.toLowerCase().includes(needle))))
      .sort((a, b) => (b.mine - a.mine) || (a.mine ? b.id - a.id : 0));  // your questions first, newest on top
    const mine = d.questions.filter((q) => q.mine).length;
    const hidden = d.questions.filter((q) => q.hidden).length;
    render(root, h("div", { class: "stack" },
      h("section", { class: "card" },
        h("div", { class: "row" },
          h("div", null,
            h("h2", { style: { margin: 0 } }, `${d.subject} question bank`),
            h("div", { class: "muted small" },
              `${d.questions.length - hidden} questions students can get · ${plural(d.topics.length, "topic")} · ${mine} written by you${hidden ? ` · ${hidden} hidden` : ""}`)),
          h("div", { class: "spacer" }),
          h("button", { class: "btn primary small", onClick: () => editor(null) }, "+ Add question"),
          h("label", { class: "btn small" }, icon("upload"), " Upload CSV",
            h("input", { type: "file", accept: ".csv,text/csv", hidden: true, onChange: upload })),
          h("button", { class: "btn small", onClick: () => download("mentora-questions-template.csv", TEMPLATE) }, icon("download"), " CSV template")),
        h("p", { class: "muted small", style: { margin: "10px 0 0" } },
          "Every subject starts with 100 Mentora starter questions. Students practise them in rounds of 10 that adapt to their weak topics. ",
          "Starter questions have not been reviewed by a teacher yet: fix or hide any that are wrong.")),
      h("section", { class: "card" },
        h("div", { class: "row", style: { marginBottom: 12 } },
          h("select", { style: { maxWidth: 220 }, "aria-label": "Topic", onChange: (e) => { st.topic = e.target.value; st.limit = PAGE; paint(); } },
            h("option", { value: "" }, "All topics"), d.topics.map((t) => h("option", { value: t, selected: st.topic === t }, t))),
          h("div", { class: "seg", style: { margin: 0 } }, [["all", "All"], ["mine", "Mine"], ["starter", "Starter"], ["hidden", "Hidden"]].map(([k, l]) => h("button", {
            class: st.show === k ? "active" : "", onClick: () => { st.show = k; st.limit = PAGE; paint(); },
          }, l))),
          h("input", {
            type: "search", value: st.q, "data-key": "bq", placeholder: "Search questions", style: { maxWidth: 240 },
            onInput: (e) => { st.q = e.target.value; st.limit = PAGE; paint(); },
          })),
        rows.length === 0 ? h("p", { class: "empty" }, "No questions match.") : null,
        h("ul", { class: "bank-list" }, rows.slice(0, st.limit).map(row)),
        rows.length > st.limit
          ? h("button", { class: "btn", onClick: () => { st.limit += PAGE; paint(); } }, `Show more (${rows.length - st.limit} left)`)
          : null)));
  }

  render(root, skeleton({ cards: 2 }));
  load();
}

/** Practice results of the folder's students in its subject (for the Analysis tab). */
export async function practiceSection(folder) {
  const d = await api.get(`/api/folders/${folder.id}/practice`);
  const practised = d.students.filter((s) => s.answered > 0);
  return h("section", { class: "card" },
    h("h2", null, "Practice in My Learning"),
    h("p", { class: "muted small", style: { marginTop: -6 } },
      `How your enrolled students do in ${plural(practised.length, "student")}' adaptive practice of this subject's question bank.`),
    practised.length === 0
      ? h("p", { class: "empty" }, "None of your students has practised this subject yet.")
      : h("div", { class: "grid cols-2" },
          h("div", null, h("h3", null, "Class topics (weakest first)"),
            h("ul", { class: "topic-list" }, d.topics.filter((t) => t.answered).map((t) => h("li", null,
              h("span", { class: "topic-name" }, t.topic),
              h("div", { class: `meter ${t.accuracy >= 0.75 ? "good" : t.accuracy >= 0.5 ? "mid" : "low"}` }, h("span", { style: { width: `${Math.round((t.accuracy ?? 0) * 100)}%` } })),
              h("span", { class: "topic-val" }, pct(t.accuracy)),
              h("span", { class: "muted small" }, plural(t.answered, "answer")))))),
          h("div", null, h("h3", null, "Students"),
            h("ul", { class: "list" }, practised.map((s) => h("li", { class: "list-row" },
              h("div", { class: "body" }, h("div", { class: "title" }, s.student.name),
                h("div", { class: "muted small" }, `${s.answered} answers · ${pct(s.accuracy)} right · ${plural(s.rounds, "round")}`),
                s.weaknesses.length ? h("div", { class: "row", style: { marginTop: 4 } }, s.weaknesses.slice(0, 3).map((t) => h("span", { class: "badge danger" }, t))) : null)))))));
}
