"""Skill registry with usage statistics and similarity search."""

import json
import threading
from datetime import datetime
from pathlib import Path

from lifeos.skills.metrics import keyword_similarity
from lifeos.storage.synchronization import synchronized


def _now() -> str:
    return datetime.utcnow().isoformat()


class SkillRegistry:
    """Persistent registry of approved and pending skills.

    Approved skills carry a ``usage`` block (uses / successes /
    failures / last_used_at) that the Executor updates on every
    invocation, and ``keywords`` used by ``find_similar`` so the
    foreground agent can proactively reuse a skill for recurring tasks.
    """

    def __init__(self, storage_path=".lifeos/skills.json"):
        self._lock = threading.RLock()
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.storage_path.exists():
            self._write({"approved": [], "pending": []})

    @synchronized
    async def list_approved(self):
        return self._read()["approved"]

    @synchronized
    async def add_pending(self, candidate, review=None):
        data = self._read()
        entry = dict(candidate)
        entry["review"] = review or {}
        entry["status"] = "pending"
        entry.setdefault(
            "usage",
            {"uses": 0, "successes": 0, "failures": 0, "last_used_at": None},
        )
        data["pending"].append(entry)
        self._write(data)
        return entry

    @synchronized
    async def approve(self, name):
        """Move a pending candidate into the approved registry."""
        data = self._read()
        for i, skill in enumerate(data["pending"]):
            if skill.get("name") == name:
                skill["status"] = "approved"
                skill["approved_at"] = _now()
                data["approved"].append(skill)
                data["pending"].pop(i)
                self._write(data)
                return skill
        return None

    @synchronized
    async def approve_by_id(self, skill_id):
        data = self._read()
        for skill in data["approved"]:
            if skill.get("id") == skill_id:
                return skill
        for index, skill in enumerate(data["pending"]):
            if skill.get("id") == skill_id:
                skill["status"] = "approved"
                skill["approved_at"] = _now()
                data["approved"].append(skill)
                data["pending"].pop(index)
                self._write(data)
                return skill
        raise KeyError(f"skill not found: {skill_id}")

    @synchronized
    async def reject_by_id(self, skill_id):
        data = self._read()
        for index, skill in enumerate(data["pending"]):
            if skill.get("id") == skill_id:
                skill["status"] = "rejected"
                data["pending"].pop(index)
                self._write(data)
                return skill
        raise KeyError(f"pending skill not found: {skill_id}")

    @synchronized
    async def find(self, name):
        data = self._read()
        for skill in data["approved"]:
            if skill.get("name") == name:
                return skill
        return None

    @synchronized
    async def find_any(self, name):
        """Find a skill by name in either pending or approved."""
        data = self._read()
        for group in ("approved", "pending"):
            for skill in data[group]:
                if skill.get("name") == name:
                    return skill
        return None

    @synchronized
    async def find_similar(self, query_text, threshold=0.15):
        """Return approved skills whose keywords match the query text.

        Uses keyword_similarity so short CJK queries score meaningfully;
        results are sorted by descending similarity so the caller can
        pick the best match for proactive skill invocation.
        """
        data = self._read()
        hits = []
        for skill in data["approved"]:
            kws = skill.get("keywords", [])
            if not kws:
                continue
            sim = keyword_similarity(query_text, kws)
            if sim >= threshold:
                hits.append((sim, skill))
        hits.sort(key=lambda pair: pair[0], reverse=True)
        return [skill for _, skill in hits]

    @synchronized
    async def record_usage(self, name, success=True):
        """Increment usage stats for a skill (approved or pending)."""
        data = self._read()
        for group in ("approved", "pending"):
            for skill in data[group]:
                if skill.get("name") == name:
                    usage = skill.setdefault(
                        "usage",
                        {"uses": 0, "successes": 0, "failures": 0, "last_used_at": None},
                    )
                    usage["uses"] += 1
                    if success:
                        usage["successes"] += 1
                    else:
                        usage["failures"] += 1
                    usage["last_used_at"] = _now()
                    self._write(data)
                    return skill
        return None

    def _read(self):
        return json.loads(self.storage_path.read_text(encoding="utf-8"))

    def _write(self, data):
        self.storage_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
