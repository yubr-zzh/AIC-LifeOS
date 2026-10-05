import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from lifeos.memory.export import parse_markdown, render_markdown
from lifeos.memory.lifecycle import MemoryLifecycle
from lifeos.memory.profile import build_memory_profile
from lifeos.memory.retriever import MemoryRetriever
from lifeos.memory.schema import (
    CURRENT_SCHEMA_VERSION,
    migrate_store,
    normalize_scope,
    normalize_source_ref,
)
from lifeos.memory.updater import MemoryUpdater, category_for_source
from lifeos.storage.atomic import write_json


_PRESERVE_REMOTE_ID = object()
_PRESERVE_REMOTE_SCOPE = object()


class MemoryManager:
    def __init__(self, storage_dir=".lifeos"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.storage_path = self.storage_dir / "memory.json"
        if not self.storage_path.exists():
            self._write(
                {
                    "schema_version": CURRENT_SCHEMA_VERSION,
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
        else:
            store = self._read()
            store, migrated = migrate_store(store, category_for_source)
            if migrated:
                self._write(store)

    async def retrieve(self, query, scope=None):
        store = self._read()
        return await MemoryRetriever(store).retrieve(query, scope=scope)

    def profile_view(self):
        """Return a fresh, non-persisted profile view from the current store."""
        return build_memory_profile(self._read())

    def active_memory_ids(self):
        store = self._read()
        return {
            entry["id"]
            for category in ("user", "project", "feedback", "reference")
            for entry in store.get(category, [])
            if entry.get("status", "active") == "active"
        }

    def memory_records(self):
        store = self._read()
        return [
            entry
            for category in ("user", "project", "feedback", "reference")
            for entry in store.get(category, [])
        ]

    def set_provider_sync(
        self,
        memory_id,
        status,
        *,
        remote_id=_PRESERVE_REMOTE_ID,
        remote_scope_key=_PRESERVE_REMOTE_SCOPE,
        error=None,
    ):
        if status not in {"synced", "pending", "deleted"}:
            raise ValueError("unsupported provider sync status")
        store = self._read()
        item = self._find_memory(store, memory_id)
        if remote_id is _PRESERVE_REMOTE_ID:
            remote_id = (item.get("provider_sync") or {}).get("remote_id")
        if remote_scope_key is _PRESERVE_REMOTE_SCOPE:
            remote_scope_key = (item.get("provider_sync") or {}).get("remote_scope_key")
        item["provider_sync"] = {
            "provider": "tencentdb",
            "status": status,
            "remote_id": remote_id,
            "remote_scope_key": remote_scope_key,
            "error": error,
            "updated_at": datetime.utcnow().isoformat(),
        }
        self._write(store)
        return item

    async def propose_update(
        self,
        source,
        content,
        trace_id=None,
        source_event_id=None,
        source_ref=None,
        scope=None,
        confidence=None,
        confidence_method=None,
        category=None,
        occurred_at=None,
    ):
        store = self._read()
        normalized_ref = normalize_source_ref(source_ref)
        normalized_scope = normalize_scope(scope)
        if scope is None and source == "direct":
            normalized_scope = {
                "kind": "global",
                "scenario_type": None,
                "project_id": None,
                "user_id": None,
            }
        if source_event_id:
            for candidate in store.get("candidates", []):
                if candidate.get("source") == source and candidate.get("source_event_id") == source_event_id:
                    return candidate
            if source_ref is None:
                source_ref = {"kind": "event", "record_id": source_event_id}
                normalized_ref = normalize_source_ref(source_ref)
        if normalized_ref is not None:
            for candidate in store.get("candidates", []):
                if (
                    candidate.get("source") == source
                    and candidate.get("source_ref") == normalized_ref
                    and candidate.get("content") == content
                    and candidate.get("category") == category
                    and normalize_scope(candidate.get("scope")) == normalized_scope
                    and candidate.get("confidence") == confidence
                    and candidate.get("confidence_method") == confidence_method
                ):
                    return candidate
        candidate = await MemoryUpdater(store).propose(
            source=source,
            content=content,
            trace_id=trace_id,
            source_ref=source_ref,
            scope=normalized_scope,
            confidence=confidence,
            confidence_method=confidence_method,
            category=category,
            occurred_at=occurred_at,
        )
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

    async def correct_memory(self, memory_id, content, reason=None):
        """Create a user-confirmed replacement and retire the previous version."""
        if not isinstance(content, dict) or not content:
            raise ValueError("replacement memory content must be a non-empty object")
        store = self._read()
        old = self._find_memory(store, memory_id)
        if old.get("status", "active") != "active":
            replacement_id = old.get("superseded_by")
            if old.get("status") == "superseded" and replacement_id:
                replacement = self._find_memory(store, replacement_id)
                if replacement.get("content") == content:
                    return replacement
            raise ValueError(f"memory cannot be corrected from status: {old.get('status', 'active')}")

        await MemoryLifecycle(store).backup()
        replacement = deepcopy(old)
        replacement.update(
            {
                "id": str(uuid4()),
                "source": "direct",
                "source_ref": {"kind": "memory_correction", "record_id": memory_id},
                "evidence_source_ref": deepcopy(old.get("source_ref")),
                "content": deepcopy(content),
                "confidence": None,
                "confidence_method": None,
                "version_of": memory_id,
                "status": "active",
                "created_at": datetime.utcnow().isoformat(),
            }
        )
        # A corrected memory has a new deterministic provider ID. Never carry
        # the superseded record's remote binding onto its replacement.
        replacement.pop("provider_sync", None)
        if reason is not None:
            if not isinstance(reason, str):
                raise ValueError("correction reason must be a string")
            replacement["correction_reason"] = reason
        old["status"] = "superseded"
        old["superseded_by"] = replacement["id"]
        old["superseded_at"] = datetime.utcnow().isoformat()
        store[old["category"]].append(replacement)
        store.setdefault("vector_index", {}).pop(memory_id, None)
        store["vector_index"][replacement["id"]] = replacement["content"]
        store["cache"] = {}
        self._write(store)
        self._sync_markdown(store)
        return replacement

    async def retract_memory(self, memory_id, reason=None):
        """Explicitly make an accepted memory unavailable to recall."""
        if reason is not None and not isinstance(reason, str):
            raise ValueError("retraction reason must be a string")
        store = self._read()
        entry = self._find_memory(store, memory_id)
        if entry.get("status") == "retracted":
            return entry
        if entry.get("status", "active") != "active":
            raise ValueError(f"memory cannot be retracted from status: {entry.get('status')}")
        await MemoryLifecycle(store).backup()
        entry["status"] = "retracted"
        entry["retracted_at"] = datetime.utcnow().isoformat()
        if reason is not None:
            entry["retraction_reason"] = reason
        store.setdefault("vector_index", {}).pop(memory_id, None)
        store["cache"] = {}
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
        """Apply edited categories while preserving runtime and audit state."""
        before = self._read()
        store = parse_markdown(text, existing_store=before)
        categories = ("user", "project", "feedback", "reference")
        previous = {
            entry["id"]: (category, entry)
            for category in categories
            for entry in before.get(category, [])
        }
        imported = {
            entry["id"]: (category, entry)
            for category in categories
            for entry in store.get(category, [])
        }
        removed_ids = previous.keys() - imported.keys()
        if removed_ids:
            raise ValueError(
                "Markdown import cannot remove accepted memories; use the explicit retract operation"
            )
        edited_ids = [
            memory_id
            for memory_id in previous.keys() & imported.keys()
            if (
                previous[memory_id][0] != imported[memory_id][0]
                or previous[memory_id][1].get("content") != imported[memory_id][1].get("content")
                or previous[memory_id][1].get("source") != imported[memory_id][1].get("source")
                or previous[memory_id][1].get("created_at") != imported[memory_id][1].get("created_at")
            )
        ]
        if edited_ids:
            raise ValueError(
                "Markdown import cannot rewrite accepted memory fields; use explicit correction or retraction operations"
            )
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

    @staticmethod
    def _find_memory(store, memory_id):
        for category in ("user", "project", "feedback", "reference"):
            for entry in store.get(category, []):
                if entry.get("id") == memory_id:
                    return entry
        raise KeyError(f"memory not found: {memory_id}")

    def _read(self):
        return json.loads(self.storage_path.read_text(encoding="utf-8"))

    def _write(self, data):
        write_json(self.storage_path, data)
