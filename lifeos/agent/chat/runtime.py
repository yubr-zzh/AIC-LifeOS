import asyncio

from lifeos.memory.schema import normalize_scope


class ChatRuntime:
    """Foreground path optimized for fast user responses."""

    def __init__(self, llm, memory, planner, executor, event_bus, trace, external_memory=None):
        self.llm = llm
        self.memory = memory
        self.planner = planner
        self.executor = executor
        self.event_bus = event_bus
        self.trace = trace
        self.external_memory = external_memory

    async def handle_message(
        self,
        user_input: str,
        session_id: str | None = None,
        memory_scope: dict | None = None,
        routing_policy="auto",
    ):
        trace_id = self.trace.start(user_input)
        resolved_scope = normalize_scope(memory_scope) if memory_scope is not None else None
        if resolved_scope is None:
            chunks = await self.memory.retrieve(user_input)
        else:
            chunks = await self.memory.retrieve(user_input, scope=resolved_scope)
        if self.external_memory is not None:
            try:
                allowed_memory_ids = self.memory.active_memory_ids()
                external = await asyncio.to_thread(
                    self.external_memory.retrieve,
                    user_input,
                    scope=resolved_scope,
                    allowed_memory_ids=allowed_memory_ids,
                )
                for category, entries in external.items():
                    existing = {item.get("id") for item in chunks.get(category, [])}
                    target = chunks.setdefault(category, [])
                    for item in entries:
                        if item.get("id") in allowed_memory_ids and item.get("id") not in existing:
                            target.append(item)
                            existing.add(item.get("id"))
            except Exception as exc:
                self.trace.event(
                    trace_id,
                    "memory.external_unavailable",
                    {"provider": "tencentdb", "error": type(exc).__name__},
                )
        self.trace.event(
            trace_id,
            "memory.retrieved",
            {"chunks": chunks, "scope": resolved_scope},
        )

        planning = await self.planner.analyze(
            user_input,
            chunks,
            routing_policy=routing_policy,
        )
        self.trace.event(
            trace_id,
            "planning.assessed",
            {
                "decision": planning["decision"],
                "confidence": planning["confidence"],
                "reason": planning["reason"],
                "route_source": planning["route_source"],
                "route_signals": planning["route_signals"],
            },
        )

        if planning["decision"] == self.planner.SELF_PLAN:
            plan = await self.planner.create_plan(planning)
            result = self._self_plan_result(user_input, planning, plan)
        else:
            result = await self.executor.execute_chat_turn(
                user_input=user_input,
                memory=chunks,
                trace_id=trace_id,
                planning=planning,
            )
            result.update(
                {
                    "decision": planning["decision"],
                    "decision_reason": planning["reason"],
                    "decision_confidence": planning["confidence"],
                    "plan_steps": planning["steps"],
                }
            )

        await self.event_bus.publish(
            "conversation.completed",
            {
                "session_id": session_id,
                "user_input": user_input,
                "memory": chunks,
                "memory_scope": resolved_scope,
                "planning": planning,
                "result": result,
            },
            trace_id=trace_id,
        )
        self.trace.event(
            trace_id,
            "conversation.completed",
            {
                "decision": planning["decision"],
                "result": result,
            },
        )
        return {
            "trace_id": trace_id,
            "response": result["response"],
            "tool_calls": result.get("tool_calls", []),
            "tool_results": result.get("tool_results", []),
            "provider": result.get("provider"),
            "model": result.get("model"),
            "decision": result.get("decision"),
            "decision_reason": result.get("decision_reason"),
            "decision_confidence": result.get("decision_confidence"),
            "plan_steps": result.get("plan_steps", []),
            "agent_enabled": result.get("decision") == self.planner.AGENT,
            "routing_policy": planning.get("routing_policy", routing_policy),
            "route_source": planning.get("route_source"),
            "route_signals": planning.get("route_signals", []),
            "requires_side_effects": planning.get("requires_side_effects", False),
        }

    def _self_plan_result(self, user_input, planning, plan):
        steps = plan.get("steps", [])
        lines = [
            "这项任务不需要 Agent。长期规划已直接把步骤反馈给你自规划。",
            "",
        ]
        for index, step in enumerate(steps, start=1):
            detail = f"：{step.get('detail')}" if step.get("detail") else ""
            timing = f"（{step.get('time')}）" if step.get("time") else ""
            lines.append(f"{index}. {step.get('title')}{detail} {timing}".rstrip())
        return {
            "response": "\n".join(lines),
            "tool_calls": [],
            "tool_results": [],
            "provider": planning.get("provider") or "lifeos-planner",
            "model": planning.get("model") or "long-term-planning",
            "decision": self.planner.SELF_PLAN,
            "decision_reason": planning["reason"],
            "decision_confidence": planning["confidence"],
            "plan_steps": steps,
        }
