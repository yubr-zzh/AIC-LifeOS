
from lifeos.agent.planner.planner import Planner
from lifeos.agent.executor.executor import Executor
from lifeos.memory.manager import MemoryManager
from lifeos.trace.system import TraceSystem

class LifeOSAgent:
    def __init__(self, llm):
        self.llm = llm
        self.memory = MemoryManager()
        self.planner = Planner(llm)
        self.executor = Executor(llm)
        self.trace = TraceSystem()

    async def run(self, user_input: str):
        trace_id = self.trace.start(user_input)

        memory = await self.memory.retrieve(user_input)

        intent = await self.planner.analyze(
            user_input,
            memory
        )

        plan = await self.planner.create_plan(intent)

        result = await self.executor.execute(plan)

        self.trace.event(
            trace_id,
            "execution_finished",
            {"plan": plan}
        )

        return {
            "trace_id": trace_id,
            "intent": intent,
            "result": result
        }
