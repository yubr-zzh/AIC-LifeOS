"""v2.0 本地 Agent 桥接：数据模型与全局常量。

方案第 6 章。所有跨进程传输的实体都在这里定义，字段名与方案 6.1–6.4 逐字对齐，
因为前端 agentTypes.ts 要照着它写。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field, fields
from typing import Any

# ---- 6.2 状态机 ----
YO = {
    "idle",
    "thinking",
    "working",
    "attention",
    "waiting_input",
    "backoff",
    "error",
    "ended",
}

# 合法迁移表。含全部同态自环（并发审批 attention→attention、并行工具 working→working、
# 审批通过后立刻跑完 attention→ended），以及 error/ended/backoff 的出边。
# 缺任何一条，正常的并发审批与任务完成都会抛异常。
YUNXU = {
    ("idle", "thinking"), ("idle", "attention"), ("idle", "waiting_input"),
    ("idle", "backoff"), ("idle", "error"),
    ("thinking", "working"), ("thinking", "idle"), ("thinking", "attention"),
    ("thinking", "waiting_input"), ("thinking", "error"),
    # 方案 6.2/C.1 的表缺这两条，但「本轮跑完 → ended」在 thinking 与 working 下
    # 都会真实发生：纯文本回答结束时是 thinking，刚跑完工具时是 working。
    # 照原表实现，正常完成任务反而会抛 InvalidTransition。
    ("thinking", "ended"),
    ("working", "thinking"), ("working", "idle"), ("working", "attention"),
    ("working", "waiting_input"), ("working", "backoff"), ("working", "error"),
    ("working", "ended"),
    ("attention", "attention"), ("attention", "working"), ("attention", "thinking"),
    ("attention", "idle"), ("attention", "ended"), ("attention", "error"),
    ("waiting_input", "attention"), ("waiting_input", "waiting_input"),
    ("waiting_input", "working"), ("waiting_input", "thinking"),
    ("waiting_input", "idle"), ("waiting_input", "ended"), ("waiting_input", "error"),
    ("backoff", "idle"), ("backoff", "error"),
    ("error", "idle"), ("error", "thinking"), ("error", "ended"),
    ("ended", "thinking"),
}

# ---- 8.3 闸门 1：permissionMode 白名单 ----
# bypassPermissions 故意不在列：实测（docs/bridge-spike-report.md 第 3 节）证明
# 该模式下 SDK 在 can_use_tool 之前就把调用自动批准了，审批回调根本不会被调用，
# 整个审批链路会静默归零。只能硬拒绝，不能降级。
MOSHI = {"manual", "acceptEdits", "plan", "auto", "dontAsk"}

# ---- 7.4 错误码 ----
CUOWEI = {
    "unauthorized", "forbidden", "not_found", "invalid_request", "conflict",
    "already_resolved", "reset_required", "input_mismatch", "mode_forbidden",
    "cwd_forbidden", "too_large", "rate_limited", "agent_unavailable", "internal",
}


def lingshou() -> str:
    """生成一个短标识（sessionId/messageId 之类）。"""
    return uuid.uuid4().hex[:8]


def xianzai() -> int:
    """当前时刻（毫秒）。全项目的 createdAt/updatedAt 都用它，保证单位一致。"""
    return int(time.time() * 1000)


@dataclass
class AgentSession:
    """一个 Agent 会话 = 一个 Claude Code 子进程 + 一次委派往返（方案 6.1）。"""

    sessionId: str
    agentId: str
    agentLabel: str
    cwd: str
    permissionMode: str = "manual"
    # effectiveMode 是当前真正生效的模式。请求值与生效值必须分开存：
    # 客户端要是非法值，我们直接 400 拒绝而不是静默降级（方案 6.1 注）。
    effectiveMode: str = "manual"
    state: str = "idle"
    title: str = ""
    claudeSessionId: str | None = None
    ownerId: str = "local"
    deviceId: str = "local"
    planId: str | None = None
    traceId: str | None = None
    batchTotal: int = 0
    batchDone: int = 0
    createdAt: int = field(default_factory=xianzai)
    updatedAt: int = field(default_factory=xianzai)
    turnCount: int = 0
    pendingPermissions: list[str] = field(default_factory=list)
    pendingQuestions: list[str] = field(default_factory=list)
    alive: bool = True
    streamEpoch: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# 工具调用的生命周期状态。与前端 `ToolCallState.type` 逐字对齐——
# 两边拼错一个字，前端会静默走 `default` 分支（显示成 completed）。
#
# 边界：P0 只有 claude_code.py 会写这些值；其他 adapter 不写，
# 前端 `guiState(undefined)` 走 completed 降级，界面可用但不区分执行中。
TOOL_STATE = {
    "streaming",              # 参数还在流（partial_json）
    "awaiting_confirmation",  # 等用户批准
    "executing",              # 已批准，正在执行
    "awaiting_post_approval", # 执行完，等用户确认结果（P0 未使用，留位）
    "completed",              # 正常结束
    "cancelled",              # 被拒绝 / 跳过 / 中断 / 超时
}


@dataclass
class AgentMessage:
    """一条完整消息（方案 6.3）。注意 seq 是会话内的消息序号，不做续传游标。"""

    messageId: str
    sessionId: str
    seq: int
    role: str
    kind: str
    text: str = ""
    toolUseId: str | None = None
    toolName: str | None = None
    toolInput: Any = None
    isError: bool = False
    isPartial: bool = False
    createdAt: int = field(default_factory=xianzai)
    # 3.1：Bridge 级全局 streamSeq，断线重连的补拉游标。
    # 只按 seq 补拉是错的——seq 是会话内序号，全局序号恒 ≥ 它，
    # 于是补拉恒定返回空数组，界面停在断线那一刻而 Agent 还在跑。
    # 放在最后是为了不打乱既有字段顺序（asdict() 的全等断言按它比）。
    xuhao: int = 0
    # 仅 tool_use / tool_cancelled 有意义：该调用的生命周期状态。
    # 空串 = 老 Bridge / 不知道，前端按 completed 处理。
    # 必须留在默认值区末尾：插到中间会改变 asdict() 的字段顺序。
    state: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PermissionRequest:
    """一次待审批的工具调用（方案 6.4）。

    inputTruncated / originalByteSize 是必填字段：审批卡要靠 inputTruncated 禁用
    「允许」按钮。schema 里少了它，被截断的命令会以 … 结尾显示而实际执行完整内容。
    """

    requestId: str
    sessionId: str
    toolName: str
    toolInput: dict[str, Any]
    # SDK 的 tool_use_id。空串 = 老 Bridge，前端降级为独立卡片。
    #
    # 注意：Claude 路径下 `requestId` 目前恒等于 `toolUseId`
    # （`http.py` 的 `_cheng_bu` 把 `toolUseId` 直接当 requestId 传），
    # 所以这不是「从无到有」的能力；显式化的理由是：
    #   1. 契约清晰，前端不必依赖隐式相等；
    #   2. 其他 adapter 的 requestId 不保证同构；
    #   3. `t-unknown` 兜底会破坏唯一性，需要能识别。
    # 必须带默认值：所有既有构造点不传也不能炸。
    toolUseId: str = ""
    title: str = ""
    displayName: str = ""
    description: str = ""
    blockedPath: str | None = None
    decisionReason: str | None = None
    agentId: str | None = None
    suggestions: list[Any] = field(default_factory=list)
    inputTruncated: bool = False
    originalByteSize: int = 0
    createdAt: int = field(default_factory=xianzai)
    expiresAt: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PendingQuestion:
    """Agent 向用户提出的待答问题（方案 6.6，走分支 A：经 can_use_tool 暴露）。"""

    questionId: str
    sessionId: str
    toolUseId: str
    questions: list[dict[str, Any]]
    state: str = "pending"  # pending | answered | cancelled | expired
    answers: list[dict[str, Any]] = field(default_factory=list)
    createdAt: int = field(default_factory=xianzai)
    expiresAt: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def guo_lu1(a1: type, a2: dict) -> dict:
    """只留 dataclass 声明过的字段。

    落盘文件是人也能改的。多出来的键直接塞进构造会 TypeError，
    而一次 TypeError 就让整个恢复失败——那等于「文件里多一个键就起不来」。
    """
    xu = {f.name for f in fields(a1)}
    return {k: v for k, v in a2.items() if k in xu}


HUI_ZI = {f.name for f in fields(AgentSession)}
XIANG_ZI = {f.name for f in fields(AgentMessage)}
