"""Reflection engine for the LifeOS Global Agent.

Produces lightweight, deterministic analyses of conversation traces and
user feedback. LLM-backed deep analysis can be layered on later by
subclassing or swapping the strategy; the current implementation keeps
every reflect() call side-effect free and JSON-serializable.
"""

from datetime import datetime

# Rating vocabulary shared with the frontend feedback UI.
RATING_WEIGHTS = {
    "plan_too_heavy": -1.0,
    "just_right": 0.5,
    "helpful": 1.0,
    "not_helpful": -1.0,
}

# Signal words that suggest a conversation involved planning or reviewing.
_PLAN_HINTS = ("计划", "规划", "安排", "周", "月", "阶段", "目标", "plan", "schedule")
_REVIEW_HINTS = ("复盘", "总结", "回顾", "review", "summary", "reflect", "反思")


def _hint_bucket(text: str) -> str:
    text_l = (text or "").lower()
    if any(h in text_l for h in _PLAN_HINTS):
        return "planning"
    if any(h in text_l for h in _REVIEW_HINTS):
        return "review"
    return "general"


class ReflectionEngine:
    """Analyzes conversations and user feedback into actionable insights.

    Two entry points:

    - ``reflect(conversation)``: called by the Global Agent after a
      ``conversation.completed`` event. Extracts the user intent bucket,
      detects whether the response went well, and proposes a memory
      candidate.
    - ``analyze_feedback(feedback_entries, window_days=7)``: called on
      a batch of feedback memory entries. Aggregates ratings and emits
      improvement suggestions the Agent can act on.
    """

    def __init__(self, llm):
        self.llm = llm

    async def reflect(self, conversation):
        user_input = conversation.get("user_input", "")
        response = conversation.get("result", {}).get("response", "")
        bucket = _hint_bucket(user_input)
        issues = []

        # Simple heuristics: empty responses and blocked tool calls are
        # the clearest failure signals visible without an LLM.
        if not response:
            issues.append("empty_response")
        tool_results = conversation.get("result", {}).get("tool_results", [])
        blocked = [
            t for t in tool_results
            if t.get("status") == "blocked" or t.get("review", {}).get("decision") == "requires_confirmation"
        ]
        if blocked:
            issues.append(f"blocked_tool_calls:{len(blocked)}")

        return {
            # This is an interaction diagnostic, not a user-profile claim.
            # Keep the raw turn and assistant response in their source stores;
            # memory candidates must not duplicate transcript text by default.
            "summary": f"Conversation intent classified as {bucket}.",
            "intent_bucket": bucket,
            "response_status": "present" if response else "empty",
            "issues": issues,
            "memory_type": f"conversation_reflection:{bucket}",
            "requires_user_distillation": True,
            "reflected_at": datetime.utcnow().isoformat(),
        }

    async def analyze_feedback(self, feedback_entries, window_days=7):
        """Aggregate user feedback into actionable improvement notes.

        ``feedback_entries`` is a list of memory entries whose content
        contains ``rating`` and optional ``note`` / ``trace_id`` fields.
        Returns a dict that can be persisted as a memory candidate.
        """
        if not feedback_entries:
            return {
                "summary": "No user feedback in window.",
                "rating_counts": {},
                "score": 0.0,
                "suggestions": [],
                "memory_type": "feedback_analysis",
                "analyzed_at": datetime.utcnow().isoformat(),
            }

        counts = {}
        weighted = 0.0
        notes = []
        for entry in feedback_entries:
            content = entry.get("content", {})
            rating = content.get("rating")
            if rating not in RATING_WEIGHTS:
                continue
            counts[rating] = counts.get(rating, 0) + 1
            weighted += RATING_WEIGHTS[rating]
            note = content.get("note")
            if note:
                notes.append(
                    {
                        "note": note,
                        "trace_id": content.get("trace_id"),
                        "created_at": entry.get("created_at"),
                    }
                )

        total = sum(counts.values())
        score = weighted / total if total else 0.0

        suggestions = []
        if counts.get("plan_too_heavy"):
            suggestions.append(
                "plans feel too heavy: break task lists into fewer, concrete next actions"
            )
        if counts.get("not_helpful"):
            suggestions.append(
                "some answers were not helpful: consider stricter memory retrieval or clarifying questions"
            )
        if counts.get("helpful") and counts.get("helpful", 0) >= 3:
            suggestions.append("keep current behavior: several answers rated helpful")

        return {
            "summary": f"Analyzed {total} feedback entries (score={score:+.2f}).",
            "rating_counts": counts,
            "score": score,
            "notes": notes,
            "suggestions": suggestions,
            "memory_type": "feedback_analysis",
            "analyzed_at": datetime.utcnow().isoformat(),
        }
