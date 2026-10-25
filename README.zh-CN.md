<p align="center">
  <img src="tools/assets/claude3.png" width="128" alt="LifeOS">
</p>

<div align="center">
  <h1>LifeOS</h1>
  <p><b>本地优先的个人智能体操作系统，运行在你的 Windows 电脑上。</b></p>
  <p><a href="README.md">English</a> · 简体中文</p>
  <a href="https://github.com/yubr-zzh/AIC-LifeOS/stargazers"><img src="https://img.shields.io/github/stars/yubr-zzh/AIC-LifeOS?style=flat-square" alt="Stars"></a>
  <img src="https://img.shields.io/badge/version-2.2.0-blue?style=flat-square" alt="Version">
  <img src="https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-lightgrey?style=flat-square" alt="Platform">
  <img src="https://img.shields.io/badge/stack-Python%20%7C%20React%20%7C%20pywebview-green?style=flat-square" alt="Stack">
  <img src="https://img.shields.io/badge/tests-985%20cases-brightgreen?style=flat-square" alt="Tests">
</div>

---

**LifeOS** 由前台 Chat Agent 和后台 Global Agent 协作组成。两者共用可靠事件总线、两阶段记忆写入、反思引擎和技能进化闭环。v2.2.0 以 Windows 桌面应用交付：pywebview（WebView2）壳、内嵌 Python 后端、本地 Agent bridge。双击 exe 即可运行。数据全部留在你的电脑上。

## 它解决什么问题

云端助手把你的笔记、日程和聊天记录放在别人的服务器上。LifeOS 把这些全部存进本机 `%USERPROFILE%\lifeOS` 的 SQLite 库。规划在应用内完成。Agent 在你标记为信任的目录里执行。每次文件写入和每条命令都先经过你的批准。

## 工作原理

```text
LifeOS.exe（pywebview 桌面壳，单实例）
  └─ lifeos.api.server（主服务，8765 起自动探测端口）
       ├─ 静态托管 frontend/dist + SPA fallback（打包态同源，无 CORS）
       ├─ 登录闸：本地账户 + PBKDF2 + HttpOnly 会话 Cookie + CSRF
       └─ bridge 子进程（lifeos.bridge.run）
            └─ Agent 适配器（claude_code 等，经 claude-agent-sdk 调本机 CLI）

核心数据流：
用户输入 → Chat Agent（记忆检索 → LLM/工具）→ 响应
        → 可靠事件总线 → Global Agent → 反思
        → 记忆候选 → 安全审查 → 持久化
```

## 功能特性

| 区域 | 你得到什么 |
| --- | --- |
| 桌面壳 | 单实例锁，端口从 8765 向上探测到 8790，关窗时停掉 bridge 和全部子进程。 |
| 账户 | 本地账户配 PBKDF2（600k 轮），HttpOnly 会话 Cookie 加 CSRF 闸，自定义头像，改密码，30 天记住密码用 Windows DPAPI 加密。 |
| 本地 Agent | bridge 独立进程，信任根确认，原生目录选择对话框。claude CLI 先探测本机，再回退捆绑副本。 |
| Agent 闭环 | 事件总线喂给反思引擎，产出记忆候选走两阶段写入，技能候选检测与评估，MCP 工具接入。 |
| 今日 | 可勾选的当日安排，内置 20 组每日提醒，Inbox 汇总 Agent 完成与待确认通知。 |
| 记录 | 每日与阶段规划、复盘用轻量 Markdown 编辑器。复盘承接计划事项。历史记录一点即达，每次保存显示 SQLite 记录编号。 |
| 工作历 | GitHub 风格贡献图，汇总全年规划、复盘、日记与心得。 |
| 对话 | 主导航与最近会话侧栏可收起，LifeOS 与 Agent 对话区拖拽调宽，一键复制，重命名，最多附带 3 个文本、代码或配置文件。 |
| Agent 面板 | 固定在页面底部，最多 20 条实时记录，未连接时草稿仍可编辑，记忆提炼视图可关闭。 |

## 安装

运行 `LifeOS-Setup-2.2.0.exe`，装好后从开始菜单或桌面快捷方式启动。用户数据放在 `%USERPROFILE%\lifeOS`。首次启动会从旧 AppData 目录复制数据，原目录保留为备份。卸载前会先询问，确认后才删数据。

免安装用法：直接运行 `dist\LifeOS\LifeOS.exe`。

