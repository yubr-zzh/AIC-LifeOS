"""Codex 适配器：接 `codex app-server`（v3.0 任务 3，方案 7.2）。

**为什么它是本轮唯一能全链路验收的新 harness**：codex 的 app-server 是
JSON-RPC 2.0 over stdio，它把「这条命令我要跑，你批不批」以 **Server→Client
请求**的形式发过来（带 id），我们用同一个 id 回响应。审批闭环就这样落地了。

## 协议事实（全部来自本机 0.157.1 导出的 schema，不是抄文档）

⚠ **方案第 4.2 节写的审批枚举 `approved` / `abort` 在本机版本里不存在。**
`codex app-server generate-json-schema --out DIR --experimental` 导出的
`CommandExecutionRequestApprovalResponse` 里，`decision` 的真实枚举是：

    "accept" | "acceptForSession" | "decline" | "cancel"
    | {"acceptWithExecpolicyAmendment": {...}} | {"applyNetworkPolicyAmendment": {...}}

文件变更那条（`FileChangeRequestApprovalResponse`）是前四个去掉两个对象变体。
cc-connect 的 `RespondPermission` 走的也是这套（`decision = "accept" | "decline"`）。
风险清单里「codex 审批枚举与文档不符」已经发生过一次，再抄错一次就是审批永远收不回来。

## 六条真机踩出来的约束（看代码看不出来的那种）

1. **`--listen stdio://` 必须显式写。** 0.152+ 任何 `--listen` 值都会让 stdio
   失去响应、全部超时（cc-connect #1781）。写 `stdio` 或 `off` 都一样。
2. **`approvalPolicy` 必须恒为 `on-request`。** codex 自己有 approval policy，
   让它按自己那套跑，用户就在 Codex 原生提示里回答了，LifeOS 的审批卡永远空着——
   这个 harness 的存在意义就没了。
3. **`turn/completed` 才是回合边界，`thread/status/changed: idle` 不是。**
   实测顺序 `turn/started` → … → `idle` → `turn/completed`，idle 早 100ms~数秒。
   拿 idle 判边界会在 Agent 还没写完结果时就收走回合。
4. **`item/completed` 与 `item/agentMessage/delta` 内容重复。** delta 是打字机效果，
   `item/completed.text` 才是完整文本。两者都发 `text` 事件 → 界面出现两条一样的消息。
5. **`item/reasoning/textDelta` 是思考，`item/agentMessage/delta` 是正文。**
   用 `messageKind` 区分，别混。
6. **审批帧不由本适配器广播。** 它调 `cheng`，由 `arbiter.jia` 广播——
   与 `claude_code` / `echo` 同口径。适配器再广播一次前端会收到两张重复的审批卡。

## 提问回路的答案形状（与 claude_code 不同，别照抄）

`ToolRequestUserInputResponse` 要 `{answers: {<questionId>: {answers: [str]}}}`，
而 `cheng("question", ...)` 回来的永远是
`PermissionResultDeny(message="用户对问题的回答：\\n- ...")`（`arbiter._du_wen`
把结构化答案拼成自然语言）。⇒ 必须从那句自然语言里把选项**解析回来**，
否则回给 codex 的是空 answers，它会把这一轮当成「用户没回答」。见 `_huida_jie_xi`。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from lifeos.bridge.adapters.chuan_shu import ZiChengAdapter

#: 握手超时。首次启动要拉起 MCP server（实测 ~5 秒），慢机器更久。
#: 给 60 秒是为了让「启动慢」表现为慢，而不是表现为失败。
SHOU_ZHEN_MIAO = 60.0
#: 单个 JSON-RPC 请求的默认预算（thread/start 要起进程，30 秒够）。
QING_QIU_MIAO = 30.0

#: Bridge 的 allow/deny → codex 的 decision 枚举（**本机 schema 为准**）。
JUECAO = {"allow": "accept", "deny": "decline"}


class CodexAdapter(ZiChengAdapter):
    """一个实例 = 一个 `codex app-server` 子进程 = 一个 codex thread。"""

    agentId = "codex"
    label = "Codex CLI"

    #: codex 的权限面由 `sandbox` 表达（read-only / workspace-write），
    #: **没有 claude-code 那种五档模式**。只声明真能兑现的三档：
    #: 传 `auto` / `dontAsk` 会被闸门 1 400 掉，而不是建一个兑现不了的会话。
    MOSHI_ZI = frozenset({"manual", "acceptEdits", "plan"})

    #: 会话 id 落在 `claudeSessionId`：**这就是 `kaishi()` 真的写出去的那个键**
    #: （下面 `self._fa("session", {…"claudeSessionId":…})`），也是
    #: `http._hui_zhuan` 的 session 分支唯一读的键。**不写 `threadId`**——
    #: `AgentSession.sessionId` 已被 LifeOS 自己的会话 id 占着。
    dui_hui_id = "claudeSessionId"
    #: app-server 是常驻进程：一条指令一个 turn，但进程活到底。
    yi_ci_xing = False
    xu_pei_zhuang = False

    #: `--listen stdio://` 必须显式写（约束 1）。
    ZHI_LING = ["codex", "app-server", "--listen", "stdio://"]

    #: **`--version` 而不是基类默认的 `--help`**。
    #: 基类抓版本号靠 `(\d+\.\d+\.\d+)` 正则，`codex --help` 的正文里
    #: 没有版本号 ⇒ 正则不匹配 ⇒ `tanjian()` 把**可执行文件路径**当版本号返回
    #: （实测抓到 `C:\...\codex.EXE`），界面上显示成一串路径。
    #: 真机 `codex --version` 输出 `codex-cli 0.157.1`，正则取到 `0.157.1`。
    #: ⚠ **不能写成 `app-server --version`**：`tanjian()` 跑的是 `[lu] + CE_WU_TOU`，
    #: `lu` 只是解析出的可执行文件，`ZHI_LING` 里那截 `app-server --listen …`
    #: **不在**探测命令里（实测 `codex app-server --version` 直接报
    #: `unexpected argument '--version'`）。
    CE_WU_TOU = ["--version"]

    def __init__(self, a1: Any = None, a2: Any = None) -> None:
        super().__init__(a1, a2)
        #: JSON-RPC 请求 id 的递增序号。**不用指令原文当 id**：codex 原样回显 id，
        #: 两个请求撞 id 就张冠李戴。
        self._qing_qiu_id = 0
        #: id -> Future，等 JSON-RPC 响应。
        self._qing_qiu_deng: dict[int, asyncio.Future] = {}
        #: 当前 turnId，中断时要用。
        self.zhuan_id = ""
        #: 本回合 Agent 说的正文（delta 累加）。
        self._zhuan_wen: list[str] = []
        #: 等待用户决定的挂起任务。**必须能在关连接时收掉**：
        #: 留着会让 `_ting_zhi_chi_cheng` 之后还有协程握着子进程 stdin。
        self._dai_dai: set[asyncio.Task] = set()

    # ---------- 能力 ----------
    @staticmethod
    def fangquan() -> bool:
        """True——app-server 会把审批请求发过来，这是本适配器存在的核心理由。"""
        return True

    @staticmethod
    def wenti2() -> bool:
        """True——`item/tool/requestUserInput` 走同一个通道。"""
        return True

    # ---------- 生命周期 ----------
    async def kaishi(self, a1: dict) -> None:
        """建立连接：spawn app-server → initialize → thread/start（或 resume）。"""
        await super().kaishi(a1)
        await self._shou_zhen()
        self.zhuan_id = ""
        cwd = a1.get("cwd") or "."
        if self.kehu_hui:
            # resume：v2.0 的 `claudeSessionId` 在这里是 codex 的 threadId。
            zhao = await self._qing_qiu("thread/resume",
                                       {"threadId": self.kehu_hui, "cwd": cwd})
            self.kehu_hui = str((zhao or {}).get("thread", {}).get("id") or self.kehu_hui)
        else:
            zhao = await self._qing_qiu("thread/start", self._thread_can(cwd))
            tid = (zhao or {}).get("thread", {}).get("id")
            if not tid:
                raise RuntimeError("codex thread/start 没有返回 threadId")
            self.kehu_hui = str(tid)
        self._fa("session", {"threadId": self.kehu_hui,
                             "claudeSessionId": self.kehu_hui})

    async def zhong_duan(self) -> None:
        """中断当前回合。

        **先发 `turn/interrupt` 再杀进程。** 直接杀的话 codex 来不及收尾，
        而我们已经收到的 delta 会停在半句上——用户看到的是「Agent 说到一半
        消失了」而不是「已中断」。
        """
        if self.jin is None:
            return
        if self.zhuan_id and self.kehu_hui:
            try:
                await asyncio.wait_for(
                    self._qing_qiu("turn/interrupt",
                                   {"threadId": self.kehu_hui, "turnId": self.zhuan_id}),
                    5.0)
            except Exception:  # noqa: BLE001
                pass  # 杀进程兜底
        await self._zhong_zhi_chi_cheng()
        self.zhuan_id = ""
        self._zhuan_wen = []

    async def gai_moshi(self, a1: str) -> None:
        """切换权限模式。

        codex 的 thread 级审批策略在线程创建时定死，`turn/start` 可按回合覆盖。
        ⇒ **approvalPolicy 恒为 `on-request`**（约束 2），热切换不动它。

        但**仍然定义这个方法**：`http._gai_moshi` 用 `hasattr` 判「这个 harness
        能不能切权限模式」，而 codex 的权限面确实是 `sandbox`（`read-only` /
        `workspace-write`），映射过去是真的生效的。下一条指令会用新档位起 turn。
        """
        if a1 not in self.MOSHI_ZI:
            raise ValueError(f"非法权限模式：{a1}")
        self.moshi = a1

    async def guan_bi(self) -> None:
        """关连接。**先收挂起任务再拆进程**（约束 6 的下半段）。"""
        for t in list(self._dai_dai):
            t.cancel()
        self._dai_dai.clear()
        await super().guan_bi()

    # ---------- 发指令 ----------
    async def _fa_chu_ming_ling(self, a1: str) -> None:
        """发一条指令 = 起一个 turn。回合结果由 `jie_shou` 判（约束 3）。"""
        await self._qing_qiu("turn/start", self._turn_can(a1))

    def jie_shou(self, a1: dict) -> dict | None:
        """**回合边界判定。这是这类适配器最承重的一行。**

        判错的后果（`chuan_shu` 文档里写过）：事件全翻译对了、单测全绿、
        真机上 `fasong()` 挂死到 15 分钟看门狗才被收走。

        真实边界是 `turn/completed`。`status == "completed"` 之外的一律当失败：
        `failed` / `interrupted`，以及不该出现在这里的 `inProgress`（出现了就是协议异常）。
        """
        if a1.get("method") != "turn/completed":
            return None
        can = a1.get("params") or {}
        zhan = can.get("turn") or {}
        zhuang = str(zhan.get("status") or "")
        cuo = zhan.get("error") or {}
        wen = "".join(self._zhuan_wen)
        xiao = {"resultText": wen, "isError": zhuang != "completed",
                "subtype": zhuang or "unknown",
                "durationMs": zhan.get("durationMs") or 0,
                "numTurns": 1, "totalCostUsd": 0.0,
                "threadId": can.get("threadId") or self.kehu_hui}
        if zhuang != "completed":
            msg = str(cuo.get("message") or f"codex 回合状态为 {zhuang!r}")
            xiao["resultText"] = msg
            xiao["errorMessage"] = msg
        self._zhuan_wen = []
        self.zhuan_id = ""
        return xiao

    # ---------- 事件翻译 ----------
    def fan_yi(self, a1: str) -> None:
        """一行 stdout → 若干统一事件。**坏行不许吞掉整轮。**"""
        try:
            zhao = json.loads(a1)
        except json.JSONDecodeError:
            self._fa("error", {"code": "codex_bad_line",
                               "message": f"codex 输出了一行非 JSON：{a1[:200]}",
                               "recoverable": True})
            return
        if not isinstance(zhao, dict):
            return
        if "id" in zhao and "method" in zhao:
            self._chui_qi(zhao)          # Server→Client 请求
        elif "id" in zhao and ("result" in zhao or "error" in zhao):
            self._da_dian(zhao)          # 响应
        elif "method" in zhao:
            self._fan_gao_gao(zhao)      # ServerNotification

    def _fan_gao_gao(self, a1: dict) -> None:
        """ServerNotification → 统一事件。判据全部来自本机 schema。"""
        fang = str(a1.get("method") or "")
        can = a1.get("params") or {}

        if fang == "turn/started":
            self.zhuan_id = str((can.get("turn") or {}).get("id") or "")
            return
        if fang == "turn/completed":
            jie = self.jie_shou(a1)
            if jie is not None:
                if jie.get("isError"):
                    self._fa("error", {"code": "codex_turn_failed",
                                       "message": jie.get("errorMessage") or "回合失败",
                                       "recoverable": False})
                self._fa("result", jie)
                self._jie_shu_kao_ben(jie)
            return
        if fang == "error":
            e = can.get("error") or {}
            self._fa("error", {"code": "codex_error",
                               "message": str(e.get("message") or "codex 报了未知错误"),
                               "recoverable": bool(can.get("willRetry"))})
            return
        if fang == "thread/status/changed":
            # **不发事件**（约束 3）：它比 turn/completed 早，当状态帧会让界面
            # 先显示「空闲」再显示「已完成」，顺序是反的。
            return

        # ---- 内容类 ----
        if fang in ("item/agentMessage/delta", "item/reasoning/textDelta",
                    "item/commandExecution/outputDelta"):
            lei = "thinking" if fang == "item/reasoning/textDelta" else "text"
            delta = str(can.get("delta") or "")
            if fang == "item/agentMessage/delta":
                self._zhuan_wen.append(delta)
            self._fa("chunk", {"messageId": self.xiang_id, "delta": delta,
                               "messageKind": lei})
            return
        if fang == "item/started":
            self._kai_xiang(can.get("item") or {})
            return
        if fang == "item/completed":
            self._wan_xiang(can.get("item") or {})
            return
        # 其余 70+ 种通知（mcpServer/*、hook/*、thread/tokenUsage/updated…）
        # 一律忽略：它们不进统一模型，硬翻译只会造出谁都不用的假字段。

    def _kai_xiang(self, a1: dict) -> None:
        """`item/started`：抓住当前消息 id，并给工具类 item 发 tool_use。"""
        lei = str(a1.get("type") or "")
        self.xiang_id = str(a1.get("id") or "")
        if lei == "agentMessage":
            self._zhuan_wen = []
        elif lei in ("userMessage", "reasoning"):
            return
        elif lei == "commandExecution":
            self._fa("tool_use", {"messageId": self.xiang_id, "toolUseId": self.xiang_id,
                                  "toolName": "Bash",
                                  "toolInput": {"command": a1.get("command") or "",
                                                "cwd": a1.get("cwd") or ""}})
        elif lei == "fileChange":
            self._fa("tool_use", {"messageId": self.xiang_id, "toolUseId": self.xiang_id,
                                  "toolName": "Edit", "toolInput": a1.get("changes") or {}})
        elif lei in ("mcpToolCall", "dynamicToolCall"):
            self._fa("tool_use", {"messageId": self.xiang_id, "toolUseId": self.xiang_id,
                                  "toolName": str(a1.get("tool") or lei),
                                  "toolInput": a1.get("arguments") or {}})

    def _wan_xiang(self, a1: dict) -> None:
        """`item/completed`：发 tool_result；正文按约束 4 去重。"""
        lei = str(a1.get("type") or "")
        # **只处理带顶层 `text` 的类型。** `userMessage` 的正文在
        # `content[].text` 里、顶层没有 `text`，所以它自然落不到下面任何
        # 分支——界面不会把用户自己的输入再显示一遍。这里**特意不写
        # `if lei == "userMessage": return`**：变异验证实测那条提前返回是
        # 不可达代码（删掉它输出完全不变），而写着「防 userMessage 回显」
        # 的死代码会让人以为这里有一道真的防线。判据落在「有没有 text」
        # 上，天然就够。
        if lei == "agentMessage":
            wen = str(a1.get("text") or "")
            # delta 已经逐字发过 chunk（打字机效果）。**这里只在 text 非空时
            # 补一条完整消息**——`_hui_zhuan` 的 chunk 不落消息，只有这条落，
            # 界面才有一份可复制的完整回复。重复发会让界面出现两条一样的消息。
            if wen:
                self._fa("text", {"messageId": self.xiang_id, "text": wen})
            return
        if lei == "commandExecution":
            self._fa("tool_result", {"toolUseId": str(a1.get("id") or ""), "toolName": "Bash",
                                     "text": str(a1.get("aggregatedOutput") or ""),
                                     "isError": (a1.get("exitCode") or 0) != 0})
        elif lei == "fileChange":
            self._fa("tool_result", {"toolUseId": str(a1.get("id") or ""), "toolName": "Edit",
                                     "text": f"文件变更：{len(a1.get('changes') or {})} 处",
                                     "isError": False})
        elif lei in ("mcpToolCall", "dynamicToolCall"):
            self._fa("tool_result", {"toolUseId": str(a1.get("id") or ""),
                                     "toolName": str(a1.get("tool") or lei),
                                     "text": json.dumps(a1.get("result") or {},
                                                        ensure_ascii=False),
                                     "isError": a1.get("error") is not None})

    # ---------- 审批与提问（挂起通道）----------
    def _chui_qi(self, a1: dict) -> None:
        """Server→Client 请求。

        **必须在读循环里同步消化掉，绝不能因不认识就静默不回**：
        不回的话 codex 一直等那个 id，回合卡到超时，用户看到的是「无响应」。
        不认识的直接回 `-32601 method not found`（cc-connect 走同一条路）。

        审批帧**不由这里广播**（约束 6）：调 `cheng` 交给 arbiter，它登记时广播。
        """
        fang = str(a1.get("method") or "")
        can = a1.get("params") or {}
        if fang == "item/tool/requestUserInput":
            self._qi_ren_wu(
                "question", {"toolUseId": str(can.get("itemId") or a1.get("id")),
                             "questions": can.get("questions") or [],
                             "title": "codex 需要你做选择"},
                lambda zhao: {"answers": self._huida_jie_xi(zhao, can.get("questions") or [])},
                a1.get("id"))
        elif fang in ("item/commandExecution/requestApproval",):
            self._qi_ren_wu(
                "permission", {"toolUseId": str(can.get("itemId") or can.get("approvalId")
                                                or a1.get("id")),
                               "toolName": "Bash",
                               "toolInput": {"command": can.get("command") or "",
                                             "cwd": can.get("cwd") or ""},
                               "title": can.get("reason") or "codex 想执行一条命令"},
                lambda zhao: self._jue_ding(zhao), a1.get("id"))
        elif fang in ("item/fileChange/requestApproval",):
            self._qi_ren_wu(
                "permission", {"toolUseId": str(can.get("itemId") or can.get("approvalId")
                                                or a1.get("id")),
                               "toolName": "Edit",
                               "toolInput": can.get("fileChanges") or {},
                               "title": can.get("reason") or "codex 想改文件"},
                lambda zhao: self._jue_ding(zhao), a1.get("id"))
        elif fang in ("item/permissions/requestApproval",):
            self._qi_ren_wu(
                "permission", {"toolUseId": str(can.get("itemId") or a1.get("id")),
                               "toolName": "Permissions",
                               "toolInput": can.get("permissions") or {},
                               "title": can.get("reason") or "codex 想申请额外权限"},
                lambda zhao: ({"permissions": can.get("permissions") or {}, "scope": "turn"}
                              if self._shi_allow(zhao) else {"permissions": {}}),
                a1.get("id"))
        else:
            self._hui_yi(a1.get("id"), error_code=-32601)
            return
        # `_qi_ren_wu` 内部已经把自己登记进 `_dai_dai`（并挂上 discard 回调）。

    def _qi_ren_wu(self, a1: str, a2: dict, a3: Any, a4: Any) -> asyncio.Task | None:
        """起一个挂起任务：交给 Bridge 等用户决定，再把结果回写给 codex。

        **必须起任务而不是直接 await**：调用点在读循环里（`fan_yi`），
        那里不能 await —— await 的话审批还没收口，读循环就停了，
        而审批请求的 id 就在这条读循环上，codex 那边永远等不到下一个响应。

        **没有 loop 时返回 None 而不是抛异常**：`fan_yi` 是同步函数，
        单元测试可以直接调它（不 spawn 子进程）。生产路径上 `kaishi()` 已经
        设好 `self.loop`，所以这个分支只在测试与异常路径上走到——
        但它必须安静地退化，因为抛异常会被 `_du_zhan` 的
        `except Exception` 吞成一条 `translate_failed` 帧，
        而挂起请求**一个都没被回**，codex 那边就一直等到回合超时。
        """
        loop = self.loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                self._hui_yi(a4, {"decision": "decline"})
                return None

        async def zhuo() -> None:
            try:
                zhao = await self._cheng(a1, a2)
            except asyncio.CancelledError:
                # 关连接时要给 codex 一个明确答复，否则它那边挂着等。
                self._hui_yi(a4, {"decision": "decline"})
                raise
            except Exception:  # noqa: BLE001
                self._hui_yi(a4, {"decision": "decline"})
                return
            self._hui_yi(a4, a3(zhao))

        fu = loop.create_task(zhuo())
        self._dai_dai.add(fu)
        fu.add_done_callback(self._dai_dai.discard)
        return fu

    # ---------- JSON-RPC 收发 ----------
    async def _shou_zhen(self) -> None:
        """initialize 请求 + initialized 通知。**两个都要发**，
        只发请求的话 codex 不开始接受 thread/start。"""
        await self._qing_qiu("initialize",
                             {"clientInfo": {"name": "lifeos-bridge", "version": "3.0"},
                              "capabilities": {"experimentalApi": True}}, SHOU_ZHEN_MIAO)
        await self._xie_xia({"jsonrpc": "2.0", "method": "initialized", "params": {}})

    async def _qing_qiu(self, a1: str, a2: dict, a3: float = QING_QIU_MIAO) -> Any:
        """发一个 JSON-RPC 请求并等响应。**id 单调递增、不复用。**"""
        self._qing_qiu_id += 1
        bian = self._qing_qiu_id
        fu = (self.loop or asyncio.get_event_loop()).create_future()
        self._qing_qiu_deng[bian] = fu
        try:
            await self._xie_xia({"jsonrpc": "2.0", "id": bian, "method": a1, "params": a2})
            zhao = await asyncio.wait_for(fu, a3)
        finally:
            self._qing_qiu_deng.pop(bian, None)
        if isinstance(zhao, dict) and zhao.get("error"):
            e = zhao["error"]
            raise RuntimeError(f"codex {a1} 失败：{e.get('message') or e}")
        return (zhao or {}).get("result")

    async def _xie_xia(self, a1: dict) -> None:
        """写一行 JSON 到 stdin。**必须带换行且 drain**——按行成帧，
        少换行 codex 那边就一直等，症状是「握手全部超时」。"""
        if self.jin is None or self.jin.stdin is None:
            raise RuntimeError("codex 子进程没起来")
        self.jin.stdin.write((json.dumps(a1, ensure_ascii=False) + "\n").encode("utf-8"))
        await self.jin.stdin.drain()

    def _da_dian(self, a1: dict) -> None:
        """JSON-RPC 响应 → 唤醒对应 Future。"""
        try:
            bian = int(a1.get("id"))
        except (TypeError, ValueError):
            return
        fu = self._qing_qiu_deng.get(bian)
        if fu is not None and not fu.done():
            fu.set_result(a1)

    def _hui_yi(self, a1: Any, a2: dict | None = None,
                error_code: int | None = None) -> None:
        """用**同一个 id** 回响应（审批决定必须原路返回）。

        同步写：调用点在读循环或挂起任务里，两个地方都不该为一次写盘 await。
        """
        xiang: dict[str, Any] = {"jsonrpc": "2.0", "id": a1}
        if error_code is not None:
            xiang["error"] = {"code": error_code, "message": "method not found"}
        else:
            xiang["result"] = a2 or {}
        if self.jin is None or self.jin.stdin is None:
            return
        try:
            self.jin.stdin.write((json.dumps(xiang, ensure_ascii=False) + "\n")
                                 .encode("utf-8"))
        except Exception:  # noqa: BLE001
            pass

    # ---------- 参数构造 ----------
    @staticmethod
    def _thread_can(a1: str) -> dict[str, Any]:
        """`thread/start` 的参数。

        **`approvalPolicy: "on-request"` 与 `sandbox: "read-only"` 是硬约束**
        （约束 2）：不给 on-request，codex 按自己策略跑，用户就在它原生提示里
        回答了；sandbox 给 read-only 是闸门 2 的兜底，不是用户的授权。
        """
        return {"cwd": a1, "approvalPolicy": "on-request", "sandbox": "read-only",
                "experimentalRawEvents": False, "persistExtendedHistory": False}

    def _turn_can(self, a1: str) -> dict[str, Any]:
        """`turn/start` 的参数。`input` 必须是 `[{type:"text",text:…}]`（schema 必需）。

        ⚠ **`sandboxPolicy` 的形状是 `{type: "readOnly"|"workspaceWrite"}`，不是
        `{mode: "read-only"}`。** 两者都写在文档里（`thread/start` 用的是
        `sandbox: "read-only"` 字符串枚举，`turn/start` 用的是这个对象），
        传错的话 codex 会**静默忽略**这个字段并沿用 thread 级设置——
        `acceptEdits` 于是不生效，而界面上模式显示的是 acceptEdits。

        **这里不开 `dangerFullAccess`**：用户授权走审批卡，不走 sandbox。
        """
        shen = "workspaceWrite" if self.moshi == "acceptEdits" else "readOnly"
        return {"threadId": self.kehu_hui,
                "input": [{"type": "text", "text": a1, "text_elements": []}],
                "approvalPolicy": "on-request",
                "sandboxPolicy": {"type": shen, "networkAccess": False}}

    # ---------- 决定与答案的翻译 ----------
    @staticmethod
    def _shi_allow(a1: Any) -> bool:
        """Bridge 回来的决定怎么算「允许」。

        `arbiter.shou` 对 allow 回 `PermissionResultAllow`，对 deny 回
        `PermissionResultDeny`。**不能用 `if zhao:` 判**——`Deny` 也是真对象。
        判错的方向必须是 deny：安全侧默认。
        """
        if a1 is None:
            return False
        xing = getattr(a1, "behavior", None)
        if xing is not None:
            return str(xing).lower() in ("allow", "accept")
        if isinstance(a1, dict):
            return bool(a1.get("allowed"))
        return False

    def _jue_ding(self, a1: Any) -> dict[str, Any]:
        """allow/deny → codex 的 decision 枚举（**本机 schema 为准**）。"""
        return {"decision": JUECAO["allow" if self._shi_allow(a1) else "deny"]}

    @staticmethod
    def _huida_jie_xi(a1: Any, a2: list[dict]) -> dict[str, dict[str, list[str]]]:
        """从 `PermissionResultDeny(message=…)` 里把答案解析回 codex 的形状。

        Bridge 侧 `arbiter._du_wen` 把结构化答案拼成
        `用户对问题的回答：\\n- 值` 这样的自然语言交给适配器，
        而 codex 要 `{<questionId>: {answers: [选中项的 label]}}`。

        **只能靠选项 label 闭集匹配**：每个 label 都是我们自己发给 codex 的，
        候选集已知。匹配不上就交空 answers——codex 会当「没回答」，
        那是对的方向（比回一个它不认识的答案好）。
        """
        wen = str(getattr(a1, "message", "") or "")
        da: dict[str, dict[str, list[str]]] = {}
        if not wen:
            return da
        for wen_ti in a2 or []:
            qid = str(wen_ti.get("id") or "")
            if not qid:
                continue
            for xuan in (wen_ti.get("options") or []):
                biao = str(xuan.get("label") or "")
                if biao and biao in wen:
                    da[qid] = {"answers": [biao]}
                    break
        return da