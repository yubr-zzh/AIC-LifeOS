<p align="center">
  <img src="tools/assets/claude3.png" width="128" alt="LifeOS">
</p>

<div align="center">
  <h1>LifeOS</h1>
  <p><b>A local-first personal agent OS that runs on your Windows machine.</b></p>
  <p>English · <a href="README.zh-CN.md">简体中文</a></p>
  <a href="https://github.com/yubr-zzh/AIC-LifeOS/stargazers"><img src="https://img.shields.io/github/stars/yubr-zzh/AIC-LifeOS?style=flat-square" alt="Stars"></a>
  <img src="https://img.shields.io/badge/version-2.2.0-blue?style=flat-square" alt="Version">
  <img src="https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-lightgrey?style=flat-square" alt="Platform">
  <img src="https://img.shields.io/badge/stack-Python%20%7C%20React%20%7C%20pywebview-green?style=flat-square" alt="Stack">
  <img src="https://img.shields.io/badge/tests-985%20cases-brightgreen?style=flat-square" alt="Tests">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue?style=flat-square" alt="License"></a>
</div>

---

**LifeOS** pairs a front-stage chat agent with a background global agent. The two share a reliable event bus, a two-phase memory store, a reflection engine, and a skill evolution loop. Version 2.2.0 ships as a Windows desktop app: a pywebview (WebView2) shell, an embedded Python backend, and a local agent bridge. Double-click the exe and it runs. All data stays on your machine.

## The problem it solves

Cloud assistants hold your notes, your schedule, and your chat history on someone else's server. LifeOS keeps all of it in a local SQLite store under `%USERPROFILE%\lifeOS`. The planner runs inside the app. The agents run on your machine, in folders you marked as trusted. You approve every file write and every command before it happens.

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

## Features

| Feature | What you get |
| --- | --- |
| Double-click and go | Install, double-click, and work in one window. Closing the window stops every background process. |
| Your data stays local | Accounts, memories, and logs live on your PC. Remember-me lasts 30 days with system-level encryption. |
| Put an agent to work | Pick a local agent and point it at a folder. It reads files, edits code, and runs commands there. |
| You approve every action | The agent shows you each file edit and each command first. It acts only after you click Allow. |
| Memory across sessions | Chats and agent results settle into memory. Your next question carries that context. |
| Today view | Check off today's plan item by item. 20 reminders arrive on schedule. Agent results and to-dos land in the inbox. |
| Plan and review | Write daily and phase plans in markdown. Reviews inherit plan items, and history opens in one click. |
| Year in one graph | A contribution-style graph aggregates your plans, reviews, diary, and notes for the year. |
| Chat workspace | Collapse the sidebars and drag to resize the panes. Copy any message, rename sessions, attach up to 3 files. |
| Live agent status | The bottom panel tracks agent progress with up to 20 items. Draft your next message even while offline. |

## Install

Installation steps:

1. Run `LifeOS-Setup-2.2.0.exe`.
2. Follow the wizard. Keep the default options.
3. Start LifeOS from the Start menu or the desktop shortcut.
4. Create your local account at first launch.

Data rules:

- User data lives in `%USERPROFILE%\lifeOS`.
- First launch copies legacy data from the old AppData folder. The original stays as a backup.
- Uninstall asks you first. It deletes data only after you confirm.

Portable use: run `dist\LifeOS\LifeOS.exe` directly, with no installer.

## Repository layout

```text
lifeos/
  desktop/          # desktop shell entry: single instance, ports, shutdown order
  api/              # main service: static hosting, login gate, tunnel gateway, devices, users
  bridge/           # local agent process: adapters, arbitration, redaction, recovery
  agent/            # chat agent, global agent, planning, execution
  memory/           # two-phase memory write: recall, candidates, lifecycle
  skills/           # skill registry, candidate detection, effect evaluation
  reflection/       # background reflection engine
  event/            # local reliable event queue
  security/         # permission review
  llm/              # unified LLM interface
  mcp/              # MCP server registry and adapters
frontend/           # React + TypeScript + Vite console (npm run build feeds dist)
tools/              # build_exe.ps1, lifeos.spec, lifeos-setup.iss, verify_*.py
tests/              # full backend test suite
docs/               # architecture and API documents
```

## Build from source

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

The build produces `dist\LifeOS\LifeOS.exe` (onedir) and `dist\LifeOS-Setup-2.2.0.exe`.

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
# backend, about 855 cases
.venv\Scripts\python -m pytest tests -q
.venv\Scripts\python -m compileall lifeos

# frontend, about 130 cases, plus typecheck
cd frontend
npm test
npm run typecheck
```

Three backend files (`tests/test_codex_lc_ji_cheng.py`, `test_liu_xing_lc_ji_cheng.py`, `test_pi_lc_ji_cheng.py`) call real external endpoints. Exclude them with `--ignore` when you work offline or in CI.

## Documentation

- [docs/api-contract.md](docs/api-contract.md), frontend and backend API alignment
- [docs/agent-memory-integration.md](docs/agent-memory-integration.md), how agent results enter memory
- [docs/memory-module-handoff.md](docs/memory-module-handoff.md), memory module handoff
- [docs/memory-provider-boundaries.md](docs/memory-provider-boundaries.md), memory provider boundaries
- [docs/lifeos-workflow-and-memory-architecture.md](docs/lifeos-workflow-and-memory-architecture.md), workflow and memory architecture
- [docs/team-module-integration-plan.md](docs/team-module-integration-plan.md), team module integration plan

## Runtime notes

- Runtime data goes to `%USERPROFILE%\lifeOS` for installs and `./lifeOS/` for source runs. The first start copies legacy AppData data and keeps the old folder as a backup.
- The main service listens on 8765 and probes upward to 8790 when busy. Test leftovers can hold ports 8766 to 8770; end the `python -m lifeos.bridge.run` process to free them.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). It covers the dev loop, the test commands, and the commit message convention.

## License

MIT. See [LICENSE](LICENSE).
