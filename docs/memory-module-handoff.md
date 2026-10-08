# LifeOS Memory 模块阶段性交接记录

> 用途：记录 Memory 模块每阶段的目标、验收证据、未决问题与下一步，供用户或其他 Agent 接手。
> 更新规则：每完成一个阶段，更新“阶段状态”和“阶段验收记录”；不要把未验证的设计写成已实现能力。
> 当前基线：2026-10-02；仓库根目录已是 Git 仓库，分支 `zhang-memory`。

## 项目目标与范围

LifeOS 的定位是 **AI + 日记本式长期 Memory + 执行力**。Memory 模块要从多类来源沉淀会影响 LifeOS 后续理解与决策的长期认知，同时保留原始记录以便按需追溯；不能把全部历史记录都塞进每次模型上下文。

长期方向包括：

- 来源不只限于执行 Agent：还包括 LifeOS 对话、每日/阶段性规划与复盘、用户反馈、项目活动、执行轨迹，以及以后可能接入的外部工具。
- 保留一份全局核心画像，以及学习、项目、文档、信息执行、外部操作等场景画像；项目型记忆默认按具体项目隔离。
- 画像应是由带来源、时间、置信度等属性的多条 Memory 动态生成的可更新视图，而不是无来源的单段总结。
- 原始记录归档与长期认知分层；检索只取当前任务所需内容，必要时再回读原始证据。
- `ai-memory` 与 TencentDB Agent Memory 是 LifeOS 目标架构中要实际使用的互补组件：前者解决项目 Agent 连续性，后者提供 L1-L3 长期认知；不能把“避免双重权威”误解成只作参考或可有可无。
- 晋升规则（项目/场景记忆何时上升到全局）尚未决定；默认不自动跨项目晋升。

## 阶段总览

| 阶段 | Goal | 状态 | 主要产物 / 验收 |
| --- | --- | --- | --- |
| 0. Git 与工作区基线 | 确认仓库与现有变更，避免覆盖用户工作 | 完成 | 根目录已为 Git 仓库；保留所有既有未跟踪项 |
| 1. 现状审计 | 搞清现有 Memory、事件流、API、持久化和测试的实际行为 | 完成 | 本文“阶段 1 验收记录”；现有测试 8/8 通过 |
| 2. 领域数据契约 | 定义原始来源引用、记忆候选、已采纳 Memory、画像视图所需字段及兼容策略 | 完成 | `lifeos/memory/schema.py` v3 契约、一次性备份迁移、API/TS 类型、回归测试 |
| 3. 记忆写入与来源接入 | 打通至少一条非 Agent 来源的计划/复盘到候选 Memory 的可审计链路 | 完成（后端 MVP） | `POST /entries/{id}/memory-candidates`；结构化来源、revision 幂等、人工审核测试 |
| 4. 生命周期与可纠错性 | 明确候选、采纳、拒绝、修正、冲突等状态变化；不擅自决定跨范围晋升 | 完成（生命周期 MVP；自动冲突检测与物理删除明确延期） | schema v3 active/superseded/retracted；显式纠正/撤回 API；非法状态转换、召回过滤与索引失效测试 |
| 5. 分层检索与隔离 | 支持全局/场景/项目检索范围，确保项目记忆不串用 | 完成（显式范围与 fail-closed 默认；自动识别延期） | 层级召回规则、用户标记过滤、跨项目/场景隔离测试；`memory_scope` 从 `/chat` 传至检索并写入事件 |
| 6. 动态画像视图 | 从有效 Memory 生成带溯源信息的核心/场景画像，不另造权威副本 | 完成（LifeOS 本地结构化只读 MVP；目标接 TencentDB L2/L3） | `/memory/profile` 按 scope 动态重建；仅 active；稳定版本 hash；来源与置信度可追溯 |
| 7. API 与用户审核入口 | 让用户检查、修正、拒绝候选并理解画像依据 | 完成 | 画像 UI、来源可追溯、从日/阶段规划复盘显式提炼候选；浏览器端手工复核待做 |
| 8. 外部记忆职责与权威边界 | 明确 LifeOS 如何组合实际要使用的 ai-memory 与 TencentDB，避免相互替代或重复权威 | 完成（已按用户纠正修订） | 两个后端均是目标能力；ai-memory 管项目连续性，TencentDB 管 L1-L3，LifeOS 管来源/审核/编排；明确本地 store 为迁移期实现 |
| 9. 外部后端适配与切换 | 实际接入 TencentDB 认知链路和 ai-memory 项目连续性，并与 LifeOS Router 联通 | 本地 HTTP mock 纵向验收完成；真实后端验收未完成 | 两适配器、显式 scope/binding 与 Planner 联通；53 项回归通过；真实后端、L2/L3、迁移/回滚仍待隔离环境验收 |
| 10. 评估与效率 | 评估召回正确性、隔离性、可解释性；再量化成本与效率 | 待开始 | 小型评测集与基线；成本优化放在正确性之后 |

## 阶段 0 验收记录

- 根目录已是 Git 仓库，当前分支 `zhang-memory`；无需重新 `git init`。
- 开始前工作区存在既有未跟踪内容，包括 `upstream/`、若干 `docs/` 图稿/预览和 `AI-MEMORY-987-HANDOFF.md`。本次没有覆盖或清理这些内容。
- `.codegraph/` 不存在，未使用 CodeGraph。

## 阶段 1 验收记录

### 当前实现链路

1. `lifeos/agent/chat/runtime.py` 在每轮聊天中调用 `memory.retrieve(user_input)`，将返回内容传给执行器，并写入 `conversation.completed` 事件。
2. `lifeos/agent/runtime.py` 的 Global Agent 消费对话/反馈事件，调用反思器，再通过 `propose_update` 生成候选。
3. `lifeos/memory/manager.py` 将数据写入 `.lifeos/memory.json`；候选确认后依次 validate、backup、apply、vector upsert、cache invalidate，并尽力同步 Markdown 镜像。
4. `lifeos/api/server.py` 暴露 `/memory`、Markdown 导入导出和候选 commit/reject 入口。
5. `lifeos/memory/retriever.py` 使用 substring、token/Jaccard 和中文字符覆盖率进行启发式排序；没有 embedding/vector 检索，目前 `vector_index` 只是存储镜像。

### 已确认的差距 / 风险

- **记忆模型过于粗粒度**：持久化分类只有 `user/project/feedback/reference`；候选与已采纳条目主要保存 `source/content/trace_id/created_at`，缺少统一的 `user_id`、`source_type/source_ref`、`scenario_type`、`project_id`、`authorization_scope`、置信度、有效状态/时间等领域字段。
- **来源归类存在静默兜底**：`lifeos/memory/updater.py` 未知 source 会默认写入 `project`，容易把新来源错误分类，而不是显式要求映射或保留中性来源。
- **检索范围不符合目标隔离模型**：`retrieve(query)` 对所有四个类别打分，不接收用户、场景或项目范围；空查询会返回全部记忆，可能造成不必要的上下文膨胀与跨项目泄漏。
- **管理器接口被绕过**：`lifeos/agent/runtime.py` 和 `lifeos/skills/detector.py` 直接调用 `_read()` 读取内部 store；调用者因此知道 JSON 内部布局，未来迁移会扩散改动。
- **画像还未实现**：当前没有由多条带溯源 Memory 生成全局/场景画像的模块或视图。
- **原始记录归档链路尚不完整**：对话事件保存于事件队列，但每日/阶段性计划与复盘尚未形成到 Memory 候选的统一来源接入；原始来源引用也未成为记忆记录的通用字段。
- **当前反思是摘要而非长期认知提炼**：`ReflectionEngine.reflect` 将用户输入和回答放进反思结果，尚无稳定性/置信度/范围判定。现有两阶段候选与用户审批是可复用起点，不应绕开。
- **配置/并发/迁移待查**：当前 JSON 文件写入路径需进一步验证并发写、崩溃恢复及已有 `.lifeos/memory.json` 的 schema 迁移策略，再决定是否调整存储。

