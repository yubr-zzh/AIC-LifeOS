"""Durable, reviewable summaries of completed local Agent results."""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from lifeos.storage.atomic import write_json


class AgentEvidenceStore:
    def __init__(self, storage_dir=".lifeos"):
        self.path = Path(storage_dir) / "agent_evidence.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        if not self.path.exists():
            write_json(self.path, [])

    def record(self, *, event_id, owner_id, session_id, summary, agent_id="claude-code"):
        if not all(isinstance(value, str) and value.strip()
                   for value in (event_id, owner_id, session_id, summary, agent_id)):
            raise ValueError("agent evidence requires event, owner, session and summary")
        with self._lock:
            rows = json.loads(self.path.read_text(encoding="utf-8"))
            for row in rows:
                if row["id"] == event_id:
                    if (row["owner_id"], row["session_id"], row["summary"]) != (
                        owner_id, session_id, summary
                    ):
                        raise ValueError("agent evidence id already has different content")
                    return row
            row = {
                "id": event_id,
                "owner_id": owner_id,
                "session_id": session_id,
                "agent_id": agent_id,
                "summary": summary,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            }
            rows.append(row)
            write_json(self.path, rows)
            return row

    def get(self, event_id, *, owner_id):
        with self._lock:
            rows = json.loads(self.path.read_text(encoding="utf-8"))
        return next((row for row in rows if row["id"] == event_id
                     and row["owner_id"] == owner_id), None)

    def list(self, *, owner_id, session_id=None):
        with self._lock:
            rows = json.loads(self.path.read_text(encoding="utf-8"))
        return [row for row in rows if row["owner_id"] == owner_id
                and (session_id is None or row["session_id"] == session_id)]
