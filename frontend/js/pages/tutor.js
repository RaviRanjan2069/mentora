import { actionLabel } from "../api.js";
import { h, icon, render } from "../dom.js";
import { richText } from "../richtext.js";
import { end, send, session, start, subscribe } from "../session.js";
import { openModal, toast } from "../ui.js";

const QUICK = [
  ["Explain again", "Can you explain that again?"],
  ["Give a hint", "Can I get a hint?"],
  ["Show similar example", "Can you show me a similar example?"],
  ["Give a practice question", "Give me a practice question"],
];

const STARTERS = [
  ["target", "Plan a study session", "Set a goal for today", "My goal today is to understand for loops and finish two exercises"],
  ["bulb", "Explain a concept", "Ask about anything in the notes", "Can you explain how range() works?"],
  ["practice", "Quiz me", "A practice question on this week", "Give me a practice question"],
  ["pen", "Look back", "Reflect on how it went", "Looking back, what should I change in how I study?"],
];

const SOURCE_NOTE = {
  course: "From your course notes",
  general: "General knowledge, not from your course notes: check important facts",
  unverified: "Uses your course notes, but some details could not be checked against them",
};

const PHASE = {
  forethought: "Forethought (planning)",
  performance: "Performance (working)",
  reflection: "Self-reflection",
};

const REFLECT = [
  ["went", "What did you get done?", "Compare it with the goal you set."],
  ["why", "What was hard, and why?", "Was it the topic, your approach, time or focus?"],
  ["next", "What will you do differently next time?", "One concrete change is enough."],
];

function message(m) {
  if (m.from === "system") return h("div", { class: "system-line" }, m.text);
  const time = m.at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const t = m.turn;
  return h(
    "div", { class: `msg ${m.from} ${t?.escalated ? "escalated" : ""}` },
    h("div", { class: "who" }, icon(m.from === "tutor" ? "bot" : "user")),
    h("div", { style: { minWidth: 0, maxWidth: "78%" } },
      h("div", { class: "bubble", style: { maxWidth: "100%" } },
        richText(m.text),
        m.streaming ? h("span", { class: "caret", "aria-hidden": "true" }) : null,
        t?.answer_source && SOURCE_NOTE[t.answer_source]
          ? h("div", { class: `source-note ${t.answer_source}` }, SOURCE_NOTE[t.answer_source]) : null,
        t?.why
          ? h("div", { class: "why" }, h("b", null, "Why this suggestion?"), ` ${t.why.replace(/^Why this suggestion:\s*/, "")}`)
          : null),
      h("div", { class: "time", style: { textAlign: m.from === "learner" ? "right" : "left" } },
        time,
        t ? [" · ", h("span", { title: "What the tutor chose to do" }, t.action === "WAIT" ? "Answer" : actionLabel(t.action))] : null)),
  );
}

/** Guided end-of-session reflection: answers go to the tutor as one message, then the session ends. */
function openReflection() {
  const answers = {};
  openModal("Before you finish: look back", (close, body) => {
    const filled = () => REFLECT.filter(([k]) => answers[k]?.trim()).length;
    const save = h("button", { class: "btn primary" }, "Save reflection and end");
    const skip = h("button", { class: "btn" }, "Skip and end");
    const sync = () => {
      save.disabled = session.busy || filled() === 0;
      skip.disabled = session.busy;
    };
    async function finish(withReflection) {
      if (withReflection) {
        const text = REFLECT.filter(([k]) => answers[k]?.trim()).map(([k, q]) => `${q} ${answers[k].trim()}`).join("\n");
        await send(text);
      }
      await end();
      toast(withReflection ? "Session ended. Your reflection is saved." : "Session ended.");
      close();
    }
    save.addEventListener("click", () => finish(true));
    skip.addEventListener("click", () => finish(false));
    sync();
    return h("div", null,
      h("p", { class: "muted", style: { marginTop: 0 } },
        "A short reflection helps you remember what worked. It also counts towards your self-reflection score on the "
        + "Home page. Answer any of these, or skip."),
      REFLECT.map(([k, q, hint]) => h(
        "div", { class: "reflect-q" },
        h("label", { for: `r-${k}` }, q),
        h("div", { class: "muted" }, hint),
        h("textarea", {
          id: `r-${k}`, rows: "2", maxlength: "1000",
          onInput: (e) => { answers[k] = e.target.value; sync(); },
        }))),
      h("div", { class: "row", style: { justifyContent: "flex-end" } }, skip, save));
  });
}

