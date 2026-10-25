# 前端大改：问题清单与阶段拆分

> **工作分支**：`zhang-UI`（远程 `https://github.com/yubr-zzh/AIC-LifeOS/tree/zhang-UI`，本地与 `origin/zhang-UI` 同步在 `52d5d2c`）。所有改写、提交、推送都落在该分支。
> **基线对比**：`zhang-UI` 相对 `main` 已经新增 9000+ 行前端代码（详见第 2 节）。这次大改不是从零开始，而是**在 zhang-UI 现有的 agent UI 之上做结构化重构 + 视觉重做**。
> 方向（已与用户确认）：重做视觉 + 重构结构；技术栈引入 shadcn / Radix 组件库。
> 本文件只列问题与边界，不动代码。每个 Issue 独立可领、可验收、可单独提交。
> 关联文档：`docs/frontend-ui-prompt.md`（早期控制台风格描述，已偏离当前实现）、`README.md`、`frontend/README.md`、仓库根 `AI-MEMORY-987-HANDOFF.md`。

---

## 2. zhang-UI 相对 main 已有的工作

`git diff main...zhang-UI --stat -- frontend/` 显示 43 个文件、9046 行新增、175 行删除。重点增量：

**新增文件（agent 工作流的前端）**

- `frontend/src/state/agentStore.ts`（548 行）+ 两份单测（`agentStore.test.ts` 312 行 + `agentStore.history.test.ts` 375 行）
- `frontend/src/api/agentClient.ts`（340 行）+ `agentTypes.ts`（529 行）+ `agentMock.ts`
- `frontend/src/hooks/useAgentStream.ts`（156 行）
- `frontend/src/panels/AgentPanel.tsx`、`AgentActivityPanel.tsx`、`AgentApprovalCard.tsx`、`AgentComposer.tsx`、`AgentMemoryCapture.tsx`、`AgentPeekBar.tsx`、`AgentQuestionCard.tsx`、`AgentsSection.tsx`、`DelegationCard.tsx`
- `frontend/src/panels/ModelProviderSettings.tsx`、`SettingsPage.tsx`
- `frontend/src/components/WorkCalendar.tsx`
- `frontend/src/styles/agent.css`（323 行新样式）
- `frontend/vitest.config.ts`

**修改文件**

- `frontend/src/App.tsx`：从 main 的 335 行扩到 361 行（13 个 section 全部内联 + 桥接 ref）
- `frontend/src/panels/ChatPanel.tsx`、`MemoryPanel.tsx`：从 main 拉来并扩展
- `frontend/src/state/store.ts`、`api/client.ts`：微调
- `frontend/src/styles/global.css`：从 main 的 748 行扩到 1059 行（+agent.css 323 行）
- `frontend/package.json` / `package-lock.json` / `vite.config.ts` / `tsconfig.node.json`

**含义**：zhang-UI 已经把"个人 OS 主页（home / 计划 / 复盘 / 日记 / 心得 / 反馈 / 工作历）"和"agent 控制台（chat / agents / admin）"两套页面同时搬上来了。所以本次重写的"基线"是 zhang-UI，不是 main。

---

## 3. 现状快照（写代码前先看这里）

| 文件 | 行数 | 现状 | 主要问题 |
|---|---|---|---|
| `frontend/src/App.tsx` | 361 | 单文件包含 shell + 导航 + 13 个 section | 无 router，全靠 if-else 分发；下拉、设置、模式桥接、页面内联 |
| `frontend/src/styles/global.css` | 1059 | 设计 token + 所有组件样式混在一起（main 上是 748 行，zhang-UI 加了 ~270 行） | 无文件分层；想改一个 token 要全文件搜 |
| `frontend/src/styles/agent.css` | 323 | zhang-UI 新增，看起来是 agent 专属样式 | 实际和 global.css 互相覆盖；命名不清晰 |
| `frontend/src/panels/ChatPanel.tsx` | 553 | 数据 + 视图 + 工具调用渲染全在一处 | 难拆；和 `AgentPanel` 边界模糊 |
| `frontend/src/panels/AgentsSection.tsx` | 551 | 本机 Agent 发现/连接/运行 | 与 ChatPanel 互相 import 风险；内含桥接逻辑 |
| `frontend/src/panels/MemoryPanel.tsx` | 436 | 5 tab + 候选人生命周期 + 审批 | 状态机 + UI 混在一起 |
| `frontend/src/panels/ModelProviderSettings.tsx` | 276 | Provider CRUD + 连通性测试 | 与 SettingsPage 重叠 |
| `frontend/src/state/store.ts` | 608 | `useReducer`，运维控制台状态 | 与 agentStore 不能互相 import |
| `frontend/src/state/agentStore.ts` | 548 | Agent 流状态，独立演进 | 通过 App.tsx 用 ref 桥接，脆弱 |
| `frontend/src/api/client.ts` | 411 | 运维 API 客户端 | 与 agentClient 各自一套类型/mock |
| `frontend/src/api/agentClient.ts` | 340 | Agent 流客户端 + mock | 与 client 类型不互通 |

