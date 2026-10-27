# Agent 侧栏 P0-A（修正版）：工具调用状态机 + 折叠渲染

> 基线：`docs/agent-sidebar-tool-call-refactor.md`（状态机）+ `docs/agent-sidebar-ui-spec.md`（UI）。
> 本文是**修正后的实施清单**，与 pi 原文冲突处以本文为准，理由逐条写明。
> 参考：`microsoft/vscode` main @ `4bda7217`，`src/vs/workbench/contrib/chat/`。

---

## 0. 与 pi 原文的差异

### 必须修正（会引入 bug）

| # | pi 原文 | 问题 | 本文做法 |
|---|---|---|---|
| C1 | `snapshot` 分支 `toolCalls: {}`，再用 `f.messages` 重建 | **快照已不带 messages**（`events.py:139`、`http.py:50`）。按原文做，每次重连清空全部工具调用，直到 transcript 拉回 | 保留存活 session 的 toolCalls，用 `pending` 修正，不整表清空 |
| C2 | "`PermissionRequest` 没有 `toolUseId`，前端无法关联" | `http.py:1288` 里 `requestId = toolUseId`，**今天就能关联**；只是隐式契约、且 `t-unknown` 兜底会破坏唯一性 | 仍然加显式字段，但定位为"契约显式化"，不是"从无到有" |
| C3 | `chunk` 帧"找当前唯一 streaming 的调用" | 并发工具调用会挂错；且原文自己承认这个限制 | 用 `partial[messageId]` 缓冲，完整 `tool_use` 到达时消费，**不需要扫描** |
| C4 | 中断时伪造 `tool_result(isError=True, state=cancelled)` | 结果从未发生；老前端会渲染成"执行失败"，与"用户中断"语义混淆 | 新增 `kind="tool_cancelled"`；前端 `MessageKind` 同步 |

### 建议修正（手感/正确性）

| # | 原文 | 本文做法 |
|---|---|---|
| S1 | snapshot 里的调用一律 `completed` | 结合 `session.state`：有 tool_use 无 result 且会话 running/attention → `executing` |
| S2 | 只处理 `permission` 帧 | `question` 帧已带 `toolUseId`（`claude_code.py:297`），同样推进到 `awaiting_confirmation` |
| S3 | 状态图标用 Unicode（`◌ ? ◍ ✓ ✕ ⊘`） | 用现有 SVG 图标集（craft-floor 禁 Unicode 当图标） |
| S4 | toolGroup 合并阈值"连续 ≥3 且全完成" | 改 ≥2，且排除 awaiting/failed |
| S5 | `durationMs = m.createdAt - Date.now()` | 两个时钟混用会出负数；clamp 到 `>= 0`，并用消息时间差优先 |
| S6 | `.agb-role` 标签条保留 | 删除（信息密度极低），由 ToolStep 的摘要行取代 |

---

## 1. 数据模型

### 1.1 后端 `lifeos/bridge/models.py`

```python
# 放在 AgentMessage 之前
# 工具调用生命周期。与前端 ToolCallState.type 逐字对齐。
# 边界：P0 只有 claude_code.py 会发 state；其他 adapter 不发，
# 前端 guiState(undefined) 走 completed 降级。
TOOL_STATE = {
    "streaming",
    "awaiting_confirmation",
    "executing",
    "awaiting_post_approval",
    "completed",
    "cancelled",
}
```

`AgentMessage` 末尾（有默认值字段区，**不能插到 `xuhao` 前**，`asdict()` 有全等断言）：

```python
    # 仅 tool_use / tool_cancelled 有意义；空串 = 老 Bridge / 不知道。
    state: str = ""
```

`PermissionRequest`：在 `toolInput` 之后、`title` 之前插入（**必须带默认值**，老调用点不传也不炸）：

```python
    # SDK 的 tool_use_id。空串 = 老 Bridge，前端降级为独立卡片。
    # 注意：Claude 路径下 requestId 目前恒等于 toolUseId；显式化是为了
    # 契约清晰 + 其他 adapter 不保证 + t-unknown 兜底会破坏唯一性。
    toolUseId: str = ""
```

### 1.2 前端 `frontend/src/api/agentTypes.ts`

