import type {
  ChatResponse,
  MemoryScope,
  EventRecord,
  FeedbackPayload,
  MemoryMarkdownResponse,
  MemoryEntry,
  MemoryStore,
  MemoryProfileView,
  MemoryCandidate,
  AgentRoutingPolicy,
  PermissionRequest,
  RunOnceResponse,
  SkillRegistryState,
  TraceRecord,
  StructuredEntry,
  StructuredEntryKind,
} from "./types";
import {
  mockEvents,
  mockMemory,
  mockPermissions,
  mockSkills,
  mockTrace,
} from "./mock";

// Tiny typed API client for LifeOS.
//
// Implements the two live endpoints that exist today:
//   POST /chat
//   POST /background/run-once
//
// Everything else (event list, memory snapshot, skills, trace detail,
// permissions) is read through `safeGet`, which falls back to mock data
// if the backend returns 404 or a network error. The frontend exposes
// a "local preview" badge so users can tell real backend data from mock.

export interface ApiOptions {
  baseUrl?: string;
  fetchImpl?: typeof fetch;
}

export interface EventsResponse {
  events: EventRecord[];
  source: "backend" | "preview";
}

export interface SourceTag<T> {
  data: T;
  source: "backend" | "preview";
}

const DEFAULT_BASE = "/api";

function getBase(opts?: ApiOptions): string {
  return (opts?.baseUrl ?? DEFAULT_BASE).replace(/\/$/, "");
}

function f(opts?: ApiOptions): typeof fetch {
  return opts?.fetchImpl ?? fetch;
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

export async function readError(res: Response): Promise<ApiError> {
  // 401 拦截（方案 6.4）：任何接口回 401 就广播，AuthGate 收到后切登录页。
  if (res.status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("lifeos:unauthorized"));
  }
  const text = await res.text().catch(() => "");
  return new ApiError(
    `HTTP ${res.status} ${res.statusText}${text ? `: ${text.slice(0, 160)}` : ""}`,
    res.status,
  );
}

export async function sendChat(
  message: string,
  opts?: ApiOptions,
  memoryScope?: MemoryScope,
  sessionId?: string,
  routingPolicy: AgentRoutingPolicy = "auto",
  agentSessionId?: string,
): Promise<ChatResponse> {
  const base = getBase(opts);
  const res = await f(opts)(`${base}/chat`, {
    method: "POST",
    headers: { "content-type": "application/json; charset=utf-8" },
    body: JSON.stringify({
      message,
      ...(memoryScope ? { memory_scope: memoryScope } : {}),
      ...(sessionId ? { session_id: sessionId } : {}),
      ...(agentSessionId ? { agent_session_id: agentSessionId } : {}),
      routing_policy: routingPolicy,
    }),
  });
  if (!res.ok) throw await readError(res);
  const data = (await res.json()) as ChatResponse;
  if (!data.trace_id || typeof data.response !== "string") {
    throw new ApiError("malformed /chat response", 500);
  }
  return {
    trace_id: data.trace_id,
    response: data.response,
    tool_calls: Array.isArray(data.tool_calls) ? data.tool_calls : [],
    tool_results: Array.isArray(data.tool_results) ? data.tool_results : [],
    ...(data.delegation ? { delegation: data.delegation } : {}),
    ...(data.decision ? { decision: data.decision } : {}),
    ...(data.decision_reason ? { decision_reason: data.decision_reason } : {}),
    ...(typeof data.decision_confidence === "number" ? { decision_confidence: data.decision_confidence } : {}),
    ...(Array.isArray(data.plan_steps) ? { plan_steps: data.plan_steps } : {}),
    ...(typeof data.agent_enabled === "boolean" ? { agent_enabled: data.agent_enabled } : {}),
    ...(data.routing_policy ? { routing_policy: data.routing_policy } : {}),
    ...(data.route_source ? { route_source: data.route_source } : {}),
    ...(Array.isArray(data.route_signals) ? { route_signals: data.route_signals } : {}),
    ...(typeof data.requires_side_effects === "boolean" ? { requires_side_effects: data.requires_side_effects } : {}),
  };
}

export async function submitFeedback(
  feedback: FeedbackPayload,
  opts?: ApiOptions,
): Promise<{ ok: boolean }> {
  const base = getBase(opts);
  const res = await f(opts)(`${base}/feedback`, {
    method: "POST",
    headers: { "content-type": "application/json; charset=utf-8" },
    body: JSON.stringify(feedback),
  });
  if (!res.ok) throw await readError(res);
  return (await res.json()) as { ok: boolean };
}

export async function runBackgroundOnce(
  opts?: ApiOptions,
): Promise<RunOnceResponse> {
  const base = getBase(opts);
  const res = await f(opts)(`${base}/background/run-once`, {
    method: "POST",
    headers: { "content-type": "application/json; charset=utf-8" },
    body: JSON.stringify({}),
  });
  if (!res.ok) throw await readError(res);
  const data = (await res.json()) as RunOnceResponse;
  return {
    processed: Array.isArray(data.processed) ? data.processed : [],
  };
}

