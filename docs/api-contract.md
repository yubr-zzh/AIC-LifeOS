# LifeOS API Alignment Document

This document aligns frontend and backend development for the current LifeOS core.

## Architecture Boundary

LifeOS has two runtime paths:

- Foreground Chat Agent: synchronous user path. It retrieves memory, executes direct LLM/tool calls, returns the response, and publishes a durable event.
- Background Global Agent: asynchronous maintenance path. It consumes reliable events through typed handlers and performs reflection, memory candidate creation, skill detection, and security review.

Frontend should treat `POST /chat` as the main user-facing action and `POST /background/run-once` as a developer/control action until a background worker loop exists.

## Base URL

```text
http://127.0.0.1:8765
```

Content type:

```text
application/json; charset=utf-8
```

## Current Implemented Endpoints

### POST /chat

Send one user message to the foreground Chat Agent.

Request body:

```json
{
  "message": "hello lifeos"
}
```

Response body:

```json
{
  "trace_id": "6f2af4b1-2c45-4f98-a43f-1b1b3a0f79f2",
  "response": "LifeOS mock response: hello lifeos",
  "tool_calls": []
}
```

Fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `trace_id` | string | ID for tracing this chat turn. |
| `response` | string | Assistant response text. |
| `tool_calls` | array | Tool calls requested by the LLM. Currently usually empty in mock mode. |

Side effect:

- Publishes a durable `conversation.completed` event to `.lifeos/events.json`.

Frontend expectations:

- Render the assistant response immediately.
- Store `trace_id` on the message.
- If `tool_calls` is non-empty, render them as execution cards.
- Optimistically show one pending `conversation.completed` event if no event-list endpoint exists yet.

### POST /background/run-once

Run one polling cycle of the Global Agent.

Request body:

```json
{}
```

Response body:

```json
{
  "processed": [
    "0f5cfd7e-7a63-4b2d-8d4b-f1b121312233"
  ]
}
```

Fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `processed` | string[] | Event IDs successfully processed in this cycle. |

Side effects:

- Marks polled events as `processing`, then `done` or `failed`.
- For `conversation.completed`, creates a memory candidate from reflection.
- May publish `skill.candidate.created` events if the detector identifies repeated/automatable work.

Frontend expectations:

- Use this as a manual "Run background once" button.
- Highlight Global Agent activity.
- If the event list is mocked, mark returned IDs as done.

## Current Data Models

### EventRecord

Source: `lifeos/event/bus.py`

```ts
type EventStatus = "pending" | "processing" | "done" | "failed";

type EventRecord = {
  id: string;
  type: string;
  payload: Record<string, unknown>;
  trace_id?: string | null;
  status: EventStatus;
  attempts: number;
  created_at: string;
  updated_at: string;
  error?: string | null;
};
```

Known event types:

| Type | Producer | Consumer |
| --- | --- | --- |
| `conversation.completed` | Chat Agent | Global Agent |
| `memory.write.requested` | Future UI/API | Global Agent |
| `skill.candidate.created` | Global Agent | Global Agent |

### ChatResponse

```ts
type ChatResponse = {
  trace_id: string;
  response: string;
  tool_calls: ToolCall[];
};
```

### ToolCall

Current executor expects tool calls shaped roughly like this:

```ts
type ToolCall = {
  name?: string;
  action?: string;
  arguments?: Record<string, unknown>;
};
```

High-risk actions may require user confirmation:

- `write_file`
- `delete_file`
- `send_email`
- `install_skill`

### MemoryStore

Source: `.lifeos/memory.json`

```ts
type MemoryStore = {
  user: MemoryEntry[];
  project: MemoryEntry[];
  feedback: MemoryEntry[];
  candidates: MemoryCandidate[];
  backups: MemoryBackup[];
  vector_index: Record<string, unknown>;
  cache: Record<string, unknown>;
};
```

### MemoryCandidate

```ts
type MemoryCandidate = {
  id: string;
  source: string;
  content: Record<string, unknown>;
  trace_id?: string | null;
  status: "candidate" | "committed" | "rejected";
  created_at: string;
  committed_at?: string;
};
```

Memory commit lifecycle:

```text
candidate -> validate -> backup -> apply -> vector_upsert -> cache_invalidate
```

### SkillRegistry

Source: `.lifeos/skills.json`

```ts
type SkillRegistry = {
  approved: Skill[];
  pending: SkillCandidate[];
};
```

### SkillCandidate

```ts
type SkillCandidate = {
  id: string;
  name: string;
  description: string;
  risk: "low" | "medium" | "high";
  source: string;
  status?: "pending" | "approved" | "rejected";
  review?: PermissionReview;
};
```

### PermissionReview

```ts
type PermissionReview = {
  decision: "allow" | "requires_confirmation" | "deny";
  reason: string;
};
```

There are two permission categories:

- Tool execution confirmation: confirms whether a high-risk existing tool/skill can run this time.
- Skill installation confirmation: confirms whether a new detected skill can be persisted into pending/registry.

## Recommended Next API Endpoints

These are not implemented yet, but the frontend should be designed around them.

### GET /events

Returns durable queue state.

Response:

```json
{
  "events": []
}
```

### GET /memory

Returns memory store snapshot.

Response:

```json
{
  "user": [],
  "project": [],
  "feedback": [],
  "candidates": [],
  "backups": [],
  "vector_index": {},
  "cache": {}
}
```

### POST /memory/candidates/{candidate_id}/commit

Requests Global Agent to commit a memory candidate.

Recommended behavior:

- Publish `memory.write.requested`.
- Return the event ID.

Response:

```json
{
  "event_id": "uuid",
  "status": "pending"
}
```

### GET /skills

Returns approved and pending skills.

Response:

```json
{
  "approved": [],
  "pending": []
}
```

### POST /skills/pending/{skill_id}/approve

Approves a pending skill candidate.

Response:

```json
{
  "skill_id": "uuid",
  "status": "approved"
}
```

### GET /traces/{trace_id}

Returns trace detail for one chat turn.

Response:

```json
{
  "input": "hello lifeos",
  "created": "2026-07-31T00:00:00",
  "events": []
}
```

### POST /permissions/{request_id}/confirm

Confirms a pending permission request.

Request:

```json
{
  "decision": "allow"
}
```

Response:

```json
{
  "request_id": "uuid",
  "decision": "allow",
  "status": "resolved"
}
```

## Error Shape

The current standard-library server uses plain HTTP errors for unknown routes. Future API should normalize errors:

```json
{
  "error": {
    "code": "not_found",
    "message": "Endpoint not found",
    "details": {}
  }
}
```

Recommended status codes:

| Status | Use |
| --- | --- |
| 200 | Successful request |
| 400 | Invalid JSON or invalid request |
| 404 | Unknown resource |
| 409 | Candidate/event state conflict |
| 422 | Validation failed |
| 500 | Unexpected server error |

## Frontend Integration Notes

- Treat missing inspection endpoints as expected during early development.
- Build an API client with mock fallback for events, memory, skills, and trace detail.
- Do not block chat rendering on Global Agent processing.
- Use `trace_id` as the join key across chat messages, events, memory candidates, and trace details.
- Render permission confirmations as separate UI objects from skill candidates.
- Clearly distinguish current backend data from local preview/mock data.