> 以上为阶段 1 当时的观察；未知来源兜底与 schema 迁移问题已在阶段 2 修复。阶段 5 已完成显式范围过滤和项目隔离基线；自动场景识别另行决策，不作为显式隔离验收前置条件。

### 测试基线

执行命令：`python -m unittest discover -s tests -v`

结果：**8 tests passed**（2026-10-02）。覆盖候选重复提交、Markdown 往返、反馈聚合去重、事件重启恢复、候选审批 API、反思重试幂等、工具结果和技能用量。当前尚无场景/项目隔离、来源字段、画像生成、跨来源接入测试。

### 阶段 1 验收结论

阶段目标达成。当前架构的合适演进方向不是先接入更多后端或先优化成本，而是先定好统一领域契约，再让一个受控纵向切片贯通来源记录 → 候选 → 用户审核 → 有范围的召回。

## 阶段 2 执行与验收记录

### Goal

在不立刻更换持久化技术的前提下，为 Memory 定义最小、可迁移、可溯源的领域数据契约，并明确当前 JSON 数据的兼容/迁移策略。字段设计必须区分：原始来源记录（证据）、候选、已采纳的原子 Memory、动态画像视图；不能把它们继续混成 category/content。

### 已完成产出

1. 盘点各 source 的调用点与现有 payload，并确认每日/阶段计划复盘已存入 `StructuredStore`，但尚未接 Memory。
2. 增加可选 `source_ref`、显式 `scope`、`occurred_at`、可空 `confidence` 与 `confidence_method`；候选与已采纳条目都会保留这些字段。
3. 加入 schema v2。打开旧版 store 时升级一次，并先在 `backups` 留存迁移前快照；旧 `user/direct` 记忆按原语义设为 `global`，其余旧条目设为 `unassigned`，并保留原内容。
4. 未知 source 新写入时显式拒绝；`structured_entry` 必须显式提供目标 category；项目 scope 必须提供 `project_id`。
5. 后端 API 文档与前端 TS 类型已扩展为兼容可选字段；晋升规则未实现。

### 阶段 2 初步盘点（2026-10-02）

现有写入路径与载荷：

| 写入入口 | 当前 source | 当前内容 / 证据 | 观察 |
| --- | --- | --- | --- |
| 用户直接记忆更新 | `direct` | 任意 dict；没有稳定公共 schema | 目前主要由测试调用 |
| 对话反思 | `reflection` | `summary`、`intent_bucket`、回答、issues、`memory_type`、反思时间 | 保存了原始问句/回答摘要；不是可直接用于画像的原子认知 |
| 用户反馈 | `user_feedback` | rating、note、trace_id | `submit_feedback` 与 Global Agent 都会提议；借 `source_event_id` 去重 |
| 反馈聚合 | `feedback_analysis` | 汇总分数、计数、notes、suggestions | 依赖直接读取 store，可能把反馈分析结果当长期认知 |
| 外部知识 | `external` | 任意 dict | 当前只有 source 映射，没有已验证的正式接入路径 |
| 每日/阶段计划与复盘 | 尚未写入 Memory | `StructuredStore` 中的 `daily_plan`、`daily_review`、`phase_plan`、`phase_review` 记录；字段含 id/kind/date/title/content/mood/metadata/created/updated | 前端已能保存到 SQLite，但尚未进入候选 Memory 管线；这是合适的非 Agent 来源纵向切片候选 |

`source_event_id` 目前只记录在候选，提交后的 Memory 条目没有复制该键；候选记录暂时保留，故当前简单重试仍能查到，但若未来清理候选历史，幂等依据会消失。应由统一来源引用承担幂等与回溯，而非依赖候选垃圾箱永久保留。

### 契约实现

建议先把“载荷内容”和“管理该记忆的元数据”分开，不再让 `content` 内部承担来源与生命周期信息。概念上可采用：

```json
{
  "id": "memory-id",
  "source": "structured_entry",
  "category": "user",
  "source_ref": {
    "kind": "structured_entry",
    "record_id": "source-record-id",
    "record_kind": "daily_review"
  },
  "scope": {
    "kind": "scenario",
    "scenario_type": "learning",
    "project_id": null,
    "user_id": null
  },
  "content": {"claim": "用户在学习任务中倾向先做可运行的小例子"},
  "created_at": "...",
  "occurred_at": "...",
  "confidence": null,
  "confidence_method": null,
  "status": "candidate"
}
```

该字段草案已成为第一版契约，具体实现见 `lifeos/memory/schema.py` 和 `lifeos/memory/updater.py`。当前约定：

- 结构化规划/复盘的原文继续保存在 `StructuredStore`；Memory 保存提炼后的内容与 `source.record_id` 引用，只有需要核对细节时才回读原文。
- 候选与已采纳 Memory 共用可追溯的内容/来源/范围字段；候选状态和审核时间等仅属于候选生命周期；原始记录不强行塞进 Memory 条目。
- 范围采用明确类型表达（至少全局、场景、项目）；`scenario_type` 和 `project_id` 不由 `content` 或类别名隐式推断。
- 旧版记录在 `MemoryManager` 初始化时版本化迁移，先把完整旧 store 作为 backup 保存；schema v2 store 再次打开不会重复迁移或备份。
- 动态画像、embedding/vector 索引与运行缓存是可重建视图/索引，不应成为原始证据或 Memory 的唯一存储。

### 本阶段采用的默认选择

- `confidence` 可为空；非空时同时记录 `confidence_method`，数值范围为 0 到 1。
- 结构化记录统一使用 source `structured_entry`；落入哪个旧 category 必须由调用方显式指定。具体场景判定留在阶段 3。
- 缺少 `project_id` 不允许声明为 project scope；写入者可以显式选择 `unassigned`，后续召回阶段禁止未归属内容进入项目范围。
- 保留现有候选审核制；阶段 2 没有自动采纳行为。

### 阶段 2 验收

- 新增测试覆盖来源/范围/置信度从 candidate 到 committed entry 的保留、未知 source 拒绝、缺少 project_id 拒绝、旧 store 迁移备份且重复打开不再迁移。
- 阶段 2 验收时 `python -m unittest discover -s tests -v`：**13 tests passed**（2026-10-02）。
- `python -m compileall -q lifeos tests`：通过；`git diff --check`：通过。
- 前端 `npm run typecheck` 未能执行：当前环境没有 `tsc` 命令；未安装前端依赖。
- 当时尚未接入每日/阶段复盘候选生成，也未改检索过滤；随后阶段 3 与阶段 5 已分别完成首轮实现。

