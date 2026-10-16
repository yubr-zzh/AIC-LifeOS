# TencentDB 已审核 L1 Atomic 创建接口提案

> 状态：阶段 9 技术提案，待项目负责人审阅；不是已实现接口，也不是对上游的承诺。
> 目的：补齐 LifeOS 将用户已审核的原子记忆写入 TencentDB L1 的缺失能力。

> 2026-10-15 核验更新：上游草稿 PR #1604 的当前提交已采用可选 `createL1` 存储能力；SQLite/Mongo 有 insert-only 实现，TCVDB 不支持。该实现仍未完成此处记录的 TCVDB 与目标 Gateway 验收，详见文末“状态更正”。

## 为什么需要上游能力

LifeOS 当前链路已经能从对话反思、每日/阶段规划复盘和用户反馈生成带来源与 scope 的候选，并在用户批准后提交。TencentDB v3 的现有 L1 `atomic/update` 不能完成新 Memory 的首次创建：上游 `MemoryCore/src/gateway/v2-router.ts` 的 `handleAtomicUpdate` 先按 ID 查询；记录不存在时返回 404，找到后才覆写内容并 `upsertL1`。因此把它当作 upsert 会导致 LifeOS 首次同步失败。

`/offload/ingest` 不是等价替代。它异步处理对话/工具轨迹并由模型抽取、去重 L1；这会重写输入语义，也不能保证抽取出的每条记录仍等于 LifeOS 已展示并获批的候选。LifeOS 不应借此绕过审核闸门。

## 已核对的当前默认分支

GitHub 当前默认分支为 `feat/server_team`。部署文档虽列出 `POST /v2/atomic/add`，并声称 Service E2E 覆盖了 L1 add，但实际 checkout 的该分支中：

- `MemoryCore/src/gateway/v2-router.ts` 的数据路由表只有 `atomic/update/query/search/delete/count`，没有 `atomic/add` 或 `atomic/create`。
- `handleAtomicUpdate` 对不存在的 ID 返回 404；它不是 create/upsert。
- TypeScript v3 SDK 只有 `updateAtomic/queryAtomic/searchAtomic/deleteAtomic/countAtomic`，没有 create/add；Python SDK 对应也只有 update。
- 本次 checkout 中没有 `MemoryCore/__tests__/e2e/test_hermes_service_e2e.py` 或 MemoryCore 测试文件；部署文档所述 E2E 不能在该 checkout 中复核。
- `IMemoryStore` 只公开 `upsertL1`。SQLite、Mongo 和 TCVDB 实现均采用覆盖式写入。腾讯云 VectorDB 的 `/document/upsert` 对相同 Document ID 会删除并替换旧文档，不能直接承担“create-only”。

因此，**接口确实缺失，但不能直接把 `upsertL1` 包一层就称作安全的 atomic create**：查后写会有并发竞态，稳定 ID 重试可能覆盖内容或向量；要实现“相同请求重试幂等、不同 payload 冲突且绝不覆写”，必须先确定存储层的原子条件写语义，尤其是 TCVDB backend 如何支持。

## 最小接口目标

新增 v3 endpoint（路径可讨论 `/v3/atomic/add`，以对齐已有部署文档；或 `/v3/atomic/create`，以明确 create-only 语义），用于创建一条已经在调用方完成抽取/审核的 L1 Atomic。已有 `atomic/update` 继续只更新既有 ID，避免暗中改变旧接口的 404/更新语义。实现前需维护者确认 TCVDB 条件插入/冲突检测能力，以及 API 的幂等契约；在这两点明确前，不应把稳定 ID 的查后 upsert 当作最终实现。

建议请求字段：

```json
{
  "team_id": "...",
  "agent_id": "...",
  "user_id": "...",
  "session_id": "lifeos-approved-memory",
  "id": "lifeos-<lifeos-memory-id>",
  "type": "persona",
  "content": "<approved memory content>",
  "background": "<source/scope provenance JSON>",
  "priority": 50,
  "metadata": {"source": "lifeos", "schema_version": 1}
}
```

`team_id`、`agent_id`、`user_id`、`id`、`type`、`content` 必填；隔离字段按现有 v3 的严格三元组规则校验。`session_id` 沿用现有 L1 可选 session 语义。`background`、`priority` 和 `metadata` 的具体约束应复用 MemoryCore 当前 `MemoryRecord`/schema 规范，而不是让 LifeOS 发明另一套兼容格式。

## 必须满足的语义

