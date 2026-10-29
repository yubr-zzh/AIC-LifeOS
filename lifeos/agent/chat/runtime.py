"""Foreground path optimized for fast user responses."""

import asyncio

from lifeos.agent.context import AgentContextStore, ConversationContextStore
from lifeos.agent.planner.planner import Planner
from lifeos.memory.schema import normalize_scope
from lifeos.memory.query_context import SessionQueryContext
from lifeos.memory.temporal import resolve_as_of


class ChatRuntime:
    """Foreground path optimized for fast user responses."""

    def __init__(self, llm, memory, executor, event_bus, trace, external_memory=None, agent_context=None,
                 planner=None, delegation_enabled=True, project_memory=None):
        self.llm = llm
        self.memory = memory
        self.executor = executor
        self.event_bus = event_bus
        self.trace = trace
        self.external_memory = external_memory
        self.project_memory = project_memory
        # planner 之前是死代码：lifeos/agent/runtime.py 实例化了它，
        # 但这里没有参数、全仓库无人调用 guihua()。不接这一步，
        # 委派计划功能就是一段永远不执行的代码。
        self.planner = planner or Planner(llm)
        # 10.1 的开关。默认开着，但必须可关——关键词在普通闲聊里出现频率极高，
        # 误触发委派且没有任何办法关掉就只能改代码。
        self.delegation_enabled = delegation_enabled
        # 7.7.1 决策回路的落点：Agent 每条指令的结果都追加到这里，
        # 下一轮对话时进大模型上下文。**只追加文本，不产生任何指向 Bridge 的调用**
        # （7.7.1 的关键约束：主服务不能自己下发下一条指令）。
        self.agent_context = agent_context or AgentContextStore()
        self.query_context = SessionQueryContext()
        self.conversation_context = ConversationContextStore()

    async def handle_message(self, user_input: str, session_id: str | None = None,
                             memory_scope: dict | None = None, routing_policy: str = "auto",
                             agent_session_id: str | None = None):
        trace_id = self.trace.start(user_input)
        resolved_scope = normalize_scope(memory_scope) if memory_scope is not None else None
        history = self.conversation_context.read(session_id, resolved_scope)
        retrieval_query = self.query_context.add_and_build(session_id, user_input, resolved_scope)
        historical_as_of = resolve_as_of(retrieval_query)
        try:
            chunks = await self.memory.retrieve(retrieval_query, scope=resolved_scope, as_of=historical_as_of)
        except TypeError:
            # Keep compatibility with memory adapters that predate as_of.
            chunks = await self.memory.retrieve(retrieval_query, scope=resolved_scope)
        if self.external_memory is not None:
            try:
                allowed_memory_ids = self.memory.active_memory_ids()
                # External providers currently expose current-state retrieval only.
                external = {} if historical_as_of is not None else await asyncio.to_thread(
                    self.external_memory.retrieve, retrieval_query,
                    scope=resolved_scope, allowed_memory_ids=allowed_memory_ids,
                )
                for category, entries in external.items():
                    existing = {item.get("id") for item in chunks.get(category, [])}
                    target = chunks.setdefault(category, [])
                    for item in entries:
                        if item.get("id") in allowed_memory_ids and item.get("id") not in existing:
                            target.append(item)
                            existing.add(item.get("id"))
            except Exception as exc:
                self.trace.event(trace_id, "memory.external_unavailable",
                                 {"provider": "tencentdb", "error": type(exc).__name__})
        # 被送进本轮上下文的记忆记一次引用。计数失败不能影响回答本身。
        try:
            await self.memory.mark_used([
                item.get("id")
                for entries in chunks.values()
                for item in entries
                if item.get("id")
            ])
        except Exception:
            pass
        self.trace.event(trace_id, "memory.retrieved",
                         {"chunks": chunks, "scope": resolved_scope})

        route_analyzer = getattr(self.planner, "analyze", None)
        legacy_plan = None
        if callable(route_analyzer):
            planning = await route_analyzer(
                user_input, chunks, routing_policy=routing_policy
            )
        else:
            # Compatibility for injected legacy planners that only implement
            # cehuao(); a returned delegation plan means this turn needs Agent.
            legacy_plan = await self.planner.cehuao(
                user_input, trace_id, self.delegation_enabled
            )
            is_agent = legacy_plan is not None
            planning = {
                "decision": "agent" if is_agent else "self_plan",
                "confidence": 1.0 if is_agent else 0.55,
                "reason": "Legacy planner returned an execution plan." if is_agent
                else "Legacy planner found no execution plan.",
                "route_source": "rules" if is_agent else "fallback",
                "route_signals": ["legacy:delegation_plan" if is_agent else "legacy:no_plan"],
                "requires_side_effects": is_agent,
                "plan_requested": False,
                "routing_policy": routing_policy,
                "steps": [],
            }
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

        # 只有进入执行路径才生成可交给本机 Agent 的委派草案。
        plan = None
        if planning["decision"] == "agent":
            build_plan = getattr(self.planner, "create_delegation_plan", None)
            plan = legacy_plan or (await build_plan(user_input, trace_id, self.delegation_enabled)
                                   if callable(build_plan) else await self.planner.cehuao(
                                       user_input, trace_id, self.delegation_enabled))
        if plan is not None:
            self.trace.event(trace_id, "delegation.planned", {"planId": plan["planId"]})

        project_context = []
        if (
            planning["decision"] == "agent"
            and self.project_memory is not None
            and resolved_scope is not None
            and resolved_scope.get("kind") == "project"
        ):
            try:
                project_context = await asyncio.to_thread(
                    self.project_memory.retrieve,
                    user_input,
                    scope=resolved_scope,
                )
                self.trace.event(
                    trace_id,
                    "memory.project_evidence_retrieved",
                    {
                        "provider": "ai-memory",
                        "source_refs": [item.get("source_ref") for item in project_context],
                        "count": len(project_context),
                    },
                )
            except Exception as exc:
                self.trace.event(
                    trace_id,
                    "memory.external_unavailable",
                    {"provider": "ai-memory", "error": type(exc).__name__},
                )

        if planning["decision"] == "self_plan":
            plan_steps = (
                await self.planner.create_plan(planning)
                if planning.get("plan_requested") and hasattr(self.planner, "create_plan")
                else {"steps": []}
            )
            answer_args = dict(
                user_input=user_input,
                memory=chunks,
                trace_id=trace_id,
                context=self.agent_context.du(agent_session_id or session_id),
            )
            if history:
                answer_args["history"] = history
            answer = getattr(self.executor, "answer_chat_turn", None)
            if callable(answer):
                result = await answer(**answer_args)
            else:
                # Compatibility for injected executors used by integrations/tests.
                result = await self.executor.execute_chat_turn(**answer_args, plan=None)
        else:
            executor_args = dict(
                user_input=user_input,
                memory=chunks,
                trace_id=trace_id,
                context=self.agent_context.du(agent_session_id or session_id),
                plan=plan,
            )
            if history:
                executor_args["history"] = history
            if project_context:
                executor_args["project_context"] = project_context
            result = await self.executor.execute_chat_turn(**executor_args)
            plan_steps = (
                await self.planner.create_plan(planning)
                if hasattr(self.planner, "create_plan") else {"steps": []}
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
        self.trace.event(trace_id, "conversation.completed", {
            "decision": planning["decision"], "result": result,
        })
        self.conversation_context.append(session_id, resolved_scope, user_input, result["response"])
        # 保持纯字典返回，不引入新返回类型——与现有风格一致。
        out = {
            "trace_id": trace_id,
            "response": result["response"],
            "tool_calls": result.get("tool_calls", []),
            "tool_results": result.get("tool_results", []),
            "provider": result.get("provider"),
            "model": result.get("model"),
            "decision": planning["decision"],
            "decision_reason": planning["reason"],
            "decision_confidence": planning["confidence"],
            "plan_steps": plan_steps["steps"],
            "agent_enabled": planning["decision"] == "agent",
            "routing_policy": planning["routing_policy"],
            "route_source": planning["route_source"],
            "route_signals": planning["route_signals"],
            "requires_side_effects": planning["requires_side_effects"],
        }
        if plan is not None:
            out["delegation"] = plan
        return out