阶段 2 Goal 达成。

## 阶段 3 执行与验收记录

- 新增 `POST /entries/{entry_id}/memory-candidates`，仅接受每日/阶段计划与复盘记录；调用方必须提交已提炼的非空 `content`、显式 `category` 与 `scope`。
- 候选保存 `source_ref`，包含结构化记录 ID、kind 和 `updated_at` revision；同一来源 revision 与同一 claim/scope 的重试返回原候选，候选已 commit 时也不会重复创建。
- 原始规划/复盘全文仍只在 SQLite `StructuredStore`；Memory 存放调用方提供的 claim 和引用，不自动复制原文或自动生成画像。
- 候选仍经既有 commit/reject 生命周期；端到端测试验证来源可追溯、重试幂等及 commit 后仍无重复。
- **未实现**前端按钮，也未接入自动提炼/保存触发；后续由阶段 7 接用户审核 UI，提炼器需另行选择真实模型/策略。当前接口可供调用方显式使用。
- 阶段 3 验收：后端 API 纵向切片通过；完整测试结果在本次验证记录中。

## 阶段 5 验收记录

- `MemoryManager.retrieve(query, scope=None)` 与 `MemoryRetriever.retrieve` 接受可选 scope。
- 没有显式 scope 时仅召回 `global`；`scenario` scope 能召回全局 + 同场景记忆；`project` scope 能召回全局 + 同场景 + 相同 `project_id` 的项目记忆。`unassigned` 永不进入检索结果。
- `direct`（用户主动提供）且未指定 scope 的新记忆默认 global；迁移时也只把旧 `user/direct` 记忆认作 global，其它旧记忆保持 unassigned。
- `user_id` 匹配可过滤显式归属的 Memory；缺少请求 user_id 时不返回绑定到某用户的条目。该字段目前只是召回过滤，不是身份认证/授权机制。
- `LifeOSAgent.run`、`ChatRuntime.handle_message` 和 `POST /chat` 显式接收 `memory_scope`，传给检索并写入 `conversation.completed` 事件。`frontend/src/api/client.ts` 的 `sendChat` 可传可选 scope，但当前 UI 不传值；未指定时默认只使用全局记忆。
- 阶段 5 的 Goal 是建立可靠的显式隔离语义，不要求隐式场景识别。自动场景/项目识别暂缓，须另行决定规则/模型、置信度阈值、用户纠正方式和失败时的 fallback；在此之前保持 global-only 默认。
- 检索回归测试现覆盖默认 global-only、global+同场景+同项目层级、排除不同场景/项目/用户、排除 unassigned 与缺省 scope 的旧条目，以及排除 superseded 记忆。

## 阶段 4 验收记录

- 确认重复 reject 是幂等的；rejected candidate 不能 commit。
- 确认 committed candidate 不能 reject，避免状态回退。
- Markdown 导入/导出往返保留 `source_ref`、`scope` 等原有元数据；现有条目的内容编辑/删除会被拒绝，避免绕开版本生命周期。
- 已确定纠错原则：候选记忆可自动整理；已采纳记忆的实质纠正不得静默覆盖；用户明确调用纠正操作时创建新版本、标记旧版为 `superseded`，并保留 `version_of` / `superseded_by` 及原证据引用。
- 已确定撤回/删除边界：疑似过时可待确认但自动冲突判定尚未实现；用户明确调用撤回后标记 `retracted` 并不可召回；彻底删除是独立强操作，本阶段未实现。撤回不删除原始来源。
- 已实现 `POST /memory/{id}/correct` 与 `POST /memory/{id}/retract`；重复相同纠正、重复撤回均幂等。superseded/retracted 记忆被检索过滤，向量索引条目移除且缓存清空；记录本身与 backup 保留。
- `MemoryPanel` 已提供显式纠正表单与撤回二次确认；preview 模式禁用操作。后续任何调用方仍必须对应用户明确意图，反思/提炼流程不得自动调用。
- Markdown 导入仍可读写新条目，但禁止删除已有条目或原位改写已有内容，须通过显式纠正/撤回操作维持生命周期语义。
- 本阶段不实现自动冲突识别，也不伪造 `needs_confirmation` 运行态：当前没有经验证的冲突检测器或结构化冲突证据生产者。所有候选仍必须经用户显式 commit/reject；检测器接入后再引入冲突专属状态与转换。
- 硬删除、原始来源删除、备份保留策略及跨持久层级联清理是独立的强操作，明确不属于本阶段 MVP。

### 验收标准

- 已覆盖 commit/reject 的幂等和非法状态转换；不重复应用或回退状态。
- Markdown 往返保留来源引用、scope 和运行时状态；既有条目不允许由导入流程静默覆盖或删除。
- 用户显式纠正产生关联新版本，旧版不再参与召回；用户显式撤回产生 tombstone，原始来源不被删除。
- 自动冲突识别和硬删除不是本阶段 MVP 验收项；前者等待可靠检测器和证据契约，后者等待删除授权、范围及级联/备份策略。

### 阶段 4 完成边界与后续项

本阶段 Goal 已达成：候选 commit/reject 与已采纳记忆纠正/撤回的状态转换明确、可重放且有审计关联。为避免把未经验证的语义判断做成自动行为，后续扩展遵循以下边界：

- **冲突识别后续项**：未来检测器必须提供候选 ID、目标 active Memory ID、双方来源引用及检测理由；标记冲突本身不能改变当前 active 版本。用户确认后走显式版本替代流程，拒绝后候选进入 rejected；目标在确认前若已非 active，操作必须冲突失败。不能仅因两条文本相似就自动覆盖或撤回记忆。
- **画像后续项**：阶段 6 已实现按需重建的画像视图，只消费 active Memory；superseded/retracted 状态变化后重建，不将旧版回流。自然语言 persona 摘要仍未实现。
- **物理删除后续项**：单独定义授权、删除范围、备份保留、原始记录是否删除、索引/缓存/画像级联、部分失败重试与完成状态，再实现不可逆清理。
- **身份与权限后续项**：当前本地原型依赖 UI 的明确操作文案；多用户身份认证和服务端授权尚未接入，不应将其描述为安全边界已由 API 强制保障。

### 本阶段验收结论

- commit/reject 重放幂等；拒绝候选不能 commit，已 commit 候选不能 reject。
- 相同纠正重放返回同一版本；superseded/retracted 条目的非法二次修改在管理器层拒绝，HTTP API 返回 409。
- superseded/retracted 条目不参与召回，向量索引移除、缓存清空；历史条目和来源引用保留。
- Markdown 导入不能绕过生命周期端点改写或移除既有条目。
- 不跨项目/场景晋升，不执行自动冲突覆盖，不做物理删除。

## 阶段 6 验收记录