**两个并存的产品叙事**（必须在 Phase 0 之前敲定，否则一切 token 决策都站不住）：

- 旧文档叙事：深色 Agent 控制台（README + `frontend-ui-prompt.md`），mono 字体、状态色、给开发者看。
- 现行实现叙事：浅薄荷色"个人操作系统"（`--bg-0: #eef7f0`、大量情感文案如"慢一点，但要向前"、13 个 section 偏生活向）。

**两个并行的运行时**（都是 zhang-UI 新引入的，不是 main 遗产）：

- `store` ↔ `agentStore`：状态互相不可见，靠 `App.tsx:114-120` 的 `useRef` + `report` 帧同步。
- `client` ↔ `agentClient`：两套 mock、两套类型、两套 fallback 标记。

**zhang-UI 已有的 13 个 section**（见 `App.tsx:38-85`）：

| 路由 key | 标题 | 当前实现位置 | 备注 |
|---|---|---|---|
| `home` | 今日概览 | `App.tsx:257-276` 内联 HomePage | 静态数据，未接 store |
| `chat` | 对话 | `panels/ChatPanel.tsx` + `AgentPanel` + `AgentPeekBar` | 状态 + 桥接 + UI 全混 |
| `agents` | 本地 Agent | `panels/AgentsSection.tsx` | 23KB 单文件 |
| `daily-plan` / `phase-plan` | 计划 | `App.tsx:308-311` PlanningPage | 共享 useEntryDraft |
| `daily-review` / `phase-review` | 复盘 | `App.tsx:313-320` ReviewPage | 共享 useEntryDraft |
| `feedback` | 反馈 | `App.tsx:358` FeedbackPage | 走 entry 保存 |
| `diary` | 日记 | `App.tsx:360` DiaryPage | 含 mood 标签 |
| `insight` | 心得 / 体验 | `App.tsx:362` InsightPage | title + content |
| `calendar` | 工作历 | `components/WorkCalendar.tsx` | 独立组件 |
| `admin` | 系统后台 | `App.tsx:364` AdminPage | 套 DataFlowView + 5 个 panel |
| `settings` | 设置 | `panels/SettingsPage.tsx` | 套 ModelProviderSettings |

**测试覆盖**（zhang-UI 新加的）：`agentStore.test.ts`、`agentStore.history.test.ts`、`agentClient.test.ts`、`AgentsSection.test.tsx`、`AgentsSection.bridge.test.tsx`、`AgentActivityPanel.test.tsx`、`AgentApprovalCard.test.tsx`、`AgentPanel.test.tsx`、`DelegationCard.test.ts`、`ModelProviderSettings.test.tsx`、`WorkCalendar.test.tsx`、`client.test.ts`—— 这是我们要保住不退化的基线。

**已知未覆盖**（值得补）：`App.tsx` 无测试；`HomePage` / `PlanningPage` / `ReviewPage` / `FeedbackPage` / `DiaryPage` / `InsightPage` / `AdminPage` / `SettingsPage` 全部内联在 App.tsx，无独立测试。

---

## 4. 总体方向（待确认）

| 决策 | 选项 | 影响 |
|---|---|---|
| 视觉方向 | 个人 OS 保持 / 回归深色控制台 / 混合（聊天后台严肃，生活页温暖） | 决定 token 起点 |
| 样式组织 | 原生 CSS 分层 / Tailwind / UnoCSS | shadcn 默认要 Tailwind；Radix Primitives 是无样式 |
| 路由 | `react-router-dom` / 保持单页 if-else | 决定 App.tsx 拆分方式 |
| 状态层 | 合并两个 store / 保留两个 + 单向桥 / 换 zustand | 决定 Phase 2 形态 |
| Agent UI 库 | shadcn (Tailwind) / Radix Primitives + 自写样式 / Mantine / Chakra | 决定所有 Issue 落地形式 |

