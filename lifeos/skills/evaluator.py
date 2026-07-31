class SkillEvaluator:
    async def evaluate(self, skill, result):
        return {
            "skill": skill.get("name"),
            "success": not bool(result.get("error")),
            "result": result,
        }

