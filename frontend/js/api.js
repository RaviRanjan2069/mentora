// Calls to the Mentora API (same origin, cookie session) and small formatting helpers.

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function request(method, path, body) {
  const resp = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (resp.status === 204) return undefined;
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new ApiError(resp.status, typeof data.detail === "string" ? data.detail : resp.statusText);
  }
  return data;
}

export const api = {
  get: (path) => request("GET", path),
  post: (path, body) => request("POST", path, body ?? {}),
  del: (path) => request("DELETE", path),
};

export async function uploadFile(path, file) {
  const fd = new FormData();
  fd.append("file", file);
  const resp = await fetch(path, { method: "POST", body: fd, credentials: "same-origin" });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new ApiError(resp.status, typeof data.detail === "string" ? data.detail : resp.statusText);
  }
  return data;
}

/** POST answered with server-sent events (reset / delta / done / error). Resolves with the
 * `done` payload; onText receives the draft reply as it grows. */
export async function postStream(path, body, onText) {
  const resp = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
  });
  if (!resp.ok || !resp.body) {
    const data = await resp.json().catch(() => ({}));
    throw new ApiError(resp.status, typeof data.detail === "string" ? data.detail : resp.statusText);
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let draft = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      const event = /^event: (.+)$/m.exec(block)?.[1];
      const raw = /^data: (.*)$/m.exec(block)?.[1];
      const data = raw ? JSON.parse(raw) : {};
      if (event === "reset") {
        draft = "";
        onText(draft);
      } else if (event === "delta") {
        draft += data.text;
        onText(draft);
      } else if (event === "done") {
        return data;
      } else if (event === "error") {
        throw new ApiError(500, data.detail ?? "The tutor could not reply.");
      }
    }
  }
  throw new ApiError(500, "The connection closed before the reply finished.");
}

/** "Planner.elicit_smart_goal.Socratic" -> "Planner · elicit smart goal (Socratic)" */
export function actionLabel(id) {
  const [agent, move, style] = id.split(".");
  if (!move) return id === "WAIT" ? "Wait" : id === "ESCALATE" ? "Escalate to teacher" : id;
  return `${agent} · ${move.replace(/_/g, " ")} (${style})`;
}

export function timeAgo(iso) {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) {
    const hrs = Math.round(s / 3600);
    return hrs === 1 ? "1 hour ago" : `${hrs} hours ago`;
  }
  const days = Math.round(s / 86400);
  return days === 1 ? "yesterday" : `${days} days ago`;
}

export const pct = (v) => (v === null || v === undefined ? "–" : `${Math.round(v * 100)}%`);

/** Split item text into question stem, code lines and (A)-(E) options. */
export function parseItem(text) {
  const lines = text.split("\n");
  const options = lines
    .map((l) => l.match(/^\(([A-E])\)\s*(.+)$/))
    .filter((m) => m !== null)
    .map((m) => ({ key: m[1], label: m[2] }));
  const rest = lines.filter((l) => !/^\([A-E]\)/.test(l));
  return { stem: rest[0] ?? "", code: rest.slice(1).join("\n").trim(), options };
}

export const errorText = (e) => (e instanceof Error ? e.message : String(e));
