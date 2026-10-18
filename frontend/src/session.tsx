import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { api, FullTurn, Item, postStream } from "./api";

export interface ChatMessage {
  from: "learner" | "tutor" | "system";
  text: string;
  at: Date;
  turn?: FullTurn;
  streaming?: boolean; // draft text still being generated
}

interface SessionState {
  sessionId: string | null;
  messages: ChatMessage[];
  context: { topic: string | null; phase: string; strategy: string | null; sources: FullTurn["source_details"] };
  busy: boolean;
  error: string | null;
  start: () => Promise<FullTurn | null>;
  ensure: () => Promise<string>;
  end: () => Promise<void>;
  send: (text: string) => Promise<FullTurn | null>;
  present: (item: Item) => Promise<FullTurn | null>;
  quiz: (itemIds: number[]) => Promise<void>;
  answer: (item: Item, response: string, confidence: number, seconds: number) => Promise<FullTurn | null>;
}

interface SavedMessage { from: "learner" | "tutor"; text: string; at: string; action?: string; why?: string | null }

const Ctx = createContext<SessionState | null>(null);

export function useSession(): SessionState {
  const s = useContext(Ctx);
  if (!s) throw new Error("useSession outside SessionProvider");
  return s;
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [context, setContext] = useState<SessionState["context"]>({ topic: null, phase: "", strategy: null, sources: [] });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<{ session_id: string | null; messages: SavedMessage[] }>("/api/me/session")
      .then((r) => {
        setSessionId(r.session_id);
        if (!r.session_id) return;
        setMessages([
          { from: "system", text: "Continuing your open session", at: new Date() },
          ...r.messages.map((m): ChatMessage => ({
            from: m.from,
            text: m.text,
            at: new Date(m.at),
            // Restored replies carry only what the chat shows: the move and why it was chosen.
            turn: m.action ? ({ action: m.action, why: m.why ?? null, escalated: false } as FullTurn) : undefined,
          })),
        ]);
      })
      .catch(() => undefined);
  }, []);

  const record = useCallback((t: FullTurn) => {
    setContext((c) => ({
      topic: t.topic ?? c.topic,
      phase: t.phase || c.phase,
      strategy: t.strategy ?? c.strategy,
      sources: t.source_details.length ? t.source_details : c.sources,
    }));
    if (t.reply) setMessages((m) => [...m, { from: "tutor", text: t.reply!, at: new Date(), turn: t }]);
  }, []);

  async function guard<T>(fn: () => Promise<T>): Promise<T | null> {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return null;
    } finally {
      setBusy(false);
    }
  }

  const start = () =>
    guard(async () => {
      const t = await api.post<FullTurn>("/api/sessions");
      setSessionId(t.session_id);
      setMessages([{ from: "system", text: "Session started", at: new Date() }]);
      record(t);
      return t;
    });

  const ensure = async (): Promise<string> => {
    if (sessionId) return sessionId;
    const t = await start();
    if (!t) throw new Error("Could not start a session");
    return t.session_id;
  };

  const end = async () => {
    await guard(async () => {
      if (!sessionId) return;
      await api.post(`/api/sessions/${sessionId}/end`);
      setMessages((m) => [...m, { from: "system", text: "Session ended", at: new Date() }]);
      setSessionId(null);
    });
  };

  const send = (text: string) =>
    guard(async () => {
      const sid = await ensure();
      setMessages((m) => [...m, { from: "learner", text, at: new Date() }]);
      // Stream the reply: a draft bubble grows as the model writes, then the final, checked
      // reply replaces it.
      const draftAt = new Date();
      const showDraft = (draft: string) =>
        setMessages((m) => {
          const rest = m.filter((x) => !x.streaming);
          return draft ? [...rest, { from: "tutor", text: draft, at: draftAt, streaming: true }] : rest;
        });
      try {
        const t = await postStream<FullTurn>(`/api/sessions/${sid}/messages/stream`, { text }, showDraft);
        showDraft("");
        record(t);
        return t;
      } catch (e) {
        showDraft("");
        throw e;
      }
    });

  const present = (item: Item) =>
    guard(async () => {
      const sid = await ensure();
      const t = await api.post<FullTurn>(`/api/sessions/${sid}/items/${item.id}/present`);
      record(t);
      return t;
    });

  const quiz = async (itemIds: number[]) => {
    await guard(async () => {
      const sid = await ensure();
      await api.post(`/api/sessions/${sid}/quiz`, { item_ids: itemIds });
    });
  };

  const answer = (item: Item, response: string, confidence: number, seconds: number) =>
    guard(async () => {
      const sid = await ensure();
      setMessages((m) => [...m, { from: "learner", text: `My answer: ${response} (${Math.round(confidence * 100)}% sure)`, at: new Date() }]);
      const t = await api.post<FullTurn>(`/api/sessions/${sid}/items/${item.id}/answer`, { response, confidence, seconds });
      record(t);
      return t;
    });

  return (
    <Ctx.Provider value={{ sessionId, messages, context, busy, error, start, ensure, end, send, present, quiz, answer }}>
      {children}
    </Ctx.Provider>
  );
}

export function useLoad<T>(path: string | null): [T | null, () => void, string | null] {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    if (!path) return;
    api.get<T>(path).then(setData).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [path]);
  useEffect(() => {
    load();
  }, [load]);
  return [data, load, error];
}
