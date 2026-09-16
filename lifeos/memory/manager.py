import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from lifeos.memory.export import parse_markdown, render_markdown
from lifeos.memory.lifecycle import MemoryLifecycle
from lifeos.memory.retriever import MemoryRetriever
from lifeos.memory.updater import MemoryUpdater
from lifeos.storage.atomic import write_json


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
                    "reference": [],
                    "candidates": [],
                    "backups": [],
                    "vector_index": {},
                    "cache": {},
                }
            )

    async def retrieve(self, query):
        store = self._read()
        return await MemoryRetriever(store).retrieve(query)

    async def propose_update(self, source, content, trace_id=None, source_event_id=None):
        store = self._read()
        if source_event_id:
            for candidate in store.get("candidates", []):
                if candidate.get("source") == source and candidate.get("source_event_id") == source_event_id:
                    return candidate
        candidate = await MemoryUpdater(store).propose(source, content, trace_id)
        if source_event_id:
            candidate["source_event_id"] = source_event_id
        self._write(store)
        return candidate

    async def commit_candidate(self, candidate_id):
        store = self._read()
        candidate = self._find_candidate(store, candidate_id)
        if candidate.get("status") == "committed":
            for category in ("user", "project", "feedback", "reference"):
                for entry in store.get(category, []):
                    if entry.get("id") == candidate_id:
                        return entry
            raise ValueError("committed candidate has no memory entry")
        if candidate.get("status") != "candidate":
            raise ValueError(f"candidate cannot be committed from status: {candidate.get('status')}")
        lifecycle = MemoryLifecycle(store)
        await lifecycle.validate(candidate)
        await lifecycle.backup()
        entry = await MemoryUpdater(store).apply(candidate)
        await lifecycle.vector_upsert(entry)
        await lifecycle.cache_invalidate()
        self._write(store)
        self._sync_markdown(store)
        return entry

    async def reject_candidate(self, candidate_id):
        store = self._read()
        candidate = self._find_candidate(store, candidate_id)
        if candidate.get("status") == "rejected":
            return candidate
        if candidate.get("status") != "candidate":
            raise ValueError(f"candidate cannot be rejected from status: {candidate.get('status')}")
        candidate["status"] = "rejected"
        self._write(store)
        return candidate

    async def update(self, memory):
        candidate = await self.propose_update(
            source="direct",
            content=memory,
            trace_id=memory.get("trace_id") if isinstance(memory, dict) else None,
        )
        return await self.commit_candidate(candidate["id"])

    def export_markdown(self, path=None) -> str:
        """Render the store to Markdown. When ``path`` is given, also
        write the file there (used for the memory.md mirror)."""
        store = self._read()
        md = render_markdown(store)
        if path:
            Path(path).write_text(md, encoding="utf-8")
        return md

    def import_markdown(self, text: str) -> dict:
        """Apply edited categories while preserving runtime and audit state."""
        before = self._read()
        store = parse_markdown(text, existing_store=before)
        categories = ("user", "project", "feedback", "reference")
        if any(store[key] != before.get(key, []) for key in categories):
            store.setdefault("backups", []).append({
                "created_at": datetime.utcnow().isoformat(),
                "store": deepcopy({key: value for key, value in before.items() if key != "backups"}),
            })
        else:
            return before
        self._write(store)
        self._sync_markdown(store)
        return store

    def _sync_markdown(self, store=None):
        """Keep the .lifeos/memory.md mirror in sync. Best-effort:
        a mirror failure must never break the main memory path."""
        try:
            md = render_markdown(store if store is not None else self._read())
            (self.storage_dir / "memory.md").write_text(md, encoding="utf-8")
        except Exception:
            pass

    def _find_candidate(self, store, candidate_id):
        for candidate in store.get("candidates", []):
            if candidate["id"] == candidate_id:
                return candidate
        raise KeyError(f"memory candidate not found: {candidate_id}")

    def _read(self):
        return json.loads(self.storage_path.read_text(encoding="utf-8"))

    def _write(self, data):
        write_json(self.storage_path, data)
