export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const resp = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (resp.status === 204) return undefined as T;
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const detail = typeof data.detail === "string" ? data.detail : resp.statusText;
    throw new ApiError(resp.status, detail);
  }
  return data as T;
}

export const api = {
  get: <T,>(p: string) => request<T>("GET", p),
  post: <T,>(p: string, b?: unknown) => request<T>("POST", p, b ?? {}),
  del: <T,>(p: string) => request<T>("DELETE", p),
};

export interface Me {
  id: string;
  role: "learner" | "teacher";
  name: string;
  via: "lti" | "dev";
  llm_backend: string;
  mode: string;
}

export interface Turn {
  session_id: string;
  turn: number;
  action: string;
  reply: string | null;
  why: string | null;
  escalated: boolean;
  support_resources: boolean;
  sources: string[];
  correct: boolean | null;
}

export interface Item {
  id: number;
  text: string;
  item_type: "mcq" | "short";
  graded: boolean;
  concepts: string[];
}

export interface Goal {
  id: number;
  text: string;
  status: string;
  smart_score: number | null;
  progress: number;
  steps: { concept?: string; text?: string; done: boolean }[];
  created_at: string;
}

export interface CalibrationPoint {
  confidence: number;
  accuracy: number;
  n: number;
}

export interface MasteryRow {
  concept: string;
  key: string;
  mastery: number;
  practised: boolean;
}

export interface Dashboard {
  name: string;
  goals: Goal[];
  mastery: MasteryRow[];
  calibration_error: number;
  calibration_points: CalibrationPoint[];
  recent_tutor_messages: { at: string; action: string; reply: string | null; why: string | null }[];
  teacher_replies: { id: number; question: string | null; response: string; at: string | null }[];
}

export interface MemoryItem {
  id: number;
  text: string;
  quality: number;
  created_at: string;
}

export interface Escalation {
  id: number;
  learner: string;
  reason: string;
  message: string | null;
  status: string;
  teacher_response: string | null;
  created_at: string;
}

export interface Decision {
  at: string;
  learner: string;
  turn: number | null;
  action: string;
  propensity: number;
  policy_version: string;
  reason: string | null;
  why: string | null;
  removed: Record<string, string[]>;
  feasible_count: number;
  escalated: boolean;
  reply: string | null;
  sources: string[];
}

export interface Rule {
  id: number;
  name: string;
  rule: { forbid: Record<string, string>; when?: Record<string, unknown> };
  active: boolean;
}

export interface Policy {
  version: string;
  type: string;
  status: string;
  metrics: Record<string, unknown>;
  reasons: string | null;
  approved_by: string | null;
  created_at: string;
  decided_at: string | null;
}

/** "Planner.elicit_smart_goal.Socratic" -> "Planner · elicit smart goal (Socratic)" */
export function actionLabel(id: string): string {
  const [agent, move, style] = id.split(".");
  if (!move) return id === "WAIT" ? "Wait" : id === "ESCALATE" ? "Escalate to teacher" : id;
  return `${agent} · ${move.replace(/_/g, " ")} (${style})`;
}

// --- additions for the redesigned app --------------------------------------------------

export interface TurnContext {
  phase: string;
  topic: string | null;
  source_details: { id: string; section: string | null; week: number | null }[];
  strategy: string | null;
  /** course: checked against the cited notes; general: model knowledge (no notes cover it);
   * unverified: cites notes but could not be confirmed. */
  answer_source?: "course" | "general" | "unverified" | null;
}
export type FullTurn = Turn & TurnContext;

export interface Home {
  name: string;
  teacher_replies: number;
  stats: {
    streak_days: number;
    topics_completed: number;
    topics_total: number;
    quiz_average: number | null;
    quiz_average_previous: number | null;
    learning_hours_week: number;
  };
  srl: { overall: number; forethought: number; performance: number; reflection: number; has_data: boolean };
  strategy: { title: string; agent: string; description: string; why: string } | null;
  activity: { kind: string; text: string; at: string }[];
  next_steps: {
    kind: "practice" | "read";
    title: string;
    concept: string;
    detail: string;
    item_ids?: number[];
    passage_id?: string | null;
  }[];
  calendar: { date: string; events: number }[];
}

export interface Concept {
  key: string;
  name: string;
  week: number | null;
  prereqs: string[];
  mastery: number;
  practised: boolean;
  item_ids: number[];
}

export interface Resource {
  id: string;
  section: string | null;
  week: number | null;
  concepts: string[];
  source: string | null;
  text: string;
}

export interface Overview {
  stats: {
    total_students: number;
    active_week: number;
    average_score: number | null;
    at_risk: number;
    simulated_students: number;
  };
  weekly: { week: number; average_score: number | null; goal_completion: number | null; answers: number }[];
  topics: { concept: string; key: string; accuracy: number; answers: number }[];
  activity: { learner: string; activity: string; at: string }[];
}

export interface StudentRow {
  id: string;
  learner: string;
  simulated: boolean;
  sessions: number;
  last_active: string | null;
  mean_mastery: number;
  quiz_average: number | null;
  answers: number;
  dropout_risk: number;
  at_risk: boolean;
  open_escalations: number;
}

export interface StatusRow {
  name: string;
  state: string;
  detail: string;
}

export function timeAgo(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} hours ago`;
  return `${Math.round(s / 86400)} days ago`;
}

export const pct = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${Math.round(v * 100)}%`);

/** Split item text into question stem, code lines and (A)-(E) options. */
export function parseItem(text: string): { stem: string; code: string; options: { key: string; label: string }[] } {
  const lines = text.split("\n");
  const options = lines
    .map((l) => l.match(/^\(([A-E])\)\s*(.+)$/))
    .filter((m): m is RegExpMatchArray => m !== null)
    .map((m) => ({ key: m[1], label: m[2] }));
  const rest = lines.filter((l) => !/^\([A-E]\)/.test(l));
  return { stem: rest[0] ?? "", code: rest.slice(1).join("\n").trim(), options };
}

async function upload<T>(path: string, file: File): Promise<T> {
  const fd = new FormData();
  fd.append("file", file);
  const resp = await fetch(path, { method: "POST", body: fd, credentials: "same-origin" });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new ApiError(resp.status, typeof data.detail === "string" ? data.detail : resp.statusText);
  return data as T;
}
export const uploadFile = upload;

export interface StudentDetail extends Home {
  id: string;
  learner: string;
  simulated: boolean;
  sessions: number;
  mastery: MasteryRow[];
  goals: { text: string; status: string; smart_score: number | null; created_at: string }[];
}

/** POST that answers with server-sent events (reset / delta / done / error). Resolves with
 * the `done` payload; `onText` receives the draft reply as it grows. */
export async function postStream<T>(path: string, body: unknown, onText: (text: string) => void): Promise<T> {
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
    let cut: number;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      const event = /^event: (.+)$/m.exec(block)?.[1];
      const raw = /^data: (.*)$/m.exec(block)?.[1];
      const data = raw ? JSON.parse(raw) : {};
      if (event === "reset") { draft = ""; onText(draft); }
      else if (event === "delta") { draft += data.text; onText(draft); }
      else if (event === "done") return data as T;
      else if (event === "error") throw new ApiError(500, data.detail ?? "The tutor could not reply.");
    }
  }
  throw new ApiError(500, "The connection closed before the reply finished.");
}