```ts
export type ToolCallState =
  | { type: "streaming"; partialInput: string }
  | { type: "awaiting_confirmation"; requestId: string | null }
  | { type: "executing"; startedAt: number }
  | { type: "awaiting_post_approval"; requestId: string | null }
  | { type: "completed"; isError: boolean; durationMs: number | null }
  | { type: "cancelled"; reason: "denied" | "skipped" | "interrupted" | "expired" };

export interface AgentToolCall {
  toolUseId: string;
  sessionId: string;
  seq: number;
  name: string;
  input: unknown;
  state: ToolCallState;
  resultText: string;
  summary: string;
}
```

`PermissionRequest` 加 `toolUseId: string;`
`AgentMessage` 加 `state?: string;`
`MessageKind` 加 `"tool_cancelled"`。

---

## 2. `agentStore`

### 2.1 状态

```ts
toolCalls: Record<string, AgentToolCall>;
```

`initialAgentState` 加 `toolCalls: {}`。

### 2.2 帧规则

**原则**：tool 相关帧只更新 `toolCalls`；`messages` 仍是持久化日志。

#### `message`（`kind === "tool_use"`）

- 照旧写入 `messages`
- 若 `toolUseId` 且表中不存在 → upsert，状态取 `guiState(m.state)`
- 若已存在 → **不覆盖**（补拉历史幂等）
- 若 `partial[m.messageId]` 存在 → 作为 `partialInput` 消费并删除

#### `message`（`kind === "tool_cancelled"`）

- 写入 `messages`
- 有对应调用 → `cancelled`，reason 从 `m.text` 映射（拒绝/中断/跳过/超时）

#### `tool_result`

- 写入 `messages`
- 有对应调用 → `completed`，`durationMs` 用 `createdAt - startedAt`（clamp ≥ 0）
- 无对应调用 → 不新建、不报错，按旧样式兜底渲染

#### `permission`

- 现有 `pending` 逻辑不动
- `p.toolUseId` 存在且有对应调用 → `awaiting_confirmation` + `requestId`

#### `permission_resolved`

- allow → `executing`（`startedAt = now`）
- deny → `cancelled(denied)`

#### `question`

- 有 `toolUseId` 且表中有 → `awaiting_confirmation`（`requestId` 用 `questionId` 不含在此，
  这里只标记"在等用户"，审批卡由 question 卡承担）

#### `chunk`（`messageKind === "tool_use"`）

- **不扫描 toolCalls**。继续写 `partial[f.messageId]`，与文本流同样的机制。
- 待完整 `tool_use` 消息到达时消费（见上）。
- `streaming` 状态只在 `tool_use` 消息先于 delta 到达时短暂存在；绝大多数情况下
  用户看到的是"生成参数中"挂在 partial 上（由 AgentPanel 渲染 streaming 气泡）。

#### `snapshot`（**C1 修正**）

```ts
// 不整表清空。只丢掉 session 已不存在的调用。
const toolCalls: Record<string, AgentToolCall> = {};
for (const tid in a.toolCalls) {
  const c = a.toolCalls[tid];
  if (sessions[c.sessionId]) toolCalls[tid] = c;
}
// 用 pending 把对应调用修正回 awaiting_confirmation
for (const p of f.pending) {
  if (p.toolUseId && toolCalls[p.toolUseId]) {
    toolCalls[p.toolUseId] = { ...toolCalls[p.toolUseId],
      state: { type: "awaiting_confirmation", requestId: p.requestId } };
  }
}
// 用会话状态推断"仍在执行"（S1）
for (const tid in toolCalls) {
  const c = toolCalls[tid];
  const s = sessions[c.sessionId];
  if (c.state.type === "completed" && c.state.durationMs === null && c.resultText === ""
      && s && (s.state === "running" || s.state === "attention")) {
    toolCalls[tid] = { ...c, state: { type: "executing", startedAt: c.seq } };
  }
}
```

#### `HISTORY`

- 合并新消息后，对**新并入的** `tool_use` 建表、`tool_result` 补结果；已有项不覆盖。

### 2.3 `guiState`

同原文，但 `cancelled` 默认 reason 用 `"interrupted"` 仅在 state 明确为 cancelled 时；
`undefined` → `completed(isError:false, durationMs:null)`。

---

## 3. `toolSummary.ts`

```ts
export function zhaiYao(name: string, input: unknown): string
export function groupLabel(names: string[], n: number): string
```

