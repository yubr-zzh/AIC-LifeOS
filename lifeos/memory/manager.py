import json
from pathlib import Path

from lifeos.memory.lifecycle import MemoryLifecycle
from lifeos.memory.retriever import MemoryRetriever
from lifeos.memory.updater import MemoryUpdater


class MemoryManager:
    def __init__(self, storage_dir=".lifeos"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.storage_path = self.storage_dir / "memory.json"
        if not self.storage_path.exists():
            self._write(
                {
                    "user": [],
                    "project": [],
                    "feedback": [],
                    "candidates": [],
                    "backups": [],
                    "vector_index": {},
                    "cache": {},
                }
            )

    async def retrieve(self, query):
        store = self._read()
        return await MemoryRetriever(store).retrieve(query)

    async def propose_update(self, source, content, trace_id=None):
        store = self._read()
        candidate = await MemoryUpdater(store).propose(source, content, trace_id)
        self._write(store)
        return candidate

    async def commit_candidate(self, candidate_id):
        store = self._read()
        candidate = self._find_candidate(store, candidate_id)
        lifecycle = MemoryLifecycle(store)
        await lifecycle.validate(candidate)
        await lifecycle.backup()
        entry = await MemoryUpdater(store).apply(candidate)
        await lifecycle.vector_upsert(entry)
        await lifecycle.cache_invalidate()
        self._write(store)
        return entry

    async def update(self, memory):
        candidate = await self.propose_update(
            source="direct",
            content=memory,
            trace_id=memory.get("trace_id") if isinstance(memory, dict) else None,
        )
        return await self.commit_candidate(candidate["id"])

    def _find_candidate(self, store, candidate_id):
        for candidate in store.get("candidates", []):
            if candidate["id"] == candidate_id:
                return candidate
        raise KeyError(f"memory candidate not found: {candidate_id}")

    def _read(self):
        return json.loads(self.storage_path.read_text(encoding="utf-8"))

    def _write(self, data):
        self.storage_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