- 新增 `MemoryManager.profile_view()` 和 `GET /memory/profile`，每次请求从当前权威 Memory store 动态重建，不持久化派生画像、不修改原 store，也不调用 LLM。
- 视图按 `user_id` 与 scope 隔离为 `core_profiles`、`scenario_profiles`、`project_profiles`；项目画像按 `project_id` 单独分组，不向场景/全局自动晋升。
- 仅纳入 active 且 scope 有效、非 `unassigned` 的记忆；候选、拒绝、superseded、retracted 与畸形 scope 均不进入画像。
- 每条画像 Memory 保留 claim、source/source_ref、evidence_source_ref、scope、created/occurred 时间、confidence/method、trace 和版本关联，支持未来 UI 解释来源。
- `version` 为不含 `generated_at` 的派生内容 SHA-256：输入内容未变时稳定，任何画像成员或内容变化时更新。无画像时返回空 profile 数组。
- 阶段 6 仅完成结构化可解释读模型；尚不生成 LLM 自然语言 persona、画像编辑 UI 或对画像内容自动归纳/提升，这些由后续阶段决定。

### 阶段 6 验收标准

- 同一权威 store 可重复生成相同 version；画像读取不写回 store。
- 不同 scope / user / project 不混组；没有身份认证时不得将 user_id 过滤误称为访问控制。
- correction 后画像仅出现新 active 版本；retraction 后对应记忆从画像中消失。
- API 契约与 TypeScript 只读类型同步；前端可编译。

## 阶段 7 验收记录

- Memory 后台新增“画像”只读页，按全局核心、场景、项目分组展示当前 active Memory；每条内容展示来源引用、来源修订、scope、发生时间及可用的置信度/方法。画像数据仍通过 `/memory/profile` 动态重建，不写入新的权威存储。
- 候选卡和已采纳记忆卡均展示来源与 scope；候选仍需用户显式采纳/拒绝，预览模式禁用写入操作。
- 每日/阶段规划与复盘保存后可手动打开“从这条记录提炼一条记忆候选”：用户自行撰写认知并显式选择全局、场景或项目范围。项目范围必须填写项目 ID；没有自动抽取、默认 scope 或自动采纳。提交后候选回到后台候选列表等待审核。
- 相关实现：`frontend/src/App.tsx`、`frontend/src/api/client.ts`、`frontend/src/panels/MemoryPanel.tsx`；使用既有 `POST /entries/{id}/memory-candidates` 与 `GET /memory/profile`，后端契约未改变。
- 构建与类型检查通过；本地需启动真实后端并手动走一遍“保存规划/复盘 → 提炼候选 → 后台审核 → 画像出现”的浏览器端流程。本轮尚未做浏览器自动化/人工截图验收。

## 阶段 8 验收记录

- 原阶段 8 文档曾错误得出“腾讯 DB 暂不作生产后端、ai-memory 为可选参考”的结论。用户指出目标是实际使用两者后，已纠正该结论，撤销“只有参考/可选”的决策。
- 当前目标边界：`ai-memory` 实际承担项目 wiki、执行轨迹和 handoff 的项目连续性；TencentDB 实际承接已审核 L1 及其有溯源的 L2/L3；LifeOS 承担多源接入、授权、候选审核、身份/scope 映射、UI 和任务级编排。
- LifeOS `.lifeos/memory.json` 是现阶段可运行的本地 MVP。目标是完成 TencentDB 迁移后将 TencentDB 作为 active L1-L3 权威、本地 store 保留只读归档/回滚；迁移前暂以 LifeOS 本地 store 为现行权威，不双写。
- `docs/memory-provider-boundaries.md` 已改为目标集成与职责文档；`docs/lifeos-workflow-and-memory-architecture.md` 的图和正文同步修订。
- 接口仍有明确待验收项：TencentDB v3 API 如何满足 LifeOS 用户审核后写入 L1；L0 原始内容复制/引用策略；LifeOS 用户/项目/场景到 TencentDB team/agent/user/session 的身份映射；跨系统纠正/撤回/删除与一次性迁移。
- 阶段 8 现在只完成目标职责与权威边界设计，不代表任何外部后端已集成。阶段 9 改为实际适配与切换，阶段 10 才做评测、cost/efficiency。

## 阶段 9 进度记录（TencentDB L1 首个代码切片）

- 阶段 9 初版新增 `lifeos/memory/providers/tencentdb.py` 并确认旧上游 `/atomic/update` 是 update-only，未绑定首写当时 fail-closed。该初版状态已由下方 2026-10-05 记录更新：LifeOS 当前按本地 Draft PR #1604 的 `/v3/atomic/create` 契约走首次创建；仍未完成真实 Gateway 联调。
- 只有 LifeOS 用户已批准并 commit 的 active Memory 才能写入 L1；候选状态直接调用 provider 会被拒绝。规划/复盘候选、对话反思候选和用户反馈候选都沿用同一个批准闸门；原始 LifeOS 对话事件仍留在本地，不复制到 TencentDB L0。
- `POST /memory/candidates/{id}/commit` 在本地 commit 后尝试同步；错误会以不含正文的错误类型保存为 `provider_sync=pending`，可通过 `POST /memory/providers/tencentdb/sync-pending` 重试。纠正/撤回会尝试删除旧远端 L1 并写入新版本；召回时额外以本地 active ID 白名单拦截远端陈旧项。
- ChatRuntime 已将 TencentDB L1 召回并入本轮上下文；远端结果必须带有效 LifeOS provenance、在本地仍 active，且 scope 可见，否则拒绝注入。provider 故障 fail-open：保留本地召回，并记录不含敏感内容的 trace 错误类型。
- 适配器通过环境变量启用：`LIFEOS_TDAI_ENDPOINT`、`LIFEOS_TDAI_SERVICE_ID`、`LIFEOS_TDAI_TEAM_ID`、`LIFEOS_TDAI_AGENT_ID`、`LIFEOS_TDAI_USER_ID`，可选 `LIFEOS_TDAI_API_KEY`、`LIFEOS_TDAI_TIMEOUT_SECONDS`。必须提供完整身份；本阶段只允许 loopback Gateway，未配置时完全关闭。未运行 Gateway 联调，也未发送任何真实记录。
- 官方 v3 SDK 契约核对：`updateAtomic` 使用身份、session、id、content、background；`searchAtomic` 使用身份、query、limit；`deleteAtomic` 按明确 ids 删除。服务端 handler 进一步证明 update 只更新既有 ID；本地 Draft PR #1604 补充 create-only API 契约，LifeOS 适配器已按该契约改造（见 2026-10-05 记录）。不能把 `/offload/ingest` 异步抽取误当直接写入替代。
- scope 隔离约束：上游 `searchAtomic` 请求没有 `session_id` 字段，不能依赖服务端按项目/场景过滤。因此 LifeOS 将 scope 保存在 `background` provenance 并在本地 fail-closed 过滤；无合法 provenance 的远端结果不参与召回。该机制尚待真实 Gateway 契约测试验证。
- 当前对话以“对话事件 → 本地反思候选 → 用户审核 → L1”接入，未做原始 L0 复制。2026-10-08 起，自动反思候选仅保留 intent bucket、响应状态和阻断类诊断，不再复制用户原话或助手完整回答；该候选标记为需用户再提炼，默认 scope 为 `unassigned`，不能直接跨域召回或同步到 TencentDB。multi-agent 轨迹尚无稳定协议，后续以含 `source_ref/scope/agent/task/time/event_type` 的最小事件适配，不要求等 executor 完工；原始工具输入/输出默认留在 LifeOS 本地轨迹，不自动外发。
- `ai-memory` 尚未接入：它继续负责 coding project wiki/lifecycle/handoff 的权威与召回；LifeOS 不复制其原始轨迹或 wiki。需要沉淀为通用用户认知时，再回到 LifeOS 候选/审批后进入 TencentDB。阶段 9 后续仍须显式绑定 workspace/project 并完成真实只读召回隔离测试。
- 新增 [`docs/tencentdb-approved-atomic-create-proposal.md`](tencentdb-approved-atomic-create-proposal.md)：最初记录审核友好的 create API 契约建议；后续据此准备 Draft PR #1604，细节见 `docs/tencentdb-atomic-create-pr-handoff.md`。
- 迁移/切换尚未发生。本地 `.lifeos/memory.json` 仍是现行权威；此切片用于接口/状态验证，不代表已有 active 数据已迁移或已进入长期双写。
- 初版离线回归覆盖身份配置 fail-closed、loopback 限制、L1 provenance、HTTP 契约、scope 过滤和 active-ID 白名单；因 create-only API 当时尚不存在，首写被 fail-closed。该部分现由 2026-10-05 纵向切片更新：新建/更新分流和生命周期重试测试已加入，全部仍为合成数据，纠正/撤回实际行为仍需隔离 Gateway 验收。

