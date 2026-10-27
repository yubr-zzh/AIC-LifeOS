"""Integration checks for session context reaching foreground memory retrieval."""

import asyncio
import unittest
from datetime import datetime, timezone

from lifeos.agent.chat.runtime import ChatRuntime


class RecordingMemory:
    def __init__(self):
        self.calls = []

    async def retrieve(self, query, scope=None, as_of=None):
        self.calls.append({"query": query, "scope": scope, "as_of": as_of})
        return {"user": []}


class SelfPlanPlanner:
    async def analyze(self, user_input, chunks, routing_policy="auto"):
        return {
            "decision": "self_plan",
            "confidence": 1.0,
            "reason": "test",
            "route_source": "rules",
            "route_signals": [],
            "requires_side_effects": False,
            "plan_requested": False,
            "routing_policy": routing_policy,
            "steps": [],
        }


class AnswerExecutor:
    async def answer_chat_turn(self, **kwargs):
        return {"response": "ok", "tool_calls": [], "tool_results": []}


class EventBus:
    async def publish(self, *args, **kwargs):
        return None


class Trace:
    def start(self, user_input):
        return "trace"

    def event(self, *args, **kwargs):
        return None


class ChatRuntimeMemoryContextTests(unittest.TestCase):
    def make_runtime(self):
        memory = RecordingMemory()
        runtime = ChatRuntime(
            llm=None,
            memory=memory,
            executor=AnswerExecutor(),
            event_bus=EventBus(),
            trace=Trace(),
            planner=SelfPlanPlanner(),
        )
        return runtime, memory

    def test_same_session_topic_reaches_historical_retrieval_with_as_of(self):
        runtime, memory = self.make_runtime()

        async def run_turns():
            await runtime.handle_message(
                "我上半年整理周会纪要时，偏好先写完整讨论过程。",
                session_id="session-a",
                memory_scope={"kind": "global"},
            )
            await runtime.handle_message(
                "那段时间我具体怎么要求的？",
                session_id="session-a",
                memory_scope={"kind": "global"},
            )

        asyncio.run(run_turns())
        call = memory.calls[-1]
        self.assertIn("周会纪要", call["query"])
        self.assertEqual(call["as_of"], datetime(2026, 6, 30, 23, 59, 59, tzinfo=timezone.utc))

    def test_missing_session_does_not_reuse_another_turns_topic(self):
        runtime, memory = self.make_runtime()

        async def run_turns():
            await runtime.handle_message(
                "我上半年整理周会纪要时，偏好先写完整讨论过程。",
                session_id="session-a",
                memory_scope={"kind": "global"},
            )
            await runtime.handle_message(
                "那段时间我具体怎么要求的？",
                session_id=None,
                memory_scope={"kind": "global"},
            )

        asyncio.run(run_turns())
        call = memory.calls[-1]
        self.assertNotIn("周会纪要", call["query"])
        self.assertIsNone(call["as_of"])

    def test_previous_exchange_reaches_model_only_in_same_session(self):
        from lifeos.agent.executor.executor import Executor

        class RecordingLLM:
            def __init__(self):
                self.calls = []

            async def complete(self, messages, tools=None):
                self.calls.append(messages)
                return {"content": "回复一", "tool_calls": []}

        llm = RecordingLLM()
        runtime, _ = self.make_runtime()
        runtime.executor = Executor(llm)

        async def run_turns():
            await runtime.handle_message("我的目标是完成论文", session_id="a")
            await runtime.handle_message("下一步呢？", session_id="a")
            await runtime.handle_message("另一个会话", session_id="b")

        asyncio.run(run_turns())
        self.assertEqual(
            [(item["role"], item["content"]) for item in llm.calls[1][1:]],
            [("user", "我的目标是完成论文"), ("assistant", "回复一"), ("user", "下一步呢？")],
        )
        self.assertEqual(len(llm.calls[2]), 2)


if __name__ == "__main__":
    unittest.main()
