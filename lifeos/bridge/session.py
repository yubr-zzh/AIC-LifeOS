"""会话状态机 + 回合编排器（方案 6.2、12.2 任务 1.9）。

**唯一 owner：只有本文件能改会话状态。** 适配器不碰状态，HTTP 层也不碰。

回合编排器（1.9）负责「多条指令串行执行」：这是 7.6「逐条发指令」的服务端落点，
也是阶段 3 决策回路（3.8）的前提——每条指令的结果都要回到 LifeOS 对话上下文。

本文件还实现 8.7 的第二、三层超时（停滞、闲置）。第一层审批超时在 arbiter 里。
**没有这三层的后果**（方案 8.7 的原话）：Bridge 崩溃 → 前端重连 → 会话停在
`working` 收不到 result → 没有任何机制退役它 → 反复几次后 5 个槽全满 →
`POST /sessions` 一律 409，用户完全无法开始新任务，且界面上没有任何东西提示为什么。
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

from lifeos.bridge.models import (
    YO,
    YUNXU,
    AgentMessage,
    AgentSession,
    PendingQuestion,
    PermissionRequest,
    lingshou,
    xianzai,
)

TING_GE = 900.0    # 停滞：working/thinking 状态下无任何帧（秒）
XIAN_ZHI = 1800.0  # 闲置：idle 会话无操作（秒）
# 每用户并发会话上限（方案 9.4、spec 10.3）。`XIAN_ZHI` 是闲置超时，两者不是一回事。
#
# **上限算的是并发的 `ownerId`，且 `ended` 与没有活进程（`alive=False`）的都不占
# 名额。** 不排除 `ended` 的话，用户跑完第 5 个任务之后这个 Bridge 就再也开不了新
# 任务了；不排除 `alive=False` 的话，重启后懒恢复出来的空壳会话会原样再演一遍——8.7
# 记的那个场景（「用户完全无法开始新任务，且界面上没有任何东西提示为什么」）换个原因
# 又发生一遍。
ZUI_DUO_HUI = 5

# 会话处于这两种状态时，停滞计时才有意义
_BUZHENG = {"working", "thinking"}

# **这四种状态下底下一定有活的 `claude` 子进程**（在跑，或在等人：审批、问题）。
# `alive` 置回 True 只认这一张表；`error`/`backoff`/`idle`/`ended` 不置——那几种
# 没有正在跑的回合。
HUO_TAI = {"thinking", "working", "attention", "waiting_input"}

# 4.4 消息落盘白名单。thinking/chunk 明文永不落盘（10.7）；
# error/rate_limit/context_reset 不在 5.5 的四类之内，恢复后由新的 error 帧补充。
LUO_PAN = {"tool_use", "tool_result", "tool_cancelled", "result", "permission_resolved", "text"}


class InvalidTransition(Exception):
    """非法状态迁移。"""


class HuiHua:
    """会话状态机 + 消息存储 + 回合编排。"""

    def __init__(self, a1: Any, a2: float = TING_GE, a3: float = XIAN_ZHI) -> None:
        self.zong = a1  # ZongXian，用来广播 state 帧
        self.suo = threading.RLock()
        self._map: dict[str, AgentSession] = {}
        self._xiang: dict[str, list[AgentMessage]] = {}
        self._shen: dict[str, PermissionRequest] = {}
        self._wen: dict[str, PendingQuestion] = {}
        self._xu: dict[str, int] = {}  # sid -> 已分配的消息 seq 计数
        self._zhong: set[str] = set()  # 被中断的 sid
        self.ting_ge = a2
        self.xian_zhi = a3
        # 第二、三层的执行者。由 Bridge 注入：session.py 不该知道适配器的存在，
        # 但真要中断/关闭一个会话就必须调到它。
        self.ting_shi: Any = None    # 停滞时通知外部中断 Agent
        self.guan_yong: Any = None   # 闲置时通知外部关闭会话
        self.cun: Any = None         # 落盘层（阶段 5），由 run.py 注入
        self._ting = threading.Event()
        self._ting_guan: threading.Thread | None = None

    # ---- 会话 CRUD ----
    def jian(self, a1: AgentSession) -> AgentSession:
        with self.suo:
            # **上限检查与插入必须同一把锁。** 分开写的话两个并发 POST 都能
            # 数到 4 个、然后各插一个，5 个上限实际放行 6 个。
            # **算的是「真在跑」的会话：非 `ended` 且底下有活的 `claude` 进程。**
            # 只看 `state != "ended"` 的话，重启后 `run.py` 懒恢复出来的会话
            # （全被重置成 `idle` + `alive=False`，没有活的子进程）会一条不剩地
            # 占满名额，用户开第 6 个直接 409，而看门狗要等 1800 秒闲置超时才
            # 回收——又是 8.7 记的那个「用户完全无法开始新任务，且界面上没有
            # 任何东西提示为什么」。
            huo = [s for s in self._map.values()
                   if s.ownerId == a1.ownerId and s.state != "ended"
                   and s.alive]
            if len(huo) >= ZUI_DUO_HUI:
                # 抛 `InvalidTransition` 而不是自造异常：HTTP 层已有的那条
                # 映射直接把它翻成 409（`http.py:do_POST`）。
                # 提示语按占名额的会话状态分叉（9.4）：`attention` 占名额是对的
                # （确实在等用户审批，Agent 还活着），但用户要做的动作是「去批」，
                # 跟他说「先关掉一个」是把他引向错误动作；其余状态既没在跑也没在
                # 等审批，用户没有一个明确可关的对象，才说关掉一个。
                if any(s.state == "attention" for s in huo):
                    ti = (f"并发会话已达上限 {ZUI_DUO_HUI}（9.4）；"
                          f"有会话在等你审批，审批完就有名额了")
                else:
                    ti = f"并发会话已达上限 {ZUI_DUO_HUI}（9.4）；先关掉一个再建"
                raise InvalidTransition(ti)
            self._map[a1.sessionId] = a1
            self._xiang[a1.sessionId] = []
            self._xu[a1.sessionId] = 0
        self._cun_hui(a1)
        return a1

    def du(self, a1: str) -> AgentSession | None:
        with self.suo:
            return self._map.get(a1)

    def shan(self, a1: str) -> bool:
        with self.suo:
            self._xiang.pop(a1, None)
            self._xu.pop(a1, None)
            self._zhong.discard(a1)
            return self._map.pop(a1, None) is not None

    def kua(self) -> list[dict[str, Any]]:
        with self.suo:
            return [s.to_dict() for s in self._map.values()]

    def quan_liao_xiang(self) -> list[dict[str, Any]]:
        with self.suo:
            out: list[dict[str, Any]] = []
            for xi in self._xiang.values():
                out.extend(m.to_dict() for m in xi)
            return out

    def dai_jue(self) -> list[dict[str, Any]]:
        with self.suo:
            return [p.to_dict() for p in self._shen.values()]

    def dai_wen(self) -> list[dict[str, Any]]:
        with self.suo:
            return [q.to_dict() for q in self._wen.values()]

    # ---- 状态机：唯一写入口 ----
    def _fu_huo(self, a1: AgentSession, a2: str) -> None:
        """进入「真的在跑或在等人」的状态时，把 `alive` 置回 True。

        `alive` 全仓只两处写：懒恢复置 False（run.py），这里置 True。只置 False
        不置 True 的话，重启后唤醒一条恢复会话——它真的起了 claude 子进程、状态
        走到 thinking——也永远不占名额，每用户 5 个的上限被「唤醒恢复会话」整条
        绕开。**调用方须已持有 `suo`。**
        """
        if a2 in HUO_TAI:
            a1.alive = True

    def geng(self, a1: str, a2: str, a3: str | None = None) -> AgentSession:
        """迁移会话状态。非法迁移抛 InvalidTransition。

        同态自环直接返回：并发审批（attention→attention）、并行工具（working→working）、
        审批通过后立刻跑完这一轮（attention→ended）都是合法的，不该抛异常。
        """
        if a2 not in YO:
            raise InvalidTransition(f"未知状态：{a2}")
        with self.suo:
            s = self._map.get(a1)
            if s is None:
                raise KeyError(a1)
            if a2 == s.state:
                # 自环也要置回 `alive`：并发审批第二次到 attention 时状态没变，
                # 从这条提前返回回去就把「子进程还活着」漏掉了。
                self._fu_huo(s, a2)
                return s
            if (s.state, a2) not in YUNXU:
                raise InvalidTransition(f"{s.state} → {a2} 非法")
            s.state = a2
            s.updatedAt = xianzai()
            # 放在合法性校验之后、锁内：非法迁移不许把 `alive` 带着改掉。
            self._fu_huo(s, a2)
        self.zong.fa("state", a1, state=a2, lastEvent=a3)
        self._cun_hui(s)
        return s

    # ---- 消息 ----
    def tian_jia(self, a1: str, a2: str, a3: str, a4: str | None = None, **a5: Any) -> AgentMessage:
        """追加一条完整消息并分配会话内 seq。返回消息。

        a4 是 messageId 覆盖值。**必须透传 SDK 的消息 id**，因为 chunk 帧就是用它
        分组的（适配器 `_liu` 的注释写明了这条约定）。这里另起一个 `m-xxxx` 的话，
        前端收到完整帧时无法替换掉对应的流式增量，只能在尾巴上追加一份，
        症状是「同一条回复显示两遍」。

        顺带刷新 `updatedAt`——8.7 的停滞计时就靠它，每一帧都算「有活动」。
        """
        with self.suo:
            self._xu[a1] = self._xu.get(a1, 0) + 1
            m = AgentMessage(
                messageId=a4 or f"m-{lingshou()}",
                sessionId=a1,
                seq=self._xu[a1],
                role=a2,
                kind=a3,
                **a5,
            )
            self._xiang.setdefault(a1, []).append(m)
            s = self._map.get(a1)
            if s is not None:
                s.updatedAt = xianzai()
        zhen = self.zong.fa("message", a1, message=m.to_dict())
        m.xuhao = zhen["streamSeq"]
        # 落盘放在锁外：锁护的是 _xiang / _xu 这两个内存结构，磁盘 I/O 不归它管。
        # 放在锁内的话，HuiHua.suo → Cun.suo 就成了一条固定顺序的嵌套锁，
        # 而别处（_cun_hui）是单独拿 Cun.suo，将来任何一处顺序写反就是死锁。
        if a3 in LUO_PAN:
            self._cun_xiang(m)
        return m

    def huo_dong(self, a1: str) -> None:
        """只刷新活动时间，不落消息。

        8.7 说的是「无任何帧」，而 chunk 帧也是帧。模型连续流式输出时
        一条完整 message 可能迟迟不来，只认完整消息的话，
        一个正在正常输出的长回答会被误判成停滞。
        """
        with self.suo:
            s = self._map.get(a1)
            if s is not None:
                s.updatedAt = xianzai()

    def juan_biao(self, a1: str, a2: int = 0, a3: int | None = None,
                  a4: int | None = None) -> list[AgentMessage]:
        """补拉消息，按全局 streamSeq 过滤——与 `ZongXian.chao_le()` 的越界
        判定用同一把尺子。两处口径必须一致，否则前端看到的补拉窗口和服务端
        认为的合法窗口差一格，那一格里的帧会被静默丢掉。

        `a2` = from（**排他**下界）、`a3` = limit、`a4` = before（**排他**上界）。
        `a3` / `a4` 缺省时是全量——既有调用点的行为一个字没变。

        取片方向按调用目的分，别统一成一种：

        | 入参 | 窗口 | 取片 | 谁在用 |
        |---|---|---|---|
        | `a2=0`、`a4=None` | 全部 | **末尾 N 条** | 首屏：打开会话看的是最近在说什么 |
        | `a4` 给定 | `xuhao < a4` | **末尾 N 条** | 向上翻：往回看更早的 |
        | `a2 > 0`、`a4=None` | `xuhao > a2` | **最早 N 条** | 增量追赶：SSE 断线后补 |

        **为什么增量取最早、其余取末尾。** 增量追赶一次可能进来 200 条而 limit 是
        50，取末尾会把中间 150 条**静默跳过去**——前端既没拿到也不知道漏了，
        界面上凭空少一大段对话。取最早则从缺口接着往后取，下一轮 `from` 推进后
        自然补齐。首屏与向上翻反过来：要的是最新/最邻近的那一段，取最早的话
        打开一条 500 条的长会话看到的是会话开头，「向上翻」这条能力在 API 上
        干脆不存在。

        `a2` 与 `a4` 同时给时窗口取交集，取片跟 `a4` 走（末尾 N 条）——向上翻优先。
        """
        with self.suo:
            lie = [m for m in self._xiang.get(a1, []) if m.xuhao > a2]
            if a4 is not None:
                lie = [m for m in lie if m.xuhao < a4]
            if a3 is None:
                return lie
            return lie[:a3] if a2 > 0 and a4 is None else lie[-a3:]

    # ---- 阶段 5：落盘与懒恢复 ----
    def _cun_hui(self, a1: AgentSession) -> None:
        """把会话元数据写进 sessions.json（全量重写，KB 级）。

        写紧跟在状态变化之后，不放在锁内：落盘失败不该让状态迁移也失败。
        Cun 内部自己会降级并记日志。
        """
        if self.cun is None:
            return
        self.cun.xie_hui(self.kua())

    def _cun_xiang(self, a1: AgentMessage) -> None:
        if self.cun is None:
            return
        self.cun.xiang_cun(a1.to_dict())

    def hui_fu(self, a1: AgentSession, a2: list[AgentMessage]) -> None:
        """把落盘的会话与消息灌回内存（阶段 5 懒恢复）。**不发任何 SSE 帧。**

        _xu 必须抬到历史最大 seq：不然新消息的 seq 会与历史撞号，
        前端按 (seq, messageId) 定位替换时会顶掉旧消息。
        """
        with self.suo:
            self._map[a1.sessionId] = a1
            self._xiang[a1.sessionId] = list(a2)
            self._xu[a1.sessionId] = max([m.seq for m in a2], default=0)

    # ---- 挂起项 ----
    def jia_shen(self, a1: PermissionRequest) -> None:
        with self.suo:
            self._shen[a1.requestId] = a1
            s = self._map.get(a1.sessionId)
            if s is not None and a1.requestId not in s.pendingPermissions:
                s.pendingPermissions.append(a1.requestId)

    def qu_shen(self, a1: str) -> PermissionRequest | None:
        with self.suo:
            p = self._shen.pop(a1, None)
            if p is not None:
                s = self._map.get(p.sessionId)
                if s is not None and a1 in s.pendingPermissions:
                    s.pendingPermissions.remove(a1)
            return p

    def jia_wen(self, a1: PendingQuestion) -> None:
        with self.suo:
            self._wen[a1.questionId] = a1
            s = self._map.get(a1.sessionId)
            if s is not None and a1.questionId not in s.pendingQuestions:
                s.pendingQuestions.append(a1.questionId)

    def qu_wen(self, a1: str) -> PendingQuestion | None:
        with self.suo:
            q = self._wen.pop(a1, None)
            if q is not None:
                s = self._map.get(q.sessionId)
                if s is not None and a1 in s.pendingQuestions:
                    s.pendingQuestions.remove(a1)
            return q

    # ---- 1.9 回合编排器 ----
    async def paichu(self, a1: str, a2: list[str], a3: Any) -> dict[str, Any]:
        """把一批指令逐条发给适配器。

        规则：串行；任一条失败即停后续并转 error；被中断即停后续。
        收尾判据是 batchDone/batchTotal（方案 6.2）——不用「还有没有后续指令」
        这种含糊说法。
        """
        s = self.du(a1)
        if s is None:
            return {"ok": False, "reason": "not_found"}
        with self.suo:
            self._zhong.discard(a1)
            s.batchTotal = len(a2)
            s.batchDone = 0
        self._cun_hui(s)
        self.geng(a1, "thinking", "batch_start")
        for i, wen in enumerate(a2):
            if a1 in self._zhong:
                self.geng(a1, "idle", "interrupted")
                return {"ok": False, "reason": "interrupted", "batchDone": s.batchDone}
            try:
                await a3.fasong(wen)
            except asyncio.CancelledError:
                # 用户主动中断：can_use_tool 协程也会这样被取消（见 spike 报告第 4 节）。
                # 重新抛出，让上层知道这次回合是被取消的，而不是执行失败。
                with self.suo:
                    self._zhong.discard(a1)
                self.geng(a1, "idle", "interrupted")
                raise
            except Exception as e:  # noqa: BLE001
                self.geng(a1, "error", f"instruction_failed: {e}")
                return {"ok": False, "reason": str(e), "batchDone": s.batchDone}
            with self.suo:
                s.batchDone += 1
                s.turnCount += 1
                s.updatedAt = xianzai()
            self._cun_hui(s)
            if i + 1 < len(a2):
                # 本条完成、还要继续：先回 idle 再起下一轮。
                # 顺序不能反——直接 idle→ended 在迁移表里非法。
                self.geng(a1, "idle", "batch_progress")
                self.geng(a1, "thinking", "next_instruction")
            else:
                self.geng(a1, "ended", "batch_done")
        return {"ok": True, "batchDone": s.batchDone, "batchTotal": s.batchTotal}

    def zhong_duan(self, a1: str) -> bool:
        """标记会话被中断。下一条指令前会停下。

        同时给「正在执行 / 等待审批」的工具调用补一条 `tool_cancelled`。
        不用伪造 `tool_result(isError=True)`：结果从未发生，标成「执行失败」
        会让用户以为命令真的跑过并失败了。独立 kind 才能表达「没跑」。
        """
        with self.suo:
            self._zhong.add(a1)
            lie = self._xiang.get(a1, [])
            # 已经有结局的调用不再补 cancelled：tool_result / tool_cancelled
            # 是独立消息，tool_use 自己的 state 不会跟着变。
            closed = {
                m.toolUseId for m in lie
                if m.kind in ("tool_result", "tool_cancelled") and m.toolUseId
            }
            gua = [
                m for m in lie
                if m.kind == "tool_use"
                and m.toolUseId
                and m.toolUseId not in closed
                and m.state in ("executing", "awaiting_confirmation")
            ]
            for m in gua:
                self.tian_jia(
                    a1, "system", "tool_cancelled",
                    toolUseId=m.toolUseId,
                    toolName=m.toolName,
                    text="用户已中断",
                    state="cancelled",
                )
        return True

    # ---- 8.7 第二、三层：停滞与闲置 ----
    def kai_dog(self) -> None:
        """启动看门狗线程。幂等。"""
        with self.suo:
            if self._ting_guan is not None and self._ting_guan.is_alive():
                return
            self._ting.clear()
            self._ting_guan = threading.Thread(target=self._kan_dog, daemon=True)
            self._ting_guan.start()

    def ting_zhi(self) -> None:
        self._ting.set()
        t = self._ting_guan
        if t is not None:
            t.join(timeout=2.0)

    def _kan_dog(self) -> None:
        while not self._ting.wait(1.0):
            now = time.time() * 1000
            with self.suo:
                sessions = list(self._map.values())
            for s in sessions:
                idle_ms = now - s.updatedAt
                if s.state in _BUZHENG and self.ting_ge > 0 and idle_ms > self.ting_ge * 1000:
                    self._ting_shi(s.sessionId, idle_ms)
                elif s.state == "idle" and self.xian_zhi > 0 and idle_ms > self.xian_zhi * 1000:
                    # 调方法而不是回调：会话必须从状态机里摘掉。
                    # 只调回调的话会话永远留在 _map 里，正是 8.7 要防的那个死局。
                    self._guan_yong(s.sessionId, idle_ms)

    def _ting_shi(self, a1: str, a2: float) -> None:
        """停滞：转 error 并中断 Agent。

        只转状态是不够的——底下的 claude 进程还在烧 token。必须真的把它停掉，
        否则「会话已失败」和「账单还在涨」会同时发生。
        """
        try:
            self.geng(a1, "error", "stall_timeout")
        except (KeyError, InvalidTransition):
            return
        self.zong.fa("error", a1, code="stall_timeout", recoverable=True,
                     message=f"Agent 已经 {a2 / 1000:.0f} 秒没有任何输出，本轮作废")
        if self.ting_shi is not None:
            try:
                self.ting_shi(a1)
            except Exception:  # noqa: BLE001
                pass

    def _guan_yong(self, a1: str, a2: float) -> None:
        """闲置：关闭会话。"""
        self.zong.fa("error", a1, code="idle_timeout", recoverable=False,
                     message=f"会话闲置 {a2 / 1000:.0f} 秒，已自动关闭")
        if self.guan_yong is not None:
            try:
                self.guan_yong(a1, a2)
            except Exception:  # noqa: BLE001
                pass
        self.shan(a1)
        # 不在这里发 session_removed：注入的回调（BridgeServer._guan_yong）会发。
        # 两处都发就是两帧，前端会收到重复的移除通知。
