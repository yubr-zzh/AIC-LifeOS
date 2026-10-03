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
- `ai-memory` 与 TencentDB Agent Memory 是可借鉴/适配的能力来源，不应在没有明确设计前形成两套重复权威数据。
- 晋升规则（项目/场景记忆何时上升到全局）尚未决定；默认不自动跨项目晋升。

## 阶段总览

| 阶段 | Goal | 状态 | 主要产物 / 验收 |
| --- | --- | --- | --- |
| 0. Git 与工作区基线 | 确认仓库与现有变更，避免覆盖用户工作 | 完成 | 根目录已为 Git 仓库；保留所有既有未跟踪项 |
| 1. 现状审计 | 搞清现有 Memory、事件流、API、持久化和测试的实际行为 | 完成 | 本文“阶段 1 验收记录”；现有测试 8/8 通过 |
| 2. 领域数据契约 | 定义原始来源引用、记忆候选、已采纳 Memory、画像视图所需字段及兼容策略 | 完成 | `lifeos/memory/schema.py` v3 契约、一次性备份迁移、API/TS 类型、回归测试 |
| 3. 记忆写入与来源接入 | 打通至少一条非 Agent 来源的计划/复盘到候选 Memory 的可审计链路 | 完成（后端 MVP） | `POST /entries/{id}/memory-candidates`；结构化来源、revision 幂等、人工审核测试 |
| 4. 生命周期与可纠错性 | 明确候选、采纳、拒绝、修正、冲突等状态变化；不擅自决定跨范围晋升 | 完成（生命周期 MVP；自动冲突检测与物理删除明确延期） | schema v3 active/superseded/retracted；显式纠正/撤回 API；非法状态转换、召回过滤与索引失效测试 |
| 5. 分层检索与隔离 | 支持全局/场景/项目检索范围，确保项目记忆不串用 | 进行中（范围过滤与显式传递已完成，自动识别待定） | 默认仅召回 global；显式 `memory_scope` 从 `/chat` 传至检索并写入事件；项目隔离测试 |
| 6. 动态画像视图 | 从有效 Memory 生成带溯源信息的核心/场景画像，不另造权威副本 | 待开始 | 可重建视图、版本/来源说明、更新测试 |
| 7. API 与用户审核入口 | 让用户检查、修正、拒绝候选并理解画像依据 | 待开始 | API 契约与端到端测试；可见来源与状态 |
| 8. 外部记忆能力适配 | 评估并隔离 ai-memory / TencentDB 的职责与适配面 | 待开始 | adapter 选择依据；不重复存储为双重权威 |
| 9. 评估与效率 | 评估召回正确性、隔离性、可解释性；再量化成本与效率 | 待开始 | 小型评测集与基线；成本优化放在正确性之后 |

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

> 以上为阶段 1 当时的观察；未知来源兜底与 schema 迁移问题已在阶段 2 修复。检索范围已在阶段 5 首轮实现，仍需接入场景识别并加强项目隔离测试。

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

## 阶段 5 首轮隔离策略

- `MemoryManager.retrieve(query, scope=None)` 与 `MemoryRetriever.retrieve` 接受可选 scope。
- 没有显式 scope 时仅召回 `global`；`scenario` scope 能召回全局 + 同场景记忆；`project` scope 能召回全局 + 同场景 + 相同 `project_id` 的项目记忆。`unassigned` 永不进入检索结果。
- `direct`（用户主动提供）且未指定 scope 的新记忆默认 global；迁移时也只把旧 `user/direct` 记忆认作 global，其它旧记忆保持 unassigned。
- 现已允许 `LifeOSAgent.run`、`ChatRuntime.handle_message` 和 `POST /chat` 显式接收 `memory_scope`，传给检索并写入 `conversation.completed` 事件。`frontend/src/api/client.ts` 的 `sendChat` 有可选参数，但当前 UI 不传值，也没有自动场景识别；未指定 scope 时默认只使用全局记忆，这是有意的 fail-closed 行为。

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
- **画像后续项**：阶段 6 的画像视图只消费 `status=active` 的 Memory；superseded/retracted 状态变化后，视图可从权威条目重建，不将旧版回流。
- **物理删除后续项**：单独定义授权、删除范围、备份保留、原始记录是否删除、索引/缓存/画像级联、部分失败重试与完成状态，再实现不可逆清理。
- **身份与权限后续项**：当前本地原型依赖 UI 的明确操作文案；多用户身份认证和服务端授权尚未接入，不应将其描述为安全边界已由 API 强制保障。

### 本阶段验收结论

- commit/reject 重放幂等；拒绝候选不能 commit，已 commit 候选不能 reject。
- 相同纠正重放返回同一版本；superseded/retracted 条目的非法二次修改在管理器层拒绝，HTTP API 返回 409。
- superseded/retracted 条目不参与召回，向量索引移除、缓存清空；历史条目和来源引用保留。
- Markdown 导入不能绕过生命周期端点改写或移除既有条目。
- 不跨项目/场景晋升，不执行自动冲突覆盖，不做物理删除。

## 风险与未决决策

- 每日/阶段记录的候选提炼方式和触发 UX 尚未定；不应默认对每次保存都调用模型。
- `confidence` 的生成/校准策略仍待设计；目前它是 nullable metadata，不代表客观概率。
- 缺失 `project_id` 的候选必须使用 `unassigned` scope，且当前检索器排除该类记录。
- `/memory` 当前返回整个内部 store；后续设计需要考虑 API 向用户暴露范围、候选和运行态存储的分离。
- 成本和效率优化暂不作为当前实现阶段的目标；先建立召回正确性、隔离性和可追溯性基线。

## 本次最新验证记录（2026-10-02）

- `python -m unittest discover -s tests -v`：**22 tests passed**，包含 schema v2 → v3 的一次性生命周期状态迁移测试。
- `python -m compileall -q lifeos tests`：通过。
- `git diff --check`：通过。
- `npm install --no-save --no-package-lock`：安装 68 个前端依赖；未修改 `package.json` 或 lockfile。
- `npm run typecheck`：通过（`tsc --noEmit`）。
- `npm run build`：通过（`tsc -b && vite build`，48 modules transformed）。
- 本轮实现已采纳记忆显式纠正/撤回、schema v3 状态迁移、非 active 检索过滤、Markdown 生命周期保护、`MemoryPanel` 用户确认表单，以及前后端 API 契约；并补充管理器与 HTTP 层对 superseded/retracted 非法变更的回归断言。自动冲突检测、画像和物理删除仍是后续阶段/独立设计项。
- 工作区原有未跟踪的上游仓库、图稿和交接内容均保留；本轮只修改 Memory 代码、API/TS 契约、架构/交接文档与回归测试，其它已有改动未动。

## 交接给下一位 Agent

1. 先读取仓库根目录的 `README.md`、本文和 `docs/lifeos-workflow-and-memory-architecture.md`。
2. 重新运行 `python -m unittest discover -s tests -v`，确认测试基线仍成立。
3. 阶段 2 完成、阶段 3 后端 MVP 完成、阶段 4 生命周期 MVP 完成、阶段 5 范围过滤和显式 `memory_scope` 传递已实现。后续转入阶段 6（动态画像视图）前，仍需另行确认阶段 5 自动场景识别是否纳入近期范围；不要自动晋升全局画像。
4. 每完成阶段后，更新本文中的阶段状态、验收证据、剩余风险和下一步 goal。
5. 保护工作区已有未提交内容；不要清理或覆盖与本任务无关的图稿、上游仓库或交接文件。
