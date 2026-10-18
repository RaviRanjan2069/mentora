import { api, errorText, parseItem, pct } from "../api.js";
import { h, hashParam, icon, plural, render } from "../dom.js";
import { richText } from "../richtext.js";
import { answer, present, quiz, send, session, subscribe } from "../session.js";
import { errorLine, skeleton } from "../ui.js";

const ROUND_SIZES = [5, 10, 20];
// Questions seen in this browser tab come last in the next round.
const seen = new Set();

/** A random round: unseen questions first. */
function pickRound(pool, size) {
  const shuffled = [...pool].sort(() => Math.random() - 0.5);
  const fresh = shuffled.filter((i) => !seen.has(i.id));
  return [...fresh, ...shuffled.filter((i) => seen.has(i.id))].slice(0, size);
}

export default function practice(root, { ask }) {
  const st = {
    concepts: null, items: null, topic: hashParam("concept"), started: false, finished: false,
    index: 0, results: {}, answer: "", confidence: 50, shownAt: Date.now(), note: null, hint: null,
    roundSize: 10, set: [],
  };

  const withItems = () => (st.concepts ?? []).filter((c) => c.item_ids.length > 0);
  const concept = () => withItems().find((c) => c.key === st.topic) ?? null;
  const pool = () => {
    const ids = new Set(concept()?.item_ids ?? []);
    return (st.items ?? []).filter((i) => ids.has(i.id));
  };

  async function open(i, fresh = false) {
    const it = st.set[i];
    if (!it) return;
    seen.add(it.id);
    st.index = i;
    st.answer = fresh ? "" : st.results[it.id]?.response ?? "";
    st.hint = null;
    st.shownAt = Date.now();
    st.note = null;
    paint();
    st.note = await present(it);
    paint();
  }

  async function begin() {
    st.set = pickRound(pool(), st.roundSize);
    st.results = {};
    st.finished = false;
    await quiz(st.set.map((i) => i.id));
    st.started = true;
    await open(0, true);
  }

  async function submit(e) {
    e.preventDefault();
    const item = st.set[st.index];
    if (!item || !st.answer.trim()) return;
    const response = st.answer.trim();
    const t = await answer(item, response, st.confidence / 100, Math.round((Date.now() - st.shownAt) / 1000));
    if (t) {
      st.results = { ...st.results, [item.id]: { response, correct: t.correct, confidence: st.confidence / 100 } };
      st.note = t;
    }
    paint();
  }

  async function askHint() {
    st.hint = await send("Can I get a hint?");
    paint();
  }

  function chooser() {
    const n = pool().length;
    return [
      h("h2", null, "Choose a topic"),
      h("div", { class: "row", style: { marginBottom: 14 } },
        h("select", {
          style: { maxWidth: 360 }, "aria-label": "Topic",
          onChange: (e) => { st.topic = e.target.value; st.started = false; paint(); },
        }, withItems().map((c) => h("option", { value: c.key, selected: c.key === st.topic },
          `${c.name} (${plural(c.item_ids.length, "question")})`))),
        h("select", {
          style: { width: "auto" }, "aria-label": "Questions per round",
          onChange: (e) => { st.roundSize = Number(e.target.value); paint(); },
        }, ROUND_SIZES.map((n2) => h("option", { value: n2, selected: n2 === st.roundSize }, `${n2} questions`))),
        h("button", { class: "btn primary", disabled: !n || session.busy, onClick: begin }, icon("play"), " Start practice")),
      h("p", { class: "muted" },
        `Each round picks ${Math.min(st.roundSize, n)} random questions from the ${n} on this topic, new ones first. `
        + "You'll rate how sure you are before each answer: it helps you notice what you really know. "
        + "Graded questions get hints only, never answers."),
    ];
  }

  function question(item, parsed) {
    const r = st.results[item.id];
    const submitBtn = h("button", { class: "btn primary", type: "submit", disabled: session.busy || !st.answer.trim() }, "Submit answer");
    const allAnswered = Object.keys(st.results).length > 0 && st.set.every((i) => st.results[i.id]);
    return h(
      "form", { onSubmit: submit },
      h("div", { class: "row between" },
        h("h2", { style: { margin: 0 } }, `Question ${st.index + 1} of ${st.set.length}`),
        h("span", { class: "muted" }, `Topic: ${concept()?.name ?? ""}`)),
      item.graded ? h("span", { class: "badge warn", style: { marginTop: 8, display: "inline-block" } }, "Graded: hints only") : null,
      h("p", { style: { marginTop: 14 } }, parsed.stem),
      parsed.code ? h("div", { class: "question-code" }, parsed.code) : null,
      parsed.options.length > 0
        ? h("div", { role: "radiogroup", "aria-label": "Options" }, parsed.options.map((o) => h(
            "label", { class: `option ${st.answer === o.key ? "selected" : ""}` },
            h("input", { type: "radio", name: "opt", checked: st.answer === o.key, onChange: () => { st.answer = o.key; paint(); } }),
            h("span", null, h("b", null, `${o.key}.`), ` ${o.label}`))))
        : h("input", {
            type: "text", value: st.answer, placeholder: "Your answer", "aria-label": "Your answer",
            style: { maxWidth: 360 }, "data-key": "answer",
            onInput: (e) => { st.answer = e.target.value; submitBtn.disabled = session.busy || !st.answer.trim(); },
          }),
      h("label", { style: { display: "block", margin: "16px 0", maxWidth: 360 } },
        "How sure are you? ", h("b", { "data-conf": "" }, `${st.confidence}%`),
        h("input", {
          type: "range", min: "0", max: "100", step: "5", value: st.confidence, style: { width: "100%" },
          onInput: (e) => {
            st.confidence = Number(e.target.value);
            e.target.parentElement.querySelector("[data-conf]").textContent = `${st.confidence}%`;
          },
        })),
      h("div", { class: "row" },
        submitBtn,
        r?.correct === true ? h("span", { class: "feedback-ok" }, "Correct") : null,
        r?.correct === false ? h("span", { class: "feedback-bad" }, "Not yet, have another go") : null,
        h("div", { class: "spacer" }),
        allAnswered
          ? h("button", { type: "button", class: "btn soft", onClick: () => { st.finished = true; paint(); } },
              "See results ", icon("arrow"))
          : null,
        st.index + 1 < st.set.length
          ? h("button", { type: "button", class: "btn", disabled: session.busy, onClick: () => open(st.index + 1) },
              "Next question ", icon("arrow"))
          : null),
      st.note?.reply
        ? h("div", { class: "card mt", style: { background: "var(--surface-2)", boxShadow: "none" } },
            h("div", { class: "muted", style: { marginBottom: 4 } }, "Your tutor"),
            h("div", { style: { whiteSpace: "pre-wrap" } }, richText(st.note.reply)),
            st.note.why ? h("div", { class: "muted small", style: { marginTop: 6 } }, st.note.why) : null)
        : null,
    );
  }

  function summary() {
    const set = st.set;
    const topic = concept()?.name ?? "";
    const answered = set.filter((i) => st.results[i.id]);
    const right = answered.filter((i) => st.results[i.id].correct).length;
    const score = answered.length ? right / answered.length : 0;
    const meanConf = answered.length ? answered.reduce((a, i) => a + st.results[i.id].confidence, 0) / answered.length : 0;
    const gap = meanConf - score;
    const wrong = set.filter((it) => st.results[it.id] && !st.results[it.id].correct);
    return h(
      "div", null,
      h("h2", null, `Results: ${topic}`),
      h("div", { class: "score-hero" },
        h("div", null, h("div", { class: "big" }, `${right}/${answered.length}`), h("div", { class: "muted" }, "correct")),
        h("div", { style: { flex: 1, minWidth: 220 } },
          h("div", { class: "row between muted" }, h("span", null, "Your average confidence"), h("b", null, pct(meanConf))),
          h("div", { class: "progress", style: { margin: "4px 0 10px" } },
            h("span", { style: { width: `${meanConf * 100}%`, background: "var(--series-2)" } })),
          h("div", { class: "row between muted" }, h("span", null, "Your accuracy"), h("b", null, pct(score))),
          h("div", { class: "progress", style: { marginTop: 4 } }, h("span", { style: { width: `${score * 100}%` } })))),
      h("p", { class: "muted" },
        Math.abs(gap) < 0.15
          ? "Your confidence was close to your results: you judged what you knew well."
          : gap > 0
            ? "You were more confident than your results. Before answering, try explaining the idea to yourself in one sentence."
            : "You knew more than you thought. It is worth trusting your reasoning a little more."),
      h("ul", { class: "list result-list mt" }, set.map((it, i) => {
        const r = st.results[it.id];
        return h("li", null,
          h("span", { class: `mark ${r?.correct ? "ok" : "bad"}` }, r?.correct ? "✓" : "✗"),
          h("div", { style: { flex: 1, minWidth: 0 } },
            h("div", null, parseItem(it.text).stem),
            h("div", { class: "muted small" }, `Your answer: ${r?.response ?? "–"} · ${pct(r?.confidence)} sure`)),
          h("button", { class: "btn small", onClick: () => { st.finished = false; open(i); } }, "Review"));
      })),
      h("div", { class: "row mt" },
        h("button", { class: "btn primary", onClick: begin }, icon("play"), " Try again"),
        wrong.length > 0
          ? h("button", {
              class: "btn soft",
              onClick: () => ask(`I got ${wrong.length} question(s) on ${topic} wrong. Can you explain the idea again?`),
            }, icon("bot"), " Go over my mistakes with the tutor")
          : null,
        h("button", { class: "btn", onClick: () => { st.started = false; st.finished = false; paint(); } }, "Pick another topic")),
    );
  }

  function paint() {
    if (!st.concepts || !st.items) return;
    const item = st.set[st.index] ?? null;
    const parsed = item ? parseItem(item.text) : null;
    const c = concept();
    const names = Object.fromEntries(st.concepts.map((x) => [x.key, x]));
    const done = st.set.filter((i) => st.results[i.id]?.correct).length;
    render(root, h(
      "div", { class: "grid cols-main-side" },
      h("section", { class: "card" },
        st.started && st.finished ? summary() : !st.started || !item ? chooser() : question(item, parsed),
        session.error ? h("p", { class: "error" }, session.error) : null),
      h("aside", { class: "stack" },
        st.started && st.set.length > 0
          ? h("section", { class: "card" },
              h("h2", null, "Question navigator"),
              h("div", { class: "navigator" }, st.set.map((it, i) => {
                const r = st.results[it.id];
                const cls = i === st.index ? "current" : r?.correct ? "right" : r ? "wrong" : "";
                return h("button", { class: cls, "aria-label": `Question ${i + 1}`, onClick: () => open(i) }, i + 1);
              })),
              h("p", { class: "muted", style: { marginTop: 10 } }, `${done} of ${st.set.length} correct`))
          : null,
        st.started
          ? h("section", { class: "card" },
              h("div", { class: "hint-card" }, icon("bulb"),
                h("div", { style: { flex: 1 } },
                  h("h3", null, "Hint"),
                  st.hint?.reply
                    ? h("p", { style: { margin: 0, whiteSpace: "pre-wrap" } }, richText(st.hint.reply))
                    : h("p", { class: "muted", style: { margin: 0 } }, "Stuck? Ask for the smallest useful nudge."),
                  h("button", { class: "btn soft small mt", disabled: session.busy, onClick: askHint }, "Get a hint"))))
          : null,
        c
          ? h("section", { class: "card" },
              h("h2", null, "Related concepts"),
              h("ul", { class: "list" }, [c.key, ...c.prereqs].map((k) => names[k]).filter(Boolean).map((x) => h(
                "li", { class: "list-row" },
                h("span", { class: "ico" }, icon("target")),
                h("div", { class: "body" },
                  h("div", { class: "title" }, x.name),
                  h("div", { class: "muted" }, x.practised ? `Estimated mastery ${pct(x.mastery)}` : "Not practised yet"))))))
          : null),
    ));
  }

  render(root, skeleton({ cards: 2 }));
  Promise.all([api.get("/api/concepts"), api.get("/api/items")])
    .then(([concepts, items]) => {
      st.concepts = concepts;
      st.items = items;
      if (!st.topic && withItems().length) st.topic = withItems()[0].key;
      paint();
    })
    .catch((e) => render(root, errorLine(errorText(e))));
  return subscribe(paint);
}
