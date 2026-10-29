# 参与 LifeOS 贡献

感谢你的关注。本文覆盖开发环境、测试命令、提交规范和发布流程。

## 搭建开发环境

需要 Windows 10 或 11、Python 3.11 或更高、Node.js。

```powershell
git clone https://github.com/yubr-zzh/AIC-LifeOS
cd AIC-LifeOS

# 后端虚拟环境
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

# 前端依赖
cd frontend
npm ci
cd ..
```

## 开发循环

```powershell
# 后端（LIFEOS_HOME 指定数据根，默认 ./lifeOS/）
.venv\Scripts\python -m lifeos.api.server

# 前端热更（5173，vite 代理 /api 到后端）
cd frontend && npm run dev

# 后端改动后跑桌面链路冒烟
.venv\Scripts\python tools\verify_desktop_link.py
```

前端代码在 `frontend/src`。面板位于 `frontend/src/panels`，传输层与类型在 `frontend/src/api`。后端代码在 `lifeos/`，按模块拆分：`api` 是主服务，`bridge` 是本地 Agent 进程，`agent` 和 `memory` 是核心闭环。

## 提交前先跑测试

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

全部测试通过、类型检查干净，改动才算就绪。修 bug 时，请在旁边补一个回归测试。

## 提交信息

仓库使用约定式提交（conventional commits）加中文摘要：

```
fix(ui): 本机Bridge卡标题改为启动桥接
chore(release): 发布 2.0.8，优化对话交互与数据目录
```

常用类型：`fix`、`feat`、`docs`、`chore`、`refactor`、`test`。一个提交只装一个逻辑改动。保持最小 diff。

## 文档双语

`README.md` 和 `CONTRIBUTING.md` 是英文版。`README.md` 和 `CONTRIBUTING.zh-CN.md` 是简体中文版。改了一边，同一个提交里更新另一边。

## 发布流程

版本号只放在三个地方：

1. `frontend/package.json` 的 `version` 字段
2. `frontend/package-lock.json`，用 `npm install --package-lock-only` 同步
3. `tools/lifeos-setup.iss` 的 `MyAppVersion` 定义

发版步骤：

```powershell
# 三处版本号改好后：
powershell -ExecutionPolicy Bypass -File tools\build_exe.ps1
ISCC.exe tools\lifeos-setup.iss
```

构建产出 `dist\LifeOS\` 和 `dist\LifeOS-Setup-X.Y.Z.exe`。删掉 `dist\` 里的上一个安装器，只留最新版本。仓库按约定提交 `dist\` 和 `build\`，所以发布提交要带上重建后的产物：

```
chore(release): 发布 2.2.0，重写双语文档并重建打包产物
```