> ⚠ shadcn 默认依赖 Tailwind。如果不想引入 Tailwind，应改用 Radix Primitives + 自写 token，或 Mantine。**Phase 0 必须先选。**

---

## 5. 阶段与 Issue 清单

### Phase 0 — 决策冻结（先做这一阶段，剩下的才有意义）

**目标**：在动代码前，把方向决策写成 `docs/frontend-rewrite-decisions.md`，并落到 README 或 ADR。任何未决的决策都阻塞 Phase 1+。

- [ ] **F-0-1 视觉方向定稿** — 在"深色控制台 / 个人 OS / 混合"中三选一；后续 token 与组件库围绕它展开。
- [ ] **F-0-2 UI 库选型** — shadcn (Tailwind) / Radix Primitives + 自写样式 / Mantine / Chakra 中三选一。理由记录在 ADR。
- [ ] **F-0-3 CSS 策略定稿** — 原生 CSS 分层（`tokens.css` + `components.css` + `panels.css`）/ Tailwind / UnoCSS。理由同上。
- [ ] **F-0-4 路由策略定稿** — `react-router-dom` v6 / 保持 if-else（仅拆分文件）。涉及 13 个 section 是否都要路由 URL。
- [ ] **F-0-5 状态层策略定稿** — 合并两 store / 保留两 store 加显式桥 / 引入 zustand。
- [ ] **F-0-6 API 层策略定稿** — 合并 client + agentClient / 保留独立 / 拆 client + 共享 types。
- [ ] **F-0-7 命名与目录约定** — `pages/` vs `panels/` 边界、组件文件 vs 组件目录、style module 命名、测试文件并置规则。
- [ ] **F-0-8 验收门槛清单** — typecheck / build / test / e2e 覆盖率 / 视觉回归基准图。

**验收**：8 项决策都有书面 ADR，每个都有"为什么"。**不做**：任何代码改动。

---

### Phase 1 — 骨架：目录、路由、token 文件拆分（低风险，高 ROI）

目标：在不动功能、不动视觉的前提下，把"凑在一坨"的代码按结构拆开。

- [ ] **F-1-1 引入 `react-router-dom`** — 把 App.tsx 的 13 个 if-else 改成路由表；URL 与 section 一一对应。保留 `dark` 主题切换和 `SettingsPage` 的弹窗行为。
- [ ] **F-1-2 拆 `global.css` 为分层文件**
  - `styles/tokens.css`（设计 token、`:root` 变量、`@media (prefers-color-scheme)`）
  - `styles/base.css`（重置、字体、滚动条、焦点环）
  - `styles/components.css`（button / pill / panel / 等基础组件）
  - `styles/layout.css`（shell、side-nav、workspace-header、page-intro）
  - `styles/pages/*.css`（每页一页）
  - `styles/index.css`（`@import` 入口）
  - **不做**：视觉调整，只是搬位置。
- [ ] **F-1-3 拆 `App.tsx`** — 把内联的 HomePage / PlanningPage / ReviewPage / FeedbackPage / DiaryPage / InsightPage / AdminPage / Task 全部移到 `frontend/src/pages/<name>.tsx`；App.tsx 只剩路由表 + shell。
- [ ] **F-1-4 抽 `NavConfig`** — `navigation` 与 `sectionMeta` 从 `App.tsx:38-85` 抽出到 `frontend/src/config/nav.ts`，独立可测。
- [ ] **F-1-5 抽 `useTheme` hook** — 把 `dark` 状态从 App.tsx 提到 `useTheme()`；后续做主题切换菜单时不用再改 App。
- [ ] **F-1-6 拆 `sectionMeta` 为各 page 自描述** — 每个 page 自带 `eyebrow / title / description`，避免 13 项 page info 集中在一个文件。
- [ ] **F-1-7 抽 `useEntryDraft`** — `App.tsx:278-306` 的 `useEntryDraft` hook 被 PlanningPage / ReviewPage / FeedbackPage / DiaryPage / InsightPage 五个页面共用，App.tsx 拆出后这个 hook 必须先独立。落到 `frontend/src/hooks/useEntryDraft.ts`。
- [ ] **F-1-8 抽 `PageIntro` 与 `Task` 公共组件** — `App.tsx:188-195` 的 page-intro 块（eyebrow + h1 + p + date）和 `App.tsx:366` 的 `Task` 都内联；拆到 `frontend/src/components/PageIntro.tsx` / `TaskRow.tsx`。
- [ ] **F-1-9 拆 `styles/agent.css`** — 这是 zhang-UI 新增的 330 行独立样式，命名上像"agent 专属"，但实际上里面很多 .content-card / .big-editor / .feedback-* 都和 global.css 互相覆盖。Phase 1.2 拆分层文件时需要明确把它并入 components.css / pages.css 还是保留 agent.css；两种方案各列取舍。
- [ ] **F-1-10 明确 `AgentPeekBar` ↔ `ChatPanel` ↔ `AgentPanel` 三角依赖** — `App.tsx:222-244` chat section 里三个组件互相传 store / api / callbacks；F-1-3 拆 chat 页时必须先把这一层规整为 props drill-down 或 Context。
- [ ] **F-1-11 把 `dark` 状态从 `useState` 升级为受控 + 持久化** — 当前 `App.tsx:103` 每次刷新回浅色。Phase 1 顺便加 localStorage 持久化与 system-prefers-color-scheme 监听。