## 风险与未决决策

- 每日/阶段记录当前采用“用户手动撰写认知并提交候选”的显式触发方式；后续如增加 AI 辅助提炼，需单独设计授权、确认、错误更正和范围选择，不可静默自动写入。
- `confidence` 的生成/校准策略仍待设计；目前它是 nullable metadata，不代表客观概率。
- 缺失 `project_id` 的候选必须使用 `unassigned` scope，且当前检索器排除该类记录。
- 自动场景/项目识别尚未实现；在设计出可审计、可纠正的 resolver 与 fail-closed fallback 前，UI 未传 scope 时应保持 global-only。
- `/memory` 当前返回整个内部 store；后续设计需要考虑 API 向用户暴露范围、候选和运行态存储的分离。
- ai-memory workspace/project 显式映射与只读适配仍未实现；TencentDB 仅完成首个 L1 代码切片，尚未通过真实 Gateway 契约联调和完整隔离测试；本阶段禁止生产/远程写入。
- TencentDB L2/L3 生成、读取及 generation refs 尚未接入；当前 scope 过滤依赖 TencentDB 搜索结果稳定返回 `background`，必须用真实 Gateway 验证。
- 成本和效率优化暂不作为当前实现阶段的目标；先建立召回正确性、隔离性和可追溯性基线。

## 本次最新验证记录（2026-10-03）

