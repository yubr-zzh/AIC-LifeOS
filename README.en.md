<p align="center">
  <img src="tools/assets/claude3.png" width="128" alt="LifeOS">
</p>

<div align="center">
  <h1>LifeOS</h1>
  <p><b>A personal agent OS that remembers, acts, and truly knows you.</b></p>
  <p>English · <a href="README.md">简体中文</a></p>
  <a href="https://github.com/yubr-zzh/AIC-LifeOS/stargazers"><img src="https://img.shields.io/github/stars/yubr-zzh/AIC-LifeOS?style=flat-square" alt="Stars"></a>
  <img src="https://img.shields.io/badge/version-2.2.4-blue?style=flat-square" alt="Version">
  <img src="https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-lightgrey?style=flat-square" alt="Platform">
  <img src="https://img.shields.io/badge/stack-Python%20%7C%20React%20%7C%20pywebview-green?style=flat-square" alt="Stack">
  <img src="https://img.shields.io/badge/tests-1100%2B%20cases-brightgreen?style=flat-square" alt="Tests">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue?style=flat-square" alt="License"></a>
</div>

---

**LifeOS** is a personal agent operating system that lives on your machine. It turns AI assistants from one-off question answering into long-term partners that remember, act, and build a profile of you so they know you better. It covers memory, execution, and review.

**The problem**: Multi-session AI tools make you re-explain the background every time, and a route you already worked out in the current session has to be rediscovered next time. General assistants usually cannot tell "the conclusion we hold now" from "a stale conclusion"; and most current AI assistants cannot build a long-term profile of you. Ask again after a while what you are doing or what you did before, and they do not really know.

**The approach**: LifeOS connects a front-stage chat agent with a background reflection agent over a reliable local event bus. Memory is kept in four layers: raw evidence, project continuity, atomic memories, and a global profile. Memory is scoped per project instead of pooled into one bucket. Writing to memory goes through "candidate, then a human approves it", and every memory can be corrected, retracted, or expired. Planning and review happen inside the app.

![LifeOS today](tools/assets/lifeos-home.png)

## Install

- First choice: download `LifeOS-Setup-2.2.4.exe` from the release.

    Installation steps:
  1. Run `LifeOS-Setup-2.2.4.exe`.
  2. Follow the wizard. Keep the default options.
  3. Start LifeOS from the Start menu or the desktop shortcut.
  4. Create your local account at first launch.

----
- Build it yourself:

```bash
# 1) get the code and install dependencies
git clone https://github.com/yubr-zzh/AIC-LifeOS.git && cd AIC-LifeOS

# 2) build the frontend (produces frontend/dist)
cd frontend && npm install && npm run build && cd ..

# 3) package the Windows desktop app (produces dist\LifeOS\LifeOS.exe)
python -m PyInstaller --noconfirm --clean tools/lifeos.spec
```
----
- Just testing, no install: unzip `dist\LifeOS` and double-click `LifeOS.exe`.
----
- Data storage:
  User data lives in `%USERPROFILE%\lifeOS`.
  First launch copies legacy data from the old AppData folder. The original folder stays as a backup.


## How it works

```text
LifeOS.exe (pywebview desktop shell, single instance)
  └─ lifeos.api.server (main service, port 8765 with auto-probe)
       ├─ static hosting of frontend/dist + SPA fallback (same origin, no CORS)
       ├─ login gate: local accounts + PBKDF2 + HttpOnly session cookie + CSRF
       └─ bridge subprocess (lifeos.bridge.run)
            └─ agent adapters (claude_code and more, via claude-agent-sdk)

Core data flow:
user input → chat agent (memory recall → LLM/tools) → reply
           → reliable event bus → global agent → reflection
           → memory candidates → security review → persist
```

## What makes LifeOS different

**Think before it acts:** Before the agent writes a file or runs a command, it puts the action in front of you. You nod, and only then does it move.

**Time teaches it your heart:** Let the machine come to know you over the days. Chats settle into memory, memory feeds reflection, and reflection grows skills. Today's items get checked today, phases carry plans and reviews, and one graph gathers the whole year at a glance.

**Keep your data close:** Notes, schedules, code, and conversations all stay in the local store under `%USERPROFILE%\lifeOS`, on no one else's server.

### Daily use

**Walk in.** Double-click to run, then create a local account at first launch. Tick remember-me for 30 days of password-free login, with credentials stored under system-level encryption.

**Assign work.** The Agent page lists every local agent as a card, with status, version, and a connect checklist. Pick one and point it at a folder. It reads files, edits code, and runs commands there, and shows you each action first. A detail drawer shows Bridge health, and you can re-detect agents at any time.