export default function tutor(root) {
  let text = "";

  function sendText(body) {
    if (!body.trim() || session.busy) return;
    text = "";
    send(body.trim());
  }

  function autosize(el) {
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }

  function paint() {
    const chatting = session.messages.some((m) => m.from !== "system");
    const sendBtn = h("button", {
      class: "send-btn", type: "submit", disabled: session.busy || !text.trim(), "aria-label": "Send",
    }, icon("send"));
    const box = h("textarea", {
      rows: "1", value: text, maxlength: "4000", placeholder: "Type your message…", "aria-label": "Message",
      "data-key": "composer",
      onInput: (e) => {
        text = e.target.value;
        sendBtn.disabled = session.busy || !text.trim();
        autosize(e.target);
      },
      onKeydown: (e) => {
        if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
          e.preventDefault();
          sendText(text);
        }
      },
    });
    const messages = h("div", { class: "messages", "aria-live": "polite" },
      !chatting && !session.busy
        ? h("div", { class: "welcome" },
            h("div", { class: "orb" }, icon("sparkle")),
            h("h3", null, "What would you like to work on?"),
            h("p", { class: "muted", style: { margin: 0 } },
              "The tutor helps you plan, practise and reflect. Pick a starting point or type your own question."),
            h("div", { class: "starters" }, STARTERS.map(([name, title, sub, msg]) => h(
              "button", { class: "starter", disabled: session.busy, onClick: () => sendText(msg) },
              icon(name), h("div", null, h("b", null, title), h("span", null, sub))))))
        : null,
      session.messages.map(message),
      session.busy && !session.messages.some((m) => m.streaming)
        ? h("div", { class: "msg tutor", "aria-label": "The tutor is replying" },
            h("div", { class: "who" }, icon("bot")),
            h("div", { class: "typing" }, h("i"), h("i"), h("i")))
        : null);
    const ctx = session.context;

    render(root, h(
      "div", { class: "grid cols-main-side" },
      h("section", { class: "card chat", "aria-label": "Tutor chat" },
        h("div", { class: "row between", style: { marginBottom: 10 } },
          h("span", { class: "muted row", style: { gap: 6 } },
            h("span", { class: `status-dot ${session.sessionId ? "" : "empty"}`, "aria-hidden": "true" }),
            session.sessionId ? "Session in progress" : "No session yet"),
          session.sessionId
            ? h("button", { class: "btn small", disabled: session.busy, onClick: openReflection }, "End session")
            : h("button", { class: "btn primary small", disabled: session.busy, onClick: () => start() },
                icon("play"), " Start a study session")),
        messages,
        session.error ? h("p", { class: "error" }, session.error) : null,
        chatting
          ? h("div", { class: "quick", "aria-label": "Quick requests" }, QUICK.map(([label, msg]) => h(
              "button", { class: "chip-btn", disabled: session.busy, onClick: () => sendText(msg) }, label)))
          : null,
        h("form", { class: "composer", onSubmit: (e) => { e.preventDefault(); sendText(text); } }, box, sendBtn),
        h("div", { class: "composer-hint" }, "Enter to send · Shift+Enter for a new line · Ctrl+K to search the notes")),
      h("aside", { class: "stack" },
        h("section", { class: "card" },
          h("h2", null, "Current learning context"),
          h("div", { class: "context-item" }, h("div", { class: "k" }, "Topic"), h("div", null, ctx.topic ?? "Not set yet")),
          h("div", { class: "context-item p2" }, h("div", { class: "k" }, "SRL phase"), h("div", null, PHASE[ctx.phase] ?? "–")),
          h("div", { class: "context-item p3" }, h("div", { class: "k" }, "Suggested strategy"), h("div", null, ctx.strategy ?? "–"))),
        h("section", { class: "card" },
          h("h2", null, "Related resources"),
          ctx.sources.length === 0 ? h("p", { class: "empty" }, "Course passages the tutor uses appear here.") : null,
          h("ul", { class: "list" }, ctx.sources.map((r) => h(
            "li", { class: "list-row" },
            h("span", { class: "ico" }, icon("file")),
            h("div", { class: "body" },
              h("div", { class: "title" }, r.section ?? r.id),
              h("div", { class: "muted" }, r.week ? `Week ${r.week} notes` : "Course notes")),
            h("a", { class: "arrow-btn", href: `#/resources?id=${r.id}`, "aria-label": `Open ${r.section ?? r.id}` }, icon("arrow"))))))),
    ));
    autosize(box);
    // Each redraw follows the conversation to its newest message (also while a reply streams in).
    messages.scrollTop = messages.scrollHeight;
  }

  paint();
  return subscribe(paint);
}
