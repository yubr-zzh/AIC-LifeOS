# LifeOS Agent

Agent 执行结果进入记忆的本地使用流程见 [docs/agent-memory-integration.md](docs/agent-memory-integration.md)。

LifeOS Agent 是一个个人智能体操作系统原型，采用前台 Chat Agent 与异步 Global Agent 协作的架构。

当前仓库聚焦于核心运行时架构，而不是早期的演示产品外壳。核心是一条可靠的智能体数据流：

```text
用户输入
-> Chat Agent
-> 记忆检索
-> LLM / 工具调用
-> 返回用户响应
-> 可靠事件总线
-> Global Agent
-> 反思
-> 记忆候选
-> 安全审查
-> 持久化记忆 / Skill
```

## 核心理念

- **前台 Chat Agent**：快速交互路径，采用接近 Claude Code 或 Hermes 的直接工具调用方式：检索相关记忆、调用 LLM/工具、返回响应，然后发布可持久化事件。
- **可靠事件总线**：连接前台与后台。事件会先持久化到本地，确保后台处理可审计、可重试。
- **后台 Global Agent**：负责维护工作流。它消费类型化事件、执行反思、提出记忆更新、发现可复用的 Skill 候选，并进行安全审查。
- **两阶段记忆写入**：不直接写入长期记忆，而是经过候选创建、校验、备份、应用、向量库更新和缓存失效等步骤。
- **分离的权限模型**：工具执行确认与 Skill 安装或持久化确认彼此独立。

## 仓库结构

```text
lifeos/
  agent/
    runtime.py              # 组合根与 Global Agent 运行时
    chat/runtime.py         # 前台 Chat Agent
    planner/planner.py      # 轻量规划辅助模块
    executor/executor.py   # Chat / 工具执行路径
  api/server.py             # 最小 HTTP API
  event/bus.py              # 本地可靠事件队列
  memory/
    manager.py              # 记忆门面
    retriever.py            # 查询时记忆检索
    updater.py              # 候选创建与应用
    lifecycle.py            # 校验、备份、向量库与缓存生命周期
  llm/client.py             # 统一 LLM 接口，默认使用 mock provider
  reflection/engine.py      # 后台反思
  security/permission.py   # 权限审查
  skills/
    registry.py             # 已批准 / 待处理 Skill 注册表
    detector.py             # Skill 候选检测
    evaluator.py            # Skill 效果评估
  mcp/
    registry.py             # MCP Server 注册表
    adapter.py              # MCP 工具适配器
  trace/system.py           # Trace 记录

docs/
  frontend-ui-prompt.md     # LifeOS UI 实现提示词
  frontend-ui-prompt.docx   # 便于分享的 Word 版本
  api-contract.md           # 前后端 API 对齐文档
  api-contract.docx         # 便于分享的 Word 版本

tools/
  md_to_docx.py             # Markdown 转 DOCX 辅助脚本
```

## 快速开始

启动最小 API 服务：

```bash
python -m lifeos.api.server
```

默认后端地址：

```text
http://127.0.0.1:8765
```

发送一条聊天消息：

```bash
curl -X POST http://127.0.0.1:8765/chat \
  -H "Content-Type: application/json" \
  -d "{\"message\":\"hello lifeos\"}"
```

运行一次后台 Global Agent 轮询：

```bash
curl -X POST http://127.0.0.1:8765/background/run-once \
  -H "Content-Type: application/json" \
  -d "{}"
```

## 当前 API

### `POST /chat`

请求：

```json
{
  "message": "hello lifeos"
}
```

响应：

```json
{
  "trace_id": "uuid",
  "response": "LifeOS mock response: hello lifeos",
  "tool_calls": []
}
```

副作用：发布一条可持久化的 `conversation.completed` 事件。

### `POST /background/run-once`

请求：

```json
{}
```

响应：

```json
{
  "processed": ["event-id"]
}
```

完整的前后端对齐说明见 [`docs/api-contract.md`](docs/api-contract.md)。

目前还提供以下检查接口：`GET /events`、`GET /memory`、`GET /skills`、`GET /traces/{trace_id}` 和 `GET /permissions`（当前返回空请求列表）。

记忆候选可通过 `POST /memory/candidates/{id}/commit` 提交，或通过 `/reject` 拒绝；待处理 Skill 可通过 `POST /skills/pending/{id}/approve` 批准，或通过 `/reject` 拒绝。这些操作会持久化到后端。工具执行和权限确认目前仍为模拟或仅供审查的流程。`POST /chat` 响应包含 `tool_results`，便于 UI 展示被拦截的工具调用。

## 前端方向

目标 UI 是一个智能体控制台或工作台，而不是营销展示页。主界面应采用 Chat Workspace，并提供运行时状态、事件队列、记忆生命周期、Skill 候选、权限和 Trace 详情等操作面板。

可直接用于实现的提示词见 [`docs/frontend-ui-prompt.md`](docs/frontend-ui-prompt.md)。

## 验证

基础语法检查：

```bash
python -m compileall lifeos
python -m unittest discover -s tests -v
```

## 运行时状态

默认情况下，本地运行时文件写入 `.lifeos/`，并由 Git 忽略。其中包括持久化事件、记忆状态和 Skill 注册表状态。