规则同原文；`basename` 同时处理 `/` 与 `\`。
`groupLabel` **只接收 name 计数**，不拼参数（不可信输入）。

---

## 4. `ToolStep.tsx`

DOM / CSS 采用 UI 规格 §9，但：

- 图标改用 SVG：`IconCheck` / `IconReject` / `IconRefresh`(旋转) / `IconChevron` / `IconCircleDot`
- `executing` 用 **shimmer 文字 + 静态图标**，不用转圈
- `awaiting_confirmation`：无 chevron、不可折叠、强制展开
- `completed.isError`：强制展开
- `prefers-reduced-motion` 降级
- 键盘可达：`role="button"` + `tabIndex=0` + `Enter/Space`

---

## 5. `AgentPanel.tsx`

### 5.1 合并流

```ts
type LiuItem = { t: "msg"; m: AgentMessage } | { t: "tool"; call: AgentToolCall } | { t: "group"; calls: AgentToolCall[] };
```

- `tool_use` / `tool_result` / `tool_cancelled` 消息：有对应调用 → 丢弃；无 → 旧样式兜底
- 按 `seq` 排序
- 相邻 tool 调用（≥2，全部 `completed` 且无错误）合并为 group
- 有 awaiting / failed 的不合并

### 5.2 边框减法（UI 规格 §10）

- `.agb` 去边框、去 padding、去背景
- 只有 `.agb-user` 有浅底
- 系统/错误类改左侧 2px 色条
- `.agb-role` 删除
- `.agp-body` padding → `12px 16px`

### 5.3 审批区

保持 `.agp-decide` 位置。ToolStep 的 `awaiting_confirmation` 与审批卡通过 `requestId` 互链
（点击 ToolStep 滚动到审批卡）。

---

## 6. Bridge（仅 claude_code.py）

- `_kuai`：tool_use 记 `state`（有完整 input → `executing`，否则 `streaming`）
- `_fa("tool_result")`：带 `state="completed"`
- 中断：`session.zhong_duan` 里对 `executing/awaiting_confirmation` 的调用追加
  `tool_cancelled` 消息（**C4**），并落盘
- `arbiter.py`：`PermissionRequest(toolUseId=...)` 透传

其他 adapter 不动（不发 state → 前端 completed 降级）。

---

## 7. 测试

### 前端
`agentStore.toolCall.test.ts`：8 项（原文 8 项 + snapshot 不清空 + question 帧 + tool_cancelled）
`ToolStep.test.tsx`：5 项
`AgentPanel.test.tsx`：4 项

### 后端
`tests/test_bridge_tool_state.py`：5 项（含 tool_cancelled 落盘）

---

## 8. 实施顺序

| # | 改动 | 验证 |
|---|---|---|
| 1 | `models.py` + `arbiter.py` | pytest |
| 2 | `agentTypes.ts` | tsc |
| 3 | `agentStore.ts` | vitest |
| 4 | `toolSummary.ts` | vitest |
| 5 | `ToolStep.tsx` + `agent.css` | vitest |
| 6 | `AgentPanel.tsx` + `.agb` 去边框 | vitest + 截图 |
| 7 | `claude_code.py` + `session.py` 中断 | pytest |

第 1-2 步向后兼容，可先合。第 3 步后即使 UI 未改，表也在正确维护。

---

## 9. 明确不做

- 不解析 `partial_json`
- 不做 diff 视图（P1）
- 不做 Steering 队列（P2）
- 不做虚拟滚动（>300 行再说）
- 不改 `PermissionRequest.title/toolInput` 的可信度分级
- 不给其他 adapter 加 state
- 不改 SSE / streamSeq / 补拉逻辑

---

## 10. 实施记录（2026-10-27）

已按本文落地，实际改动与原文的差异记录在此，供后续维护参考：

1. **`PermissionRequest.toolUseId` 在前端是可选字段（`?`）**，不是必填。
   老 Bridge 的帧里没有这个键，写成必填会让所有既有测试夹具和旧数据编译失败；
   运行时统一用 `p.toolUseId || f.requestId` 兜底。

2. **`snapshot` 同时支持两种来源**：真机快照不带 messages（只保留现有表 +
   `pending` 修正 + 会话状态推断），预览/假帧源带 messages 时再从合并后的
   `messages` 建表。只做前者会让预览模式看不到折叠行。

3. **`permission_resolved.decision` 的真实取值是 `user_allow` / `user_deny` /
   `auto_deny`**（`arbiter.JUE_ZHU`），不是 `allow` / `deny`。reducer 用
   `/allow/` 判定；只判 `=== "allow"` 会把所有批准当成拒绝。

4. **`durationMs` 优先用 Bridge 时钟**：`guiState(executing, m.createdAt)`。
   原来用 `Date.now()` 会和 `tool_result.createdAt` 相减出负数，clamp 成 0。

5. **`chunk(tool_use)` 用 `partial[messageId]` 缓冲**，完整 `tool_use` 到达时
   消费为 `partialInput`，不再"扫描唯一 streaming 调用"（并发会挂错）。

6. **中断补 `tool_cancelled`**，并跳过已经有 `tool_result` / `tool_cancelled`
   的调用（tool_use 自身 state 不会随结果变化）。

7. **图标全部用 SVG**（`IconCheck` / `IconReject` / `IconRefresh` / `IconPause` /
   `IconSlash` / `IconChevron` / `IconCircleDot`），未引入 Unicode 符号。

### 验证

- 前端：typecheck 干净；14 个测试文件 **110 通过 + 12 skipped**
- 后端：`test_*bridge*.py` **211 项通过**
- 构建：`vite build` 1.78s
- 预览模式截图：`frontend/.shots/agent-sidebar-p0a-v2.png`

## 11. P0-B 实施记录（2026-10-27）

在 P0-A 之上补齐 VSCode 侧栏的结构层，共四项：

### 11.1 turn 分组

- 新增 `frontend/src/panels/agentFlow.ts`（纯函数，无 React 依赖）：
  `buildTurns()` / `flowItems()` / `contextItems()` / `toolTier()`。
- **轮次边界 = `role === "user" && kind === "text"`**。只判 `role === "user"`
  会把每条 `tool_result` 都切成新一轮（SDK 里 tool_result 的角色也是 user）。
- turns 是 messages 的**派生视图**，不进 reducer。放进 reducer 要在快照、
  补拉、去重三条路径各维护一次，漂移风险高于收益。
- 工具调用按 seq 落到「最后一个 `start <= call.seq`」的轮次；只有调用、
  没有消息时补一个 `user: null` 的轮作为兜底。

### 11.2 三档可见度

- `toolTier()`：`Read / Grep / Glob / WebFetch / WebSearch / TodoWrite /
  BashOutput` 为 `progress` 档，成功时渲染成**不可交互的一行**——不是
  `<button>`，不进 Tab 序，无 hover 反馈。
- `Bash / Write / Edit / MultiEdit` 等为 `expandable`，保持可展开。
- **失败与等待审批无视档位**，一律展开可见。

### 11.3 轮次 footer 工具栏

- hover 出现「复制 / 重试」，用 `visibility` 而非 `display` 切换，避免 hover
  时布局跳动；`@media (hover: none)` 下回退常显。
- 「重试」复用 `api.act.send`，不是新接口。

### 11.4 已使用的上下文（§7）

- `contextItems()` 只读工具输入里的 `file_path` / `notebook_path` /
  `pattern`，按 `(kind,label)` 去重，**不拼任何 Agent 文本**。
- 渲染成轮次底部的 `<details>` 折叠条：一轮可能读 20 个文件，常驻 chip 墙
  会把回答挤没。

### 11.5 Steering 队列（P2 提前做）

- Agent 执行中（`state ∉ {idle, ended}`）Enter 只入队，不直接发。
  直接发会让 Bridge 同时起两条 `paichu`，两串工具调用交错。
- `flushing` ref 保证**一次只放行一条**：发出去的瞬间状态还没翻成
  `thinking`，不拦住的话第二条会在同一帧被连带发出。
- 状态回到 `idle` / `ended` 时自动放行队首；发送失败留在队里等下次状态变迁，
  不静默丢弃。排队项可单独取消。

### 未做（有意）

- **审批卡不按 `.chat-confirmation-widget2` 重写**：现有 `.apr` 已包含可信/
  不可信分区、超时进度、截断保护、危险命令二次确认，信息量高于 VSCode 的
  widget，照抄是降级。
- 虚拟列表：会话超过 300 行再考虑。
- **Agent 输出仍未渲染 Markdown**（纯文本 + `white-space: pre-wrap`）。
  需要 `react-markdown` + `remark-gfm`，属于新增依赖，待确认。

### 验证

- 前端：typecheck 干净；15 个测试文件 **126 通过 + 12 skipped**
- 后端：`test_*bridge*.py` **211 项通过**
- 预览模式截图：`frontend/.shots/agent-sidebar-p0b2.png`
