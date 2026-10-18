// The learner's tutoring session, shared by the Tutor and Practice pages and the command
// palette. Pages subscribe() and redraw when it changes.
import { api, errorText, postStream } from "./api.js";

const listeners = new Set();

export const session = {
  sessionId: null,
  messages: [], // {from: "learner"|"tutor"|"system", text, at: Date, turn?, streaming?}
  context: { topic: null, phase: "", strategy: null, sources: [] },
  busy: false,
  error: null,
  loaded: false,
};

function changed() {
  for (const fn of listeners) fn();
}

/** Calls fn on every change; returns the unsubscribe function. */
export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Restore an open session (and its transcript) after a reload. */
export async function loadSession() {
  if (session.loaded) return;
  session.loaded = true;
  try {
    const r = await api.get("/api/me/session");
    session.sessionId = r.session_id;
    if (r.session_id) {
      session.messages = [
        { from: "system", text: "Continuing your open session", at: new Date() },
        ...r.messages.map((m) => ({
          from: m.from,
          text: m.text,
          at: new Date(m.at),
          // Restored replies carry only what the chat shows: the move and why it was chosen.
          turn: m.action ? { action: m.action, why: m.why ?? null, escalated: false } : undefined,
        })),
      ];
    }
  } catch {
    /* no open session */
  }
  changed();
}

export function resetSession() {
  Object.assign(session, {
    sessionId: null, messages: [], busy: false, error: null, loaded: false,
    context: { topic: null, phase: "", strategy: null, sources: [] },
  });
}

function record(t) {
  const c = session.context;
  session.context = {
    topic: t.topic ?? c.topic,
    phase: t.phase || c.phase,
    strategy: t.strategy ?? c.strategy,
    sources: t.source_details?.length ? t.source_details : c.sources,
  };
  if (t.reply) session.messages = [...session.messages, { from: "tutor", text: t.reply, at: new Date(), turn: t }];
}

async function guard(fn) {
  session.busy = true;
  session.error = null;
  changed();
  try {
    return await fn();
  } catch (e) {
    session.error = errorText(e);
    return null;
  } finally {
    session.busy = false;
    changed();
  }
}

async function startNow() {
  const t = await api.post("/api/sessions");
  session.sessionId = t.session_id;
  session.messages = [{ from: "system", text: "Session started", at: new Date() }];
  record(t);
  return t;
}

export const start = () => guard(startNow);

async function ensure() {
  if (session.sessionId) return session.sessionId;
  return (await startNow()).session_id;
}

export function end() {
  return guard(async () => {
    if (!session.sessionId) return;
    await api.post(`/api/sessions/${session.sessionId}/end`);
    session.messages = [...session.messages, { from: "system", text: "Session ended", at: new Date() }];
    session.sessionId = null;
  });
}

/** Send a chat message; the reply streams into a draft bubble, then the final reply replaces it. */
export function send(text) {
  return guard(async () => {
    const sid = await ensure();
    session.messages = [...session.messages, { from: "learner", text, at: new Date() }];
    changed();
    const draftAt = new Date();
    const showDraft = (draft) => {
      const rest = session.messages.filter((m) => !m.streaming);
      session.messages = draft ? [...rest, { from: "tutor", text: draft, at: draftAt, streaming: true }] : rest;
      changed();
    };
    try {
      const t = await postStream(`/api/sessions/${sid}/messages/stream`, { text }, showDraft);
      showDraft("");
      record(t);
      return t;
    } catch (e) {
      showDraft("");
      throw e;
    }
  });
}

export function present(item) {
  return guard(async () => {
    const sid = await ensure();
    const t = await api.post(`/api/sessions/${sid}/items/${item.id}/present`);
    record(t);
    return t;
  });
}

export function quiz(itemIds) {
  return guard(async () => {
    const sid = await ensure();
    await api.post(`/api/sessions/${sid}/quiz`, { item_ids: itemIds });
  });
}

export function answer(item, response, confidence, seconds) {
  return guard(async () => {
    const sid = await ensure();
    session.messages = [...session.messages, {
      from: "learner", text: `My answer: ${response} (${Math.round(confidence * 100)}% sure)`, at: new Date(),
    }];
    const t = await api.post(`/api/sessions/${sid}/items/${item.id}/answer`, { response, confidence, seconds });
    record(t);
    return t;
  });
}
