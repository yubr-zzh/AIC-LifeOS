# LifeOS Agent Console

The frontend workbench for the [LifeOS Agent](../README.md) core. A dark
operational agent-console, not a SaaS landing page. It surfaces the
foreground Chat Agent, the reliable Event Bus, and the background
Global Agent side-by-side so the data flow is visible, not hidden.

## Quick Start

Start the Python backend (terminal A):

```bash
cd ..  # back to repo root
python -m lifeos.api.server
```

Then in terminal B:

```bash
npm install
npm run dev
```

Open http://127.0.0.1:5173.

Vite proxies `/api/*` to the Python backend at `http://127.0.0.1:8765`,
so the frontend can use a relative `/api` base in both dev and production.

For a production-style check:

```bash
npm run build
npm run preview
```

## What you get

- **Chat Workspace** — send messages to `POST /chat`, see the assistant
  reply, copy `trace_id`, expand `tool_calls` as execution cards.
- **Runtime Rail** — compact panel with Chat Agent status, Event Bus
  counts, Global Agent activity, and the current data-mode badge.
- **Data Flow View** — 11-stage pipeline (User Input -> Chat Agent ->
  Memory Retrieve -> LLM/Tool -> Response -> Event Bus -> Global Agent
  -> Reflection -> Memory Candidate -> Security Review -> Commit).
  The active stage lights up; visited stages stay tinted.
- **Event Queue** — durable `.lifeos/events.json` rows with status,
  type, attempts, timestamp; click a `trace` chip to open the trace.
- **Memory Panel** — five tabs (User / Project / Feedback /
  Candidates / Backups). Candidates show the lifecycle stages
  `candidate -> validated -> backed_up -> applied -> vector_upserted
  -> cache_invalidated`. Approve / Reject buttons call the future
  `POST /memory/candidates/{id}/commit`.
- **Skills Panel** — Approved + Pending candidates, risk pills,
  review decision badge. Approve / Reject buttons call the future
  `POST /skills/pending/{id}/approve`.
- **Trace Inspector** — opens when you click a trace chip anywhere.
- **Permissions Panel** — split between **tool execution** and
  **skill installation** confirmations; resolves via the future
  `POST /permissions/{id}/confirm`.
- **Top Bar** — data-mode badge (`live` vs `local preview`) is the
  single source of truth for "are you seeing real backend data or
  mock fallback?".

## Endpoints

The backend currently implements two endpoints. Everything else is
read through a typed client with **mock fallback**, labelled as
`local preview` in the UI.

| Endpoint | Status | Frontend behavior |
| --- | --- | --- |
| `POST /chat` | implemented | live call, no fallback |
| `POST /background/run-once` | implemented | live call, no fallback |
| `GET /events` | not implemented | 404 -> mock events |
| `GET /memory` | not implemented | 404 -> mock memory |
| `GET /skills` | not implemented | 404 -> mock skills |
| `GET /traces/{trace_id}` | not implemented | 404 -> mock trace |
| `GET /permissions` | not implemented | 404 -> mock permissions |
| `POST /memory/candidates/{id}/commit` | not implemented | button is present, call returns 404 (UI labels this) |
| `POST /skills/pending/{id}/approve` | not implemented | button is present, call returns 404 (UI labels this) |
| `POST /permissions/{id}/confirm` | not implemented | button is present, call returns 404 (UI labels this) |

When `POST /background/run-once` returns `processed: ["…"]`, the
frontend marks the matching event rows as `done` and the Global Agent
status pill cycles through `polling -> reflecting -> writing memory
-> detecting skills -> idle`. Optimistic events generated from chat
turns are also marked done when the server reports `processed`
without an explicit ID list.

## Visual direction

Dark industrial agent-console. Deep graphite background with a
subtle grid texture (no marketing blobs / gradients). Status colors
match the existing backend event states:

- pending — amber
- processing — blue
- done — green
- failed — red
- requires_confirmation — violet
- idle — neutral gray

Compact monospace labels, thin borders, low-radius corners, status
pills with leading dots, mono IDs that are click-to-copy.

## Project layout

```text
frontend/
  index.html
  package.json
  tsconfig.json / tsconfig.app.json / tsconfig.node.json
  vite.config.ts
  src/
    main.tsx            # entry
    App.tsx             # layout, mobile/desktop switch
    api/
      types.ts          # shared TS types
      client.ts         # typed API client with mock fallback
      mock.ts           # mock data for not-yet-implemented endpoints
    state/
      store.ts          # useReducer-based store + side effects
    components/
      Panel.tsx         # generic panel chrome
      StatusPill.tsx
      SourceBadge.tsx   # live / local preview badge
      CopyId.tsx        # click-to-copy ID
      Icons.tsx         # inline SVG icons
    panels/
      TopBar.tsx
      ChatPanel.tsx
      RuntimeRail.tsx
      DataFlowView.tsx
      EventsPanel.tsx
      MemoryPanel.tsx
      SkillsPanel.tsx
      PermissionsPanel.tsx
      TracePanel.tsx
    styles/
      global.css        # design tokens + utilities
```

## Known gaps

- `GET /events`, `GET /memory`, `GET /skills`, `GET /traces/{id}`,
  `GET /permissions` are all 501/404 in the current Python backend.
  The frontend falls back to mock data and clearly labels it
  `local preview` per the data-mode badge in the top bar.
- `POST /memory/candidates/{id}/commit`,
  `POST /skills/pending/{id}/approve`,
  `POST /permissions/{id}/confirm` are wired into the UI but the
  backend does not implement them. Approve / Reject currently
  mutate local store state only; once the endpoints exist, the
  optimistic actions can be replaced with real `fetch` calls
  from `src/api/client.ts`.
- The trace detail view shows preview data because the backend
  `TraceSystem` stores records in process memory only; there is no
  `GET /traces/{id}` endpoint yet.
