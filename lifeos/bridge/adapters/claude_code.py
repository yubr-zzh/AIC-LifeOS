"""Claude Code 适配器：接真实的 claude-agent-sdk（方案 9.3、任务 3.1–3.5）。

**这个文件是 SDK 与本项目之间唯一的翻译层。** 上层（session / arbiter / http）
永远只见 6.3 的统一模型，看不见任何 `snake_case` 的 SDK 字段。
把翻译逻辑散到别处，等于同一套映射要写两遍，然后两遍都会漂。

三条实测得来的硬约束（`docs/bridge-spike-report.md`，比方案正文优先）：

1. `permission_mode="bypassPermissions"` 下 `can_use_tool` **永不被调用**。
   所以本文件不做模式白名单，那是 `planner_guard.py` 闸门 1 的事。
2. `ToolPermissionContext.title` 在 `AskUserQuestion` 场景恒为 `null`。
   提问的标题只能自己从 `input.questions[0].question` 取。
3. `AskUserQuestion` 的答案只能用 `PermissionResultDeny(message=...)` 回传。
   单纯 allow 等于「用户没回答」，Agent 会明说「选择被取消了」。

**边界（方案 9.1）**：本文件不知道 HTTP、SSE、token、隧道的存在。
它只做四件事——spawn、收发、权限回调、提问回调。事件通过注入的两个回调出去：
`hui`（发事件）与 `cheng`（挂起等决定）。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ConversationResetMessage,
    PermissionResultDeny,
    RateLimitEvent,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    ToolPermissionContext,
    UserMessage,
)

from lifeos.bridge.adapters.base import AgentAdapter
from lifeos.bridge.pingju import gel as _ge_li

# **SDK 子进程窗口闪现的修补（2026-10-10）。**
# Bridge 由主服务以 `DETACHED_PROCESS` 拉起，自身无控制台；SDK 经
# `anyio.open_process` spawn 的 claude CLI 继承不到控制台就自开一个新窗口，
# 跑完即关——网页上表现为闪现的终端窗。SDK 不暴露 creationflags，故在
# 模块加载时对 `anyio.open_process` 做一次性包装：win32 上补
# `CREATE_NO_WINDOW`，其余平台原样透传。只影响本进程，不改 SDK 文件。
# 依据：anyio 的 asyncio 后端把多余 kwargs 透传给
# `asyncio.create_subprocess_exec`，与 SDK 调用处的参数不冲突。
import anyio as _anyio
import sys as _sys

_yuan_open_process = _anyio.open_process


def _open_process(*a: Any, **kw: Any) -> Any:
    if _sys.platform == "win32":
        kw["creationflags"] = kw.get("creationflags", 0) | 0x08000000  # CREATE_NO_WINDOW
    return _yuan_open_process(*a, **kw)


_anyio.open_process = _open_process

# 方案 9.3：max_turns 取 200。单条委派指令是「有明确终点的任务」，
# 200 轮足够；再高说明指令拆分本身有问题。
ZHUAN_SHANG = 200

# **单会话花费封顶已取消**（用户 2026-10-02 裁定）。原来这里是
# `XIAN_GE = 5.0`，与 `max_turns` 两个维度一起封（轮数 + 美元）。常量与
# 那行 `max_budget_usd` 一并删掉了，别加回来。
#
# **为什么是「不下发」而不是传 `-1` 或一个很大的数**（SDK 的真实语义，
# 2026-10-02 对着 `.venv` 核过，不是照文档）：`claude_agent_sdk/types.py:2056`
# 是 `max_budget_usd: float | None = None`，而
# `_internal/transport/subprocess_cli.py:613` 只在 `is not None` 时才
# `cmd.extend(["--max-budget-usd", ...])`。⇒ **`None` 才表示压根不给这个
# flag**；`-1` 会被原样交给 CLI，那是错的做法。
#
# **`maxBudgetUsd` 这个请求体字段保留但一律不读。** 删字段是破坏性变更，
# 前端契约不破；而忽略它已经达到了「服务端不设预算」的全部效果。**别把
# `a1.get("maxBudgetUsd")` 加回来**：留着那个入口等于换个名字把单会话预算
# 留着，还能让调用方按会话设上限——而「取消」的意思是服务端不设、也不接受
# 调用方设。
#
# **这条与并发上限无关，别一起改。** 每用户 5 个并发会话的额度
# （`session.ZUI_DUO_HUI`）照旧，那是资源隔离，不是花费封顶。

# SDK 的 permission_mode 字面量里没有 "manual"，是 "default"（方案变更记录已纠错）。
MO_SHI = {"manual": "default", "acceptEdits": "acceptEdits", "plan": "plan",
          "auto": "auto", "dontAsk": "dontAsk"}


def _qu(a1: Any, a2: str, a3: Any = None) -> Any:
    """取一个字段，dict 与对象都支持。

    **SDK 给的是 dataclass 实例（`ToolUseBlock` / `TextBlock` / …），不是 dict。**
    实测（`tools/_probe_sdk.py`）：按 dict 写的翻译器在真机上一条消息都翻译不出来，
    而照着 spike 报告里的 dict 形态写的单测全绿——报告里记的是渲染后的形态。
    两种都要认，否则要么单测假通过、要么真机全哑。
    """
    if isinstance(a1, dict):
        return a1.get(a2, a3)
    return getattr(a1, a2, a3)


def shi_ren(a1: Any) -> dict[str, Any]:
    """把 SDK 的一块内容翻译成统一模型的字段。

    **不能靠 `block.type` 分派**——实测内容块上根本没有 `type` 字段。
    只能按字段存在性判断，顺序也有讲究：ToolUseBlock 同时有 `id`/`name`/`input`，
    先判它才不会和别的块混淆。
    """
    if a1 is None:
        return {}
    if _qu(a1, "id") is not None and _qu(a1, "name") is not None:
        return {"kind": "tool_use", "toolUseId": _qu(a1, "id", ""),
                "toolName": _qu(a1, "name", ""), "toolInput": _qu(a1, "input", {})}
    if _qu(a1, "thinking") is not None:
        return {"kind": "thinking", "text": _qu(a1, "thinking", "")}
    if _qu(a1, "text") is not None:
        return {"kind": "text", "text": _qu(a1, "text", "")}
    return {}


class ClaudeCodeAdapter(AgentAdapter):
    """真实适配器。一个实例 = 一个 claude 子进程 = 一个 Agent 会话。"""

    agentId = "claude-code"
    label = "Claude Code"

    def __init__(self, a1: Any = None, a2: Any = None) -> None:
        self.hui = a1      # 事件回调 (kind, payload)
        self.cheng = a2    # 挂起回调 async (kind, payload) -> 任何值
        self.kehu: ClaudeSDKClient | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.moshi = "manual"
        self.gong_ju: dict[str, str] = {}   # toolUseId -> toolName（工具结果块里没有名字）
        self.xiang_id = ""                  # 当前流式消息的 messageId
        self.kehu_hui = ""                   # SDK 的 session_id
        self.guan_le = False
        self.zhu_zi = 0

    # ---------- 对外能力（方案 9.2）----------
    @staticmethod
    def fangquan() -> bool:
        """能否接管权限。True——这正是本适配器存在的理由。"""
        return True

    @staticmethod
    def wenti2() -> bool:
        """能否接管提问。True（经 can_use_tool 暴露，spike 报告第 6 节）。"""
        return True

    async def tanjian(self) -> dict[str, Any]:
        """探测本机是否可用。**绝不能抛异常**——探测失败要能被当成数据返回。"""
        import importlib.metadata as md
        import re as _re
        import subprocess

        ban = None
        try:
            ban = md.version("claude-agent-sdk")
        except md.PackageNotFoundError:
            pass
        try:
            kw: dict[str, Any] = {}
            if _sys.platform == "win32":
                # Bridge 无控制台（DETACHED_PROCESS 拉起），探测子进程不补
                # CREATE_NO_WINDOW 就会在桌面闪现终端窗。
                kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
            chu = subprocess.run(["claude", "--version"], capture_output=True,
                                 text=True, timeout=10, **kw)
            m = _re.search(r"(\d+\.\d+\.\d+)", chu.stdout or "")
            cli = m.group(1) if m else None
        except (OSError, subprocess.SubprocessError):
            cli = None
        if cli is None:
            return {"available": False, "version": None, "sdkVersion": ban,
                    "error": "本机找不到 claude CLI，或它没有版本号"}
        return {"available": True, "version": cli, "sdkVersion": ban, "error": None}

    async def kaishi(self, a1: dict) -> None:
        """建立底层连接。a1 含 cwd、permissionMode、resume、maxTurns 等。"""
        self.loop = asyncio.get_running_loop()
        mo = a1.get("permissionMode", "manual")
        if mo not in MO_SHI:  # 正常不会走到：planner_guard 闸门 1 已经拒了
            mo = "manual"
        self.moshi = mo
        self.kehu = ClaudeSDKClient(ClaudeAgentOptions(
            cwd=a1["cwd"],
            permission_mode=MO_SHI[mo],
            can_use_tool=self._fangquan,
            include_partial_messages=True,   # chunk 帧的来源
            max_turns=int(a1.get("maxTurns", ZHUAN_SHANG)),
            # **刻意不下发 `max_budget_usd`。** 单会话预算已取消（裁定见模块顶部
            # `ZHUAN_SHANG` 下面那段）：不下发这个参数 → `ClaudeAgentOptions`
            # 用它自己的默认 `None` → SDK 不往 CLI 塞 `--max-budget-usd`。
            # 请求体里的 `maxBudgetUsd` 也**故意不读**——详见顶部那段。
            # 改动三（2026-10-10）：隔离关（默认）时加载 user + project 两级——
            # CLAUDE.md、skills、settings.json 全部生效，harness 表现得像用户
            # 自己开的终端。只有 `LIFEOS_GELI=1` 回到空列表：不加载用户的
            # 任何本机配置（spike 报告第 2 节实测不丢上下文），委派环境干净
            # 可预测——多人共用一台机器时才值得付这个代价。
            setting_sources=[] if _ge_li() else ["user", "project"],
            resume=a1.get("resume"),
            # 凭据隔离（spec 11.2）。不传时 SDK 走 `~/.claude`，多人共用一台
            # 机器就是共用凭据（15.5 点名的风险）。传的是**增量**：SDK 把
            # options.env 展开在继承来的 os.environ 之后（只覆盖同名键），
            # 所以只给 CLAUDE_CONFIG_DIR 不会把 SYSTEMROOT/PATH 抹掉。
            # **必须归一成 dict，绝不能传 None。** SDK 0.2.160 的
            # `ClaudeAgentOptions.env` 默认是空 dict，但显式传 None 会被
            # dataclass 原样存下；transport 里 `{**inherited, **options.env}`
            # 随即 `TypeError: 'NoneType' object is not a mapping`，被包成
            # `CLIConnectionError: Failed to start Claude Code` —— 前端连
            # 后端一开会话就报的那个错（2026-10-10 实测复现）。
            env=a1.get("env") or {},
        ))
        await self.kehu.connect()
        self.guan_le = False

    async def fasong(self, a1: str) -> dict:
        """发一条指令并等这一轮跑完。回合边界由 ResultMessage 判定（方案 9.3）。"""
        if self.kehu is None:
            raise RuntimeError("会话尚未建立")
        await self.kehu.query(a1)
        zhao: ResultMessage | None = None
        async for xin in self.kehu.receive_response():
            self._fan(xin)
            if isinstance(xin, ResultMessage):
                zhao = xin
        if zhao is None:
            # 一条 ResultMessage 都没有就收流：进程已经死了。
            # 这里必须显式失败——返回空 dict 会让回合编排器以为本条成功了。
            raise RuntimeError("这一轮没有收到 ResultMessage，Agent 进程可能已退出")
        self.zhu_zi += 1
        return {
            "resultText": zhao.result or "",
            "isError": bool(zhao.is_error),
            "subtype": zhao.subtype or "",
            "durationMs": int(zhao.duration_ms or 0),
            "numTurns": int(zhao.num_turns or 0),
            "totalCostUsd": float(zhao.total_cost_usd or 0.0),
        }

    async def zhong_duan(self) -> None:
        """中断当前回合。

        注意与「取消挂起回调」的区别：spike 报告第 4 节实测，被挂起的
        `can_use_tool` 协程会收到 CancelledError，同时 SDK 产出
        `ResultMessage(subtype="error_during_execution")`。挂起项的收口由
        arbiter 负责（它已经先被 `ShenQing.zhong_duan` 收口过了），本函数只管发信号。
        """
        if self.kehu is not None:
            await self.kehu.interrupt()

    async def guan_bi(self) -> None:
        """关闭连接并回收子进程。"""
        self.guan_le = True
        if self.kehu is not None:
            try:
                await self.kehu.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self.kehu = None

    async def gai_moshi(self, a1: str) -> None:
        """切换权限模式，不重启进程。**调用方必须先过白名单**（8.3 闸门 1）。"""
        if a1 not in MO_SHI:
            raise ValueError(f"非法权限模式：{a1}")
        if self.kehu is not None:
            await self.kehu.set_permission_mode(MO_SHI[a1])
        self.moshi = a1

    # ---------- 权限与提问（3.3、3.4）----------
    def _fangquan(self, a1: str, a2: dict, a3: ToolPermissionContext):
        """`can_use_tool` 是同步入口返回 awaitable，不能直接写成 async。"""
        return self._deng(a1, a2, a3)

    async def _deng(self, a1: str, a2: dict, a3: ToolPermissionContext):
        # 空串与 None 一样有害：requestId 为空时 POST /permissions/ 会打到错误路径，
        # 而 R3 的幂等是建立在这个 ID 上的。
        if not a3.tool_use_id:
            # 方案 9.3 的硬校验。放它进来会让每张卡都 POST /permissions/None → 404
            # → 一直挂到超时；R3 的幂等完全建立在这个 ID 上。
            self._fa("error", {"code": "missing_tool_use_id", "toolName": a1,
                               "message": "SDK 未提供 tool_use_id，已拒绝该调用",
                               "recoverable": True})
            return PermissionResultDeny(message="缺少 tool_use_id，无法向你确认，已拒绝")

        if a1 == "AskUserQuestion":
            # 6.6 分支 A。title 在这个场景恒为 null，标题自己从 input 里取。
            wen = a2.get("questions") or []
            biaoti = _qu(wen[0], "question", "") if wen else ""
            return await self._cheng("question", {
                "toolUseId": a3.tool_use_id,
                "questions": wen,
                "title": biaoti or "Agent 需要你做选择",
            })

        return await self._cheng("permission", {
            "toolUseId": a3.tool_use_id,
            "toolName": a1,
            "toolInput": a2,
            "title": a3.title or "",
            "displayName": a3.display_name or "",
            "description": a3.description or "",
            "blockedPath": a3.blocked_path,
            "decisionReason": a3.decision_reason,
            "agentId": a3.agent_id,
            "suggestions": self._ti_yi(a3.suggestions),
        })

    @staticmethod
    def _ti_yi(a1: Any) -> list[dict[str, Any]]:
        """把 SDK 的 suggestions 归一成 6.4 的形状。"""
        out = []
        for u in a1 or []:
            if isinstance(u, dict):
                out.append(u)
                continue
            out.append({
                "type": getattr(u, "type", "addRules"),
                "behavior": getattr(u, "behavior", "allow"),
                "mode": getattr(u, "mode", None),
                "directories": getattr(u, "directories", None),
                "destination": getattr(u, "destination", "session"),
                "rules": [{"toolName": getattr(r, "tool_name", ""),
                           "ruleContent": getattr(r, "rule_content", None)}
                          for r in (getattr(u, "rules", None) or [])],
            })
        return out

    async def _cheng(self, a1: str, a2: dict) -> Any:
        """交给 Bridge 的挂起通道。没有挂起能力时一律拒绝（安全侧默认）。"""
        if self.cheng is None:
            return PermissionResultDeny(message="没有可用的审批通道，已拒绝")
        try:
            return await self.cheng(a1, a2)
        except asyncio.CancelledError:
            # 用户中断会走到这里。**必须原样抛出**：吞掉它会让上层以为
            # 这次调用正常返回了，而 Agent 那边已经在取消这条协程了。
            raise

    # ---------- 消息翻译（3.2）----------
    def _fan(self, a1: Any) -> None:
        """一条 SDK 消息 → 若干统一模型事件。异常一律转 error 帧，不让协程静默死掉。"""
        try:
            if isinstance(a1, SystemMessage):
                if a1.subtype == "init":
                    self.kehu_hui = (a1.data or {}).get("session_id", "")
                    self._fa("session", {"claudeSessionId": self.kehu_hui})
                return
            if isinstance(a1, StreamEvent):
                self._liu(a1)
                return
            if isinstance(a1, AssistantMessage):
                if a1.error:
                    self._fa("error", {"code": "assistant_error",
                                       "message": str(a1.error), "recoverable": True})
                # message_id 与 chunk 帧的 messageId 同源：前端靠它把流式增量
                # 归并到最终消息上，缺了就只能把两条都显示出来。
                mid = _qu(a1, "message_id") or ""
                for b in a1.content or []:
                    self._kuai(b, mid)
                return
            if isinstance(a1, UserMessage):
                for b in a1.content or []:
                    tid = _qu(b, "tool_use_id")
                    if tid is None:
                        continue
                    self._fa("tool_result", {
                        "toolUseId": tid,
                        "toolName": self.gong_ju.get(tid, ""),
                        "text": self._wen_lu(_qu(b, "content")),
                        "isError": bool(_qu(b, "is_error")),
                        # 前端据此把调用推进到 completed。老版本没有这个键，
                        # 前端 guiState(undefined) 走默认分支，不会崩。
                        "state": "completed",
                    })
                return
            if isinstance(a1, ResultMessage):
                self._fa("result", {
                    "subtype": a1.subtype or "",
                    "durationMs": int(a1.duration_ms or 0),
                    "numTurns": int(a1.num_turns or 0),
                    "totalCostUsd": float(a1.total_cost_usd or 0.0),
                    "isError": bool(a1.is_error),
                    "resultText": a1.result or "",
                })
                if a1.is_error and (a1.subtype or "") != "success":
                    self._fa("error", {
                        "code": a1.subtype or "agent_error",
                        "message": self._wen_lu(a1.errors) or (a1.result or "Agent 报错"),
                        "recoverable": (a1.subtype or "") != "error_during_execution",
                    })
                return
            if isinstance(a1, RateLimitEvent):
                d = a1.rate_limit_info
                self._fa("rate_limit", {"text": f"触发限流：{getattr(d, 'status', '')} "
                                                f"{getattr(d, 'resets_at', '')}".strip()})
                return
            if isinstance(a1, ConversationResetMessage):
                self.kehu_hui = a1.new_conversation_id or ""
                self._fa("context_reset", {"text": "上下文已重置，Agent 换了一个新会话"})
                self._fa("session", {"claudeSessionId": self.kehu_hui})
                return
        except Exception as e:  # noqa: BLE001
            self._fa("error", {"code": "translate_failed",
                               "message": f"{type(e).__name__}: {e}", "recoverable": True})

    def _kuai(self, a1: Any, a2: str = "") -> None:
        """翻译 AssistantMessage 里的一块内容。a2 是该消息的 SDK message_id。"""
        d = shi_ren(a1)
        if not d:
            return
        if d["kind"] == "tool_use":
            self.gong_ju[d["toolUseId"]] = d["toolName"]
            # 走到 _kuai 说明这里是**完整** AssistantMessage 的内容块，
            # 参数已经成型（partial_json 走的是 _liu 的 chunk 帧）。
            # 因此这里标 executing 而不是 streaming；需要审批时，
            # 随后的 permission 帧会把它改成 awaiting_confirmation。
            d["state"] = "executing"
        if a2:
            d["messageId"] = a2
        self._fa(d["kind"], d)

    def _liu(self, a1: StreamEvent) -> None:
        """StreamEvent → chunk 帧。chunk 不是真相（6.3），只用于打字机效果。"""
        e = a1.event if isinstance(a1.event, dict) else {}
        lei = e.get("type", "")
        if lei == "message_start":
            # 抓住这条消息的 id：后续所有 delta 与最终的 AssistantMessage.message_id
            # 是同一个值，前端才能按 messageId 分组、收到完整帧时整段替换。
            self.xiang_id = (e.get("message") or {}).get("id", "") or a1.uuid
            return
        if lei == "message_stop":
            self.xiang_id = ""
            return
        delta = e.get("delta") or {}
        wen = delta.get("text") or delta.get("thinking") or delta.get("partial_json") or ""
        if not wen:
            return
        if "partial_json" in delta:
            kinds = "tool_use"
        elif "thinking" in delta:
            kinds = "thinking"
        else:
            kinds = "text"
        self._fa("chunk", {"messageId": self.xiang_id or a1.uuid,
                           "delta": wen, "messageKind": kinds})

    @staticmethod
    def _wen_lu(a1: Any) -> str:
        """工具结果 / 错误列表 → 纯文本。结构不固定，只做尽力提取。"""
        if a1 is None:
            return ""
        if isinstance(a1, str):
            return a1
        if not isinstance(a1, (list, dict)):
            # SDK 的块对象（如 ToolResultBlock）直接取文本字段
            wen = _qu(a1, "text")
            if wen is not None:
                return str(wen)
        if isinstance(a1, list):
            return "\n".join(ClaudeCodeAdapter._wen_lu(x) for x in a1 if x is not None)
        if isinstance(a1, dict):
            if "text" in a1:
                return str(a1["text"])
            if "content" in a1:
                return ClaudeCodeAdapter._wen_lu(a1["content"])
            return json.dumps(a1, ensure_ascii=False)[:2000]
        return str(a1)

    # ---------- 子进程 pid（3.6）----------
    def qu_pid(self) -> int | None:
        """取 SDK spawn 出来的 claude 子进程 pid。

        SDK 用 `anyio.open_process` 起进程并存在 transport 的 `_process` 上，
        没有公开的 pid 属性。这里读私有路径，读不到就返回 None——
        宁可不记 pid（下次靠父进程死亡带走），也不要猜一个 pid 去 kill。
        """
        try:
            jin = getattr(self.kehu, "_transport", None)
            jin = getattr(jin, "_process", None)
            pid = getattr(jin, "pid", None)
            return int(pid) if isinstance(pid, int) and pid > 0 else None
        except Exception:  # noqa: BLE001
            return None

    def _fa(self, a1: str, a2: dict) -> None:
        if self.hui:
            try:
                self.hui(a1, a2)
            except Exception:  # noqa: BLE001
                pass
