"""事件總線：全局 streamSeq、重放緩衝、多訂閱者廣播（方案 7.2、4.4）。

三條設計要點，動之前先讀懂：

1. **streamSeq 是 Bridge 級全局單調遞增**，不是會話內序號。SSE 的 `id:` 就是它。
   兩個會話各推進到 20 會共用同一個 id:20，斷網重連按「補發 > 20」過濾就會永久
   丟掉另一個會話的審批幀。AgentMessage.seq 仍然只是會話內的消息序號。
2. **廣播絕不無鎖遍歷，也絕不阻塞**。每個訂閱者一個隊列 + 一個專屬寫線程，
   這裡只做 put_nowait。慢客戶端不能拖住所有會話。
3. **關鍵幀永不丟**。隊列滿時按幀類型分級處理：關鍵幀寧可主動斷開該訂閱者
   （它會走重連 + snapshot 路徑把狀態補齊），可丟幀才做丟棄。
"""

from __future__ import annotations

import queue
import threading
from collections import deque
from typing import Any

# 隊列滿時必須保證送達的幀。丟了它們，服務端就再也不知道「用戶是否已經決定過」。
JIJIAN = {
    "snapshot", "permission", "permission_resolved", "question", "question_resolved",
    "state", "result", "session_added", "session_removed", "device_status",
    "delegation_update", "agent_status", "error",
    # **message 必須在這裡。** 它是對話正文的真相，而 snapshot 明確不帶
    # messages（見 `zha_pian()` 的說明）。丟一條 message 就等於永久丟一段
    # 回答——前端只剩殘缺的 chunk 累加值，症狀是「Agent 的長輸出被截斷」。
    # 隊列滿時寧可斷開該訂閱者（它會重連 + 補發），也不靜默丟正文。
    "message",
}
# 丟了也能靠重連的 snapshot / transcript 補回來的幀。
# **只有 chunk**：它是打字機效果，不是真相（6.3）。
KEI = {"chunk"}

CHONG_FANG = 2000  # 重放緩衝深度
DUI_LI = 512      # 每訂閱者隊列容量


class DingYue:
    """一個 SSE 訂閱者。隊列歸它自己，寫線程歸它自己。"""

    def __init__(self, a1: str, a2: str | None = None) -> None:
        self.sid = a1
        self.yuan = a2  # 來源 userId/deviceId，用于连接数上限
        self.que: queue.Queue = queue.Queue(maxsize=DUI_LI)
        self.chao = False  # 关键帧投递失败：写线程据此主动断开
        self.guan = False
        self.last = 0  # 已写出的最大 streamSeq

    def ru(self, a1: dict[str, Any]) -> None:
        """投递一帧。满了按类型分级处理，绝不阻塞调用方。"""
        lei = a1["type"]
        try:
            self.que.put_nowait(a1)
            return
        except queue.Full:
            pass
        if lei in JIJIAN:
            self.chao = True
            return
        # 可丢帧：腾一个位置再放。丢最旧的一条。
        try:
            self.que.get_nowait()
            self.que.put_nowait(a1)
        except (queue.Empty, queue.Full):
            self.chao = True


