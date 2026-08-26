
class Executor:
    def __init__(self, llm):
        self.llm = llm

    async def execute(self, plan):
        results = []

        for step in plan["steps"]:
            result = await self._execute_step(step)
            results.append(result)

        return results

    async def _execute_step(self, step):
        return {
            "step": step["id"],
            "output": "executed:" + step["action"]
        }