1. **创建而非抽取**：只写请求中的获批 Atomic，不触发 LLM extraction、dedup merge 或额外生成。
2. **身份隔离**：记录 tenant 坐标由 v3 请求确定；不得从客户端可控的 provenance JSON 推导身份。
3. **稳定 ID 幂等**：相同 ID、身份与相同规范化 payload 的重试返回成功且不重复建行/向量；相同 ID 但 payload 不同则返回明确冲突，不能静默覆写。该保证必须由存储层原子语义支撑，不能依赖 handler 的 read-then-write。
4. **可追溯**：精确保留 `background`/`metadata` 与 LifeOS `source_ref`、scope、approval ref；读/search 返回值要能让调用方拿到这些字段，不能只返回 `scene_name` 的有损映射。
5. **失败原子性**：验证、持久化、向量写入的失败语义要有清晰响应；不能在 API 返回成功但记录不可召回时静默丢失。
6. **分层更新与删除**：后续纠正走现有 `atomic/update`，撤回走 `atomic/delete`，二者继续强制相同 tenant 坐标；LifeOS 保留本地 lifecycle 状态作为召回闸门。

## LifeOS 对接策略

- 只有 LifeOS 本地 `active` 且由用户批准的 Memory 可调用 create。
- 用 `lifeos-<memory_id>` 作为外部 ID；持久化外部 ID 与 provider 状态，超时重试同一 ID。
- 首次 create 成功后，纠正才可 update 新版本并清理旧 ID；撤回应删除远端 ID。远端错误时本地审核/撤回状态仍为权威，召回必须通过本地 active-ID allowlist。
- 不同步原始对话 L0；只传用户实际审核过的候选内容和最小必要 provenance。
- 上游能力未具备前，LifeOS 仅保留本地记忆并标记外部同步 pending/capability unavailable；不能把现有 `atomic/update` 说成首次写入成功。

## 验收建议

- 上游 handler 单测：新 ID 创建；同 payload 同 ID 重放幂等；异 payload 冲突；跨 user/agent/team 写入拒绝；metadata/background round-trip。
- Gateway 集成测：创建后按 ID 查询、关键词 search、update、delete；检验向量/文本索引最终可见。
- LifeOS 合成数据 E2E：candidate → approve → create → retrieve（同 scope 可见、跨项目不可见）→ correct → retract；断网/超时重试无重复、拒绝候选零请求。
- 只有上述 Gateway E2E 通过后，才启用远程写入配置；不以 mock transport 的 HTTP 形状测试替代服务端验收。

## 证据与未决项

