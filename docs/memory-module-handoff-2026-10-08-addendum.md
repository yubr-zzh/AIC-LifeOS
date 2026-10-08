# Memory 模块阶段验收补充（2026-10-08）

## 对话来源记忆与真实 Gateway 联调

- 新增对话气泡入口：用户可手工写出提炼后的 claim，并选择全局/场景/项目 scope；API 只读取用户输入的 claim 与 trace ID，不读取或复制对话原文。项目 scope 必须为 `project` category；其他 scope 必须为 `user` category。候选需经“我的记忆”明确批准后才会同步。
- 新增回归测试覆盖 trace 来源引用、原文标记不泄露、提交前不写远端、批准后才触发 provider。对话反思自动生成候选现已仅保留结构化诊断，要求用户自行提炼，不再复制原始问答。
- 使用本地合成用户、合成 Bearer key 和临时 SQLite Gateway，真实走通 LifeOS HTTP 对话候选 API → 用户批准/commit → TencentDB `/v3/atomic/create` → `/v3/atomic/search` 召回。批准前远端搜索为空，批准后状态为 `synced` 且召回到 claim；原始聊天标记未出现在远端结果中。测试服务和精确临时数据目录已停止并删除。未使用真实个人记录或模型 API。
- 验证：本轮修改前后完整 LifeOS Python suite 最近一次 **55 tests passed**；`npm run typecheck`、`npm run build` 通过。结束前仍需重跑 `python -m compileall -q lifeos tests`、`git diff --check` 和完整 Python suite。
- 阶段 9 仍未完成：本地真实 Gateway 已验证单条全局写入与对话来源写入，但多条不同 ID 的首次 create 被上游 `queryL1Records(recordIds)` 未按 ID 过滤的问题阻塞；跨 team/agent 产生错误状态，不能以 LifeOS 侧绕过。上游 focused Vitest 为 **7 passed, 1 failed**，剩余失败是 `/atomic/query` fixture 假函数必需参数与 handler 无参调用不一致。尚未获准修改 TencentDB upstream 源码；继续保持 source untouched，等待用户明确授权或维护者修复。
- ai-memory 真实服务只读项目隔离 E2E 已通过（当前二进制 v2.4.1；两个项目互不可见，未映射/global scope 不发起外查），但它早于工作区源码版本，需待源码可构建时复验。
- 本次提交仅包含本文件、主交接文档及 LifeOS 阶段 9 代码/测试；根目录其他未跟踪内容与 upstream 仓库均不纳入。保留 `upstream/ai-memory` 中用户已有的 `payload.rs` 等修改。

## 规划/复盘来源真实 Gateway 验收

- 使用本地合成 daily review 原始记录，经 LifeOS `POST /entries/{id}/memory-candidates` 创建手工提炼的全局候选；`source_ref` 保留原始结构化记录 ID、`daily_review` 类型与日期 revision/occurred_at。
- 审批前通过真实 Gateway 搜索不到候选；明确 commit 后 LifeOS 状态转为 `synced`，真实 `/v3/atomic/create` 写入后可由 `/v3/atomic/search` 召回。Gateway 中可核验 source_ref，原始复盘正文标记未进入候选或远端结果。
- 本次使用新的隔离 SQLite data-dir、loopback Gateway 和合成身份/key；未接入真实日记/计划/复盘、未使用 LLM。Gateway 进程已停止，精确临时数据目录已删除。
- 本次新增的真实 Gateway 验收只覆盖单条全局 review 记忆。多个不同 ID 首次 create 的上游过滤缺陷仍在，不能据此声称多个记忆/多个 scope 的真实 Gateway 验收完成。
- Agent/tool 执行轨迹边界保持：原始轨迹只留在 LifeOS/Agent 的本地证据存储，不自动复制到 TencentDB 或 ai-memory；未来若要沉淀用户长期认知，必须由用户手工提炼并通过现有候选审核；project Agent 连续性由显式映射的 ai-memory 只读读取负责。

## 聊天 Router 记忆范围贯通

- 核对发现后端 ChatRuntime 已按显式 `memory_scope` 进行 TencentDB scope 检索，并只在 Agent 路由 + project scope 下读取映射的 ai-memory；但前端 `sendMessage` 之前没有把 scope 传给 `/chat`，所以 UI 无法触发该链路。
- 已在聊天 composer 增加本轮范围选择（全局/场景/项目）；项目 scope 缺少 project ID 会阻止发送。每次切换对话重置为全局，避免把上个项目的 scope 意外带入新对话。所选 scope 经 Store → `sendChat` → `/chat` 传入本轮；project 只提示读取显式映射的 ai-memory，不做跨项目 fallback。
- `npm run typecheck` 与 `npm run build` 通过。浏览器级视觉 smoke 未运行：仓库 frontend 未安装 Playwright，且 `webapp-testing` skill 文件当前不可用；没有声称完成视觉验收。
- 另用独立临时 Gateway 对单条合成 `phase_plan` project memory 做了真实 create/recall：scope map 的 team/agent/user/session 坐标按配置写入；只在映射项目 scope 下召回，换成另一个未映射项目或 global scope 都是 0 hit；原始规划正文标记未外发。该独立验证不覆盖同一 Gateway 多条 atom 的首次 create。

## 真实 Gateway 生命周期验收

- 对一条合成 daily review 来源的全局记忆，真实走通未批准时远端无命中 → 用户批准后 create/synced → 用户纠正时删除旧 remote ID 并创建新 ID → 用户撤回后新 ID 不再召回。
- 断言按确定性 remote ID 和返回内容校验，避免关键词重叠造成误判。LifeOS 本地 lifecycle 与 Gateway atom 状态一致；合成原始复盘标记始终未出现在远端 payload/搜索结果。
- 验收使用新的临时 SQLite Gateway 和合成身份/key；结束后服务停止、临时目录删除。该项证明单条记录的 create/update/delete 生命周期，不代表多条新 atom 的首次 create 已解决。
- 为替代旧版 ai-memory 二进制验证当前源码，尝试使用独立 Cargo target 构建；在线构建因 crates.io TLS/凭据失败（`zopfli 0.8.3`），离线构建因本机缓存缺少 `bumpalo 3.20.2` 失败。没有覆盖现有 target 或改动 ai-memory 源文件；原 v2.4.1 真实 HTTP 隔离结果仍是目前可用证据。
