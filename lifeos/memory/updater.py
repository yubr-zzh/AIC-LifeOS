import uuid
from datetime import datetime
from typing import Any, Dict


def _now() -> str:
    return datetime.utcnow().isoformat()


class MemoryUpdater:
    def __init__(self, store):
        self.store = store

    async def propose(self, source: str, content: Dict[str, Any], trace_id: str | None):
        candidate = {
            "id": str(uuid.uuid4()),
            "source": source,
            "content": content,
            "trace_id": trace_id,
            "status": "candidate",
            "created_at": _now(),
        }
        self.store.setdefault("candidates", []).append(candidate)
        return candidate

    async def apply(self, candidate: Dict[str, Any]):
        entry = {
            "id": candidate["id"],
            "source": candidate["source"],
            "content": candidate["content"],
            "trace_id": candidate.get("trace_id"),
            "created_at": _now(),
        }
        self.store.setdefault("project", []).append(entry)
        candidate["status"] = "committed"
        candidate["committed_at"] = _now()
        return entry