## 从源码构建

需要 Windows 10 或 11，外加：

- Python 3.11 或更高（开发机实测 3.13）
- Node.js，构建前端
- Inno Setup 6，仅出安装器时需要
- 原生 `claude.exe`，可选。SDK 拒绝 npm 的 `.cmd` 垫片，打包兜底需要原生 exe

```powershell
# 1) 后端虚拟环境
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

# 2) 前端依赖
cd frontend
npm ci
cd ..

# 3) 指定要捆绑的原生 claude.exe（可选，未设则运行时探测 PATH）
$env:LIFEOS_CLAUDE_SRC = "C:\path\to\claude.exe"

# 4) 一键打包：npm run build → PyInstaller → 可选捆绑 claude.exe
powershell -ExecutionPolicy Bypass -File tools\build_exe.ps1

# 5) 编译安装器，可选
ISCC.exe tools\lifeos-setup.iss
```

产物：`dist\LifeOS\LifeOS.exe`（onedir）和 `dist\LifeOS-Setup-2.2.0.exe`（安装器）。

## 开发调试

```powershell
# 后端（LIFEOS_HOME 指定数据根，默认 ./lifeOS/）
.venv\Scripts\python -m lifeos.api.server

# 前端热更（5173，vite 代理 /api 到后端）
cd frontend && npm run dev

# 桌面链路冒烟：/api 归一 + 直连代理 + bridge/start
.venv\Scripts\python tools\verify_desktop_link.py
```

## 测试

```powershell
# 后端，约 855 个用例
.venv\Scripts\python -m pytest tests -q
.venv\Scripts\python -m compileall lifeos

# 前端，约 130 个用例，另附类型检查
cd frontend
npm test
npm run typecheck
```

三个后端文件（`tests/test_codex_lc_ji_cheng.py`、`test_liu_xing_lc_ji_cheng.py`、`test_pi_lc_ji_cheng.py`）会访问真实外网端点。离线或 CI 环境请加 `--ignore` 排除。

## 目录结构

```text
lifeos/
  desktop/          # 桌面壳入口：单实例、端口、关停时序
  api/              # 主服务：静态托管、登录闸、隧道网关、设备、用户
  bridge/           # 本地 Agent 进程：适配器、仲裁、脱敏、恢复
  agent/            # Chat Agent、Global Agent、规划、执行
  memory/           # 两阶段记忆写入：检索、候选、生命周期
  skills/           # 技能注册表、候选检测、效果评估
  reflection/       # 后台反思引擎
  event/            # 本地可靠事件队列
  security/         # 权限审查
  llm/              # 统一 LLM 接口
  mcp/              # MCP Server 注册表与适配
frontend/           # React + TypeScript + Vite 控制台（npm run build 产 dist）
tools/              # build_exe.ps1、lifeos.spec、lifeos-setup.iss、verify_*.py
tests/              # 后端全量测试
docs/               # 架构与 API 文档
```

## 文档索引

- [docs/api-contract.md](docs/api-contract.md)，前后端 API 对齐
- [docs/agent-memory-integration.md](docs/agent-memory-integration.md)，Agent 执行结果进入记忆的流程
- [docs/memory-module-handoff.md](docs/memory-module-handoff.md)，记忆模块交接
- [docs/memory-provider-boundaries.md](docs/memory-provider-boundaries.md)，记忆 Provider 边界
- [docs/lifeos-workflow-and-memory-architecture.md](docs/lifeos-workflow-and-memory-architecture.md)，工作流与记忆架构
- [docs/team-module-integration-plan.md](docs/team-module-integration-plan.md)，团队模块集成方案

## 运行注意

- 运行时数据：安装版写 `%USERPROFILE%\lifeOS`，源码运行写当前目录 `./lifeOS/`。首次启动从 AppData 旧目录复制迁移，旧目录保留为备份。
- 未捆绑 claude.exe 时，运行时从 PATH 探测。npm 安装的 `.cmd` 垫片会被 SDK 拒绝，请用原生 exe。
- 主服务默认 8765，被占时向上探测到 8790。测试残留的 bridge 进程可能占住 8766 到 8770，结束 `python -m lifeos.bridge.run` 进程即可释放。

## 参与贡献

见 [CONTRIBUTING.zh-CN.md](CONTRIBUTING.zh-CN.md)。内容包括开发流程、测试命令和提交信息规范。
