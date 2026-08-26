
class Planner:
    def __init__(self, llm):
        self.llm = llm

    async def analyze(self, user_input, memory):
        return {
            "goal": user_input,
            "complexity": self._estimate_complexity(user_input),
            "need_tools": False
        }

    async def create_plan(self, intent):
        return {
            "steps": [
                {
                    "id": 1,
                    "action": "reason",
                    "input": intent["goal"]
                }
            ]
        }

    def _estimate_complexity(self, text):
        if len(text) > 100:
            return 2
        return 1
