"""审批与提问的唯一收口（方案 8.5、8.2、8.7）。

**所有**决定路径——用户点按、建议规则、超时、中断、截断、清扫、跨重启重放——
都必须汇入 `ShenQing.shou()` 这一个函数。这是反例 #1 的解药：只要存在第二条收口路径，
两条路径迟早会在某次并发下给出互相矛盾的决定。

三条不可违反的语义：

1. **幂等**：已收口的再收一次返回 `already_resolved`，绝不重复执行。
2. **先标记后交回**（第 6 步在第 11 步之前）：否则交回期间来的第二个决定会重复
   触发第 11 步。
3. **同步函数**：第 11 步用 `future.set_result()` 而不是 `await`。这样收口不会被
   SDK 的 event loop 调度卡住，也不会在多线程的 HTTP 请求处理线程里 await。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from claude_agent_sdk import (
    PermissionResult,
    PermissionResultAllow,
    PermissionResultDeny,
    PermissionUpdate,
)

from lifeos.bridge.models import PendingQuestion, PermissionRequest, lingshou, xianzai
from lifeos.bridge.planner_guard import JuDuan, ShenKa

# 8.2.1：下行单帧上限。只截断字符串值，标识类字段一律不碰。
ZHEN_KUANG = 64 * 1024

# 8.7：三层超时的默认值
SHEN_HE = 600.0  # 审批超时 10 分钟
TING_GE = 900.0  # 停滞超时 15 分钟
XIAN_ZHI = 1800.0  # 闲置超时 30 分钟

# 3.2：决定的中文文案。取消与拒绝必须可区分（8.6）——落盘后一眼能看出
# 是用户亲手点的，还是超时/规则自动判的。
JUE_ZHU = {"user_allow": "用户手动批准", "user_deny": "用户手动拒绝",
           "auto_deny": "系统自动拒绝"}
JUE_YUAN = {"timeout": "等待审批超时", "interrupt": "用户中断了本次委派",
            "truncated": "输入被截断，无法安全批准", "deny_baseline": "命中禁止规则"}


def zhen_duan(a1: Any, a2: int = ZHEN_KUANG) -> tuple[Any, bool, int]:
    """按字节预算截断。返回 (截断后, 是否截断, 原始字节数)。

    只截断字符串值；数字、布尔、列表结构保持原样，因为截断一个布尔值没有意义，
    却会让 Agent 执行出错。
    """
    yuan = json.dumps(a1, ensure_ascii=False).encode("utf-8")
    chang = len(yuan)
    if chang <= a2:
        return a1, False, chang

    def jian(x: Any) -> Any:
        if isinstance(x, str):
            zhao = json.dumps(x[: a2], ensure_ascii=False)
            if len(zhao.encode("utf-8")) > a2:
                zhao = json.dumps(x[: a2 // 2], ensure_ascii=False)
            return zhao.strip('"') + "…"
        if isinstance(x, dict):
            return {k: jian(v) for k, v in x.items()}
        if isinstance(x, list):
            return [jian(v) for v in x[:50]]
        return x

    return jian(a1), True, chang


def _jiao_hui(a1: asyncio.Future | None, a2: Any) -> None:
    """把决定交回等待中的适配器。

    收口发生在 HTTP 请求线程，而适配器在另一个线程的 event loop 里 await 这个
    future。跨线程直接 `set_result` 会丢失唤醒（等待方一直挂着直到超时），
    所以走 `call_soon_threadsafe`——它在任何线程调用都是正确的。
    """
    if a1 is None or a1.done():
        return
    try:
        loop = a1.get_loop()
        if loop.is_closed():
            return
        if loop.is_running():
            loop.call_soon_threadsafe(a1.set_result, a2)
        else:
            # 没有循环在跑（单元测试、已停止的会话），直接设值，否则永远不会被唤醒
            a1.set_result(a2)
    except RuntimeError:
        a1.set_result(a2)


def wen_hash(a1: Any) -> str:
    """审批幂等的比对指纹（8.6）。

    收口时与重放时**必须**用同一个函数算：一边拿截断前的 toolInput、
    一边拿截断后的算，重放就永远不命中，而症状是「重启后又被问一遍」。
    所以这里只有一处实现，两边都调它。
    """
    return hashlib.sha256(
        json.dumps(a1, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]


@dataclass
class DaiJue:
    """一条挂起的审批（方案 8.5.1 的 PendingEntry）。"""

    requestId: str
    sessionId: str
    agentId: str
    toolName: str
    toolInput: dict
    inputTruncated: bool = False
    originalByteSize: int = 0
    createdAt: float = field(default_factory=time.time)
    expiresAt: float = 0.0
    resolved: bool = False
    result: PermissionResult | None = None
    decision: str | None = None
    autoReason: str | None = None
    resolvedAt: float | None = None
    future: asyncio.Future | None = None
    timer: threading.Timer | None = None
    suggestions: list[Any] = field(default_factory=list)
    title: str = ""


@dataclass
class DaiWen:
    """一条挂起的提问（方案 6.6）。"""

    questionId: str
    sessionId: str
    toolUseId: str
    questions: list[dict[str, Any]]
    createdAt: float = field(default_factory=time.time)
    expiresAt: float = 0.0
    resolved: bool = False
    state: str = "pending"
    future: asyncio.Future | None = None
    timer: threading.Timer | None = None


class ShenQing:
    """审批与提问的仲裁器。"""

    def __init__(self, a1: Any, a2: Any, a3: ShenKa, a4: float = SHEN_HE,
                 a5: Any = None) -> None:
        self.hua = a1  # HuiHua
        self.zong = a2  # ZongXian
        self.shen = a3  # ShenKa，三道闸门
        self.suo = threading.RLock()
        self._pending: dict[str, DaiJue] = {}
        self._wenti: dict[str, DaiWen] = {}
        self._timers: dict[str, threading.Timer] = {}
        # 进程内的审计流水（含 deny_baseline、dropped_updates），不落盘
        self.jue_chao: list[dict[str, Any]] = []
        # 已收口的提问流水，与 `jue_chao` 同形。**`sessionId` 每条必带**：
        # `_da_wen` 的「已收口」分支靠它做归属校验（spec 10.3）。
        # 提问原来收口就从 `_wenti` 里 pop 掉、什么都不留，于是那个分支
        # 只能一律 409——拿一个错的 questionId 会被告知「已被收口」，
        # 而用户从来没见过这个提问，提示语把人引向错误结论。
        self.wen_chao: list[dict[str, Any]] = []
        self.cun = a5  # 落盘层（阶段 5）。None = 不落盘，测试里就这样
        self.lu_dao: Any = None  # 展示旁路出站（7.7.2），由 run.py 注入
        # 跨重启重放的索引：(sessionId, tool_use_id) -> [历史决定, ...]
        # 一个 id 可能对应多条历史（同一次调用被收口过不止一次的情况），
        # 按时间正序存，命中时取最后一条。
        self.jue_ji: dict[tuple[str, str], list[dict]] = {}
        for ji in (self.cun.jue_qu() if self.cun is not None else []):
            self.jue_ji.setdefault(
                (str(ji.get("sessionId", "")), str(ji.get("requestId", ""))), []
            ).append(ji)
        self.shi_ji = a4

    # ---- 登记挂起项 ----
    def jia(self, a1: str, a2: str, a3: str, a4: str, a5: dict,
            a6: asyncio.Future | None, a7: str = "", a8: list[Any] | None = None) -> DaiJue:
        """登记一条待审批，并起审批超时定时器。

        a1=sessionId a2=agentId a3=requestId(===tool_use_id) a4=toolName
        a5=toolInput a6=future a7=title a8=suggestions

        **最前面先查跨重启重放**（在任何定时器、卡片、状态迁移之前）：
        命中就返回历史决定，不进 _pending、不起定时器、不迁状态。
        """
        ti, duan, chang = zhen_duan(a5)
        # 重放闸门。哈希拿截断后的 ti 算——shou() 落盘时算的也是它。
        guo = self._cha_ji(a1, a3, wen_hash(ti))
        if guo is not None:
            jue = str(guo.get("decision") or "auto_deny")
            yuan = guo.get("autoReason")
            d = DaiJue(
                requestId=a3, sessionId=a1, agentId=a2, toolName=a4, toolInput=ti,
                inputTruncated=duan, originalByteSize=chang, expiresAt=time.time(),
                future=a6, resolved=True, decision=jue, autoReason=yuan,
                resolvedAt=time.time(),
                result=self._gou_zao(jue, ti,
                                     self._jue_yuan(jue, yuan), yuan),
            )
            self._fa_jue(d, jue, yuan, True, guo)
            _jiao_hui(a6, d.result)
            return d
        with self.suo:
            d = DaiJue(
                requestId=a3,
                sessionId=a1,
                agentId=a2,
                toolName=a4,
                toolInput=ti,
                inputTruncated=duan,
                originalByteSize=chang,
                expiresAt=time.time() + self.shi_ji,
                future=a6,
                suggestions=a8 or [],
                title=a7,
            )
            self._pending[d.requestId] = d
            t = threading.Timer(self.shi_ji, self._chao_shi, args=(d.requestId,))
            t.daemon = True
            d.timer = t
            self._timers[d.requestId] = t
            t.start()
        q = PermissionRequest(
            requestId=d.requestId, sessionId=a1, toolName=d.toolName, toolInput=ti,
            # `a3` 是 requestId，Claude 路径下它同时就是 tool_use_id
            # （见 `http.py: _cheng_bu`）。`t-unknown` 是缺 id 时的兜底，
            # 把它当成真实 id 会让多张卡撞在同一个键上，所以落成空串，
            # 前端据此降级为「独立卡片」而不是错误关联。
            toolUseId="" if a3 == "t-unknown" else a3,
            title=a7, displayName=d.toolName, agentId=a2, suggestions=d.suggestions,
            inputTruncated=duan, originalByteSize=chang,
            createdAt=xianzai(), expiresAt=int(d.expiresAt * 1000),
        )
        self.hua.jia_shen(q)
        self.zong.fa("permission", a1, request=q.to_dict())
        return d

    def _cha_ji(self, a1: str, a2: str, a3: str) -> dict | None:
        """按 (sessionId, tool_use_id) 且 inputHash 相符 找最近一次历史决定。

        只按 id 匹配是不够的：用户批准过 ls 之后，复用同一 id 的 rm -rf
        会被当作已批准直接放行。id 来自 Agent 侧，不该被单独信任为
        「这次调用与那次相同」的证据。
        """
        with self.suo:
            lie = self.jue_ji.get((a1, a2)) or []
            for ji in reversed(lie):
                if ji.get("inputHash") == a3:
                    return ji
            if lie:
                self.zong.fa("error", a1, code="input_mismatch", recoverable=True,
                             message="同一个 tool_use_id 的命令内容与历史批准的不一致，"
                                     "已按新的调用重新请求审批")
            return None

    @staticmethod
    def _jue_yuan(a1: str, a2: str | None) -> str:
        yuan = JUE_YUAN.get(a2 or "", a2 or "")
        return f"{JUE_ZHU.get(a1, a1)}" + (f"（{yuan}）" if yuan else "")

    def _gou_zao(self, a1: str, a2: Any, a3: str, a4: str | None,
                 a5: list[PermissionUpdate] | None = None,
                 a6: bool = False) -> PermissionResult:
        """构造 SDK 返回值。收口与重放共用一处，否则两条路径的 deny 文案会漂。

        a1=decision a2=updated_input a3=deny message a4=autoReason
        a5=updatedPermissions a6=强制 interrupt（透传 shou() 的 a7）
        """
        if a1 == "user_allow":
            return PermissionResultAllow(updated_input=a2, updated_permissions=a5 or None)
        return PermissionResultDeny(message=a3 or "用户拒绝",
                                    interrupt=(a4 == "interrupt" or a6))

    def zhong_duan(self, a1: str) -> int:
        """中断一个会话：把该会话所有挂起项按 interrupt 收口。

        中断也是一条决定路径，必须汇入 shou()——否则挂起的审批会一直活到超时，
        而 Agent 那边早就被 CancelledError 取消走了（spike 报告第 4 节）。
        注意与「浏览器 SSE 断开」区分：那种情况**不 resolve 任何东西**（方案 8.4 的 R1）。
        """
        with self.suo:
            dai = [d for d in self._pending.values() if d.sessionId == a1]
        for d in dai:
            self.shou(d, "auto_deny", a3="用户中断了本次委派", a6="interrupt")
        with self.suo:
            wen = [q for q in self._wenti.values() if q.sessionId == a1]
        for q in wen:
            self.da_wen(q, [], "cancelled")
        return len(dai) + len(wen)

    def _chao_shi(self, a1: str) -> None:
        """审批超时：auto_deny(timeout)。安全侧默认。"""
        with self.suo:
            d = self._pending.get(a1)
        if d is not None:
            self.shou(d, "auto_deny", a3="等待审批超时", a6="timeout")

    # ---- 8.5.2 唯一的收口函数 ----
    def shou(self, a1: DaiJue, a2: str, *, a3: str = "", a4: dict | None = None,
             a5: list[PermissionUpdate] | None = None, a6: str | None = None,
             a7: bool = False) -> dict[str, Any]:
        """唯一的审批收口。幂等。返回本次调用的实际结果，供 HTTP 层决定 200 还是 409。"""
        with self.suo:
            # 1. 幂等闸门（R3）：已 resolved → 不重复执行，返回首次结果
            if a1.resolved:
                return {"status": "already_resolved", "decision": a1.decision,
                        "autoReason": a1.autoReason, "resolvedAt": a1.resolvedAt}

            # 2. 完整性闸门（R2）：被截断的输入不允许 allow
            if a2 == "user_allow" and a1.inputTruncated:
                a2, a6 = "auto_deny", "truncated"
                a3 = "输入已截断，无法安全批准"

            # 3. 一致性闸门（8.2.2）：updatedInput 必须等于原始 tool_input。
            #    前端校验没有意义——一个前端 bug 就够让用户批准 A、执行 B。
            if a2 == "user_allow" and a4 is not None and a4 != a1.toolInput:
                return {"status": "input_mismatch", "expected": a1.toolInput, "received": a4}

            # 4. 落点约束（8.2.3）：只允许 destination == "session"。
            #    放开的话，用户在网页点一次「总是允许 Bash」，SDK 就会往
            #    ~/.claude/settings.json 写永久规则，同时作用于这台机器上所有其他会话。
            keep = [u for u in (a5 or []) if getattr(u, "destination", None) == "session"]
            if a5 and len(keep) != len(a5):
                self.jue_chao.append({
                    "requestId": a1.requestId, "kind": "dropped_updates",
                    "dropped": len(a5) - len(keep),
                    "at": time.time(),
                })

            # 5. 构造 SDK 返回值
            r = self._gou_zao(a2, a4 or a1.toolInput, a3, a6, keep, a7)

            # 6. 先标记已解决，再交回 —— 防止交回期间重入
            a1.resolved = True
            a1.result = r
            a1.decision = a2
            a1.autoReason = a6
            a1.resolvedAt = time.time()

            # 7. 取消超时定时器（漏了会让 PendingEntry 在内存多活一个超时周期）
            t = self._timers.pop(a1.requestId, None)
            if t is not None:
                t.cancel()
            a1.timer = None

            # 8. 从 pending 原子移除（不在遍历中改集合）
            self._pending.pop(a1.requestId, None)
            self.hua.qu_shen(a1.requestId)

            # 9. 落盘决定（阶段 5.5 跨重启重放的依据）
            ji = {
                "requestId": a1.requestId, "sessionId": a1.sessionId,
                "decision": a2, "autoReason": a6,
                # 哈希拿 a1.toolInput 算——它已经是 zhen_duan() 截断之后的那份。
                # 重放那边也必须拿截断后的算，两边口径差一点就永远不命中，
                # 而症状是「重启后又被问了一遍」，查起来会先怀疑落盘没写成功。
                "inputHash": wen_hash(a1.toolInput),
                "at": time.time(),
            }
            self.jue_chao.append(ji)
            # 写不进去只影响「重启后要不要再问一次」，绝不能因此让这次收口失败，
            # 所以 Cun 内部自己降级并记日志。
            if self.cun is not None:
                self.cun.jue_cun(ji)
                # 进程内也同步索引：同一个 tool_use_id 在本次进程里再走一次
                # jia() 时，重放闸门照样命中，不必等到重启。
                self.jue_ji.setdefault((ji["sessionId"], ji["requestId"]), []).append(ji)

        # 10. 广播 permission_resolved（并落成消息，见 _fa_jue 的注释）
        self._fa_jue(a1, a2, a6, False)

        # 11. 把结果交回 SDK —— resolve 而非 await：本函数是同步的
        _jiao_hui(a1.future, r)

        return {"status": "ok", "decision": a2, "autoReason": a6}

    def _jue_wen(self, a1: DaiJue, a2: str, a3: str | None, a4: bool,
                 a5: dict | None = None) -> str:
        """决定摘要。replayed=True 时说清「这是重启前的决定，本次直接沿用」。"""
        zhu = JUE_ZHU.get(a2, a2)
        yuan = JUE_YUAN.get(a3 or "", a3 or "")
        tou = f"{zhu}（{yuan}）" if yuan else zhu
        if a4:
            kuo = a5 or {}
            return (f"{tou}。这条命令在 Bridge 重启前就已经有决定了，"
                    f"本次直接沿用，没有再次打扰你。"
                    f"（原决定时间：{kuo.get('at', '未知')}）")
        return f"{tou}：{a1.toolName}"

    def _fa_jue(self, a1: DaiJue, a2: str, a3: str | None, a4: bool,
                a5: dict | None = None) -> None:
        """广播 permission_resolved，并把它落成一条消息。

        落成消息是 3.2 的要求：只发帧的话，重启恢复后的历史里没有这一类，
        用户看不到刚才的命令是被谁批准的。Task 8 的重放路径也走这里。
        """
        self.hua.tian_jia(a1.sessionId, "system", "permission_resolved",
                          text=self._jue_wen(a1, a2, a3, a4, a5))
        self.zong.fa("permission_resolved", a1.sessionId, requestId=a1.requestId,
                     decision=a2,
                     autoDecided=a2.startswith("auto_") or a3 is not None,
                     autoReason=a3, replayed=a4)
        if self.lu_dao is not None:
            # detail 的四个键与 7.1 表逐字对齐，多一个都不给
            self.lu_dao.jue_guo(a1.sessionId, {
                "requestId": a1.requestId, "decision": a2,
                "autoReason": a3, "replayed": a4,
            })

    def cha_xun(self, a1: str, a2: str, a3: list[dict[str, Any]],
                a4: asyncio.Future | None = None) -> DaiWen:
        """登记一条待答问题。走独立通道，不占用审批通道。"""
        with self.suo:
            q = DaiWen(questionId=f"q-{lingshou()}", sessionId=a1, toolUseId=a2,
                       questions=a3, future=a4, expiresAt=time.time() + self.shi_ji)
            self._wenti[q.questionId] = q
            t = threading.Timer(self.shi_ji, self._chao_wen, args=(q.questionId,))
            t.daemon = True
            q.timer = t
            t.start()
        w = PendingQuestion(questionId=q.questionId, sessionId=a1, toolUseId=a2,
                            questions=a3, expiresAt=int(q.expiresAt * 1000))
        self.hua.jia_wen(w)
        self.zong.fa("question", a1, question=w.to_dict())
        return q

    def _chao_wen(self, a1: str) -> None:
        with self.suo:
            q = self._wenti.get(a1)
        if q is not None and not q.resolved:
            self.da_wen(q, [], "expired")

    def da_wen(self, a1: DaiWen, a2: list[dict[str, Any]],
               a3: str = "answered") -> dict[str, Any]:
        """提问收口。

        答案必须以 `deny + message` 回传给 SDK：实测（spike 报告第 7 节）
        单纯 allow 等于「用户没回答」，Agent 会明确报告「选择被取消了」。
        """
        with self.suo:
            if a1.resolved:
                return {"status": "already_resolved", "state": a1.state}
            a1.resolved = True
            a1.state = a3
            t = self._timers.pop(a1.questionId, None)
            if t is not None:
                t.cancel()
            a1.timer = None
            self._wenti.pop(a1.questionId, None)
            self.hua.qu_wen(a1.questionId)
            # 落一条已收口流水，供 `_da_wen` 区分「已收口」(409) 与
            # 「从来不存在」(404)。**`sessionId` 每条必带**：归属校验靠它。
            self.wen_chao.append({"questionId": a1.questionId,
                                  "sessionId": a1.sessionId,
                                  "state": a3, "at": time.time()})
            wen = self._du_wen(a1, a2) if a3 == "answered" else "用户未能在时限内回答"
        self.zong.fa("question_resolved", a1.sessionId, questionId=a1.questionId,
                     state=a3, replayed=False)
        _jiao_hui(a1.future, PermissionResultDeny(behavior="deny", message=wen))
        return {"status": "ok", "state": a3}

    @staticmethod
    def _du_wen(a1: DaiWen, a2: list[dict[str, Any]]) -> str:
        """把结构化答案拼成给 Agent 的自然语言。"""
        cha = []
        for x in a2:
            b = x.get("values") or []
            if b:
                cha.append(f"- {b}")
        return "用户对问题的回答：\n" + "\n".join(cha) if cha else "用户未作答"

    # ---- 闸门 2 的实际执行点 ----
    def shibai(self, a1: str, a2: str, a3: dict, a4: str, a5: asyncio.Future | None,
               a6: str = "") -> None:
        """命中 deny 基线时直接收口，不给用户看审批卡。

        deny 基线必须在服务端强制执行，不能靠前端隐藏按钮。而且这里**必须**走
        shou() 这条唯一收口路径——另起一条就会破坏「所有决定汇入一处」这个前提。

        a1=toolName a2=sessionId a3=toolInput a4=cwd a5=future a6=toolUseId
        """
        yuan = self.shen.shibai(a1, a3, a4)
        if yuan is None:
            return
        d = DaiJue(
            requestId=a6 or a3.get("__tool_use_id__") or f"p-{lingshou()}",
            sessionId=a2, agentId="claude-code", toolName=a1, toolInput=a3,
            future=a5, autoReason="deny_baseline", expiresAt=time.time(),
        )
        with self.suo:
            self._pending[d.requestId] = d
        self.jue_chao.append({"requestId": d.requestId, "kind": "deny_baseline",
                              "reason": yuan, "at": time.time()})
        self.shou(d, "auto_deny", a3=yuan, a6="deny_baseline")
