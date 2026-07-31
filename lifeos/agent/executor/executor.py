class Executor:
    def __init__(self, llm, skill_registry=None, permission_manager=None, trace=None):
        self.llm = llm
        self.skill_registry = skill_registry
        self.permission_manager = permission_manager
        self.trace = trace

    async def execute_chat_turn(self, user_input, memory, trace_id=None):
        messages = [
            {
                "role": "system",
                "content": "You are the foreground LifeOS Chat Agent.",
            },
            {
                "role": "user",
                "content": user_input,
                "memory": memory,
            },
        ]
        completion = await self.llm.complete(messages)
        tool_calls = completion.get("tool_calls", [])
        tool_results = []

        for tool_call in tool_calls:
            review = await self.permission_manager.review_tool_execution(tool_call)
            if review["decision"] != "allow":
                tool_results.append(
                    {
                        "tool_call": tool_call,
                        "status": "blocked",
                        "review": review,
                    }
                )
                continue
            tool_results.append(await self._execute_tool_call(tool_call))

        response = completion.get("content") or self._fallback_response(user_input)
        if self.trace and trace_id:
            self.trace.event(
                trace_id,
                "chat.executed",
                {"tool_calls": tool_calls, "tool_results": tool_results},
            )
        return {
            "response": response,
            "tool_calls": tool_calls,
            "tool_results": tool_results,
        }

    async def execute(self, plan):
        results = []
        for step in plan["steps"]:
            results.append(await self._execute_step(step))
        return results

    async def _execute_step(self, step):
        return {
            "step": step["id"],
            "output": "executed:" + step["action"],
        }

    async def _execute_tool_call(self, tool_call):
        return {
            "tool_call": tool_call,
            "status": "executed",
            "output": f"executed:{tool_call.get('name', 'tool')}",
        }

    def _fallback_response(self, user_input):
        return f"Received: {user_input}"

