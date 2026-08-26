import json
from pathlib import Path

from lifeos.memory.export import parse_markdown, render_markdown
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
        self._sync_markdown(store)
        return entry

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
        """Replace the store with an edited Markdown document."""
        store = parse_markdown(text)
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
        self.storage_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