**验收**：`npm run typecheck`、`npm run build`、`npm test` 全绿；视觉零变化（手动 diff 或加视觉回归）。**不做**：UI 库、状态合并、视觉重做。

---

### Phase 2 — 状态层与 API 层整合

目标：消灭 store 与 agentStore、client 与 agentClient 之间的隐形耦合。

- [ ] **F-2-1 评估 store 合并方案** — 写一份 memo：`store.ts`（18KB）和 `agentStore.ts`（27KB）的字段集合、reducer 数量、订阅关系；给出合并 / 桥接 / 拆三方案的取舍。
- [ ] **F-2-2 引入 zustand / 选定状态库**（取决于 F-0-5）。
- [ ] **F-2-3 合并 `store` 与 `agentStore`**（或确认保留两个 + 单向桥） — 让 `APPEND_AGENT_SUMMARY` 不再依赖 App.tsx 里的 ref。
- [ ] **F-2-4 合并 `client` 与 `agentClient` 的类型** — 把 `agentTypes.ts` 与 `types.ts` 去重；共享 `Status` / `DataMode` / `MemoryScope` 等。
- [ ] **F-2-5 合并 mock fallback** — 单一 `markSource` 函数；让 mock 数据来源可观察。
- [ ] **F-2-6 API 错误处理统一** — 改用 React Query / SWR 或统一 `useApi` hook，去掉散落的 try/catch。
- [ ] **F-2-7 抽 `useAgentStream` 的副作用** — 当前的 mock SSE 在 hook 里直接定时器 + 状态机；考虑放到独立 `agentLoop` 模块，方便测试。

**验收**：94 项前端测试全过；`App.tsx` 不再持有桥接 ref；mock 数据切换可观察。**不做**：视觉重做。

---

### Phase 3 — UI 组件库接入与基础组件 redesign

- [ ] **F-3-1 选定并接入 UI 库**（取决于 F-0-2） — shadcn CLI 初始化 / Radix Primitives 装包 / Mantine Provider。
- [ ] **F-3-2 替换 `<button>` 体系** — 现在的 `button` 是手写 `var(--bg-2)`，全文件搜 `<button` 排查手写样式；统一到 UI 库的 Button + variants。
- [ ] **F-3-3 替换 `<StatusPill>` / `<SourceBadge>` / `<CopyId>`** — 用 `Badge` + `Toast`（或自包装）替代手写。
- [ ] **F-3-4 替换面板 `<Panel>` / `content-card`** — 用 `Card` + `Tabs` 替代手写 .content-card 类。
- [ ] **F-3-5 替换 Modal / Popover（`settings-popover`、`AgentComposer` 弹层）** — 用 `Dialog` / `Popover`。
- [ ] **F-3-6 替换 Select / Tabs / Tooltip / Toast** — `ModelProviderSettings` / `MemoryPanel` 里有大量原生 `<select>`，全部改 UI 库组件。
- [ ] **F-3-7 替换 `<textarea>` 富文本扩展** — Daily / Diary / Insight / Feedback 的"大编辑器"目前是裸 `<textarea>`；考虑接 Tiptap 或 Lexical（仅记录为候选，本阶段不实现）。
- [ ] **F-3-8 抽出图标系统** — 当前 `Icons.tsx` 是手写 inline SVG；统一为 lucide-react 或 heroicons。
- [ ] **F-3-9 引入暗色模式 token** — 当前 `theme-night` 是局部覆盖；用 UI 库的 theme system 替代。
- [ ] **F-3-10 `useFocusTrap` / `useKeyboardShortcuts`** — 抽公共可访问性 hooks。

