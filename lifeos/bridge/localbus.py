"""决策回路的出站通道（方案 7.7.1、9.5 的 localbus）。

**这一条是「用户全程只在 LifeOS 界面操作」真正落地的地方。** 每条委派指令跑完后，
Bridge 把结果摘要 POST 回主服务，主服务把它追加进 `ChatRuntime` 的上下文——
LifeOS 的大模型下一轮就能看到「Agent 刚才做了什么、结果是什么」，从而重新判断。

三条不能违反的约束（7.7.1 原文）：

1. 主服务收到这些事件**只往上下文里追加文本**，不产生任何指向 Bridge 的出站调用。
   主服务不能因为收到一个 result 就自己去下发下一条指令。
2. 内容要花 LLM token，必须**精简且脱敏**。脱敏在这里做，不在主服务做——
   Bridge 才知道 Agent 实际吐了什么。
3. 断线**不 resolve 任何挂起项**（8.4）。所以这里的失败只丢事件，不能碰会话状态。

实现上刻意只有一条后台线程 + 一个队列：出站是「尽力而为」的旁路，
为它做重试/落盘不值得——事件丢了用户顶多少一条上下文，
而把它做成可靠队列就等于在 Agent 旁边再养一个会卡住的东西。
"""

from __future__ import annotations

import json
import os
import queue
import threading
import urllib.request
import uuid
from typing import Any

# 脱敏的实现搬到了 tuomi.py（日志也要用同一套）。这里保留同名转调，
# 阶段 3 的调用点一个都不用改。
from lifeos.bridge.tuomi import CHANG, tuomi


def tui_mian(a1: Any, a2: int = CHANG) -> str:
    return tuomi(a1, a2)


class LuDao:
    """本地直连的出站通道。

    只有一个 worker 线程：出站失败重试会占住 HTTP 线程（真实跑过就知道，
    一个 10 秒超时的 POST 足以让整个审批链路看起来像网络抖动）。
    """

    def __init__(self, a1: str | None = None, a2: float = 5.0) -> None:
        self.url = (a1 or os.environ.get("LIFEOS_MAIN_URL")
                    or "http://127.0.0.1:8765").rstrip("/") + "/api/agent-events"
        self.shi_jian = a2
        self.que: queue.Queue = queue.Queue(maxsize=256)
        self.song_le = 0
        self.shi_biao = 0
        self._ting = threading.Event()
        self.gong_zuo = threading.Thread(target=self._song, daemon=True)
        self.gong_zuo.start()

    def ting_zhi(self) -> None:
        self._ting.set()

    def fa(self, a1: str, a2: str | None, a3: dict) -> None:
        """发一个决策回路事件。永不抛异常、永不阻塞。"""
        zhen = {"kind": a1, "sessionId": a2, "eventId": uuid.uuid4().hex,
                "detail": a3}
        try:
            self.que.put_nowait(zhen)
        except queue.Full:
            # 队列满说明主服务长时间不可达。继续堆积只会让 Agent 侧变慢，
            # 而这些事件本来就是可丢的旁路。
            self.shi_biao += 1

    # 语义糖：三个高频事件各一个方法，调用点读起来像人话
    def jie_guo(self, a1: str, a2: dict) -> None:
        self.fa("agent.result", a1, a2)

    def shi_bai(self, a1: str, a2: dict) -> None:
        self.fa("agent.failed", a1, a2)

    def jie_shu(self, a1: str, a2: dict) -> None:
        self.fa("agent.ended", a1, a2)

    def ji_hua(self, a1: str, a2: dict) -> None:
        self.fa("plan.updated", a1, a2)

    # 7.7.2 展示旁路的六个 kind。全部只写事件总线，不进 LLM 上下文。
    def lian_jie(self, a1: dict) -> None:
        self.fa("bridge.connected", None, a1)

    def duan_kai(self, a1: dict) -> None:
        self.fa("bridge.disconnected", None, a1)

    def jian_hui(self, a1: str, a2: dict) -> None:
        self.fa("session.created", a1, a2)

    def guan_hui(self, a1: str, a2: dict) -> None:
        self.fa("session.closed", a1, a2)

    def jue_guo(self, a1: str, a2: dict) -> None:
        self.fa("permission.resolved", a1, a2)

    def beng_kui(self, a1: str, a2: dict) -> None:
        self.fa("agent.crashed", a1, a2)

    def _song(self) -> None:
        while not self._ting.is_set():
            try:
                zhen = self.que.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._fa_chu(zhen)
            except Exception:  # noqa: BLE001
                self.shi_biao += 1

    def _fa_chu(self, a1: dict) -> None:
        shu = json.dumps(a1, ensure_ascii=False, default=str).encode("utf-8")
        req = urllib.request.Request(
            self.url, data=shu, method="POST",
            headers={"content-type": "application/json; charset=utf-8",
                     "x-lifeos-agent": "bridge"},
        )
        # 本机有系统代理，默认 opener 会走代理把回环请求变成 502。必须显式关掉。
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with op.open(req, timeout=self.shi_jian) as r:
            r.read()
        self.song_le += 1
