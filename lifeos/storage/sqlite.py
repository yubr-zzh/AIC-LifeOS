import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StructuredStore:
    """SQLite storage for user-facing structured LifeOS records.

    The first version deliberately keeps the schema small and explicit. A
    single table supports daily/phase planning, reviews, diary, insights and
    feedback while preserving room for typed metadata as the model grows.
    """

    VALID_KINDS = {
        "daily_plan",
        "daily_review",
        "phase_plan",
        "phase_review",
        "diary",
        "insight",
        "feedback",
    }

    def __init__(self, database_path: str | Path = ".lifeos/lifeos.db"):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._session() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS structured_entries (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL CHECK (kind IN (
                        'daily_plan', 'daily_review', 'phase_plan',
                        'phase_review', 'diary', 'insight', 'feedback'
                    )),
                    entry_date TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL DEFAULT '',
                    mood TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_entries_kind_date "
                "ON structured_entries(kind, entry_date DESC)"
            )

    def list_entries(
        self,
        kind: Optional[str] = None,
        entry_date: Optional[str] = None,
        limit: int = 100,
    ) -> list[Dict[str, Any]]:
        query = "SELECT * FROM structured_entries"
        clauses: list[str] = []
        params: list[Any] = []
        if kind:
            self._validate_kind(kind)
            clauses.append("kind = ?")
            params.append(kind)
        if entry_date:
            clauses.append("entry_date = ?")
            params.append(entry_date)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY entry_date DESC, updated_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 500)))
        with self._session() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get(self, entry_id: str) -> Optional[Dict[str, Any]]:
        with self._session() as connection:
            row = connection.execute(
                "SELECT * FROM structured_entries WHERE id = ?", (entry_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def upsert(self, payload: Dict[str, Any], entry_id: Optional[str] = None) -> Dict[str, Any]:
        kind = str(payload.get("kind", ""))
        self._validate_kind(kind)
        entry_date = str(payload.get("entry_date") or datetime.now().date().isoformat())
        title = str(payload.get("title") or "")
        content = str(payload.get("content") or "")
        mood = payload.get("mood")
        metadata = payload.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")

        now = _now()
        record_id = entry_id or str(uuid.uuid4())
        with self._session() as connection:
            existing = connection.execute(
                "SELECT created_at FROM structured_entries WHERE id = ?", (record_id,)
            ).fetchone()
            created_at = existing["created_at"] if existing else now
            connection.execute(
                """
                INSERT INTO structured_entries
                    (id, kind, entry_date, title, content, mood,
                     metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    kind = excluded.kind,
                    entry_date = excluded.entry_date,
                    title = excluded.title,
                    content = excluded.content,
                    mood = excluded.mood,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    record_id,
                    kind,
                    entry_date,
                    title,
                    content,
                    mood,
                    json.dumps(metadata, ensure_ascii=False),
                    created_at,
                    now,
                ),
            )
        return self.get(record_id)  # type: ignore[return-value]

    def delete(self, entry_id: str) -> bool:
        with self._session() as connection:
            result = connection.execute(
                "DELETE FROM structured_entries WHERE id = ?", (entry_id,)
            )
        return result.rowcount > 0

    def _validate_kind(self, kind: str) -> None:
        if kind not in self.VALID_KINDS:
            raise ValueError(f"unsupported structured entry kind: {kind}")

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        record = dict(row)
        record["metadata"] = json.loads(record.pop("metadata_json") or "{}")
        return record
