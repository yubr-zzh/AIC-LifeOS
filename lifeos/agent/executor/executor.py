
# Minimum similarity for the executor to treat an approved skill as
# applicable to the current user input.
SKILL_INVOKE_THRESHOLD = 0.15


class Executor:
    def __init__(self, llm, skill_registry=None, permission_manager=None, trace=None):
        self.llm = llm
        self.skill_registry = skill_registry
        self.permission_manager = permission_manager
        self.trace = trace

    async def _match_skill(self, user_input):
        """Find the best approved skill for this input, if any."""
        if self.skill_registry is None:
            return None
        similar = await self.skill_registry.find_similar(
            user_input, threshold=SKILL_INVOKE_THRESHOLD
        )
        if not similar:
            return None
        return similar[0]

    async def execute_chat_turn(self, user_input, memory, trace_id=None):
        skill = await self._match_skill(user_input)
        if skill and self.trace and trace_id:
            self.trace.event(
                trace_id,
                "skill.invoked",
                {"skill": skill.get("name"), "description": skill.get("description")},
            )
        system_prompt = "You are the foreground LifeOS Chat Agent."
        if skill:
            system_prompt += (
                "\nThe user has an approved skill for this kind of task: "
                f"'{skill.get('name')}' - {skill.get('description')}. "
                "Follow it to keep results consistent."
            )
        messages = [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_input,
                "memory": memory,
            },
        ]
        try:
            completion = await self.llm.complete(messages)
        except Exception:
            if skill and self.skill_registry is not None:
                await self.skill_registry.record_usage(skill["name"], success=False)
            raise
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
        if skill and self.skill_registry is not None:
            succeeded = bool(completion.get("content")) and all(
                result.get("status") == "executed" for result in tool_results
            )
            await self.skill_registry.record_usage(skill["name"], success=succeeded)
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