**验收**：所有手写 `button` / `select` / `tabs` 替换完毕；`a11y` 走查（axe）；视觉保持或微调；测试全绿。

---

### Phase 4 — 视觉重做与设计系统

- [ ] **F-4-1 选定设计语言版本** — 控制台 vs OS vs 混合（取决于 F-0-1）。
- [ ] **F-4-2 重建设计 token** — 色板（surface / border / text / accent / status）、字号、间距、半径、阴影、动效曲线；写到 `styles/tokens.css` 或 token JSON。
- [ ] **F-4-3 主页视觉改版** — `HomePage` 的"今日焦点 / 今日进度 / 今日安排 / 生活节奏 / 引言 / 最近记录"6 卡，按新视觉重画。
- [ ] **F-4-4 对话工作区视觉改版** — `ChatPanel` + `AgentPanel` + `AgentPeekBar` 的三态（split / peek / collapsed）。
- [ ] **F-4-5 设置页视觉改版** — `SettingsPage` + `ModelProviderSettings` 整合，去掉内嵌弹窗。
- [ ] **F-4-6 计划 / 复盘 / 日记 / 心得 视觉统一** — 4 类记录页的"大编辑器 + 心情标签 + 保存按钮"模式抽出共享布局。
- [ ] **F-4-7 反馈页 + Admin 后台 视觉统一**。
- [ ] **F-4-8 移动端响应式补全** — App.tsx `mobile/desktop switch` 是注释，实际没切；按设计重新做断点。
- [ ] **F-4-9 动效与微交互** — 路由切换、面板展开、状态色变化、消息进入；统一 `framer-motion` 或 CSS。

**验收**：用 F-0-8 视觉基准图回归；a11y axe 全绿。

---

### Phase 5 — 大组件拆分（最难的部分）

- [ ] **F-5-1 拆 `ChatPanel.tsx`** — 数据 hook + 工具调用卡片 / 消息列表 / 输入区 / 头部 / 审批卡片分文件。**注意**：zhang-UI 这版 ChatPanel 已经很大（24KB），里面大概率还有 zhang-memory 历史合过来的工具调用展开逻辑。
- [ ] **F-5-2 拆 `AgentsSection.tsx`** — 连接、发现、运行三类卡片各自独立；与 `ChatPanel` 的边界明确（什么 import 什么不 import）。已有 `AgentsSection.test.tsx` 和 `bridge.test.tsx` 两份测试是合并的强约束。
- [ ] **F-5-3 拆 `MemoryPanel.tsx`** — 5 个 tab 各自成组件；候选人生命周期状态机抽到独立 hook。
- [ ] **F-5-4 拆 `ModelProviderSettings.tsx`** — Provider 列表、表单、连通性测试三块拆开。
- [ ] **F-5-5 拆 `agentStore.ts` 的 reducer 簇**（取决于 F-2）。**已有 `agentStore.test.ts` 312 行 + `history.test.ts` 375 行做基线**，重构时不能让任一测试变红。
- [ ] **F-5-6 抽 `DataFlowView` 的状态机** — 11 阶段流水线目前是手算 active 节点；改为声明式 `<fsm>` 组件。
- [ ] **F-5-7 抽 `TracePanel` 的拖拽 / 抽屉** — 当前是 inline 展开；考虑改为全局 Drawer。
- [ ] **F-5-8 拆 `AgentPanel.tsx`** — 11KB，按 composer / activity / approval / memory capture 子面板拆。
- [ ] **F-5-9 拆 `useAgentStream` + 状态机** — 5KB 的 hook 与 `agentStore` 的耦合很重；先建一份依赖图（被谁调用 / 调用谁 / 谁在订阅），再决定拆模块边界。

**验收**：单文件均 < 400 行；`agentStore.test.ts` / `agentStore.history.test.ts` / `agentClient.test.ts` / `AgentsSection.test.tsx` / `AgentsSection.bridge.test.tsx` 全绿；测试覆盖率不下降。

