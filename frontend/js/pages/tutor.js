// AI Tutor: a simple full-screen chat. Ask anything; answers stream in. Conversations are kept
// (History) and a New chat starts fresh. Markdown from the model is shown safely (never as HTML).
import { api, errorText, timeAgo } from "../api.js";
import { h, icon, logo, render } from "../dom.js";
import { copyText, openDrawer, toast } from "../ui.js";

const SUGGESTIONS = [
  ["Explain a concept", "Explain recursion with a simple example"],
  ["Debug my code", "Why does my Java loop never end? for (int i = 0; i < 10; i--) {}"],
  ["Make a study plan", "How should I prepare for my DBMS exam in two weeks?"],
  ["Quiz me", "Ask me 5 quick questions about Python lists"],
];
const PENDING = "mentora-chat-pending";

// --- a small, safe Markdown renderer -----------------------------------------------------------

function inline(text) {
  const out = [];
  const re = /(`[^`\n]+`|\*\*[^*\n]+\*\*|__[^_\n]+__|\*[^*\n]+\*)/g;
  let last = 0;
  for (const m of text.matchAll(re)) {
    out.push(text.slice(last, m.index));
    const t = m[0];
    if (t.startsWith("`")) out.push(h("code", { class: "inline-code" }, t.slice(1, -1)));
    else if (t.startsWith("**") || t.startsWith("__")) out.push(h("strong", null, t.slice(2, -2)));
    else out.push(h("em", null, t.slice(1, -1)));
    last = m.index + t.length;
  }
  out.push(text.slice(last));
  return out;
}

function codeBlock(code, lang) {
  return h("div", { class: "code-block chat-code" },
    h("div", { class: "code-head" }, h("span", null, lang || "code"),
      h("button", { class: "icon-btn", "aria-label": "Copy code", onClick: () => copyText(code) }, icon("copy"))),
    h("pre", null, h("code", null, code)));
}

export function markdown(text) {
  const out = [];
  // each match is one whole code block; an unclosed one (still streaming) runs to the end
  const fence = /```([a-zA-Z0-9+#-]*)[^\S\n]*\n?([\s\S]*?)(?:```|$)/g;
  let last = 0;
  for (const m of text.matchAll(fence)) {
    prose(text.slice(last, m.index), out);
    out.push(codeBlock(m[2].replace(/\n$/, ""), m[1]));
    last = m.index + m[0].length;
    if (!m[0]) break;
  }
  prose(text.slice(last), out);
  return out;
}

