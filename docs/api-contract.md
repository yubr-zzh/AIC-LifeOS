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
  "message": "hello lifeos",
  "memory_scope": {
    "kind": "scenario",
    "scenario_type": "learning",
    "project_id": null,
    "user_id": null
  }
}
```

`memory_scope` is optional. When omitted, recall is limited to global Memory.
When supplied, it must be a valid explicit scope and is included in the durable
`conversation.completed` event; the backend does not infer scenario or project
identity yet.

Recall is hierarchical: `global` sees global entries; `scenario` sees global
plus entries in the same `scenario_type`; `project` sees global, same-scenario,
and entries with the same `project_id`. Other scenarios/projects and
`unassigned` entries are excluded. If a Memory has a non-null `user_id`, the
request must supply the same ID for that entry to match. This is a retrieval
filter only, not authentication or authorization. The current API does not
automatically classify a message into a scenario/project; callers must pass an
explicit scope or accept the global-only default.

Response body:

```json
{
  "trace_id": "6f2af4b1-2c45-4f98-a43f-1b1b3a0f79f2",
  "response": "LifeOS mock response: hello lifeos",
  "tool_calls": [],
  "tool_results": []
}
```

Fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `trace_id` | string | ID for tracing this chat turn. |
| `response` | string | Assistant response text. |
| `tool_calls` | array | Tool calls requested by the LLM. Currently usually empty in mock mode. |
| `tool_results` | array | Execution or blocked status for each requested tool call. |

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
  schema_version: number;
  user: MemoryEntry[];
  project: MemoryEntry[];
  feedback: MemoryEntry[];
  reference: MemoryEntry[];
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
  source: string; // origin kind: direct, reflection, user_feedback, etc.
  category: "user" | "project" | "feedback" | "reference";
  source_ref: MemorySourceRef | null;
  scope: MemoryScope;
  occurred_at: string | null;
  confidence: number | null;
  confidence_method: string | null;
  content: Record<string, unknown>;
  trace_id?: string | null;
  status: "candidate" | "committed" | "rejected";
  created_at: string;
  committed_at?: string;
};

type MemorySourceRef = {
  kind: string;
  record_id: string;
  record_kind?: string;
  revision?: string;
  trace_id?: string | null;
};

type MemoryScope = {
  kind: "global" | "scenario" | "project" | "unassigned";
  scenario_type: string | null;
  project_id: string | null;
  user_id: string | null;
};
```

Memory entries carry the same provenance, scope, occurrence-time, and optional
confidence fields as candidates. New stores use schema version 3. Existing
stores are upgraded once and retain a pre-upgrade snapshot in `backups`; legacy
`user/direct` records become `global`, other legacy records without a scope are
marked `unassigned`, and existing accepted memories become `active`. Unknown
sources are rejected on new writes instead of being silently routed to project
memory. `structured_entry` sources must specify an explicit category.

Memory commit lifecycle:

```text
candidate -> validate -> backup -> apply -> vector_upsert -> cache_invalidate
```

Accepted-memory lifecycle:

```text
active --POST /memory/{id}/correct--> superseded + new active version
active --POST /memory/{id}/retract--> retracted
```

Both operations are intended only for explicit user-directed actions. The
current Memory UI provides a correction form and a second-step retraction
confirmation; the local prototype has no authenticated user identity, so the
API relies on its caller to honor that intent boundary. Correction requires a
non-empty replacement `content`; it keeps the prior evidence reference on the
new version and links the versions with `version_of` / `superseded_by`.
Retraction and supersession remove the prior item from recall, vector index and
cache, while keeping its record and source in the store. Retraction is
idempotent. Physical deletion and deletion of original source records are not
implemented by these endpoints. Markdown export remains readable, but import
cannot remove accepted memories or rewrite their content; callers must use the
explicit correction/retraction endpoints so the lifecycle state is preserved.

The current candidate states are `candidate`, `committed`, and `rejected`.
There is no `needs_confirmation` runtime state yet: no conflict detector
currently produces a structured conflict target and evidence. Candidates
remain subject to explicit commit/reject review. A future detector must not
mutate an active memory; conflict confirmation should use a separate, auditable
transition after the detector and evidence contract are defined.

