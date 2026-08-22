import type {
  ChatResponse,
  EventRecord,
  MemoryStore,
  PermissionRequest,
  RunOnceResponse,
  SkillRegistryState,
  TraceRecord,
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

async function readError(res: Response): Promise<ApiError> {
  const text = await res.text().catch(() => "");
  return new ApiError(
    `HTTP ${res.status} ${res.statusText}${text ? `: ${text.slice(0, 160)}` : ""}`,
    res.status,
  );
}

export async function sendChat(
  message: string,
  opts?: ApiOptions,
): Promise<ChatResponse> {
  const base = getBase(opts);
  const res = await f(opts)(`${base}/chat`, {
    method: "POST",
    headers: { "content-type": "application/json; charset=utf-8" },
    body: JSON.stringify({ message }),
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
  };
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
