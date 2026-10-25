# LifeOS Governance Mini-set v1

LifeOS 长程记忆治理能力的合成问答集。20 个案例覆盖 scope 隔离、记忆版本、有效期、撤回、授权晋升、来源链和拒答。案例采用多轮、口语化的 LifeOS 对话，包含历史上下文与当前问题。所有人物、项目、记录与对话均为虚构，不含真实用户数据。

## 文件

- `cases.jsonl`：每行一个独立评测案例，UTF-8 编码。
- `manifest.json`：数据版本、范围、许可和字段约定。
- `../../tools/validate_memory_dataset.py`：结构及证据引用校验器。

## 运行

在仓库根目录执行：

```powershell
python tools/validate_memory_dataset.py
```

校验器不调用模型，不评估自然语言答案质量；它检查 JSONL 结构、唯一 ID、必需字段、预期证据 ID 是否存在，以及 `must_not_use_ids` 是否有效。

## 约定

- `memories` 是该题可见的候选记忆集合，包含干扰项和不可使用项。
- `expected_evidence_ids` 是正确回答必须引用的证据；拒答时为空。
- `must_not_use_ids` 是本题禁止用作当前答案依据的记录，例如跨项目、已撤回、过期或已被替代的记录。
- `expected_action` 使用 `answer`、`abstain`、`clarify` 或 `deny_promotion`。
- `conversation` 是当前问题之前的多轮上下文，按顺序记录 `user`/`assistant` 发言；当前待回答内容单独放在 `question`。
- `expected_answer` 是人工编写的语义要点，不要求逐字匹配。
- 所有时间为 ISO 8601，带时区。`as_of` 是评测查询时间。

此 mini-set 用来验证治理边界，不代表通用长对话记忆能力，也不替代 LongMemEval 等公开基准。