function prose(text, out) {
  {
    let list = null;
    for (const block of text.split(/\n{2,}/)) {
      for (const raw of block.split("\n")) {
        const line = raw.trimEnd();
        if (!line.trim()) continue;
        if (/^\s*[=-]{3,}\s*$/.test(line)) { // "Title" underlined with --- or ===: a heading
          const prev = out[out.length - 1];
          if (prev && prev.tagName === "P") out[out.length - 1] = h("h3", null, ...prev.childNodes);
          continue;
        }
        const heading = line.match(/^(#{1,4})\s+(.*)$/);
        const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
        const numbered = line.match(/^\s*(\d+)[.)]\s+(.*)$/);
        if (bullet || numbered) {
          const kind = bullet ? "ul" : "ol";
          if (!list || list.tagName.toLowerCase() !== kind) {
            list = h(kind, numbered ? { start: numbered[1] } : null);
            out.push(list);
          }
          list.appendChild(h("li", null, inline(bullet ? bullet[1] : numbered[2])));
          continue;
        }
        list = null;
        if (heading) out.push(h(heading[1].length <= 2 ? "h3" : "h4", null, inline(heading[2])));
        else out.push(h("p", null, inline(line)));
      }
      list = null;
    }
  }
}

// --- the page ----------------------------------------------------------------------------------

export default function tutor(root, { me }) {
  if (me.via !== "account") {
    render(root, h("section", { class: "card" }, h("h2", null, "AI Tutor"),
      h("p", { class: "muted" }, "The AI tutor needs a Mentora account. Sign out and create one.")));
    return undefined;
  }
  const first = (me.name || "there").split(" ")[0];
  const st = { thread: null, title: null, messages: [], busy: false, draft: "", offline: me.llm_backend === "offline" };
  let alive = true;

  const log = h("div", { class: "chat-log", "aria-live": "polite" });
  const input = h("textarea", {
    rows: "1", placeholder: `Ask anything, ${first}…`, "aria-label": "Your question", maxlength: "4000",
    onInput: () => { st.draft = input.value; grow(); },
    onKeydown: (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        send(input.value);
      }
    },
  });
  const sendBtn = h("button", { class: "chat-send", "aria-label": "Send", onClick: () => send(input.value) }, icon("send"));
  const head = h("div", { class: "chat-head" });

  function grow() {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 200)}px`;
    sendBtn.disabled = st.busy || !input.value.trim();
  }

  function scrollDown() {
    log.scrollTop = log.scrollHeight;
  }

  function bubble(msg) {
    if (msg.role === "user") {
      return h("div", { class: "msg-row user" }, h("div", { class: "chat-bubble user" }, msg.text));
    }
    return h("div", { class: "msg-row bot" },
      h("span", { class: "bot-avatar" }, logo()),
      h("div", { class: `chat-bubble bot ${msg.error ? "error" : ""} ${msg.support ? "support" : ""}` },
        msg.pending && !msg.text ? h("div", { class: "typing" }, h("i"), h("i"), h("i")) : markdown(msg.text),
        !msg.pending && !msg.error && msg.text
          ? h("div", { class: "bubble-tools" }, h("button", { class: "link-btn inline small", onClick: () => copyText(msg.text) }, icon("copy"), " Copy"))
          : null));
  }

  function welcome() {
    return h("div", { class: "chat-welcome" },
      h("div", { class: "welcome-logo" }, logo()),
      h("h2", null, `Welcome, ${first}!`),
      h("p", { class: "muted" }, "I'm your AI tutor. Ask me anything: concepts, code, exam preparation or homework doubts."),
      st.offline ? h("p", { class: "chat-offline" }, icon("alert"), " The AI model is offline right now, so answers may not come. Try again later.") : null,
      h("div", { class: "chat-suggest" }, SUGGESTIONS.map(([title, q]) => h("button", { onClick: () => send(q) },
        h("b", null, title), h("span", null, q)))));
  }

  function paintLog() {
    render(log, st.messages.length ? h("div", { class: "chat-inner" }, st.messages.map(bubble)) : welcome());
    scrollDown();
  }

  function paintHead() {
    render(head,
      h("div", { class: "chat-title" }, st.title || "New chat"),
      h("div", { class: "spacer" }),
      h("button", { class: "btn small", onClick: history }, icon("clock"), " History"),
      h("button", { class: "btn small primary", disabled: st.busy, onClick: newChat }, icon("pen"), " New chat"));
  }

  function newChat() {
    st.thread = null;
    st.title = null;
    st.messages = [];
    paintHead();
    paintLog();
    input.focus();
  }

  async function open(id) {
    try {
      const t = await api.get(`/api/chat/threads/${id}`);
      Object.assign(st, { thread: t.id, title: t.title, messages: t.messages });
      paintHead();
      paintLog();
    } catch (e) {
      toast(errorText(e), "error");
    }
  }

  function history() {
    openDrawer("Your conversations", (close, body) => {
      const paint = (rows) => render(body, rows.length === 0 ? h("p", { class: "empty" }, "No conversations yet.")
        : h("ul", { class: "chat-history" }, rows.map((t) => h("li", { class: t.id === st.thread ? "active" : "" },
            h("button", { class: "hist-open", onClick: () => { close(); open(t.id); } },
              h("b", null, t.title), h("span", { class: "muted small" }, `${timeAgo(t.updated_at)} · ${t.messages} messages`)),
            h("button", {
              class: "icon-btn", "aria-label": "Delete conversation",
              onClick: async () => {
                await api.del(`/api/chat/threads/${t.id}`);
                if (t.id === st.thread) newChat();
                paint(await api.get("/api/chat/threads"));
              },
            }, icon("trash"))))));
      render(body, h("p", { class: "muted" }, "Loading…"));
      api.get("/api/chat/threads").then(paint).catch((e) => render(body, h("p", { class: "error" }, errorText(e))));
    });
  }

  async function send(raw) {
    const text = (raw ?? "").trim();
    if (!text || st.busy) return;
    st.busy = true;
    input.value = "";
    st.draft = "";
    grow();
    const reply = { role: "assistant", text: "", pending: true };
    st.messages.push({ role: "user", text }, reply);
    paintHead();
    paintLog();
    let replyEl = log.querySelector(".msg-row.bot:last-child .chat-bubble");
    let frame = 0;
    const repaintReply = () => {
      frame = 0;
      if (!alive) return;
      const row = bubble(reply);
      const last = log.querySelector(".msg-row.bot:last-child");
      if (last) last.replaceWith(row);
      replyEl = row;
      const nearBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 160;
      if (nearBottom) scrollDown();
    };
    try {
      const resp = await fetch("/api/chat/ask", {
        method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, thread_id: st.thread }),
      });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(typeof data.detail === "string" ? data.detail : "The tutor could not reply just now.");
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let cut;
        while ((cut = buf.indexOf("\n\n")) >= 0) {
          const block = buf.slice(0, cut);
          buf = buf.slice(cut + 2);
          const event = block.match(/^event: (.*)$/m)?.[1];
          const data = JSON.parse(block.match(/^data: (.*)$/m)?.[1] ?? "{}");
          if (event === "thread") {
            st.thread = data.id;
            st.title = data.title;
            paintHead();
          } else if (event === "delta") {
            reply.text += data.text;
            if (!frame) frame = window.requestAnimationFrame(repaintReply);
          } else if (event === "done") {
            Object.assign(reply, { text: data.text, pending: false, support: Boolean(data.support) });
          } else if (event === "error") {
            Object.assign(reply, { text: data.detail, pending: false, error: true });
            if (data.offline) st.offline = true;
          }
        }
      }
      if (reply.pending) Object.assign(reply, { pending: false, error: !reply.text, text: reply.text || "The reply was cut off. Please try again." });
    } catch (e) {
      Object.assign(reply, { text: errorText(e), pending: false, error: true });
    }
    if (frame) window.cancelAnimationFrame(frame);
    st.busy = false;
    if (alive) {
      repaintReply();
      paintHead();
      grow();
      input.focus();
    }
  }

  render(root, h("div", { class: "chat-page" },
    head,
    log,
    h("div", { class: "chat-composer" },
      h("div", { class: "composer-box" }, input, sendBtn),
      h("div", { class: "composer-note muted small" }, "Enter to send · Shift+Enter for a new line · The AI can make mistakes, so check important facts."))));
  paintHead();
  paintLog();
  grow();
  input.focus();
  let pending = null;
  try {
    pending = window.sessionStorage.getItem(PENDING);
    window.sessionStorage.removeItem(PENDING);
  } catch {
    /* nothing pre-filled */
  }
  if (pending) send(pending);
  return () => { alive = false; };
}
