# Agent 执行结果接入 Memory

当前实现把 `liu` 分支的 Claude Code Bridge 接入 LifeOS 的记忆审核流程。它面向本机单用户：Bridge 负责执行与回传，LifeOS 保存可审阅的结果摘要，用户从摘要中手写长期有用的认知并提交候选。只有在 Memory 面板审核通过后，认知才会进入长期记忆。

## 本地运行

在仓库根目录安装 `requirements.txt` 并运行 `python -m lifeos.api.server`。在 `frontend/` 执行 `npm ci` 和 `npm run dev`，打开 Vite 提示的本地地址。主服务默认监听 `127.0.0.1:8765`。本地 Agent 页面可启动 Bridge、配对设备；Chat 的 Agent 区域可以委派 Claude Code 执行任务。真实执行需要本机可用的 Claude Code 环境。

## 从执行结果到记忆

1. Claude Code 完成一条委派后，Bridge 向 `POST /api/agent-events` 发送 `agent.result`，包含 `sessionId`、`eventId` 和结果摘要。LifeOS 将摘要追加到该会话上下文，并按 `eventId` 保存证据；重复回调不会生成第二份证据。
2. Chat 的 Agent 区域会列出当前会话最近的结果。选择一条结果，填写稳定的项目 ID 和一条自己确认的认知，提交后得到 `agent_execution` 来源的 `project` 记忆候选。原始执行输出不会直接变成长期记忆。
3. 在「系统后台 → Memory」审核候选。提交审核后，本地长期记忆生效；如果配置了现有的 TencentDB 适配器，也会沿用原有的批准后同步与失败重试流程。
4. 在 Chat 的项目 ID 输入框填入同一 ID，即使用该项目的记忆范围检索。不同项目的认知相互隔离；不填项目 ID 时只使用全局范围。

证据保存在 `.lifeos/agent_evidence.json`，原始 Bridge 会话数据仍由 Bridge 管理。证据 API 为 `GET /agent/evidence?session_id=...`；提案 API 为 `POST /agent/evidence/{eventId}/memory-candidates`，请求体是 `{"claim":"...","project_id":"..."}`。同一结果、认知和范围重复提交只返回同一候选。

## 当前边界

- 执行端目前只有 Claude Code Bridge。Memory 的来源、证据和审批路径可供后续 Agent 适配器复用，但尚无其他执行端。
- 这是本机单用户流程，服务端用户身份由当前本地用户配置提供；尚未提供面向公网的登录和跨设备身份验证。
- Bridge 回调只接受本机回环地址。结果摘要会进入会话上下文；只有用户手写并审核的认知会进入长期记忆。
- 项目 ID 由用户明确填写，当前没有自动推断项目或从 Bridge 元数据绑定项目。