class ZongXian:
    """事件总线。唯一分配 streamSeq 的地方。"""

    def __init__(self, a1: str, a2: int = 0) -> None:
        self.suo = threading.RLock()
        self.ji = f"i-{a1}"  # instanceId，每次进程启动一个新 UUID
        self.shui = a2  # streamEpoch，本实例内的重启次数
        self.seq = 0
        self.huan: deque[tuple[int, dict[str, Any]]] = deque(maxlen=CHONG_FANG)
        self.ding: dict[str, DingYue] = {}
        self.zhan: Any = None  # HuiHua，快照时由 http 注入，避免循环依赖

    # ---- 发帧 ----
    def fa(self, a1: str, a2: str | None = None, bu_guang_bo: bool = True, **a3: Any) -> dict[str, Any]:
        """分配 streamSeq 并广播。返回该帧。

        bu_guang_bo=False 时只占一个 seq 号、不推给其他订阅者——snapshot 走这条路：
        它是一个真实的数据帧（客户端会记住它的 id），但不该让别的连接重复收到。
        """
        with self.suo:
            self.seq += 1
            # streamSeq 由本类独占分配，**调用方传进来的不算数**：dict 展开是
            # 后者覆盖前者，`zha_pian()` 又确实带着一个自己读出来的 streamSeq，
            # 不挡掉的话快照对外宣布的序号会比真实序号小 1，还会和上一帧撞号。
            # 后果是 duibu 的补发窗口 (lastEventId, snapshot.seq] 窄一格，
            # 那一格里的帧被静默丢掉——用户看到的是审批卡凭空不出现。
            a3.pop("streamSeq", None)
            zhen = {"type": a1, "sessionId": a2, "streamSeq": self.seq, **a3}
            # 消息帧把自己这一帧的 streamSeq 也写进 message 里。
            # 必须在锁内、广播之前做完：fa() 返回时帧已经进了重放缓冲和
            # 各订阅者的队列，事后再补写就是改一个正在别人线程里排队的对象。
            xiao = a3.get("message")
            if isinstance(xiao, dict):
                xiao["xuhao"] = self.seq
            # 只有真正广播出去的帧才进重放缓冲。snapshot 走 bu_guang_bo=False，
            # 它是「此刻」的全量拷贝，不是历史事件——存进去的话，下次重连的补发
            # 批次里会混进一串过期快照，客户端会把它们当普通帧应用，用旧状态
            # 覆盖掉当前状态（症状：早已收口的审批突然复活，把界面掰回双栏）。
            if bu_guang_bo:
                self.huan.append((self.seq, zhen))
                for d in list(self.ding.values()):
                    d.ru(zhen)
        return zhen

    def xu_hao(self) -> int:
        with self.suo:
            return self.seq

    # ---- 订阅 ----
    def dingyue(self, a1: str, a2: str | None = None) -> DingYue:
        with self.suo:
            d = DingYue(a1, a2)
            self.ding[d.sid] = d
            return d

    def tuixie(self, a1: DingYue) -> None:
        with self.suo:
            self.ding.pop(a1.sid, None)

    def shu_ling(self, a1: str | None) -> int:
        """统计某个来源（userId/deviceId）的在线连接数。"""
        with self.suo:
            return sum(1 for d in self.ding.values() if d.yuan == a1)

    def lie_ding(self) -> list[DingYue]:
        with self.suo:
            return list(self.ding.values())

    # ---- 快照与断点续传 ----
    def zha_pian(self) -> dict[str, Any]:
        """全量快照。连接建立与每次重连的第一帧。

        **不要在这里放 streamSeq**——它由 fa() 分配。放了也不会生效（fa 会挡掉），
        但会让人以为快照的序号可以自选。

        **不带 messages（阶段 7 域 E）。** 快照只回答「此刻有哪些会话、
        有哪些待处理」，不回答「历史上说过什么」——历史走
        `GET /sessions/{sid}/transcript`，那边有 `limit` 兜底。
        带全量消息会让这一帧随会话长度无界增长，而 `tunnel.py:457`
        超过 `ZUI_DA`（1 MiB）直接断隧道，症状是反复断开重连。
        """
        with self.suo:
            return {
                "instanceId": self.ji,
                "streamEpoch": self.shui,
                "sessions": self.zhan.kua() if self.zhan else [],
                "pending": self.zhan.dai_jue() if self.zhan else [],
                "questions": self.zhan.dai_wen() if self.zhan else [],
            }

    def duibu(self, a1: int | None) -> list[dict[str, Any]]:
        """按 lastEventId 取补发帧。

        返回顺序固定：先 snapshot，再补发批次（方案 7.2.4）。

        **snapshot 不分配新的 streamSeq，它上报的就是当前游标 self.seq。**
        它是一次全量状态报告，不是一个事件——给它分配新序号的话，那个序号会比
        补发批次里每一帧都大，而客户端是以 snapshot 的 seq 为去重基线的，
        于是整批补发帧（含还没送达的审批帧）被静默丢掉。真机症状：
        「Agent 卡着不动，其实是在等我批准，而审批卡始终没出现」。

        补发批次仍然照发：快照的内容覆盖到 self.seq，批次里的帧序号都更小，
        客户端按基线丢掉它们是正确行为；留着是为了万一内容不全还有一层。
        """
        with self.suo:
            zha = {"type": "snapshot", "sessionId": None, **self.zha_pian()}
            zha["streamSeq"] = self.seq
            now = zha["streamSeq"]
            if a1 is None or a1 >= now:
                return [zha]
            # 右闭区间 (a1, now]，与文档一致。写成 a1 < s < now 会漏掉最新那一帧，
            # 而它往往正是客户端还没收到的审批帧。
            bu = [z for s, z in self.huan if a1 < s <= now]
            return [zha, *bu]

    def chao_le(self, a1: int) -> bool:
        """from 越界判定。Bridge 重启后旧游标会大于当前 seq，此时必须让前端重置
        （返回 409 reset_required），绝不能静默返回空数组——
        那会让前端以为已是最新，界面空白，而 Agent 那边还在跑。"""
        return a1 > self.seq
