"""Foreground path optimized for fast user responses."""

import asyncio

from lifeos.agent.context import AgentContextStore
from lifeos.agent.planner.planner import Planner
from lifeos.memory.schema import normalize_scope


class ChatRuntime:
    """Foreground path optimized for fast user responses."""

    def __init__(self, llm, memory, executor, event_bus, trace, external_memory=None, agent_context=None,
                 planner=None, delegation_enabled=True):
        self.llm = llm
        self.memory = memory
        self.executor = executor
        self.event_bus = event_bus
        self.trace = trace
        self.external_memory = external_memory
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

    async def handle_message(self, user_input: str, session_id: str | None = None,
                             memory_scope: dict | None = None):
        trace_id = self.trace.start(user_input)
        resolved_scope = normalize_scope(memory_scope) if memory_scope is not None else None
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
                self.trace.event(trace_id, "memory.external_unavailable",
                                 {"provider": "tencentdb", "error": type(exc).__name__})
        self.trace.event(trace_id, "memory.retrieved",
                         {"chunks": chunks, "scope": resolved_scope})

        # 先规划：委派计划要跟着这条消息一起返回，前端才能把卡片贴在它下面。
        plan = await self.planner.cehuao(user_input, trace_id, self.delegation_enabled)
        if plan is not None:
            self.trace.event(trace_id, "delegation.planned", {"planId": plan["planId"]})

        result = await self.executor.execute_chat_turn(
            user_input=user_input,
            memory=chunks,
            trace_id=trace_id,
            context=self.agent_context.du(session_id),
            plan=plan,
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
        # 保持纯字典返回，不引入新返回类型——与现有风格一致。
        out = {
            "trace_id": trace_id,
            "response": result["response"],
            "tool_calls": result.get("tool_calls", []),
            "tool_results": result.get("tool_results", []),
        }
        if plan is not None:
            out["delegation"] = plan
        return out
