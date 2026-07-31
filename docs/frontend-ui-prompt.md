# LifeOS Frontend UI Implementation Prompt

You are building the first production-quality frontend for LifeOS, a personal agent operating system. Build the actual usable app interface, not a landing page.

## Product Context

LifeOS has two agents:

- Chat Agent: the foreground, low-latency path. It behaves like Claude Code or Hermes-style direct tool calling. It retrieves memory, calls the LLM/tools, returns a response, then publishes a durable event.
- Global Agent: the background maintainer. It consumes reliable events, runs reflection, proposes memory updates, detects reusable skill candidates, performs security review, and updates long-term state.

The frontend should make this architecture visible without becoming a diagram-only dashboard. The main user experience is still chat, but the user should be able to see the data flow, background queue, memory lifecycle, skill candidates, and permission confirmations.

## Desired App Shape

Create a single-page web app with these main areas:

1. Chat Workspace
   - Primary center panel.
   - User sends messages to the Chat Agent.
   - Assistant responses stream or appear in a polished message timeline.
   - Show the `trace_id` for each turn in a compact, copyable affordance.
   - If `tool_calls` exist, render them as expandable execution cards with status.

2. Runtime Rail
   - A compact side panel showing foreground/background state.
   - Show Chat Agent status: idle, thinking, tool calling, responded.
   - Show Event Bus status: queued, processing, failed, done.
   - Show Global Agent status: polling, reflecting, writing memory, detecting skills.

3. Data Flow View
   - A visual pipeline matching this flow:
     User Input -> Chat Agent -> Memory Retrieve -> LLM/Tool Call -> Response -> Event Bus -> Global Agent -> Reflection -> Memory Candidate -> Security Review -> Commit/Cache Invalidate.
   - Use it as an operational view, not a decorative hero.
   - Highlight the active step for the latest trace.

4. Memory Panel
   - Tabs for User, Project, Feedback, Candidates, Backups.
   - Candidates should show lifecycle states:
     candidate -> validated -> backed_up -> applied -> vector_upserted -> cache_invalidated.
   - Provide buttons for future actions: approve, reject, inspect diff. Disable them if the backend endpoint is not available yet.

5. Skills Panel
   - Approved skills and pending skill candidates.
   - Pending candidates show source, description, risk, review decision, and whether user confirmation is required.
   - Separate execution permissions from installation/persistence permissions.

6. Event Queue Panel
   - Show durable events with fields:
     id, type, status, attempts, trace_id, created_at, updated_at, error.
   - Failed events should be visually distinct and easy to inspect.
   - Include a "Run background once" control that calls `POST /background/run-once`.

## Design Direction

Use a dense, operational, agent-console aesthetic. This is a workbench for inspecting an intelligent system, not a SaaS marketing page.

Design principles:

- Start with the actual app screen, not a hero.
- Keep layout dense but calm. Use panels, rails, tables, timelines, and inspector drawers.
- Avoid generic purple gradients, big rounded marketing cards, and decorative blobs.
- Use clear status colors:
  - pending: amber
  - processing: blue
  - done: green
  - failed/blocked: red
  - requires confirmation: violet or magenta accent
- Use icons for actions such as send, refresh, copy, inspect, approve, reject, run, pause.
- Use compact buttons and tooltips.
- No large explanatory text blocks inside the UI. The interface should be self-evident.

Recommended visual language:

- Background: deep graphite or ink, with subtle grid or terminal-like texture.
- Panels: thin borders, low-radius corners, crisp separators.
- Typography: use a readable UI font plus a monospaced font for IDs, traces, event names, and payloads.
- Motion: subtle state transitions, active pipeline pulses, message arrival animation, queue row status change animation.

## Frontend Behavior

Use the current API contract:

- `POST /chat`
- `POST /background/run-once`

Because many inspection endpoints are not implemented yet, build the frontend with a typed API client and mock fallback data for:

- event queue list
- memory store
- skill registry
- trace detail
- permission confirmations

Make the mock mode visually marked as "local preview data" but keep the app behavior realistic.

When `/chat` succeeds:

1. Append the user message.
2. Append the assistant response.
3. Store `trace_id` in the current trace state.
4. Render returned `tool_calls`.
5. Optimistically append a `conversation.completed` pending event in the Event Queue Panel.

When `/background/run-once` succeeds:

1. Mark processed event IDs as done.
2. Add or refresh mock memory candidate/reflection state if no real inspection endpoint exists.
3. Highlight Global Agent activity briefly.

## API Base

Default backend:

```text
http://127.0.0.1:8765
```

Requests and responses are JSON.

## Implementation Requirements

- Build a real usable frontend, preferably React + TypeScript.
- Create a small API client layer instead of calling `fetch` directly inside components.
- Define TypeScript types for ChatResponse, EventRecord, MemoryCandidate, SkillCandidate, PermissionReview, and TraceRecord.
- Handle loading, empty, success, and error states.
- Make the app responsive:
  - Desktop: chat center, runtime/data panels around it.
  - Mobile: chat first, panels behind tabs or drawers.
- Include local mock data for unavailable endpoints.
- Keep components organized by domain: chat, events, memory, skills, trace, runtime.

## Current Backend Contract

`POST /chat`

Request:

```json
{
  "message": "hello lifeos"
}
```

Response:

```json
{
  "trace_id": "uuid",
  "response": "LifeOS mock response: hello lifeos",
  "tool_calls": []
}
```

`POST /background/run-once`

Request:

```json
{}
```

Response:

```json
{
  "processed": ["event-id-1"]
}
```

## Future Endpoints To Design Around

The UI should be ready for these future endpoints, but must not break if they are missing:

- `GET /events`
- `GET /memory`
- `GET /skills`
- `GET /traces/{trace_id}`
- `POST /memory/candidates/{candidate_id}/commit`
- `POST /skills/pending/{skill_id}/approve`
- `POST /permissions/{request_id}/confirm`

Use mock fallback until implemented.

