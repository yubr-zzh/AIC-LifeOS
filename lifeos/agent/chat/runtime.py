from lifeos.memory.schema import normalize_scope


class ChatRuntime:
    """Foreground path optimized for fast user responses."""

    def __init__(self, llm, memory, executor, event_bus, trace):
        self.llm = llm
        self.memory = memory
        self.executor = executor
        self.event_bus = event_bus
        self.trace = trace

    async def handle_message(
        self,
        user_input: str,
        session_id: str | None = None,
        memory_scope: dict | None = None,
    ):
        trace_id = self.trace.start(user_input)
        resolved_scope = normalize_scope(memory_scope) if memory_scope is not None else None
        chunks = await self.memory.retrieve(user_input, scope=resolved_scope)
        self.trace.event(
            trace_id,
            "memory.retrieved",
            {"chunks": chunks, "scope": resolved_scope},
        )

        result = await self.executor.execute_chat_turn(
            user_input=user_input,
            memory=chunks,
            trace_id=trace_id,
        )

        await self.event_bus.publish(
            "conversation.completed",
            {
                "session_id": session_id,
                "user_input": user_input,
                "memory": chunks,
                "memory_scope": resolved_scope,
                "result": result,
            },
            trace_id=trace_id,
        )
        self.trace.event(trace_id, "conversation.completed", {"result": result})
        return {
            "trace_id": trace_id,
            "response": result["response"],
            "tool_calls": result.get("tool_calls", []),
            "tool_results": result.get("tool_results", []),
        }
