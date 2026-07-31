import json
from pathlib import Path


class SkillRegistry:
    def __init__(self, storage_path=".lifeos/skills.json"):
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.storage_path.exists():
            self._write({"approved": [], "pending": []})

    async def list_approved(self):
        return self._read()["approved"]

    async def add_pending(self, candidate, review=None):
        data = self._read()
        entry = dict(candidate)
        entry["review"] = review or {}
        entry["status"] = "pending"
        data["pending"].append(entry)
        self._write(data)
        return entry

    async def find(self, name):
        data = self._read()
        for skill in data["approved"]:
            if skill.get("name") == name:
                return skill
        return None

    def _read(self):
        return json.loads(self.storage_path.read_text(encoding="utf-8"))

    def _write(self, data):
        self.storage_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