// Safe GET — falls back to mock data when the endpoint is not implemented.
// We intentionally treat 404 and network errors as "endpoint missing" rather
// than as fatal errors, because the LifeOS backend does not yet expose most
// inspection endpoints.
export async function safeGet<T>(
  path: string,
  fallback: () => T,
  opts?: ApiOptions,
): Promise<SourceTag<T>> {
  const base = getBase(opts);
  try {
    const res = await f(opts)(`${base}${path}`, { method: "GET" });
    if (res.ok) {
      const data = (await res.json()) as T;
      return { data, source: "backend" };
    }
    if (res.status !== 404 && res.status < 500) {
      // 4xx other than 404 is unexpected; still fall back but warn via console.
      // 401 不走 readError（这条路径直接回退），在这里补上广播（方案 6.4）。
      if (res.status === 401 && typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("lifeos:unauthorized"));
      }
      console.warn(`[lifeos] GET ${path} -> ${res.status}, using preview data`);
    }
    return { data: fallback(), source: "preview" };
  } catch (err) {
    console.warn(`[lifeos] GET ${path} failed, using preview data:`, err);
    return { data: fallback(), source: "preview" };
  }
}

export async function getEvents(opts?: ApiOptions): Promise<EventsResponse> {
  const r = await safeGet<{ events: EventRecord[] }>(
    "/events",
    () => ({ events: mockEvents() }),
    opts,
  );
  return { events: r.data.events, source: r.source };
}

export async function getMemory(opts?: ApiOptions): Promise<SourceTag<MemoryStore>> {
  return safeGet<MemoryStore>("/memory", mockMemory, opts);
}

export async function getMemoryProfile(
  opts?: ApiOptions,
): Promise<SourceTag<MemoryProfileView>> {
  return safeGet<MemoryProfileView>(
    "/memory/profile",
    () => ({
      schema_version: 1,
      version: "preview-empty",
      generated_at: "",
      core_profiles: [],
      scenario_profiles: [],
      project_profiles: [],
    }),
    opts,
  );
}

export async function proposeEntryMemoryCandidate(
  entryId: string,
  input: { claim: string; scope: MemoryScope; category: "user" | "project" },
  opts?: ApiOptions,
): Promise<{ status: string; candidate: MemoryCandidate }> {
  const base = getBase(opts);
  const res = await f(opts)(`${base}/entries/${encodeURIComponent(entryId)}/memory-candidates`, {
    method: "POST",
    headers: { "content-type": "application/json; charset=utf-8" },
    body: JSON.stringify({ content: { claim: input.claim.trim() }, scope: input.scope, category: input.category }),
  });
  if (!res.ok) throw await readError(res);
  return (await res.json()) as { status: string; candidate: MemoryCandidate };
}

export async function proposeTraceMemoryCandidate(
  traceId: string,
  input: { claim: string; scope: MemoryScope; category: "user" | "project" },
  opts?: ApiOptions,
): Promise<{ status: string; candidate: MemoryCandidate }> {
  const res = await f(opts)(`${getBase(opts)}/traces/${encodeURIComponent(traceId)}/memory-candidates`, {
    method: "POST",
    headers: { "content-type": "application/json; charset=utf-8" },
    body: JSON.stringify({
      content: { claim: input.claim.trim() },
      scope: input.scope,
      category: input.category,
    }),
  });
  if (!res.ok) throw await readError(res);
  return (await res.json()) as { status: string; candidate: MemoryCandidate };
}

export interface AgentEvidence {
  id: string;
  owner_id: string;
  session_id: string;
  agent_id: string;
  summary: string;
  occurred_at: string;
}

export async function listAgentEvidence(sessionId: string, opts?: ApiOptions): Promise<AgentEvidence[]> {
  const res = await f(opts)(`${getBase(opts)}/agent/evidence?session_id=${encodeURIComponent(sessionId)}`);
  if (!res.ok) throw await readError(res);
  const data = (await res.json()) as { items: AgentEvidence[] };
  return data.items;
}

export async function proposeAgentMemoryCandidate(
  evidenceId: string, claim: string, projectId: string, opts?: ApiOptions,
): Promise<{ status: string; candidate: MemoryCandidate }> {
  const res = await f(opts)(`${getBase(opts)}/agent/evidence/${encodeURIComponent(evidenceId)}/memory-candidates`, {
    method: "POST",
    headers: { "content-type": "application/json; charset=utf-8" },
    body: JSON.stringify({ claim, project_id: projectId }),
  });
  if (!res.ok) throw await readError(res);
  return (await res.json()) as { status: string; candidate: MemoryCandidate };
}

export async function getMemoryMarkdown(
  opts?: ApiOptions,
): Promise<MemoryMarkdownResponse> {
  const base = getBase(opts);
  const res = await f(opts)(`${base}/memory/markdown`, { method: "GET" });
  if (!res.ok) throw await readError(res);
  return (await res.json()) as MemoryMarkdownResponse;
}