### POST /memory/{memory_id}/correct

Request: `{"content":{"claim":"..."},"reason":"optional explanation"}`

Response: `{"status":"active","memory":{...}}`. A repeated identical
correction to an already superseded ID returns the same replacement. Other
attempts to mutate a non-active version return HTTP 409.

### POST /memory/{memory_id}/retract

Request: `{"reason":"optional explanation"}`

Response: `{"status":"retracted","memory":{...}}`. Repeating a retraction
returns the existing retracted memory.

### GET /memory/profile

Returns a derived, on-demand profile view from active Memory entries. This is a
read model only: it is not persisted as a second source of truth, does not call
an LLM, and does not promote entries between scopes. The view contains the
original structured claims with source references, timestamps, confidence, and
scope so that a later presentation layer can explain every item.

```json
{
  "schema_version": 1,
  "version": "sha256-of-profile-content",
  "generated_at": "2026-10-03T00:00:00",
  "core_profiles": [
    {
      "scope": {"kind": "global", "scenario_type": null, "project_id": null, "user_id": null},
      "memory_count": 1,
      "memories": [
        {
          "id": "memory-id",
          "source": "direct",
          "source_ref": {"kind": "manual", "record_id": "note-id"},
          "confidence": 0.9,
          "confidence_method": "user_confirmed",
          "content": {"claim": "prefers concise answers"},
          "status": "active"
        }
      ]
    }
  ],
  "scenario_profiles": [],
  "project_profiles": []
}
```

Groups are keyed by their exact scope dimensions, including `user_id`; project
profiles remain separate by project ID. `unassigned`, malformed-scope, and
non-active entries are omitted. `version` is a stable SHA-256 digest of the
profile content and is unchanged by `generated_at`; consumers can use it to
detect whether the derived view changed. An empty store returns empty profile
arrays. The endpoint has no authenticated-user filtering yet and must be
treated as a local prototype inspection endpoint, not a per-user access-control
boundary.

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

## Additional Implemented Endpoints

The frontend reads these endpoints directly. Mock fallback is used only when an
endpoint is unavailable.

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

Commits a memory candidate synchronously through the validation, backup,
apply, index, and cache lifecycle. Repeated commits return the same entry.

Response:

```json
{
  "status": "committed",
  "item": {}
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
  "status": "approved",
  "skill": {}
}
```

### GET /traces/{trace_id}

Returns trace detail for one chat turn.

Response:

```json
{
  "trace_id": "uuid",
  "input": "hello lifeos",
  "created": "2026-07-31T00:00:00",
  "events": []
}
```

### Additional actions

- `POST /memory/candidates/{candidate_id}/reject` marks a pending candidate rejected.
- `POST /skills/pending/{skill_id}/reject` removes a pending skill.
- `POST /entries/{entry_id}/memory-candidates` proposes a distilled Memory from a
  saved daily/phase plan or review. The caller must provide non-empty `content`,
  an explicit legacy `category`, and an explicit `scope`; the backend links the
  candidate to the structured entry ID, kind, revision, and entry date. It does
  not copy or summarize the source record automatically. Replaying the same
  proposal for the same entry revision returns the existing candidate.

Example request:

```json
{
  "content": { "claim": "学习时先做小例子有助于理解" },
  "category": "user",
  "scope": {
    "kind": "scenario",
    "scenario_type": "learning",
    "project_id": null
  }
}
```

This endpoint keeps original plan/review text in `StructuredStore`; the
candidate stores only the caller-supplied distilled content and a source
reference. The candidate still requires the existing user commit/reject step.
- `GET /permissions` currently returns `{ "requests": [] }` because persisted
  permission requests and execution resumption are not implemented.

## Planned Endpoint

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

- Use the implemented inspection endpoints for live state; retain mock fallback
  only for an unavailable backend.
- Do not block chat rendering on Global Agent processing.
- Use `trace_id` as the join key across chat messages, events, memory candidates, and trace details.
- Render permission confirmations as separate UI objects from skill candidates.
- Clearly distinguish current backend data from local preview/mock data.