- 服务端 handler/路由：[当前默认分支 `v2-router.ts`](https://github.com/TencentCloud/TencentDB-Agent-Memory/blob/feat/server_team/MemoryCore/src/gateway/v2-router.ts)，数据路由表缺少 create/add；`handleAtomicUpdate` 对 missing ID 返回 404。
- SDK 路由/请求字段：[TypeScript v3 client](https://github.com/TencentCloud/TencentDB-Agent-Memory/blob/feat/server_team/sdk/memory-core/typescript/src/v3/client.ts)；Python v3 client 也只有 update。
- 文档/API 不一致：[部署文档](https://github.com/TencentCloud/TencentDB-Agent-Memory/blob/feat/server_team/README.deployment.md#L555-L571) 声称有 `/v2/atomic/add`，而当前默认分支的实现中不存在该路由；同一文档的 Service E2E 章节声称 L1 add 被测，但对应脚本不在当前 checkout。
- 存储冲突语义：[腾讯云 VectorDB upsert 文档](https://cloud.tencent.com/document/product/1709/95121) 明确说明相同 Document ID 会删除并替换已有 Document；当前 `TcvdbMemoryStore` 也只调用 `client.upsert`。
- 条件更新不是条件创建：[腾讯云 VectorDB HTTP update 文档](https://cloud.tencent.com/document/product/1709/100563) 描述按 Document ID 与 Filter 更新已有 Document，并以 `affectedCount` 反馈更新条数；它不能创建不存在的 Document。当前本地 `TcvdbClient.update()` 正是调用 `/document/update`，没有 `/document/insert` 或 create-if-absent 方法。
- 本提案尚未确定：L1 `type` 的 LifeOS category 映射、priority/confidence 的表示方式、是否要求 generation log/approval reference 一等字段、服务端向量写入的强一致或最终一致承诺。这些需结合 TencentDB 维护者的现有 MemoryRecord 约定讨论，不能由适配层擅自定稿。

## 2026-10-15 状态更正

更正 2026-10-04 记录：它描述的 lease + `upsertL1()` 中间实现已不是当前 feature branch HEAD，不能继续作为现状引用。当前本地 checkout 的 `feat/atomic-create-approved-memory` HEAD 为 `9979d4ee`（2026-10-04，PR #1604），Gateway 调用可选存储接口 `createL1`；SQLite 以主键约束执行 insert-only，Mongo standalone/replica set 使用 `insertOne`，Gateway 仅在读回完全相同的 tenant 与 payload 时将重试视为幂等成功。Mongo sharded 与不支持该能力的 backend fail closed，不回退到 upsert。

PR #1604 增加了 v3 路由、Python/TypeScript SDK 与 API 文档，但尚未在此处验证 Vitest、TypeScript 类型检查或目标部署的真实 Gateway 行为。TCVDB adapter 没有 `createL1`，调用返回 501；因此该 PR 是 SQLite/Mongo 的部分能力，不是 LifeOS 当前目标 backend 的完整解决方案。LifeOS 的 create 开关应继续关闭，直到目标部署/backend 与其冲突/幂等语义通过验收。

当前 nested checkout 不是干净工作树：`MemoryCore/src/core/store/sqlite/memory-store.ts` 及相关 atomic-create 测试有未提交修改（主要涉及按 `recordIds` 查询时精确过滤，避免把 tenant-wide 查询误当成 ID 冲突）。这些属于现有工作区内容，本轮只记录状态，没有改动或清理。

官方资料存在语义/API 不一致：[VectorDB HTTP `/document/upsert` 文档](https://cloud.tencent.com/document/product/1709/95121) 和当前 TCVDB store/client 路径都指向同 ID 替换；[VectorDB FAQ](https://cloud.tencent.com/document/product/1709/104774) 则把“插入”与“更新”分开描述为已存在 ID 不覆盖。FAQ 没有说明该“插入”对应哪个当前 HTTP endpoint、SDK method 或版本，也没有说明冲突响应及并发原子保证。腾讯官方 Go SDK 的公开 API 模型列有 `/document/upsert` 的 `UpsertReq` 与 `/document/update` 的 `UpdateReq`，暂未发现独立 document insert request（[SDK API package](https://pkg.go.dev/github.com/tencent/vectordatabase-sdk-go/tcvectordb/api/document)）。因此目前只能确认本仓库 adapter 使用覆盖式 upsert、公开资料没有给出可直接采用的独立条件插入方案；不能断言服务端完全没有 insert-only 原语，也不能把 FAQ 当成已经可用的原子保证。下一步需要维护者指出 FAQ 所指具体 API/SDK 调用，并确认并发行为。

### 安全的实现决策

1. 不提交当前 lease + `upsertL1` 版本作为 atomic/create 修复，也不声称仅将 API 定义收窄即可满足“绝不覆写”。
2. 当前 feature branch 已将 create-only 能力放入可选存储接口 `createL1`：SQLite 使用不带冲突更新的普通 INSERT；Mongo 在 standalone/replica set topology 使用 `insertOne`。唯一键冲突后 Gateway 读回胜出记录，仅对完全相同 payload 幂等成功。Gateway 不依赖 read-then-upsert 或分布式 lease。Mongo sharded topology 会 fail closed，因为 `_id` 非 shard key 时全局唯一性未被数据库保证。此代码尚未通过 Vitest/类型检查，不能视为验收完成。
3. TCVDB adapter 当前未实现 `createL1`，Gateway 对该后端显式返回 `501` 并 fail closed；禁止 fallback 到 `/document/upsert`。由于 LifeOS 当前目标包含 TCVDB，这只是安全的 partial capability，不算完成目标。
4. 首先向维护者/官方文档确认 FAQ 所说的 insert 对应的 endpoint、SDK method、版本、重复 ID 响应及并发原子保证；如果存在且满足原子性，再在 TCVDB adapter 实现并测试。若不存在，则讨论新增/暴露真正的 TCVDB 原子 create 原语或调整目标/后端约束。普通 lease、读后写、`document/update` 都不能替代。

### 下一步验证计划

- [x] 对照当前 TCVDB client/store 和 Gateway 路由，确认本仓库实际调用是 `/document/upsert`。
- [x] 查官方 upsert、update API：upsert 文档描述同 ID 替换；update 面向已有记录。
- [ ] 查清官方 FAQ 所说“不覆盖”的 insert 实际对应哪个 endpoint/SDK method、版本和并发保证；相关资料互相矛盾，不能先行推断服务端没有该能力。
- [ ] 向维护者/VectorDB 官方渠道核对 FAQ 所述 insert 语义对应的具体 HTTP endpoint、SDK 方法、版本及并发原子保证；取得可复现请求前不把它视为可用原语。
- [ ] 决定 PR 是否拆为“SQLite/Mongo 原子 create API + TCVDB 明确 unsupported”，或者等 TCVDB create-only 原语后做跨 backend 完整实现。
- [x] 重做当前分支 Gateway handler/store 接口；新增相同/不同 payload 并发冲突测试和 unsupported-store fail-closed 测试。
- [ ] 增加/接通真实 SQLite 与 Mongo store contract 测试（当前仓库 shared contract 未发现调用点），并确保 Mongo 分片部署的全局 ID 唯一前提写进接口约束。
- [ ] 依用户授权/环境可用性补齐 Vitest、类型检查及相关 Gateway 集成测试；本轮未安装依赖，Vitest 当前不可运行。
- [ ] 继续核实 TCVDB 条件插入原语；TCVDB create 能力未完成前，不能认为 LifeOS 目标已达成。
