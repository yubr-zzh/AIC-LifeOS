# Contributing to LifeOS

Thanks for your interest. This document covers the dev setup, the test commands, the commit convention, and the release process.

## Set up a dev environment

You need Windows 10 or 11, Python 3.11 or newer, and Node.js.

```powershell
git clone https://github.com/yubr-zzh/AIC-LifeOS
cd AIC-LifeOS

# backend virtualenv
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

# frontend dependencies
cd frontend
npm ci
cd ..
```

## The dev loop

```powershell
# backend (LIFEOS_HOME sets the data root, default ./lifeOS/)
.venv\Scripts\python -m lifeos.api.server

# frontend dev server on 5173, vite proxies /api to the backend
cd frontend && npm run dev

# desktop-link smoke test after backend changes
.venv\Scripts\python tools\verify_desktop_link.py
```

The frontend lives in `frontend/src`. Panels sit in `frontend/src/panels`, the transport layer and types in `frontend/src/api`. The backend lives in `lifeos/`, split by module: `api` for the main service, `bridge` for the local agent process, `agent` and `memory` for the core loop.

## Run the tests before you commit

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

A change is ready when all tests pass and the typecheck stays clean. When you fix a bug, add a regression test next to it.

## Commit messages

The repo uses conventional commits with a Chinese summary:

```
fix(ui): 本机Bridge卡标题改为启动桥接
chore(release): 发布 2.0.8，优化对话交互与数据目录
```

Common types: `fix`, `feat`, `docs`, `chore`, `refactor`, `test`. One commit carries one logical change. Keep diffs minimal.

## Documentation is bilingual

`README.md` and `CONTRIBUTING.md` are English. `README.zh-CN.md` and `CONTRIBUTING.zh-CN.md` are Simplified Chinese. When you change one, update its twin in the same commit.

## Release process

Version numbers live in exactly three places:

1. `frontend/package.json`, the `version` field
2. `frontend/package-lock.json`, synced with `npm install --package-lock-only`
3. `tools/lifeos-setup.iss`, the `MyAppVersion` define

To cut a release:

```powershell
# bump the version in all three places, then:
powershell -ExecutionPolicy Bypass -File tools\build_exe.ps1
ISCC.exe tools\lifeos-setup.iss
```

The build writes `dist\LifeOS\` and `dist\LifeOS-Setup-X.Y.Z.exe`. Delete the previous installer from `dist\` so only one version ships. The repo commits `dist\` and `build\` on purpose, so the release commit carries the rebuilt artifacts:

```
chore(release): 发布 2.2.0，重写双语文档并重建打包产物
```
