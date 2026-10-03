# LifeOS 外部记忆能力边界与适配决策

> 状态：阶段 8 决策记录（2026-10-03）  
> 范围：评估 `ai-memory` 与 TencentDB Agent Memory 对 LifeOS 的职责、数据权威和未来适配面。本文不代表已实现外部服务集成。

## 决策摘要

1. **LifeOS 是用户长期认知的唯一权威。** 当前已采纳的 Memory、候选审核状态和由 active Memory 构建的画像都归 LifeOS 管理；外部系统的结果不能直接覆盖或创建 active Memory。
2. **`ai-memory` 定位为可选的项目工作连续性来源。** 它擅长编码项目中的 lifecycle capture、项目 wiki、handoff 和跨 Agent 接续。将来若接入，第一步只做当前项目的只读召回，不做全量同步或双写。
3. **TencentDB Agent Memory 暂不作为 LifeOS 的生产记忆后端。** 它的 L0–L3 记忆管线与 LifeOS 当前的原始记录、候选/active Memory 和画像模型有显著重叠。当前只借鉴分层渐进披露、召回和溯源设计，并可做独立对照评测；不得同时维护两份用户画像权威。
4. **暂不增加通用 Adapter 框架或运行时依赖。** 当前只有一个明确的潜在只读项目召回场景，且 LifeOS 尚无外部 Memory Provider 接口、项目身份映射和服务配置。先把最小契约定清楚，等具体接入时用单一垂直切片验证。

## 事实基线

| 能力/数据 | LifeOS 当前实现 | `ai-memory` 当前定位 | TencentDB Agent Memory 当前定位 |
| --- | --- | --- | --- |
| 项目连续性 | 有 project scope 的 Memory 候选/召回原型；无跨 Agent 项目 wiki/handoff 后端 | 面向 coding agent 的项目级 Git Markdown wiki，SQLite 是派生检索索引；支持 lifecycle hooks、MCP/HTTP、handoff | 支持 Agent/Team 等隔离坐标，也能保存对话与场景，但并非专门的 Git 项目工作 wiki |
| 用户长期认知 | `.lifeos/memory.json` 保存候选和已采纳 Memory；`GET /memory/profile` 从 active 项目/场景/全局 Memory 动态重建 | 支持项目 wiki 及可选 global/supplemental global 内容；不应把其 global scope 解释为 LifeOS 的用户画像 | 提供 L0 conversation、L1 atomic、L2 scenario、L3 core profile，且自带生成/召回管线 |
| 来源与治理 | `source_ref`、scope、confidence metadata、candidate → commit/reject、correct/retract | hook sanitizer、wiki 版本链、audit、来源/证据元信息；契约围绕 workspace/project/operator | L0–L3 generation references/logs；v3 请求要求 `team_id`、`agent_id`、`user_id` |
| 与 LifeOS 的重叠风险 | —— | 若将其项目 wiki 写回 LifeOS，会重复保存项目进展；若将其 global notes 当作 persona，会混淆范围 | 若同时接收 LifeOS 的原始记录并生成 L1–L3，会重复存储和推导长期认知，且产生画像冲突 |

当前 LifeOS 的长期 Memory 权威位于 `MemoryManager` 所持有的本地 JSON store；结构化规划/复盘等原始条目位于 `StructuredStore` SQLite。现有聊天事件存储不能据此视为完整、永久的原始对话档案。不同来源的原始归档策略仍需后续单独完善。

## 职责与数据归属

| 数据类 | 权威系统 | 外部系统允许扮演的角色 |
| --- | --- | --- |
| LifeOS 对话、规划/复盘、用户反馈原始内容 | 各 LifeOS 来源存储；来源 ID/修订必须可追溯 | 不自动复制完整内容；确有授权的场景可传递最小必要片段 |
| 用户长期认知候选、审核决定、active Memory、纠正/撤回历史 | **LifeOS** | 可提供带来源的只读证据或建议；不得直接写 active Memory |
| 全局/场景/项目画像视图 | **LifeOS 派生 read model** | TencentDB 的 L3 可作为隔离评测输出，不作为生产画像来源 |
| Agent coding session、项目决策 wiki、handoff | 未来可选 **`ai-memory`** 项目空间；当前 LifeOS 尚未接入 | 通过明确项目身份只读查询；若之后启用外部写入，仍由 ai-memory 自己治理其 wiki |
| 召回结果的本次上下文组合 | **LifeOS Memory Router** | 将外部命中作为带 provider 标记的证据片段；不可静默并入会话历史或画像 |

