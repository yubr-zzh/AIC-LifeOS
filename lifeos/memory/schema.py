"""Shared validation for scoped, provenance-aware memory records."""

from copy import deepcopy
from datetime import datetime
from typing import Any, Dict


MEMORY_CATEGORIES = {"user", "project", "feedback", "reference"}
MEMORY_SOURCES = {
    "direct",
    "user_feedback",
    "feedback_analysis",
    "reflection",
    "external",
    "structured_entry",
    "agent_execution",
}
SCOPE_KINDS = {"global", "scenario", "project", "unassigned"}
CURRENT_SCHEMA_VERSION = 4


def migrate_store(store: Dict[str, Any], source_category) -> tuple[Dict[str, Any], bool]:
    """Upgrade the legacy flat store, retaining a one-time pre-migration backup."""
    version = store.get("schema_version", 1)
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError(f"invalid memory schema version: {version}")
    if version == CURRENT_SCHEMA_VERSION:
        return store, False
    if version > CURRENT_SCHEMA_VERSION or version < 1:
        raise ValueError(f"unsupported memory schema version: {version}")

    original = deepcopy(store)
    migrated = deepcopy(store)
    for category in MEMORY_CATEGORIES:
        migrated.setdefault(category, [])
        for entry in migrated[category]:
            entry.setdefault("category", category)
            entry.setdefault("source_ref", None)
            if "scope" not in entry and category == "user" and entry.get("source") == "direct":
                entry["scope"] = normalize_scope(
                    {"kind": "global", "scenario_type": None, "project_id": None}
                )
            else:
                entry.setdefault("scope", normalize_scope(None))
            entry.setdefault("confidence", None)
            entry.setdefault("confidence_method", None)
            entry.setdefault("occurred_at", None)
            entry.setdefault("confirmed_at", entry.get("committed_at"))
            entry.setdefault("valid_from", None)
            entry.setdefault("valid_until", None)
            entry.setdefault("promotion", None)
            entry.setdefault("status", "active")

    migrated.setdefault("candidates", [])
    for candidate in migrated["candidates"]:
        if candidate.get("category") not in MEMORY_CATEGORIES:
            try:
                candidate["category"] = source_category(candidate.get("source", ""))
            except ValueError:
                # Preserve historical routing for old data only. New writes
                # reject unknown sources instead of silently routing them.
                candidate["category"] = "project"
        candidate.setdefault("source_ref", None)
        if candidate["source_ref"] is None and candidate.get("source_event_id"):
            candidate["source_ref"] = {
                "kind": "event",
                "record_id": candidate["source_event_id"],
            }
        if "scope" not in candidate and candidate.get("source") == "direct":
            candidate["scope"] = normalize_scope(
                {"kind": "global", "scenario_type": None, "project_id": None}
            )
        else:
            candidate.setdefault("scope", normalize_scope(None))
        candidate.setdefault("confidence", None)
        candidate.setdefault("confidence_method", None)
        candidate.setdefault("occurred_at", None)
        candidate.setdefault("valid_from", None)
        candidate.setdefault("valid_until", None)

    migrated.setdefault("backups", [])
    migrated.setdefault("vector_index", {})
    migrated.setdefault("cache", {})
    migrated["schema_version"] = CURRENT_SCHEMA_VERSION
    migrated["backups"].append(
        {
            "created_at": datetime.utcnow().isoformat(),
            "store": original,
        }
    )
    return migrated, True


def normalize_scope(scope: Dict[str, Any] | None) -> Dict[str, Any]:
    """Return a validated scope; missing scope is deliberately unassigned."""
    if scope is None:
        return {
            "kind": "unassigned",
            "scenario_type": None,
            "project_id": None,
            "user_id": None,
        }
    if not isinstance(scope, dict):
        raise ValueError("memory scope must be an object")

    normalized = {
        "kind": scope.get("kind"),
        "scenario_type": scope.get("scenario_type"),
        "project_id": scope.get("project_id"),
        "user_id": scope.get("user_id"),
    }
    for field in ("scenario_type", "project_id", "user_id"):
        value = normalized[field]
        if value is not None and not isinstance(value, str):
            raise ValueError(f"memory scope {field} must be a string or null")
    if not isinstance(normalized["kind"], str) or normalized["kind"] not in SCOPE_KINDS:
        raise ValueError(f"unsupported memory scope kind: {normalized['kind']}")
    if normalized["kind"] == "scenario" and not isinstance(normalized["scenario_type"], str):
        raise ValueError("scenario scope requires scenario_type")
    if normalized["kind"] == "scenario" and not normalized["scenario_type"].strip():
        raise ValueError("scenario scope requires scenario_type")
    if normalized["kind"] == "project" and not isinstance(normalized["project_id"], str):
        raise ValueError("project scope requires project_id")
    if normalized["kind"] == "project" and not normalized["project_id"].strip():
        raise ValueError("project scope requires project_id")
    if normalized["kind"] != "project" and normalized["project_id"] is not None:
        raise ValueError("project_id is only valid for project scope")
    return normalized


def normalize_source_ref(source_ref: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if source_ref is None:
        return None
    if not isinstance(source_ref, dict):
        raise ValueError("memory source_ref must be an object")
    normalized = deepcopy(source_ref)
    if (
        not isinstance(normalized.get("kind"), str)
        or not normalized["kind"].strip()
        or not isinstance(normalized.get("record_id"), str)
        or not normalized["record_id"].strip()
    ):
        raise ValueError("memory source_ref requires kind and record_id")
    return normalized


def validate_confidence(confidence: float | None, method: str | None) -> None:
    if confidence is None:
        if method is not None:
            raise ValueError("confidence_method requires confidence")
        return
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("confidence must be a number between 0 and 1")
    if not 0 <= confidence <= 1:
        raise ValueError("confidence must be a number between 0 and 1")
    if not isinstance(method, str) or not method.strip():
        raise ValueError("confidence requires confidence_method")


def validate_validity(valid_from: str | None, valid_until: str | None) -> None:
    """Validate optional effective-time bounds as ISO-8601 timestamps."""
    for field, value in (("valid_from", valid_from), ("valid_until", valid_until)):
        if value is not None:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must be an ISO-8601 timestamp or null")
            try:
                datetime.fromisoformat(value)
            except ValueError as exc:
                raise ValueError(f"{field} must be an ISO-8601 timestamp or null") from exc
    if valid_from and valid_until:
        start = datetime.fromisoformat(valid_from)
        end = datetime.fromisoformat(valid_until)
        if start.tzinfo != end.tzinfo:
            raise ValueError("validity timestamps must use compatible timezone information")
        if end <= start:
            raise ValueError("valid_until must be later than valid_from")
