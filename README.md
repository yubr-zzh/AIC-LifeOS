# LifeOS Agent

LifeOS Agent is a personal agent operating-system prototype built around a foreground Chat Agent and an asynchronous Global Agent.

The current repository focuses on the core runtime architecture, not the older demo product shell. Its center of gravity is a reliable agent data flow:

```text
User Input
-> Chat Agent
-> Memory Retrieval
-> LLM / Tool Calling
-> User Response
-> Reliable Event Bus
-> Global Agent
-> Reflection
-> Memory Candidate
-> Security Review
-> Memory / Skill Persistence
```

## Core Ideas

- **Foreground Chat Agent**: the fast path. It behaves closer to Claude Code or Hermes-style direct tool calling: retrieve relevant memory, call the LLM/tools, return a response, then publish a durable event.
- **Reliable Event Bus**: the foreground/background boundary. Events are persisted locally so background work is auditable and retryable.
- **Background Global Agent**: the maintenance path. It consumes typed events, runs reflection, proposes memory updates, detects reusable skill candidates, and performs security review.
- **Two-phase Memory Writes**: long-term memory is not written directly. It flows through candidate creation, validation, backup, apply, vector upsert, and cache invalidation.
- **Split Permission Model**: tool execution confirmation is separate from skill installation or persistence confirmation.

## Repository Layout

```text
lifeos/
  agent/
    runtime.py              # Composition root and Global Agent runtime
    chat/runtime.py         # Foreground Chat Agent
    planner/planner.py      # Lightweight planning helper
    executor/executor.py    # Chat/tool execution path
  api/server.py             # Minimal HTTP API
  event/bus.py              # Reliable local event queue
  memory/
    manager.py              # Memory facade
    retriever.py            # Query-time retrieval
    updater.py              # Candidate creation and apply
    lifecycle.py            # Validate/backup/vector/cache lifecycle
  llm/client.py             # Unified LLM interface, mock provider by default
  reflection/engine.py      # Background reflection
  security/permission.py    # Permission review
  skills/
    registry.py             # Approved/pending skill registry
    detector.py             # Skill candidate detection
    evaluator.py            # Skill result evaluation
  mcp/
    registry.py             # MCP server registry
    adapter.py              # MCP tool adapter
  trace/system.py           # Trace records

docs/
  frontend-ui-prompt.md     # Prompt for implementing the LifeOS UI
  frontend-ui-prompt.docx   # Word version for sharing
  api-contract.md           # Frontend/backend API alignment
  api-contract.docx         # Word version for sharing

tools/
  md_to_docx.py             # Markdown-to-DOCX conversion helper
```

## Quick Start

Run the minimal API server:

```bash
python -m lifeos.api.server
```

Default backend URL:

```text
http://127.0.0.1:8765
```

Send a chat message:

```bash
curl -X POST http://127.0.0.1:8765/chat \
  -H "Content-Type: application/json" \
  -d "{\"message\":\"hello lifeos\"}"
```

Run one background Global Agent polling cycle:

```bash
curl -X POST http://127.0.0.1:8765/background/run-once \
  -H "Content-Type: application/json" \
  -d "{}"
```

## Current API

### `POST /chat`

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

Side effect: publishes a durable `conversation.completed` event.

### `POST /background/run-once`

Request:

```json
{}
```

Response:

```json
{
  "processed": ["event-id"]
}
```

See `docs/api-contract.md` for the full frontend/backend alignment document.

## Frontend Direction

The intended UI is an agent console or workbench, not a marketing page. The main screen should be a Chat Workspace with operational panels for runtime state, event queue, memory lifecycle, skill candidates, permissions, and trace details.

See `docs/frontend-ui-prompt.md` for a ready-to-use implementation prompt.

## Validation

Basic syntax check:

```bash
python -m compileall lifeos
```

## Runtime State

Local runtime files are written under `.lifeos/` by default and are ignored by git. This includes durable events, memory state, and skill registry state.