跨系统传播只允许“最小必要、带引用、单向进入当前任务上下文”。如果用户明确要求把外部证据沉淀为长期认知，应在 LifeOS 创建候选，保留原始 provider/ref，再走既有人工审核流程。

## 最小未来适配契约（设计，不是当前代码）

```text
ExternalMemoryProvider
  provider_id: stable identifier
  capabilities: declared read/write surfaces
  recall(request) -> Evidence[]

RecallRequest
  query: current task text
  scope: { user_id?, scenario_type?, project_id?, workspace_id? }
  limit: bounded result count

Evidence
  provider_id
  external_ref
  title / bounded excerpt
  source_scope
  occurred_at / updated_at (when available)
  retrieval metadata (when available)
```

适配边界：

- 第一种实现只需 `recall`，不要求所有 provider 支持统一写入、删除、画像生成或任务管理。
- LifeOS 项目 ID 到 provider 项目坐标的映射必须显式且稳定；不能只靠模糊 repo 名称推断。缺失/歧义时跳过项目 provider，不做全局兜底。
- 结果带明确的 `provider_id` 与 `external_ref`，作为不可信外部上下文展示/注入；受统一条数和长度上限约束。具体额度、超时和重试策略由阶段 9 的效率评测确定。
- Provider 超时/不可用不能阻断 LifeOS 本地召回；UI/trace 必须能区分“没有命中”和“外部源不可用”。
- 外部命中只有在再次显式提出候选并经用户审核后，才可能进入 LifeOS active Memory。
- 任何可写适配都必须另行规定用户授权、幂等键、版本冲突、删除语义和审计；不从只读接口隐式扩展。

## 采用顺序与决策门

1. **优先候选：`ai-memory` 只读项目召回。** 触发条件：LifeOS 执行项目任务时，用户确实需要跨 Codex/Claude Code 等工具共享项目决策、handoff 或进展，而且当前 LifeOS 项目记忆不能可靠提供这些内容。
2. 触发后先验证一个已明确映射的测试项目，通过 MCP/HTTP 读取少量项目 wiki/handoff；不捕获新 hook、不自动写 wiki、不导入为 LifeOS Memory。
3. 验收必须覆盖正确项目命中、相似项目不串用、无映射时拒绝查询、provider 故障时本地召回仍可用，以及每条结果能回到外部页面引用。
4. **TencentDB 暂无生产 adapter。** 只有当隔离评测证明其层级召回/归纳在 LifeOS 的具体场景上优于现有实现，且输出能保留原子证据与 provenance、身份映射和删除责任也能明确时，才重新评估。初次实验使用合成或脱敏数据，不双写真实用户记忆。

## 证据与版本边界

- `ai-memory` 上游架构：[docs/ARCHITECTURE.md](https://github.com/akitaonrails/ai-memory/blob/main/docs/ARCHITECTURE.md)；使用方式：[docs/cookbook.md](https://github.com/akitaonrails/ai-memory/blob/main/docs/cookbook.md)。该项目说明 Markdown wiki 是事实来源，SQLite 是派生索引，并提供 MCP/HTTP、hook 和 handoff 等能力。
- TencentDB Agent Memory 上游：[MemoryCore/README_CN.md](https://github.com/TencentCloud/TencentDB-Agent-Memory/blob/feat/server_team/MemoryCore/README_CN.md)。当前文档列出 L0–L3、HTTP Gateway/SDK、generation reference；v3 记忆数据面要求 `team_id`、`agent_id`、`user_id`。此接口/分支状态可能变化，真正实施前必须复核。
- 本地 `upstream/ai-memory` 检查时处于 `docs/codex-shared-daemon-recovery`，HEAD `82b9c581`，不是 `main`；其 cookbook/architecture 仅作为本地补充材料。本决策采用上游 main 的官方架构文档核对能力，不把本地分支状态误称为最新。
- LifeOS 代码证据：`lifeos/memory/manager.py`、`lifeos/memory/retriever.py`、`lifeos/memory/profile.py`、`lifeos/storage/sqlite.py`、`lifeos/api/server.py`。

## 后续工作

- 本决策不引入运行时代码或外部服务依赖。
- 下一阶段先补一次阶段 7 UI 浏览器验收并建立召回质量评测基线；如真实任务证明需要跨工具项目连续性，再单独开 `ai-memory` 只读 provider 纵向切片。
- 暂不以“架构上可接入”为理由预先抽象多 provider 插件框架。