---

### Phase 6 — 质量门禁与文档

- [ ] **F-6-1 加 ESLint + Prettier**
- [ ] **F-6-2 加 Playwright e2e** — 至少：登录态（如果有）、对话、审批、设置切换。
- [ ] **F-6-3 视觉回归** — Chromatic / Percy / 自写截图对比。
- [ ] **F-6-4 Storybook** — 每个基础组件一个 story。
- [ ] **F-6-5 更新 `frontend/README.md`** — 与新目录、新组件库、新脚本对齐。
- [ ] **F-6-6 删旧文档** — `docs/frontend-ui-prompt.md` 的"深色控制台"叙事要么改写要么废弃。

---

## 6. 不在范围（明确不做）

- 后端 Python 重构（`lifeos/` 子系统本期不动）。
- 数据契约变更（`docs/api-contract.md` 不动）。
- 把"个人 OS 页面"翻译成"开发者控制台"——这是决策项 F-0-1，不在自动范围内。
- 引入后端持久化（仍走本地 SQLite 与 .lifeos/）。
- 把 main 拉过来的"主分支纯净前端"再合并回 zhang-UI——除非用户明确说"先把 zhang-UI 收齐再开新阶段"，否则默认所有改动都从 zhang-UI HEAD 出发。
- 删除/废弃 zhang-UI 上任何已有的 Agent 相关组件（AgentPanel / AgentsSection / 等等），即使它们当前代码质量差；本轮只做重构，不做减法。

---

## 7. 推荐顺序（用户拍板后我会按这个推进）

1. **Phase 0**：全 8 项决策写 ADR（`docs/frontend-rewrite-decisions.md`）→ **阻塞后续**
2. **Phase 1 全部**（F-1-1 ~ F-1-11）→ 见得到结构改善，最容易出 PR。提交节奏建议：F-1-1/1-2/1-3 各一个 commit；F-1-4~1-6 合并；F-1-7~1-9 合并；F-1-10/1-11 各自。
3. **Phase 2 前 3 项**（F-2-1 ~ F-2-3）→ 把 App.tsx 的桥接 ref 拆掉。**前置 F-1-3 完成**，否则测不出来。
4. **Phase 3 全 10 项** → 替换手写组件。每替换一类（button / select / tabs / dialog）单独 commit。
5. **Phase 4** → 视觉重做（最重）。每个 page 单独 PR。
6. **Phase 5** → 大组件拆分。**强约束**：`agentStore.test.ts` / `history.test.ts` / `bridge.test.tsx` 全程不能红。
7. **Phase 6** → 质量门禁。
8. **每完成一个阶段** → 跑 `npm test` 记录 baseline diff；推送前 `git pull --rebase origin/zhang-UI`。

---

## 8. 风险与未决项

| 风险 | 缓解 |
|---|---|
| shadcn 默认 Tailwind，与"保持原生 CSS"冲突 | F-0-2 / F-0-3 必须同时定 |
| 测试覆盖不足，重构时漏行为 | F-1 之前先跑 `npm test`，记录 baseline（zhang-UI 已有 ~12 个测试文件、约 1500 行测试代码） |
| App.tsx 拆分时丢失设置 / 弹窗 / 桥接副作用 | F-1-3 必须在 React DevTools 里 diff 前后 props 树 |
| 视觉重做偏离用户预期 | F-4-1 必须先出 2 版 mock，等用户选 |
| "Agent 桥接 ref"在重构时无声破坏 | F-2-3 之前增加一个测试断言 `APPEND_AGENT_SUMMARY` 触发 |
| zhang-UI 与 main 长期分叉，未来 main 提交合不回来 | 每次提交前 `git fetch origin main`，本轮结束前不删旧分支 |
| `agent.css` / `global.css` 互相覆盖规则 | F-1-2 拆分层时做一次 `grep -n "^\.[a-z-]*{"` 分类统计，决定 agent.css 留还是并入 |
| 远程 zhang-UI 被其他人继续推进，本地分叉 | 每次开工先 `git fetch origin zhang-UI && git rebase`；冲突时停下与用户确认 |
| `useAgentStream` 的 mock SSE 行为 vs 真实后端 | Phase 2 之前先和后端对齐一次，确认接口形态（是 SSE / WebSocket / 轮询） |

---

写完。等你逐项拍板（或者一起拍），再开 Phase 0。