export async function importMemoryMarkdown(
  markdown: string,
  opts?: ApiOptions,
): Promise<{ ok: boolean; categories: Record<string, number> }> {
  const base = getBase(opts);
  const res = await f(opts)(`${base}/memory/markdown`, {
    method: "POST",
    headers: { "content-type": "application/json; charset=utf-8" },
    body: JSON.stringify({ markdown }),
  });
  if (!res.ok) throw await readError(res);
  return (await res.json()) as { ok: boolean; categories: Record<string, number> };
}

export async function correctMemory(
  memoryId: string,
  content: Record<string, unknown>,
  reason?: string,
  opts?: ApiOptions,
): Promise<MemoryEntry> {
  const base = getBase(opts);
  const res = await f(opts)(`${base}/memory/${encodeURIComponent(memoryId)}/correct`, {
    method: "POST",
    headers: { "content-type": "application/json; charset=utf-8" },
    body: JSON.stringify({ content, ...(reason ? { reason } : {}) }),
  });
  if (!res.ok) throw await readError(res);
  const data = (await res.json()) as { memory: MemoryEntry };
  return data.memory;
}

export async function retractMemory(
  memoryId: string,
  reason?: string,
  opts?: ApiOptions,
): Promise<MemoryEntry> {
  const base = getBase(opts);
  const res = await f(opts)(`${base}/memory/${encodeURIComponent(memoryId)}/retract`, {
    method: "POST",
    headers: { "content-type": "application/json; charset=utf-8" },
    body: JSON.stringify(reason ? { reason } : {}),
  });
  if (!res.ok) throw await readError(res);
  const data = (await res.json()) as { memory: MemoryEntry };
  return data.memory;
}

async function postAction<T>(path: string, opts?: ApiOptions, body?: unknown): Promise<T> {
  const res = await f(opts)(`${getBase(opts)}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json; charset=utf-8" },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) throw await readError(res);
  return (await res.json()) as T;
}

/** content 传了就按用户改过的正文入库，不传就原样采纳候选内容。 */
export function commitMemoryCandidate(id: string, content?: Record<string, unknown>, opts?: ApiOptions) {
  return postAction<{ status: "committed" }>(
    `/memory/candidates/${encodeURIComponent(id)}/commit`,
    opts,
    content ? { content } : undefined,
  );
}

export function rejectMemoryCandidate(id: string, opts?: ApiOptions) {
  return postAction<{ status: "rejected" }>(`/memory/candidates/${encodeURIComponent(id)}/reject`, opts);
}

export function approvePendingSkill(id: string, opts?: ApiOptions) {
  return postAction<{ status: "approved" }>(`/skills/pending/${encodeURIComponent(id)}/approve`, opts);
}

export function rejectPendingSkill(id: string, opts?: ApiOptions) {
  return postAction<{ status: "rejected" }>(`/skills/pending/${encodeURIComponent(id)}/reject`, opts);
}

export async function getSkills(
  opts?: ApiOptions,
): Promise<SourceTag<SkillRegistryState>> {
  return safeGet<SkillRegistryState>("/skills", mockSkills, opts);
}

export async function getTrace(
  traceId: string,
  opts?: ApiOptions,
): Promise<SourceTag<TraceRecord>> {
  return safeGet<TraceRecord>(`/traces/${encodeURIComponent(traceId)}`, () =>
    mockTrace(traceId),
  opts,
  );
}

export async function getPermissions(
  opts?: ApiOptions,
): Promise<SourceTag<PermissionRequest[]>> {
  return safeGet<{ requests: PermissionRequest[] }>(
    "/permissions",
    () => ({ requests: mockPermissions() }),
    opts,
  ).then(({ data, source }) => ({ data: data.requests, source }));
}

export async function listEntries(
  kind: StructuredEntryKind,
  opts?: ApiOptions,
): Promise<StructuredEntry[]> {
  const base = getBase(opts);
  const res = await f(opts)(`${base}/entries?kind=${encodeURIComponent(kind)}`, { method: "GET" });
  if (!res.ok) throw await readError(res);
  const data = (await res.json()) as { entries: StructuredEntry[] };
  return Array.isArray(data.entries) ? data.entries : [];
}

export async function saveEntry(
  entry: {
    id?: string;
    kind: StructuredEntryKind;
    entry_date?: string;
    title?: string;
    content?: string;
    mood?: string | null;
    metadata?: Record<string, unknown>;
  },
  opts?: ApiOptions,
): Promise<StructuredEntry> {
  const base = getBase(opts);
  const method = entry.id ? "PUT" : "POST";
  const path = entry.id ? `/entries/${encodeURIComponent(entry.id)}` : "/entries";
  const res = await f(opts)(`${base}${path}`, {
    method,
    headers: { "content-type": "application/json; charset=utf-8" },
    body: JSON.stringify(entry),
  });
  if (!res.ok) throw await readError(res);
  const data = (await res.json()) as { entry: StructuredEntry };
  return data.entry;
}
