# 队友模块接入计划与阶段验收

目标分支：`feat/agent-memory-integration`。只做小切片选择性移植，不整支合并；每个切片单独验证、单独提交。遇到删除现有能力、改变记忆权威来源、身份映射或安全边界等取舍时，先停下来与用户确认。

## 召回清单

| 来源 | 已确认内容 | 处理方式 |
|---|---|---|
| `origin/api&nonAgent` | 模型 Provider 配置、连通性测试、默认模型切换 | Provider MVP 已选择性接入，见提交 `68ef5f4`；该分支其他控制台/Vault 改动暂不整体搬运 |
| `origin/zhang-memory` | 对话显式 scope、对话记忆提炼候选、ai-memory 项目只读适配器、TencentDB 适配器及 UI/测试更新 | 按功能切片核对，不接入删除 `agent_evidence` 的变更 |
| `origin/liu` | v3 Bridge/harness 及多执行后端实现 | 当前目标分支已有多种执行后端；逐适配器比较契约和缺失能力后再决定接入 |

## 阶段状态

### 阶段 A：模型 Provider 设置 MVP — 完成

- 设置页提供 Provider 配置、编辑、删除、连通性测试和激活默认模型。
- 聊天运行时读取激活模型；API Key 不回传，Windows 上使用 DPAPI 加密存储。
- 验收：`npm run typecheck`、前端 94 项测试、`npm run build`、模型 Provider 后端 3 项单测通过；未用真实供应商 Key 做网络联调。
- 提交：`68ef5f4 feat(settings): add model provider configuration`。

### 阶段 B：对话 scope 与用户确认的记忆候选 — 完成

- 每轮对话显式选择 global / scenario / project scope，并保存在本地对话历史；旧历史的 `projectId` 继续兼容。
- 成功对话可由用户手动写出“提炼结论”，只提交结论及 trace 来源引用，原始对话不复制进 Memory。
- 候选仍须在记忆页审核；审核前不写入长期 Memory，也不同步外部 Provider。
- 验收：后端集成测试覆盖范围、来源引用、原始对话不泄漏、非法 scope 拒绝；`python -m unittest tests.test_agent_memory_integration tests.test_model_providers -v` 5 项通过；前端 typecheck、build、94 项测试通过；`git diff --check` 通过。
- 源码参考：`origin/zhang-memory` 的 `a40ea69 feat(memory): connect scoped conversation memory flow`，按当前实现适配而非 cherry-pick 整个提交。
- 提交：`9bd2a74 feat(memory): capture scoped conversation memories`。

### 阶段 C：ai-memory 项目只读检索 — 完成

- 实现显式 LifeOS project ID → ai-memory workspace/project 映射、只读 search/page 请求、路径/跨项目校验和检索上限。
- 仅当本轮是明确 project scope 且进入 Agent 执行时检索；外部页面只进入本轮不可信提示上下文，Trace 仅保留 source_ref，事件和 LifeOS Memory 不保存页面正文。
- 配置经环境变量读取：`LIFEOS_AIMEMORY_ENDPOINT`、`LIFEOS_AIMEMORY_PROJECT_MAP`，可选 `LIFEOS_AIMEMORY_API_TOKEN`、`LIFEOS_AIMEMORY_TIMEOUT_SECONDS`。当前只允许 loopback endpoint；没有新增 UI 配置页。
- 验收：ai-memory adapter 配置/隔离/HTTP mock 和 transient context 共 5 个新测试通过；记忆/provider 联合测试 10 项通过；前端 typecheck 与 94 项测试通过；Python 编译与 `git diff --check` 通过。没有访问真实 ai-memory 服务。
- 源码参考：`origin/zhang-memory` 的 `ecdac8f feat(memory): verify external adapters with local HTTP mocks`，适配到当前 ChatRuntime / Executor，不移植其不同的 planner 架构。
- 提交：`ac037b4 feat(memory): add scoped ai-memory project retrieval`。

### 阶段 D：TencentDB 适配差异与审批写入 — 等待用户确认范围

- 对照当前 TencentDB adapter 与 `origin/zhang-memory` 的修改，先核验 v3 创建/更新能力、外部 ID 对应关系、scope 身份映射及审批后写入语义。
- 不启用新的外部写入路径，不切换 Memory 权威来源；若候选创建或身份映射依赖上游未提供的能力，先与用户讨论。
- 已发现队友版本使用 `/v3/atomic/create`，但目前没有可验证的上游接口证据；只对该端点做 mock 测试不足以证明真实服务支持。已向用户询问先接 scope 映射和只读召回、写入保持关闭，还是暂时跳过 TencentDB。

### 阶段 E：Liu Bridge 能力契约补齐 — 部分完成

- Codex、Pi、Hermes、Kimi、OpenCode 等适配器已在当前分支；无审批回路的知情确认、权限子集校验和一次性进程 PID 上报/回收也已存在，不重复搬运。
- 已从 `origin/liu` 选择性补齐 `/agents` 的 `fangquan`、`wenti2`、`dui_hui_id` 三个 v3 能力字段，保留 `canUseTool`、`canAskQuestion` 旧字段；新旧布尔字段取同一来源。
- 验收：补丁前 `tests.test_neng_li_qian_yue` 有 1 项失败（缺少 `fangquan`）；补丁后 22 项通过。此测试运行时输出了凭据目录权限告警，但测试通过；未改动目录权限或用户数据。
- 暂不移植 Liu 分支“版本不匹配时对所有 Agent 强制 plan”的改动：它扩大现有门禁范围，且不是所有后端都支持 `plan`，可能改变执行/安全语义。等待用户确认门禁策略。

## 后续顺序

1. 等待用户确定 TencentDB 此轮接入范围；在此之前不引入 `/v3/atomic/create` 写入。
2. 完成 Liu Bridge 能力契约剩余审查并独立提交；版本门禁范围先按用户意见处理。
3. 对照 `origin/liu` 的 Bridge 和适配器逐项找缺口；禁止以整分支合并代替兼容审查。
4. 最后审阅 `origin/api&nonAgent` 其余页面和存储功能，仅接入明确缺失且与当前路由/存储架构兼容的项。

## 当前已知风险 / 暂停条件

- `origin/zhang-memory` 相对目标分支包含大范围架构差异；最新快照会删除 `lifeos/memory/agent_evidence.py` 及相关测试。当前实现刻意保留执行证据链，没有应用这些删除。
- `origin/liu` 与当前执行适配器高度重叠，且全分支差异包含大量文件删除；在逐文件差异完成前不做合并。
- 不执行 `git push`，除非用户明确要求。工作区已有未跟踪的本地启动脚本，接入提交不得包含它们。
