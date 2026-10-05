"""Small, fail-closed HTTP adapter for TencentDB Agent Memory v3.

This adapter deliberately has no implicit default endpoint or identity. It is
configured only when all isolation coordinates are supplied explicitly.
"""

import ipaddress
import hashlib
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
    scope_map: dict | None = None

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
        raw_scope_map = env.get("LIFEOS_TDAI_SCOPE_MAP", "").strip()
        configured = any(values.values()) or bool(raw_scope_map)
        if not configured:
            return None
        if not all(values.values()):
            missing = [name for field, name in names.items() if not values[field]]
            raise ValueError(f"incomplete TencentDB configuration; missing: {', '.join(missing)}")
        scope_map = {}
        if raw_scope_map:
            try:
                scope_map = json.loads(raw_scope_map)
            except json.JSONDecodeError as exc:
                raise ValueError("LIFEOS_TDAI_SCOPE_MAP must be valid JSON") from exc
            if not isinstance(scope_map, dict):
                raise ValueError("LIFEOS_TDAI_SCOPE_MAP must be an object")
            required_coordinates = {"team_id", "agent_id", "user_id", "session_id"}
            for scope_key, coordinates in scope_map.items():
                if (
                    not isinstance(scope_key, str)
                    or not scope_key
                    or not isinstance(coordinates, dict)
                    or not required_coordinates.issubset(coordinates)
                    or any(not isinstance(coordinates[key], str) or not coordinates[key].strip() for key in required_coordinates)
                ):
                    raise ValueError(
                        "each TencentDB scope mapping requires team_id, agent_id, user_id, and session_id"
                    )
        parsed = urlparse(values["endpoint"])
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("LIFEOS_TDAI_ENDPOINT must be an http(s) URL")
        config = cls(
            **values,
            scope_map=scope_map,
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

    _ATOMIC_TYPES = {
        "user": "persona",
        "project": "work_fact",
        "feedback": "episodic",
        "reference": "work_artifact",
    }

    def __init__(self, config: TencentDBConfig, transport=None):
        self.config = config
        self._transport = transport or self._http_post

    @staticmethod
    def _scope_key(scope):
        scope = scope or {"kind": "global"}
        kind = scope.get("kind")
        if kind == "global":
            return "global"
        if kind == "project" and isinstance(scope.get("project_id"), str):
            return f"project:{scope['project_id']}"
        if kind == "scenario" and isinstance(scope.get("scenario_type"), str):
            return f"scenario:{scope['scenario_type']}"
        return None

    def coordinates_for_scope(self, scope, *, required=True):
        """Resolve an explicit LifeOS scope to TencentDB tenancy coordinates."""
        key = self._scope_key(scope)
        if key == "global":
            return {
                "team_id": self.config.team_id,
                "agent_id": self.config.agent_id,
                "user_id": self.config.user_id,
                "session_id": "lifeos-global-memory",
            }
        coordinates = (self.config.scope_map or {}).get(key) if key else None
        if coordinates:
            return dict(coordinates)
        if required:
            raise TencentDBError(f"no explicit TencentDB identity mapping for LifeOS scope: {key or 'unassigned'}")
        return None

    def scope_key_for(self, scope):
        coordinates = self.coordinates_for_scope(scope, required=False)
        if coordinates is None:
            raise TencentDBError(
                f"no explicit TencentDB identity mapping for LifeOS scope: {self._scope_key(scope) or 'unassigned'}"
            )
        canonical = json.dumps(coordinates, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
        return f"{self._scope_key(scope)}@{fingerprint}"

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
        """Build a deterministic L1 create/update request for approved memory."""
        if item.get("status") != "active":
            raise ValueError("only active, user-approved memories may be sent to TencentDB")
        memory_id = item.get("id")
        content = item.get("content")
        category = item.get("category")
        if (
            not isinstance(memory_id, str)
            or not memory_id
            or not isinstance(content, dict)
            or category not in self._ATOMIC_TYPES
        ):
            raise ValueError("approved memory requires an id, supported category, and object content")
        scope = item.get("scope") or {"kind": "global"}
        coordinates = self.coordinates_for_scope(scope)
        provenance = {
            "lifeos_memory_id": memory_id,
            "source": item.get("source"),
            "source_ref": item.get("source_ref"),
            "scope": scope,
            "category": item.get("category"),
            "confidence": item.get("confidence"),
            "occurred_at": item.get("occurred_at"),
        }
        return {
            **coordinates,
            "id": f"lifeos-{memory_id}",
            "type": self._ATOMIC_TYPES[category],
            "priority": 50,
            "content": json.dumps(content, ensure_ascii=False, sort_keys=True),
            "background": json.dumps(provenance, ensure_ascii=False, sort_keys=True),
            "metadata": {
                "lifeos_memory_id": memory_id,
                "lifeos_scope_kind": (item.get("scope") or {}).get("kind", "unassigned"),
            },
        }

    def write_approved_memory(self, item):
        payload = self.approved_memory_payload(item)
        expected_remote_id = f"lifeos-{item.get('id')}"
        sync = item.get("provider_sync") or {}
        remote_id = sync.get("remote_id")
        scope_key = self.scope_key_for(item.get("scope"))
        bound_scope_key = sync.get("remote_scope_key")
        if bound_scope_key is not None and bound_scope_key != scope_key:
            raise TencentDBError("TencentDB remote memory scope binding does not match the LifeOS scope")
        if sync.get("status") == "synced" and bound_scope_key != scope_key:
            raise TencentDBError("synced TencentDB memory is missing its matching scope binding")
        if remote_id is not None and remote_id != expected_remote_id:
            raise TencentDBError("TencentDB remote memory binding does not match the deterministic LifeOS ID")
        if sync.get("status") == "synced" and remote_id != expected_remote_id:
            raise TencentDBError("synced TencentDB memory is missing its matching remote ID")
        if remote_id == expected_remote_id:
            return self._transport("/v3/atomic/update", payload)
        return self._transport("/v3/atomic/create", payload)

    def delete_approved_memory(self, memory_id, *, scope=None, remote_scope_key=None):
        if not isinstance(memory_id, str) or not memory_id:
            raise ValueError("memory id is required")
        scope_key = self.scope_key_for(scope)
        if remote_scope_key is not None and remote_scope_key != scope_key:
            raise TencentDBError("TencentDB remote memory scope binding does not match the LifeOS scope")
        coordinates = self.coordinates_for_scope(scope)
        return self._transport(
            "/v3/atomic/delete",
            {
                **{key: coordinates[key] for key in ("team_id", "agent_id", "user_id")},
                "ids": [f"lifeos-{memory_id}"],
            },
        )

    def search_memories(self, query, scope=None, limit=5):
        if not isinstance(query, str) or not query.strip():
            return []
        coordinates = self.coordinates_for_scope(scope, required=False)
        if coordinates is None:
            return []
        payload = {
            **coordinates,
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
