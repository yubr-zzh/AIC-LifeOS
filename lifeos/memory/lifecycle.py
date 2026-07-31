import copy
from datetime import datetime
from typing import Any, Dict


class MemoryLifecycle:
    def __init__(self, store):
        self.store = store

    async def validate(self, candidate: Dict[str, Any]):
        if not candidate.get("content"):
            raise ValueError("memory candidate content is empty")
        return {"decision": "allow", "reason": "non-empty candidate"}

    async def backup(self):
        backup = {
            "created_at": datetime.utcnow().isoformat(),
            "store": copy.deepcopy(
                {
                    key: value
                    for key, value in self.store.items()
                    if key != "backups"
                }
            ),
        }
        self.store.setdefault("backups", []).append(backup)
        return backup

    async def vector_upsert(self, entry: Dict[str, Any]):
        self.store.setdefault("vector_index", {})[entry["id"]] = entry["content"]

    async def cache_invalidate(self):
        self.store["cache"] = {}

