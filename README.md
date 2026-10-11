# LifeOS 桌面版（软件 v1.0）

LifeOS 是一个本地优先的个人智能体操作系统：前台 Chat Agent 与后台 Global Agent 协作，配合可靠事件总线、两阶段记忆写入、反思引擎与技能进化。软件 v1.0 以 **Windows 桌面应用**形态交付——pywebview（WebView2）壳 + 内嵌后端 + 本地 Agent bridge，双击即用，数据全部留在本机。

```text
LifeOS.exe（pywebview 桌面壳，单实例）
  └─ lifeos.api.server（主服务，8765 起自动探测端口）
       ├─ 静态托管 frontend/dist + SPA fallback（打包态同源，无 CORS）
       ├─ 登录闸：本地账户 + PBKDF2 + HttpOnly 会话 Cookie + CSRF
       └─ bridge 子进程（lifeos.bridge.run）
            └─ Agent 适配器（claude_code 等，经 claude-agent-sdk 调本机 CLI）

核心数据流：
用户输入 → Chat Agent（记忆检索 → LLM/工具）→ 响应
        → 可靠事件总线 → Global Agent → 反思 → 记忆候选 → 安全审查 → 持久化
```

## 功能特性

- **桌面应用**：单实例锁、端口自动探测、关窗后自动停 bridge 与 claude 子进程。
- **登录体系**：本地账户（PBKDF2 600k 轮），会话 Cookie + CSRF 防线；首次使用直接创建账户。
- **本地 Agent**：bridge 独立进程 + 信任根目录确认 + 目录选择对话框；claude CLI「检测本机优先、捆绑兜底」双策略。
- **Agent 进化闭环**：事件总线 → 反思引擎 → 记忆候选（两阶段写入）→ 技能候选检测与评估 → MCP 工具接入。

## 快速使用

- **安装器**：运行 `LifeOS-Setup-x.x.exe`（Inno Setup 产物），装后从开始菜单/桌面启动；用户数据在 `%LOCALAPPDATA%\LifeOS`，卸载时可选保留。
- **免安装**：直接运行 `dist\LifeOS\LifeOS.exe`。

## 从源码构建

环境要求（Windows 10/11）：

- Python 3.11+（开发机实测 3.13）
- Node.js（构建前端）
- Inno Setup 6（可选，出安装器）
- 原生 `claude.exe`（可选但推荐：SDK 拒绝 npm 的 `.cmd` 垫片，打包态需原生 exe 捆绑兜底）

```powershell
# 1) 后端虚拟环境
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

# 2) 前端依赖
cd frontend
npm ci
cd ..

# 3) 指定要捆绑的原生 claude.exe（可选，未设则运行时走 PATH 探测）
$env:LIFEOS_CLAUDE_SRC = "C:\path\to\claude.exe"

# 4) 一键打包：npm run build → PyInstaller → 捆绑 claude.exe
powershell -ExecutionPolicy Bypass -File tools\build_exe.ps1

# 5)（可选）编译安装器
ISCC.exe tools\lifeos-setup.iss
```

产物：`dist\LifeOS\LifeOS.exe`（onedir）与 `dist\LifeOS-Setup-0.1.0.exe`（安装器）。

## 开发调试

```powershell
# 后端（LIFEOS_HOME 指定数据根，默认 .lifeos/）
.venv\Scripts\python -m lifeos.api.server

# 前端热更（5173，vite 代理 /api 到后端）
cd frontend && npm run dev

# 桌面链路冒烟：/api 归一 + 直连代理 + bridge/start
.venv\Scripts\python tools\verify_desktop_link.py
```

## 测试

```powershell
.venv\Scripts\python -m pytest tests -q
.venv\Scripts\python -m compileall lifeos
```

全量约 855 个用例。注意：`tests/test_codex_lc_ji_cheng.py`、`test_liu_xing_lc_ji_cheng.py`、`test_pi_lc_ji_cheng.py` 会访问真实外网端点，离线或 CI 环境请加 `--ignore` 排除。

## 目录结构

```text
lifeos/
  desktop/          # 桌面壳入口（单实例/端口/装配/关停时序）
  api/              # 主服务：静态托管、登录闸、隧道网关、设备、用户
  bridge/           # 本地 Agent 进程：适配器、仲裁、脱敏、恢复
  agent/            # Chat Agent / Global Agent / 规划 / 执行
  memory/           # 两阶段记忆写入：检索、候选、生命周期
  skills/           # 技能注册表、候选检测、效果评估
  reflection/       # 后台反思引擎
  event/            # 本地可靠事件队列
  security/         # 权限审查
  llm/              # 统一 LLM 接口
  mcp/              # MCP Server 注册表与适配
frontend/           # React + TypeScript + Vite 控制台（npm run build 产 dist）
tools/              # build_exe.ps1 / lifeos.spec / lifeos-setup.iss / verify_*.py
tests/              # 后端全量测试
docs/               # 架构与 API 文档
```

## 文档索引

- [docs/api-contract.md](docs/api-contract.md) — 前后端 API 对齐
- [docs/agent-memory-integration.md](docs/agent-memory-integration.md) — Agent 执行结果进入记忆的流程
- [docs/memory-module-handoff.md](docs/memory-module-handoff.md) — 记忆模块交接
- [docs/memory-provider-boundaries.md](docs/memory-provider-boundaries.md) — 记忆 Provider 边界
- [docs/lifeos-workflow-and-memory-architecture.md](docs/lifeos-workflow-and-memory-architecture.md) — 工作流与记忆架构
- [docs/team-module-integration-plan.md](docs/team-module-integration-plan.md) — 团队模块集成方案

## 注意事项

- 运行时数据写入 `.lifeos/`（仓库内开发态）或 `%LOCALAPPDATA%\LifeOS`（打包态），均已忽略/不随安装目录。
- 打包若未捆绑 claude.exe，运行时从 PATH 探测；npm 安装的 `.cmd` 垫片会被 SDK 拒绝，务必用原生 exe。
- 主服务默认 8765，被占时向上探测至 8790；测试残留的 bridge 进程可能占住 8766-8770，可结束 `python -m lifeos.bridge.run` 进程清理。
