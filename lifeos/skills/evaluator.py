"""Skill result evaluation and per-skill success statistics."""

RATING_SCORES = {
    "helpful": 1.0,
    "just_right": 0.5,
    "not_helpful": -1.0,
    "plan_too_heavy": -1.0,
}


class SkillEvaluator:
    """Evaluates a skill execution result.

    A run counts as successful only when there is no error AND no tool
    call was blocked by the permission layer. User ratings can be folded
    in later via ``rating_score`` when aggregating per-skill stats.
    """

    async def evaluate(self, skill, result):
        error = result.get("error")
        tool_results = result.get("tool_results", []) or []
        blocked = sum(1 for t in tool_results if t.get("status") == "blocked")
        success = (not error) and blocked == 0
        return {
            "skill": skill.get("name"),
            "success": success,
            "blocked_calls": blocked,
            "result": result,
        }

    @staticmethod
    def rating_score(rating):
        """Map a user rating value to its numeric contribution."""
        return RATING_SCORES.get(rating, 0.0)
