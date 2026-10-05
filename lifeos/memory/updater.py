"""Memory candidate proposal and apply (category routing)."""

import uuid
from datetime import datetime
from typing import Any, Dict

from lifeos.memory.schema import (
    MEMORY_CATEGORIES,
    MEMORY_SOURCES,
    normalize_scope,
    normalize_source_ref,
    validate_confidence,
)


def _now() -> str:
    return datetime.utcnow().isoformat()


# Map recognized candidate sources to the legacy display/storage category.
# New source kinds require an explicit category; there is no silent fallback.
SOURCE_CATEGORY = {
    "direct": "user",                 # 用户主动提供的画像 / 偏好
    "user_feedback": "feedback",      # 用户评分反馈
    "feedback_analysis": "feedback",  # 对反馈的聚合分析
    "reflection": "project",          # 对话反思 -> 项目上下文
    "external": "reference",          # 外部知识资源
    "agent_execution": "project",  # 用户从 Agent 执行结果中确认的项目认知
}


def category_for_source(source: str) -> str:
    if not isinstance(source, str):
        raise ValueError(f"unknown memory source: {source}")
    try:
        return SOURCE_CATEGORY[source]
    except KeyError as exc:
        raise ValueError(f"unknown memory source: {source}") from exc


class MemoryUpdater:
    def __init__(self, store):
        self.store = store

    async def propose(
        self,
        source: str,
        content: Dict[str, Any],
        trace_id: str | None,
        source_ref: Dict[str, Any] | None = None,
        scope: Dict[str, Any] | None = None,
        confidence: float | None = None,
        confidence_method: str | None = None,
        category: str | None = None,
        occurred_at: str | None = None,
    ):
        if not isinstance(source, str) or source not in MEMORY_SOURCES:
            raise ValueError(f"unknown memory source: {source}")
        default_category = SOURCE_CATEGORY.get(source)
        if category is None:
            if default_category is None:
                raise ValueError(f"memory source requires an explicit category: {source}")
            category = default_category
        if not isinstance(category, str) or category not in MEMORY_CATEGORIES:
            raise ValueError(f"unsupported memory category: {category}")
        validate_confidence(confidence, confidence_method)
        normalized_scope = normalize_scope(scope)
        if scope is None and source == "direct":
            normalized_scope = {
                "kind": "global",
                "scenario_type": None,
                "project_id": None,
                "user_id": None,
            }
        candidate = {
            "id": str(uuid.uuid4()),
            "source": source,
            "category": category,
            "source_ref": normalize_source_ref(source_ref),
            "scope": normalized_scope,
            "confidence": confidence,
            "confidence_method": confidence_method,
            "occurred_at": occurred_at,
            "content": content,
            "trace_id": trace_id,
            "status": "candidate",
            "created_at": _now(),
        }
        self.store.setdefault("candidates", []).append(candidate)
        return candidate

    async def apply(self, candidate: Dict[str, Any]):
        entry = {
            "id": candidate["id"],
            "source": candidate["source"],
            "category": candidate.get("category") or category_for_source(candidate.get("source", "")),
            "source_ref": candidate.get("source_ref"),
            "scope": normalize_scope(candidate.get("scope")),
            "confidence": candidate.get("confidence"),
            "confidence_method": candidate.get("confidence_method"),
            "occurred_at": candidate.get("occurred_at"),
            "content": candidate["content"],
            "trace_id": candidate.get("trace_id"),
            "status": "active",
            "created_at": _now(),
        }
        category = entry["category"]
        self.store.setdefault(category, []).append(entry)
        candidate["status"] = "committed"
        candidate["committed_at"] = _now()
        return entry
