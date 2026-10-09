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

### 阶段 B：对话 scope 与用户确认的记忆候选 — 完成，待单独提交

- 每轮对话显式选择 global / scenario / project scope，并保存在本地对话历史；旧历史的 `projectId` 继续兼容。
- 成功对话可由用户手动写出“提炼结论”，只提交结论及 trace 来源引用，原始对话不复制进 Memory。
- 候选仍须在记忆页审核；审核前不写入长期 Memory，也不同步外部 Provider。
- 验收：后端集成测试覆盖范围、来源引用、原始对话不泄漏、非法 scope 拒绝；`python -m unittest tests.test_agent_memory_integration tests.test_model_providers -v` 5 项通过；前端 typecheck、build、94 项测试通过；`git diff --check` 通过。
- 源码参考：`origin/zhang-memory` 的 `a40ea69 feat(memory): connect scoped conversation memory flow`，按当前实现适配而非 cherry-pick 整个提交。

### 阶段 C：ai-memory 项目只读检索 — 待开始

- 先审查适配器 API 和现有 ChatRuntime 的检索插入点，再实现显式 LifeOS project ID 映射与只读检索。
- HTTP 联调用本地 mock；不访问外部服务、不复制原始页面进 LifeOS Memory。

## 后续顺序

1. 完成阶段 B 的构建/差异检查并独立提交。
2. 对照 `origin/zhang-memory` 的 `lifeos/memory/providers/ai_memory.py`，接入 ai-memory 的显式项目映射、只读检索及 HTTP mock 测试；不复制原始页面进 LifeOS Memory。
3. 单独核对 TencentDB 适配器差异：明确原子创建能力、LifeOS 审批后写入、身份映射与撤回语义。遇到接口/权威数据冲突时先讨论，不擅自更换权威存储。
4. 对照 `origin/liu` 的 Bridge 和适配器，按 Codex、Pi、Hermes、Kimi、OpenCode 等契约逐项找缺口；禁止以整分支合并代替兼容审查。
5. 最后审阅 `origin/api&nonAgent` 其余页面和存储功能，仅接入明确缺失且与当前路由/存储架构兼容的项。

## 当前已知风险 / 暂停条件

- `origin/zhang-memory` 相对目标分支包含大范围架构差异；最新快照会删除 `lifeos/memory/agent_evidence.py` 及相关测试。当前实现刻意保留执行证据链，没有应用这些删除。
- `origin/liu` 与当前执行适配器高度重叠，且全分支差异包含大量文件删除；在逐文件差异完成前不做合并。
- 不执行 `git push`，除非用户明确要求。工作区已有未跟踪的本地启动脚本，接入提交不得包含它们。
