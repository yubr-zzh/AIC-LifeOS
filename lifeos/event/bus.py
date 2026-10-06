import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from lifeos.storage.atomic import write_json
from lifeos.storage.synchronization import synchronized


def _now() -> str:
    return datetime.utcnow().isoformat()


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

    def __init__(self, storage_path: str | Path = ".lifeos/events.json"):
        self._lock = threading.RLock()
        self.storage_path = Path(storage_path)
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
            if interrupted:
                self._write_events(events)

    @synchronized
    async def publish(
        self,
        event_type: str,
        payload: Dict[str, Any],
        trace_id: Optional[str] = None,
    ) -> Event:
        event = Event(type=event_type, payload=payload, trace_id=trace_id)
        events = self._read_events()
        events.append(asdict(event))
        self._write_events(events)
        return event

    @synchronized
    async def poll(self, limit: int = 10) -> list[Event]:
        events = self._read_events()
        pending = [
            Event(**event)
            for event in events
            if event.get("status") in {"pending", "failed"}
        ]
        return pending[:limit]

    @synchronized
    async def mark_processing(self, event_id: str) -> None:
        self._update_event(event_id, status="processing", attempts_increment=1)

    @synchronized
    async def mark_done(self, event_id: str) -> None:
        self._update_event(event_id, status="done", error=None)

    @synchronized
    async def mark_failed(self, event_id: str, error: str) -> None:
        self._update_event(event_id, status="failed", error=error)

    @synchronized
    def all_events(self) -> Iterable[Event]:
        return [Event(**event) for event in self._read_events()]

    def _read_events(self) -> list[Dict[str, Any]]:
        return json.loads(self.storage_path.read_text(encoding="utf-8"))

    def _write_events(self, events: list[Dict[str, Any]]) -> None:
        write_json(self.storage_path, events)

    @synchronized
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
