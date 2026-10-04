"""Small, fail-closed HTTP adapter for TencentDB Agent Memory v3.

This adapter deliberately has no implicit default endpoint or identity. It is
configured only when all isolation coordinates are supplied explicitly.
"""

import ipaddress
import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class TencentDBError(RuntimeError):
    pass


@dataclass(frozen=True)
class TencentDBConfig:
    endpoint: str
    service_id: str
    team_id: str
    agent_id: str
    user_id: str
    api_key: str | None = None
    timeout_seconds: float = 5.0

    @classmethod
    def from_env(cls, environ=None):
        env = os.environ if environ is None else environ
        names = {
            "endpoint": "LIFEOS_TDAI_ENDPOINT",
            "service_id": "LIFEOS_TDAI_SERVICE_ID",
            "team_id": "LIFEOS_TDAI_TEAM_ID",
            "agent_id": "LIFEOS_TDAI_AGENT_ID",
            "user_id": "LIFEOS_TDAI_USER_ID",
        }
        values = {field: env.get(name, "").strip() for field, name in names.items()}
        configured = any(values.values())
        if not configured:
            return None
        if not all(values.values()):
            missing = [name for field, name in names.items() if not values[field]]
            raise ValueError(f"incomplete TencentDB configuration; missing: {', '.join(missing)}")
        parsed = urlparse(values["endpoint"])
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("LIFEOS_TDAI_ENDPOINT must be an http(s) URL")
        config = cls(
            **values,
            api_key=env.get("LIFEOS_TDAI_API_KEY") or None,
            timeout_seconds=float(env.get("LIFEOS_TDAI_TIMEOUT_SECONDS", "5")),
        )
        if not config.is_loopback:
            raise ValueError("LifeOS TencentDB adapter only permits a loopback Gateway in this phase")
        if config.timeout_seconds <= 0:
            raise ValueError("LIFEOS_TDAI_TIMEOUT_SECONDS must be positive")
        return config

    @property
    def is_loopback(self):
        host = (urlparse(self.endpoint).hostname or "").lower()
        if host == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False


class TencentDBMemoryAdapter:
    """v3 atomic-memory writer and recall client; raw chat capture is separate."""

    def __init__(self, config: TencentDBConfig, transport=None):
        self.config = config
        self._transport = transport or self._http_post

    def _http_post(self, path, payload):
        headers = {
            "Content-Type": "application/json",
            "x-tdai-service-id": self.config.service_id,
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        request = Request(
            self.config.endpoint.rstrip("/") + path,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                result = json.load(response)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise TencentDBError(f"TencentDB request failed: {type(exc).__name__}") from exc
        if not isinstance(result, dict) or result.get("code") not in (None, 0):
            raise TencentDBError("TencentDB returned an unsuccessful response")
        return result.get("data", result)

    def approved_memory_payload(self, item):
        """Build an L1 write/update request for an approved LifeOS item.

        This payload is only valid for an item already bound to the matching
        TencentDB ID; the upstream update endpoint does not create missing IDs.
        """
        if item.get("status") != "active":
            raise ValueError("only active, user-approved memories may be sent to TencentDB")
        memory_id = item.get("id")
        content = item.get("content")
        if not isinstance(memory_id, str) or not memory_id or not isinstance(content, dict):
            raise ValueError("approved memory requires an id and object content")
        provenance = {
            "lifeos_memory_id": memory_id,
            "source": item.get("source"),
            "source_ref": item.get("source_ref"),
            "scope": item.get("scope"),
            "category": item.get("category"),
            "confidence": item.get("confidence"),
            "occurred_at": item.get("occurred_at"),
        }
        return {
            "team_id": self.config.team_id,
            "agent_id": self.config.agent_id,
            "user_id": self.config.user_id,
            "session_id": "lifeos-approved-memory",
            "id": f"lifeos-{memory_id}",
            "content": json.dumps(content, ensure_ascii=False, sort_keys=True),
            "background": json.dumps(provenance, ensure_ascii=False, sort_keys=True),
        }

    def write_approved_memory(self, item):
        payload = self.approved_memory_payload(item)
        expected_remote_id = f"lifeos-{item.get('id')}"
        sync = item.get("provider_sync") or {}
        if sync.get("status") != "synced" or sync.get("remote_id") != expected_remote_id:
            raise TencentDBError(
                "TencentDB v3 atomic/update cannot create a new LifeOS memory; "
                "an upstream atomic-create API is required"
            )
        return self._transport("/v3/atomic/update", payload)

    def delete_approved_memory(self, memory_id):
        if not isinstance(memory_id, str) or not memory_id:
            raise ValueError("memory id is required")
        return self._transport(
            "/v3/atomic/delete",
            {
                "team_id": self.config.team_id,
                "agent_id": self.config.agent_id,
                "user_id": self.config.user_id,
                "ids": [f"lifeos-{memory_id}"],
            },
        )

    def search_memories(self, query, scope=None, limit=5):
        if not isinstance(query, str) or not query.strip():
            return []
        payload = {
            "team_id": self.config.team_id,
            "agent_id": self.config.agent_id,
            "user_id": self.config.user_id,
            "query": query,
            "limit": max(1, min(int(limit), 50)),
        }
        result = self._transport("/v3/atomic/search", payload)
        items = result.get("items", []) if isinstance(result, dict) else []
        return [item for item in items if self._is_visible(item, scope)]

    @classmethod
    def _is_visible(cls, item, requested_scope):
        """Fail closed: accept only LifeOS-provenanced results in visible scopes."""
        try:
            background = json.loads(item.get("background") or "{}")
            provenance = background if isinstance(background, dict) else {}
            actual = provenance.get("scope") or {"kind": "unassigned"}
        except (TypeError, json.JSONDecodeError):
            return False
        kind = (requested_scope or {}).get("kind", "global")
        if actual.get("kind") == "global":
            return True
        if kind == "scenario":
            return (
                actual.get("kind") == "scenario"
                and actual.get("scenario_type") == requested_scope.get("scenario_type")
                and actual.get("user_id") in (None, requested_scope.get("user_id"))
            )
        if kind == "project":
            same_user = actual.get("user_id") in (None, requested_scope.get("user_id"))
            same_project = (
                actual.get("kind") == "project"
                and actual.get("project_id") == requested_scope.get("project_id")
            )
            same_scenario = (
                actual.get("kind") == "scenario"
                and actual.get("scenario_type") == requested_scope.get("scenario_type")
            )
            return same_user and (same_project or same_scenario)
        return False

    def retrieve(self, query, scope=None, limit=5, allowed_memory_ids=None):
        items = self.search_memories(query, scope=scope, limit=limit)
        grouped = {"user": [], "project": [], "feedback": [], "reference": []}
        for item in items:
            try:
                metadata = json.loads(item.get("background") or "{}")
                content = json.loads(item.get("content") or "null")
            except (TypeError, json.JSONDecodeError):
                continue
            memory_id = metadata.get("lifeos_memory_id")
            if allowed_memory_ids is not None and memory_id not in allowed_memory_ids:
                continue
            category = metadata.get("category")
            if category not in grouped or not isinstance(content, dict):
                continue
            grouped[category].append(
                {
                    "id": memory_id or item.get("id"),
                    "content": content,
                    "source": metadata.get("source", "external"),
                    "source_ref": metadata.get("source_ref"),
                    "scope": metadata.get("scope"),
                    "confidence": metadata.get("confidence"),
                    "occurred_at": metadata.get("occurred_at"),
                    "status": "active",
                    "provider": "tencentdb",
                }
            )
        return grouped