- `python -m unittest discover -s tests -v`：**23 tests passed**，包括画像视图分组、来源保留、稳定版本、读取无写入，以及纠正/撤回后的重建测试。
- `python -m compileall -q lifeos tests`：通过。
- `git diff --check`：通过。
- `frontend/` 中 `npm run typecheck`：通过（`tsc --noEmit`）。
- `frontend/` 中 `npm run build`：通过（49 modules transformed；本轮页面交互尚未做浏览器自动化验收）。
- 阶段 7 再次通过 `npm run typecheck`、`npm run build`、`git diff --check` 与 Python 23 项回归；前端 UI 流程仍需浏览器手工验收。
- 阶段 8 `python -m unittest discover -s tests -v`：23 tests passed；`python -m compileall -q lifeos tests` 与 `git diff --check` 通过。本阶段没有运行时代码变更。
- 本次应用户反馈修订阶段 8 架构方向：只改文档，`git diff --check` 通过；运行测试集无需重跑，因无代码变更。
- 自动场景识别与自然语言画像总结未实现。
- 阶段 8 只修改 `docs/memory-provider-boundaries.md`、整体架构和交接文档；工作区原有未跟踪的上游仓库、图稿和交接内容均保留。
- 阶段 9 TencentDB L1 当前切片：`python -m unittest discover -s tests -v` **28 tests passed**；`python -m compileall -q lifeos tests` 和 `git diff --check` 通过。新增的 404 合成测试对应上游已读到的服务端行为；本机 TencentDB Gateway 尚未运行，因此无真实服务 E2E。
- 2026-10-03 进一步核对 TencentDB 当前默认分支 `feat/server_team`：部署文档虽列 `/v2/atomic/add` 并声称有 Service E2E，实际路由只有 `/atomic/update/query/search/delete/count`；`handleAtomicUpdate` 对缺失 ID 返回 404；TS/Python SDK 均无 L1 create/add；当前 checkout 也没有文档所列的 MemoryCore E2E 脚本或 MemoryCore 测试文件。结论是“文档与代码不一致，实际创建路由缺失”。
- 新发现的实现阻塞：`IMemoryStore` 仅提供 `upsertL1`。本仓库 TCVDB adapter 使用覆盖式 upsert，故不能以 read-then-upsert 实现“相同请求重试幂等、不同 payload 冲突且绝不覆写”的 atomic create。官方 VectorDB `/document/upsert` 文档称同 ID 会替换，但官方 FAQ 又称 insert 不覆盖已有 ID；FAQ 未说明对应 endpoint/SDK method、版本或并发保证。TCVDB 原语结论应保持“待确认”，不能断言服务端没有。
- 已更新 [`docs/tencentdb-approved-atomic-create-proposal.md`](tencentdb-approved-atomic-create-proposal.md)，补入默认分支核验和存储层原子写阻塞；另准备 [`docs/tencentdb-atomic-create-issue-draft.md`](tencentdb-atomic-create-issue-draft.md) 作为待审 issue 草稿。下一步应先请 TencentDB 维护者确认 TCVDB 可用的条件插入/幂等语义、API 命名与文档/E2E discrepancy，再实施跨后端 handler、store、SDK 与测试；本机克隆位于 `upstream/TencentDB-Agent-Memory`，当前 `feat/server_team` 工作区未修改。
- 用户已报告该 issue 已提交；源码公开，因此转为自行基于当前代码准备 PR，而非等待维护者回复。
- 2026-10-04 上游分支 `feat/atomic-create-approved-memory` 已新增 `/v3/atomic/create` 路由（v3-only）、TS/Python v3 SDK、Gateway 合成测试、SQLite audit CHECK 迁移，并扩展 `metadata` 到 create→query/search 往返。用例覆盖 v2 不暴露 create、新建、相同 payload 重试、不同 payload 冲突、跨用户隐藏、缺少锁后端 fail-closed、provenance round-trip；部署文档中的虚构 `/v2/atomic/add` 已移除，缺失的 Service E2E 已标记为当前 checkout 不可复现。
- 2026-10-04 再核验修正：不应只把 PR 承诺收窄成“Gateway 内由 lease 协调”，因为该方案仍调用覆盖式 `upsertL1`，不能阻止绕开 Gateway 的写入，也没有写入 fencing；租约到期后在途 upsert 不可撤销，故仍可能覆盖，不能作为 create-only API 保留。官方 `/document/update` 是已有文档的更新路径；VectorDB `/document/upsert` 文档称同 ID 替换，而官方 FAQ 又称 insert 不覆盖。FAQ 未指出具体 endpoint/SDK method、版本和并发保证，TCVDB 原语状态应视为未确认。详情和新的实现方案已写入 [`docs/tencentdb-approved-atomic-create-proposal.md`](tencentdb-approved-atomic-create-proposal.md)。
- 2026-10-04 已按用户同意开始重做：`IMemoryStore` 增加可选 `createL1`；SQLite 用普通 INSERT（同主键冲突不会更新），Mongo standalone/replica set 用 `insertOne`（重复键返回冲突）；Gateway 现在用存储层插入结果裁决竞态，不再把分布式 lease 当原子性依据；同 payload 并发重试读回后幂等成功，异 payload 冲突。TCVDB 未实现能力，Mongo sharded topology 也因全局唯一键不确定而禁用；两者 Gateway 均返回 `501`，不调用覆盖式 upsert。新增 Gateway 并发同/异 payload 与 unsupported store 测试、SQLite store 测试、Mongo fake-driver 单测和 shared store contract 测试；API/deployment/SDK 文档及 changelog 已注明支持范围。
- MongoDB 官方文档说明分片集合在 `_id` 非 shard key 时只按 shard 强制唯一；当前存储层利用既有 `hello` topology probe 对 sharded 部署禁用 create。若未来为 Mongo sharded 设计包含全局 ID 的唯一 shard/index 方案，再单独启用。证据：[MongoDB sharded unique index 限制](https://www.mongodb.com/docs/manual/core/sharding-shard-key-indexes/)。
- 本轮新增真实 SQLite store 测试（重复 ID 不覆盖）与 Mongo insertOne fake-driver 单测（重复键不覆盖、其他错误继续抛出），以及 Gateway 同/异 payload 并发与 TCVDB unsupported 测试；这些测试尚未执行。
- 本轮验证：Node 24 `--experimental-strip-types --check` 对 router、Gateway/store tests、SQLite/Mongo store、store types 通过；`git diff --check` 通过。`npm test -- --run src/gateway/v2-router.atomic-create.test.ts` 未能运行，因无 `node_modules`/Vitest；未安装依赖，尚无 TS typecheck 或真实 SQLite/Mongo Gateway 验收。工作分支仍 `feat/atomic-create-approved-memory`，未 commit/push/PR。
- 2026-10-04 本轮复核：Node 24 `--experimental-strip-types --check` 对 Router、SQLite/Mongo store 和新增三个测试文件通过；nested `git diff --check` 通过。确认 shared store contract 目前只有定义、没有调用方，故新增 contract test 不会自动执行；已有具体 SQLite 测试及 Mongo fake-driver 测试补上覆盖。依赖目录不存在，Vitest 与 TypeScript typecheck 仍无法执行；按用户要求未安装。进一步检查确认本仓库 TCVDB client 只调 `/document/upsert`；腾讯官方 Go SDK API 模型公开 `UpsertReq`、`UpdateReq`，未发现独立 document insert request，但 FAQ 仍称 insert 不覆盖且未给出并发保证。结论仍是“现有 adapter 无原子 create”，不是“服务端确定没有原语”。方案与 issue 草稿已写清待维护者澄清的问题。未 commit/push/PR。
- 当前明确的下一步 goal：获取 FAQ 所指 insert 操作的具体 endpoint/SDK method、版本、重复 ID 响应与并发保证；再决定是否能实现 TCVDB `createL1`。同时在依赖已提供的环境中运行本分支 Vitest 与 TS typecheck。在这两项未完成前，不把该分支视为可提 PR 的完整 TCVDB 能力实现。
- 2026-10-04 按用户授权已创建 Draft PR [#1604](https://github.com/TencentCloud/TencentDB-Agent-Memory/pull/1604)，base=`feat/server_team`，head=`yubr-zzh:feat/atomic-create-approved-memory`；commit `9979d4e` 带 DCO sign-off。PR 如实注明当前 partial support、TCVDB fail-closed、文档矛盾待维护者澄清，以及 Vitest/typecheck 未运行。当前 fork 原先没有该分支，已成功推送；上游没有被直接推送。尚未合并。

## 交接给下一位 Agent

### 2026-10-05 阶段 9 LifeOS 腾讯云 L1 写入纵向切片（覆盖上方旧状态）

- LifeOS `TencentDBMemoryAdapter` 现在按腾讯仓库本地 Draft PR #1604 的契约路由：未绑定时 `/v3/atomic/create`，绑定相同确定性远端 ID 时 `/v3/atomic/update`；binding 不一致 fail closed。
- 对已批准 active memory 才构造外发 payload；显式映射类别 `user/project/feedback/reference` 到 TencentDB `persona/work_fact/episodic/work_artifact`，附 LifeOS source/scope/confidence provenance。请求身份仍必须来自完整显式配置，Gateway 仅允许 loopback。
- 修复 provider-sync 重试状态会清空 remote ID 的问题；若更新请求成功但响应超时，重试仍会走 update。修正 memory 使用新 ID，移除从旧 memory 复制来的 provider binding，避免错误更新旧记录。
- 验证：5 个聚焦测试通过；`python -m unittest discover -s tests -v` **30 tests passed**。测试使用 fake transport 和本机合成 HTTP stub；未安装依赖、未启动真实 TencentDB Gateway、未发送真实用户数据。
- 上游依赖状态：`upstream/TencentDB-Agent-Memory` 本地分支 `feat/atomic-create-approved-memory`，Draft PR #1604 尚未合并；它的 atomic/create 未支持 TCVDB（unsupported backend 会 fail closed）。因此这只是按待审 API 契约准备 LifeOS adapter，不能算真实 Gateway / TCVDB 端到端适配完成。
- 下一步 goal：在 PR #1604 API 契约稳定且有可运行的隔离 Gateway/backend 后，用合成租户验证首次 create、相同 payload 重试、不同 payload 冲突、更新、纠正、删除和 recall provenance/scope；之后再处理 L2/L3 和 ai-memory 项目 adapter。身份按 project/scenario 映射与后端物理隔离仍需设计/实测，当前本地过滤不等同物理隔离。
- 本次只修改 LifeOS adapter、生命周期同步状态处理、回归测试和两份阶段文档；未修改 nested TencentDB 源码，未 commit/push/PR。保留所有原有未跟踪文件和用户工作。

### 2026-10-05 阶段 9 ai-memory 项目只读与提示词传递切片

- 新增 `lifeos/memory/providers/ai_memory.py`：Loopback-only `/api/v1/search` + page-read client；只接受精确的 `LIFEOS_AIMEMORY_PROJECT_MAP`，不 fallback 到全局/未映射项目；限制最多 3 页、单页 6,000 字符，只读，不创建或改写 ai-memory 内容。
- ChatRuntime 仅在本轮显式 `memory_scope.kind=project` 且存在精确映射时查 ai-memory。页面文本只作为当前模型请求的临时证据；LifeOS event/trace 仅记录 provider/source refs/数量，不保存外部页面正文。
- 发现并修复上下文协议缺陷：API 分支的 LLM adapter 会归一化消息，只发送标准 `role`/`content`，因此旧 Executor 的自定义 `memory` 字段会被静默丢弃。Executor 现将 approved memory 与 project evidence 以 JSON 数据块加入用户消息文本，并在 system 指令中标记为不可信引用材料；敏感正文不进入 trace/event。
- TencentDB 身份隔离补齐：`LIFEOS_TDAI_SCOPE_MAP` 显式映射 `project:<id>` / `scenario:<type>` 到 team/agent/user/session；未映射 scope 不发送写入或搜索请求。provider sync 保存 scope+坐标指纹；重试、纠正和删除校验 binding，配置映射漂移 fail closed。
- 环境配置入口：TencentDB 使用既有 `LIFEOS_TDAI_*` 基础变量及 `LIFEOS_TDAI_SCOPE_MAP` JSON；ai-memory 使用 `LIFEOS_AIMEMORY_ENDPOINT`、可选 `LIFEOS_AIMEMORY_API_TOKEN` 和 `LIFEOS_AIMEMORY_PROJECT_MAP` JSON。两者当前都要求 loopback 服务。
- 验证（本记录初版）：`python -m unittest discover -s tests -v` **35 tests passed**；`python -m compileall -q lifeos tests`、`git diff --check` 通过。调用为 fake transport/loopback stub，没有真实 ai-memory daemon 或 TencentDB Gateway E2E，也未发送真实个人数据。
- 阶段 9 未完成：缺 TencentDB create PR merge/可运行 backend；TCVDB atomic create unsupported；TencentDB L2/L3 + generation refs 和实际远端生命周期未接；ai-memory live token/project isolation 未接；迁移切换/回滚未做。不能用离线测试宣称真实适配完成。
- 同步只读审查远程 `origin/api&nonAgent`（`0886317`）：它是当前 `zhang-memory` 基线的直接后代，但含 31 个文件、约 8.5k 行变更；改动与本地未提交的 `server.py`、Chat runtime、executor、测试文件重叠。当前不能在脏工作区直接合并，也不建议未验收就整支采纳。
- 审查发现需先处理的风险：API 无认证但可配置非 loopback 监听；模型 API key 以明文保存在 `.lifeos/models.json`（Windows 上 `chmod(0600)` 不能作为 ACL 保障）；`ThreadingHTTPServer` 并发访问尚无锁的 JSON-backed Memory/Event 等状态，可能丢失更新；`/models/test` 可使用请求提供的自定义 URL，需纳入 SSRF/本地服务访问边界。远程分支测试本轮未运行，不能宣称已通过。
- 后续建议先保护当前阶段 9 改动并完成可运行服务的端到端门槛；再按 API 分支功能切片验证、修正上述边界和补并发回归测试，最后才决定是否整合。当前未 commit/push，保留现有工作区改动。

### 2026-10-05 阶段 9 本地 HTTP mock 验收

- 新增两个仅含合成数据的 loopback HTTP mock 集成测试：ai-memory mock 验证真实 HTTP/JSON/Bearer 流程、显式 workspace/project 参数及拒绝隔壁项目命中；TencentDB mock 连接真实 LifeOS 审核 API 与真实 `urlopen` adapter，覆盖候选不外发、首次 create 返回 503、pending 重试 create、重复批准走 update、按允许 ID 召回、纠正时旧 ID 删除/新 ID 创建、撤回删除新 ID。
- TencentDB mock 使用确定性 create-only 语义，冲突 payload 返回 409；这些用例验证的是 LifeOS client 与本地 mock 的集成行为，不等同于上游真实 Gateway / TCVDB 的兼容性证明。
- 最新验证：`python -m unittest discover -s tests -v` **37 tests passed**；`python -m compileall -q lifeos tests` 与 `git diff --check` 通过。无真实 key、真实后端或个人记忆参与。
- 阶段 9 仍未整体完成：真实上游 API E2E、TencentDB L2/L3 生成及 refs、ai-memory daemon 权限/邻接项目隔离、迁移/回滚尚未验收；当前不切换权威、不双写，不 commit/push。

### 2026-10-06 `api&nonAgent` 分支集成记录

- 已把队友的 API/console/routing 分支集成到 `zhang-memory` 工作区；ChatRuntime 保留 Planner 路由，并且只在 `force_agent`/Agent 决策及显式 project scope 下查询 ai-memory。项目正文仍只作为当前模型请求中的不可信引用，不写入 LifeOS event/trace。
- 修复安全边界：非 loopback API listener 必须配置 `LIFEOS_API_TOKEN`，远程请求需 Bearer 校验；Windows 模型 API key 用当前用户 DPAPI 加密，并在下次读取时迁移旧明文 key。Loopback 仍按本机可信边界处理；其他平台依赖文件权限。
- 为 `ThreadingHTTPServer` 下的 JSON-backed Memory、EventBus、SkillRegistry 读改写增加实例级锁；合成多线程测试确认并发候选与事件写入没有丢失。
- 验证：`python -m unittest discover -s tests -v` **53 tests passed**；`python -m compileall -q lifeos tests`、`git diff --check`、`npm run typecheck`、`npm run build` 通过。Playwright 前端-only smoke 渲染了页面且无 JS page error；后端未启动以免读取本地 `.lifeos` 数据。
- 此处尚未 commit/push；前端/模型 provider/Planner 新功能尚未做真实 provider API 联调。TencentDB/ai-memory 真实端到端与阶段 9 迁移验收仍未完成。

### 2026-10-07 合成用户的全局 + 项目记忆纵向验收

- 扩展 `test_tencentdb_approval_retry_lifecycle_against_isolated_http_mock`：在临时目录中创建合成用户 `synthetic-user` 的每日复盘来源（全局记忆）和阶段规划来源（`lifeos-sandbox` 项目记忆），经 LifeOS HTTP API 提交候选；断言来源记录 ID/revision 可追溯、原始记录正文不会复制进候选/远端 atom，且候选在用户批准前不发送到远端。
- 合成 TencentDB Gateway 首次对全局 create 返回 503；项目候选按显式项目坐标成功写入；重试只同步待处理的全局 atom。断言全局与项目使用不同的 team/agent/session 绑定，重复批准使用 update，画像视图能分别列出全局/项目记忆并保留来源与置信度，按范围召回可命中相应记忆。
- 继续验证项目记忆纠正会以新 ID 替换旧 atom、撤回只删除项目 atom 且保留该用户的全局记忆。其他既有用例另行验证混合结果中的隔壁项目、无效 provenance 和未映射范围 fail-closed。
- 验证：定向合成 Gateway 用例通过；完整 `python -m unittest discover -s tests -v` **53 tests passed**；`python -m compileall -q lifeos tests` 与 `git diff --check` 通过。所有数据均在测试临时目录，未读取或改写真实 `.lifeos` 数据。
- 结论边界：这证明 LifeOS API、生命周期、画像和 TencentDB adapter 在本地 stub 下的全局/项目行为贯通；它不证明真实 Gateway/TCVDB 兼容性，也没有调用 LLM 自动提炼。TencentDB L2/L3 生成及 generation refs、真实 ai-memory 服务/权限、迁移与回滚仍未验收；阶段 9 仍未整体完成，暂不需要提供 API key。
- 下一步 Goal：等具备包含 atomic-create 契约的隔离 TencentDB Gateway 后，用同一组脱敏合成场景做真实协议 E2E；随后连接隔离 ai-memory 服务验证两个相邻项目。真实用户数据接入前继续使用临时目录与显式授权。

### 2026-10-08 阶段 9 本地 Gateway 可运行性核对

- 检查 `upstream/TencentDB-Agent-Memory/MemoryCore`：本地分支包含 `/v3/atomic/create` 路由和 `feat/atomic-create-approved-memory` 实现；Gateway standalone 配置绑定 `127.0.0.1`、SQLite、BM25，`atomic/create` 路径本身不调用 LLM，因而该纵向验收不需要真实模型 API key。
- 经用户许可后，在该目录运行 `npm install --no-save --package-lock=false --ignore-scripts`；依赖仅落在被忽略的 `node_modules/`，未生成 lockfile、未修改上游源码。启动真实 Gateway 于 loopback + 临时 SQLite `TDAI_DATA_DIR`，使用合成 Bearer key 与身份，不调用模型 Provider。Gateway 启动日志有 `D:\data\log` 写入 EPERM，但服务可正常响应；测试结束后已停止服务并删除精确的临时 SQLite 数据目录。
- 真实 LifeOS HTTP → approval → adapter → Gateway SQLite → recall：单条全局记忆通过；批准前远端搜索为空，批准后 `/v3/atomic/create` 写入并可召回，重复批准走 update 且成功；远端结果没有原始复盘文本。该结果只证明单条写入链路。
- 真实多记忆测试暴露阻断缺陷：首条记忆写入后，再用同一 `service_id` 创建不同新 ID 时，上游 `/v3/atomic/create` 返回 409；若换不同 team/agent，则错误返回 404。源码证据：`handleAtomicCreate()` 调 `queryL1Records({recordIds:[input.id]})`，但当前 SQLite `queryL1Records()` 实现忽略 `recordIds` 并返回所有记录，继而把别的 atom 当成目标 ID 冲突。LifeOS adapter 正确保留 `pending`，没有误标 synced。当前无法靠 LifeOS adapter 安全绕过此行为，需先修上游查重实现/契约。
- 上游 focused Vitest `node_modules/.bin/vitest.cmd run src/gateway/v2-router.atomic-create.test.ts` 结果 **7 passed, 1 failed**：atomic-create fixture 的首条创建与幂等重试断言通过，但随后 query 断言返回 500；fixture 的 `queryL1Records` 假函数要求必传参数，而被测 `/atomic/query` 合法地无参调用它。该失败表明现有 focused test fixture 还不完整；未修改上游文件。
- 本仓库 `python -m unittest discover -s tests -v` **54 tests passed**，`python -m compileall -q lifeos tests`、`git diff --check` 通过。真实 Gateway E2E 暴露的问题不在 LifeOS stub suite 中。
- 下一步 Goal：用户确认后，在上游本地 `feat/atomic-create-approved-memory` 上补 `queryL1Records` 的 exact-ID 过滤及 regression test（多个不同 ID、相同 payload 重试、跨租户 ID 碰撞），修复 atomic-create fixture 的无参调用，再重跑 SQLite/Gateway focused tests；随后重跑本 LifeOS 真实 Gateway 多项目隔离、纠正/撤回、重启持久化 E2E。ai-memory 真实只读隔离已用 2.4.1 binary 验收，待当前源码版本可运行时再回归。Agent/tool 原始轨迹不自动外发，只允许用户审批后的提炼候选进入记忆。

### 2026-10-08 ai-memory 真实 HTTP 只读隔离验收

- 使用工作区已有 `upstream/ai-memory/target/debug/ai-memory.exe`（版本 2.4.1），在专用临时 data-dir 启动 loopback HTTP 服务；禁用 watcher / embedding / LLM，不请求外部模型。通过服务管理接口写入两份合成项目页，再从 LifeOS `AiMemoryProjectAdapter` 调真实 `/api/v1/search` 与 page-read。
- 两个明确映射项目各自能搜索并读取自己的页面；用项目 A 独有 token 搜索项目 B 返回 0；unmapped project 与 global scope 不发起外部查询。验收通过；服务已停止，临时 wiki/index 数据已删除。
- 该结果证明当前只读 API 契约和相邻项目隔离能在真实服务上工作；二进制版本为 2.4.1，早于工作区当前源码，未来应以实际部署/更新版本再回归一次。原 `upstream/ai-memory` 工作区已有 `crates/ai-memory-hooks/src/payload.rs` 修改，未触碰、未清理、未提交。

### 2026-10-08 对话反思候选隐私收敛

- 发现旧 `ReflectionEngine.reflect()` 将原始 `user_input` 与完整助手 `response` 复制到 `reflection` memory candidate；虽然候选默认 `unassigned` 且远端仍要用户批准，但这偏离“原始记录留在来源库、长期记忆只存提炼认知”的原则。
- 现改为仅保存 intent bucket、响应是否存在、阻断类问题计数等结构化诊断，并标记 `requires_user_distillation=true`；不得把这类诊断当作用户画像事实。新增隐私回归测试先确认旧实现泄漏、再确认修复后不含合成敏感标记。
- 验证：全量 `python -m unittest discover -s tests -v` **54 tests passed**；`python -m compileall -q lifeos tests`、`git diff --check` 通过。真实 Gateway 单条全局写入/召回已另行通过，但多记忆 E2E 被上游 SQLite 查重缺陷阻断；ai-memory 服务验收未做。LifeOS 源码和测试变更未 commit/push。
- 后续仍需决定反思诊断候选在 UI 中是否应显示为“待用户提炼”而非普通待批准项；未确认前，保持不分配 scope、不自动远端同步。

1. 先读取仓库根目录的 `README.md`、本文和 `docs/lifeos-workflow-and-memory-architecture.md`。
2. 重新运行 `python -m unittest discover -s tests -v`，确认测试基线仍成立。
3. 阶段 2 至阶段 8（修订后目标边界设计）已完成；阶段 9 TencentDB contribution 尚未验收。当前分支已开始采用存储层 insert-only；SQLite/Mongo 已有初步实现，TCVDB 明确 unsupported。不能声称 LifeOS 已能经 TCVDB 首次写入，且测试/类型检查未跑完。
4. 当前实现分支：`upstream/TencentDB-Agent-Memory` 的 `feat/atomic-create-approved-memory`（基于 `feat/server_team`）。变更含 Gateway schema/route、L1 audit 类型与 SQLite 旧表迁移、SQLite/Mongo 初步 `createL1`、TS/Python v3 SDK、中英文 README/API 文档、metadata query/search round-trip、并发与 unsupported-backend 测试。Node syntax checks 和 `git diff --check` 通过；Vitest 不可运行（无依赖且未安装）；尚无 TS typecheck/真实 store/Gateway E2E。尚未 commit/push/open PR。
5. 下一步：先补真实 SQLite `createL1` 测试；检验 Mongo duplicate key 与 sharded ID 限制；审查 SQLite migration/audit failure 行为；然后在获准且环境可用后跑 Vitest/typecheck/Gateway tests。并行继续核实 TCVDB insert-only 原语；该能力未实现前，不能算解决 LifeOS 首写。不要将当前分支提为已完整支持 TCVDB 的 PR；用户自己提交 PR，未经明确授权不 commit/push/open PR。
4. 每完成阶段后，更新本文中的阶段状态、验收证据、剩余风险和下一步 goal。
5. 保护工作区已有未提交内容；不要清理或覆盖与本任务无关的图稿、上游仓库或交接文件。
