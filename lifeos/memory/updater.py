"""Memory candidate proposal and apply (category routing)."""

import uuid
from datetime import datetime
from typing import Any, Dict


def _now() -> str:
    return datetime.utcnow().isoformat()


# Map a candidate source to the memory category it should be committed
# into. Unknown sources fall back to "project" so nothing is lost.
SOURCE_CATEGORY = {
    "direct": "user",                 # 用户主动提供的画像 / 偏好
    "user_feedback": "feedback",      # 用户评分反馈
    "feedback_analysis": "feedback",  # 对反馈的聚合分析
    "reflection": "project",          # 对话反思 -> 项目上下文
    "external": "reference",          # 外部知识资源
}


def category_for_source(source: str) -> str:
    return SOURCE_CATEGORY.get(source, "project")


class MemoryUpdater:
    def __init__(self, store):
        self.store = store

    async def propose(self, source: str, content: Dict[str, Any], trace_id: str | None):
        candidate = {
            "id": str(uuid.uuid4()),
            "source": source,
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
            "content": candidate["content"],
            "trace_id": candidate.get("trace_id"),
            "created_at": _now(),
        }
        category = category_for_source(candidate.get("source", ""))
        self.store.setdefault(category, []).append(entry)
        candidate["status"] = "committed"
        candidate["committed_at"] = _now()
        return entry