**Talk.** Every exchange stays in one turn block: your question, then the answer. Replies render Markdown and math. Tool calls fold to one line. Read-only calls shrink to plain text once they finish. Commands and file writes keep a line you can click open for input and output. Failures and pending approvals stay open until you handle them. The agent's reasoning shows on its own line. A folded strip under each turn lists the files and search patterns that turn touched. Hover a turn to copy or retry it. Text streams in. An over-long reply splits into several messages, with nothing lost. Press Enter while the agent works, and the message queues until the turn ends. Question and permission boxes still pop up when the agent needs a choice or an approval, and the agent keeps running once you answer. Earlier chats and agent results settle into memory, and the main model reads each agent reply in full. Copy any message, rename sessions, and attach up to 3 files per message, 200 KB each.

**Today.** Check off today's plan item by item. 20 reminder groups arrive on schedule, and agent results and to-dos land in the Inbox at the top right. Collapse the sidebar; drag to widen the chat pane.

**Over the year.** Write daily and phase plans in Markdown. The editor takes slash commands for task lists, bullets, numbered lists, headings, and quotes. Reviews inherit plan items. The year work calendar gathers plans, reviews, diary, and notes into one contribution-style graph at a glance.

### Tips

- Closing the window stops every background process. Nothing lingers.
- Draft your message even when no agent is connected.
- Uninstall asks first; your data goes only after you confirm.
- Accounts, memories, and logs live in `%USERPROFILE%\lifeOS`. Back up that one folder and you have it all.

## Repository layout

```text
lifeos/
  desktop/          # desktop shell entry: single instance, ports, shutdown order
  api/              # main service: static hosting, login gate, tunnel gateway, devices, users
  bridge/           # local agent process: adapters, arbitration, redaction, recovery
  agent/            # chat agent, global agent, planning, execution
  memory/           # two-phase memory write: recall, candidates, lifecycle, governance, graph and temporal views
  skills/           # skill registry, candidate detection, effect evaluation
  reflection/       # background reflection engine
  event/            # local reliable event queue
  security/         # permission review
  llm/              # unified LLM interface
  mcp/              # MCP server registry and adapters
frontend/           # React + TypeScript + Vite console (npm run build feeds dist)
tools/              # build_exe.ps1, lifeos.spec, lifeos-setup.iss, verify_*.py
tests/              # full backend test suite
datasets/           # memory governance fixtures and LongMemEval-S templates
docs/               # architecture and API documents
```

## Build from source when developing or contributing

You need Windows 10 or 11 plus:

- Python 3.11 or newer (tested on 3.13)
- Node.js, for the frontend build
- Inno Setup 6, only if you want the installer

```powershell
# 1) backend virtualenv
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

# 2) frontend dependencies
cd frontend
npm ci
cd ..

# 3) one-shot build: npm run build → PyInstaller
powershell -ExecutionPolicy Bypass -File tools\build_exe.ps1

# 4) installer, optional
ISCC.exe tools\lifeos-setup.iss
```

The build produces `dist\LifeOS\LifeOS.exe` (onedir) and `dist\LifeOS-Setup-2.2.4.exe`.

## Development

```powershell
# backend (LIFEOS_HOME sets the data root, default ./lifeOS/)
.venv\Scripts\python -m lifeos.api.server

# frontend dev server on 5173, vite proxies /api to the backend
cd frontend && npm run dev

# desktop-link smoke test: /api normalization, direct proxy, bridge/start
.venv\Scripts\python tools\verify_desktop_link.py
```

## Tests

```powershell
# backend, about 930 cases
.venv\Scripts\python -m pytest tests -q
.venv\Scripts\python -m compileall lifeos

# frontend, about 190 cases, plus typecheck
cd frontend
npm test
npm run typecheck
```

Three backend files (`tests/test_codex_lc_ji_cheng.py`, `test_liu_xing_lc_ji_cheng.py`, `test_pi_lc_ji_cheng.py`) call real external endpoints. Exclude them with `--ignore` when you work offline or in CI.

## Documentation

- [docs/api-contract.md](docs/api-contract.md), frontend and backend API alignment
- [docs/agent-memory-integration.md](docs/agent-memory-integration.md), how agent results enter memory
- [docs/memory-module-handoff.md](docs/memory-module-handoff.md), memory module handoff
- [docs/memory-design-principles.md](docs/memory-design-principles.md), memory design principles
- [docs/memory-provider-boundaries.md](docs/memory-provider-boundaries.md), memory provider boundaries
- [docs/lifeos-workflow-and-memory-architecture.md](docs/lifeos-workflow-and-memory-architecture.md), workflow and memory architecture
- [docs/team-module-integration-plan.md](docs/team-module-integration-plan.md), team module integration plan
- [docs/frontend-rewrite-issues.md](docs/frontend-rewrite-issues.md), frontend rewrite issue log
- [docs/tencentdb-approved-atomic-create-proposal.md](docs/tencentdb-approved-atomic-create-proposal.md), TencentDB atomic create proposal

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). It covers the dev loop, the test commands, and the commit message convention.

## License

MIT. See [LICENSE](LICENSE).
