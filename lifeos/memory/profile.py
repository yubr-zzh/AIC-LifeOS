"""Build deterministic, source-backed profile views from active memories.

The profile is a read model, not another persistence authority. It contains
the accepted memory claims and their provenance, grouped by scope; it does not
ask an LLM to invent a prose summary or promote memories between scopes.
"""

import hashlib
import json
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict

from lifeos.memory.schema import normalize_scope
from lifeos.memory.retriever import MemoryRetriever


PROFILE_SCHEMA_VERSION = 1
MEMORY_CATEGORIES = ("user", "project", "feedback", "reference")
PROFILE_FIELDS = (
    "id",
    "source",
    "category",
    "source_ref",
    "evidence_source_ref",
    "scope",
    "confidence",
    "confidence_method",
    "occurred_at",
    "confirmed_at",
    "valid_from",
    "valid_until",
    "promotion",
    "content",
    "trace_id",
    "status",
    "version_of",
    "superseded_by",
    "created_at",
    "committed_at",
)


def build_memory_profile(store: Dict[str, Any]) -> Dict[str, Any]:
    """Derive global, scenario, and project profiles from active entries only."""
    grouped = {"core_profiles": {}, "scenario_profiles": {}, "project_profiles": {}}
    now = datetime.now().astimezone()
    entries_by_id = {
        entry.get("id"): entry
        for category in MEMORY_CATEGORIES
        for entry in store.get(category, []) or []
        if entry.get("id")
    }

    for category in MEMORY_CATEGORIES:
        for entry in store.get(category, []) or []:
            if entry.get("status", "active") != "active":
                continue
            # A derived profile claim is only as current as every source that
            # supports it. Retrieval already applies this guard; applying it
            # here prevents stale claims from leaking through profile_view().
            if entry.get("source_ids") and not MemoryRetriever._lifecycle_matches(
                entry,
                now,
                entries_by_id,
                historical=False,
            ):
                continue
            try:
                scope = normalize_scope(entry.get("scope"))
            except ValueError:
                # Malformed or legacy scope must not leak into a profile.
                continue
            kind = scope["kind"]
            if kind == "unassigned":
                continue

            if kind == "global":
                bucket = "core_profiles"
                dimensions = (scope["user_id"],)
            elif kind == "scenario":
                bucket = "scenario_profiles"
                dimensions = (scope["user_id"], scope["scenario_type"])
            else:
                bucket = "project_profiles"
                dimensions = (scope["user_id"], scope["scenario_type"], scope["project_id"])

            key = json.dumps(dimensions, ensure_ascii=False, separators=(",", ":"))
            if key not in grouped[bucket]:
                grouped[bucket][key] = {
                    "scope": scope,
                    "memory_count": 0,
                    "memories": [],
                }
            profile = grouped[bucket][key]
            profile["memory_count"] += 1
            profile["memories"].append(
                {field: deepcopy(entry[field]) for field in PROFILE_FIELDS if field in entry}
            )

    result = {
        "schema_version": PROFILE_SCHEMA_VERSION,
        **{
            bucket: sorted(
                profiles.values(),
                key=lambda profile: json.dumps(
                    profile["scope"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ),
            )
            for bucket, profiles in grouped.items()
        },
    }
    for profiles in (result["core_profiles"], result["scenario_profiles"], result["project_profiles"]):
        for profile in profiles:
            profile["memories"].sort(
                key=lambda memory: (
                    memory.get("occurred_at") or memory.get("created_at") or "",
                    memory.get("id", ""),
                ),
                reverse=True,
            )

    canonical = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    result["version"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    result["generated_at"] = datetime.utcnow().isoformat()
    return result
