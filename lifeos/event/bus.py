import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from lifeos.storage.atomic import write_json
from lifeos.time_util import du_shi, xie_shi


def _now() -> str:
    return xie_shi()


# 10.7：事件总线的保留期与总量上限。超期事件会让 events.json 无限变大，
# 而它每次都是全量读写——一个几百 MB 的 events.json 会让 /events 每次卡住。
BAO_LIU = 7 * 86400
FENG_DING = 1 << 30  # 1 GB


@dataclass
class Event:
    type: str
    payload: Dict[str, Any]
    trace_id: Optional[str] = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "pending"
    attempts: int = 0
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    error: Optional[str] = None


class ReliableEventBus:
    """Small durable queue for the foreground/background LifeOS boundary."""

    def __init__(self, storage_path=".lifeos/events.json", *,
                 bao_liu=BAO_LIU, feng_ding=FENG_DING):
        self.storage_path = Path(storage_path)
        self.bao_liu = bao_liu
        self.feng_ding = feng_ding
        self.ri = logging.getLogger("lifeos.event")
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.storage_path.exists():
            self._write_events([])
        else:
            events = self._read_events()
            interrupted = False
            for event in events:
                if event.get("status") == "processing":
                    event["status"] = "failed"
                    event["error"] = "interrupted during processing; retryable"
                    event["updated_at"] = _now()
                    interrupted = True
            # 启动时也淘汰一次：上一次异常退出之前可能已经攒了一堆超期事件
            liu = self._tao_tai(events)
            if len(liu) != len(events):
                events = liu
                interrupted = True
            if interrupted:
                self._write_events(events)

    async def publish(
        self,
        event_type: str,
        payload: Dict[str, Any],
        trace_id: Optional[str] = None,
    ) -> Event:
        event = Event(type=event_type, payload=payload, trace_id=trace_id)
        events = self._tao_tai(self._read_events())
        events.append(asdict(event))
        self._write_events(events)
        return event

    async def poll(self, limit: int = 10) -> list[Event]:
        events = self._read_events()
        pending = [
            Event(**event)
            for event in events
            if event.get("status") in {"pending", "failed"}
        ]
        return pending[:limit]

    async def mark_processing(self, event_id: str) -> None:
        self._update_event(event_id, status="processing", attempts_increment=1)

    async def mark_done(self, event_id: str) -> None:
        self._update_event(event_id, status="done", error=None)

    async def mark_failed(self, event_id: str, error: str) -> None:
        self._update_event(event_id, status="failed", error=error)

    def all_events(self) -> Iterable[Event]:
        return [Event(**event) for event in self._read_events()]

    def _read_events(self) -> list[Dict[str, Any]]:
        return json.loads(self.storage_path.read_text(encoding="utf-8"))

    def _write_events(self, events: list[Dict[str, Any]]) -> None:
        write_json(self.storage_path, events)

    def _update_event(
        self,
        event_id: str,
        *,
        status: str,
        error: Optional[str] = None,
        attempts_increment: int = 0,
    ) -> None:
        events = self._read_events()
        for event in events:
            if event["id"] == event_id:
                event["status"] = status
                event["updated_at"] = _now()
                event["error"] = error
                event["attempts"] = int(event.get("attempts", 0)) + attempts_increment
                self._write_events(events)
                return
        raise KeyError(f"event not found: {event_id}")

    # ---- 10.7 保留期与总量 ----
    def _da_xiao(self, a1):
        """一整个事件数组序列化后有多少字节。"""
        return len(json.dumps(a1, ensure_ascii=False, default=str).encode("utf-8"))

    def _da_yi(self, a1):
        """一条事件的字节数，+1 是数组里分隔用的那个逗号。"""
        return len(json.dumps(a1, ensure_ascii=False, default=str).encode("utf-8")) + 1

    def _chao_qi(self, a1):
        """`created_at` 是否超过保留期。

        **两边都必须是 aware。** 历史事件里混着 naive（老代码的 `utcnow()`
        写的）、带 `Z` 的和带偏移的；直接拿 `utcnow()` 去减一个 aware 值抛的是
        `TypeError: can't subtract offset-naive and offset-aware datetimes`，
        **不是 `ValueError`**，原来那个 `except ValueError` 接不住，整个总线
        在读文件那一刻就炸。

        解析不出来一律按**未过期**处理：宁多留一条事件，不可少删一条。
        """
        at = du_shi(a1.get("created_at"))
        if at is None:
            return False
        return (datetime.now(timezone.utc) - at).total_seconds() > self.bao_liu

    def _tao_tai(self, events):
        """按保留期与总量淘汰。**pending 一条都不删。**

        pending 是待处理的业务事件，删掉等于丢功能，所以总量超限时也只淘汰
        非 pending，顺序是 done → failed → 其他。真的只剩 pending 还超限时
        写一行 warning 停下——宁可文件大，不可丢事件。

        三条实现上的讲究：
        1. 淘汰只决定「谁可以被删」，**返回时保持原有顺序**，不把 pending
           提到前面。`poll()` 取的是文件顺序里的前 limit 条，重排会改它的语义。
        2. 每条事件的大小只算一次，再从总和里逐条减；每淘汰一条就重新序列化
           整个列表是 O(n²)，在 1 GB 这个量级上等于把主服务卡死。
        3. 超期淘汰与总量淘汰合成一趟，中间结果不落盘。
        """
        shou = [e for e in events
                if e.get("status") == "pending" or not self._chao_qi(e)]
        if self._da_xiao(shou) <= self.feng_ding:
            return shou
        # 越「已经处理完」的越先淘汰
        pai = {"done": 0, "failed": 1}
        ke = sorted((e for e in shou if e.get("status") != "pending"),
                    key=lambda e: (pai.get(e.get("status"), 2),
                                   str(e.get("created_at", ""))))
        ling = [e for e in shou if e.get("status") == "pending"]
        jia = [self._da_yi(e) for e in ke]
        zong = self._da_xiao(ling) + sum(jia)
        i = 0
        while i < len(ke) and zong > self.feng_ding:
            zong -= jia[i]
            i += 1
        if zong > self.feng_ding:
            self.ri.warning(
                "events.json 只剩 %d 条 pending 仍有约 %d 字节，超过上限 %d；"
                "本层不删除任何 pending，请人工归档", len(ling), zong, self.feng_ding)
            return ling
        diu = {id(e) for e in ke[:i]}
        return [e for e in shou if id(e) not in diu]
