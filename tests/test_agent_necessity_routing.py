import asyncio
import json
import unittest

from lifeos.agent.chat.runtime import ChatRuntime
from lifeos.agent.planner.planner import Planner


def run(coro):
    return asyncio.run(coro)


class FakeLLM:
    def __init__(self, result=None, error=None):
        self.result = result or {
            "decision": "self_plan",
            "confidence": 0.93,
            "reason": "只需提供建议",
            "requires_side_effects": False,
            "steps": [{"title": "先明确目标", "detail": "", "time": "今天"}],
        }
        self.error = error
        self.calls = 0

    async def complete(self, messages, tools=None):
        self.calls += 1
        if self.error:
            raise self.error
        return {
            "content": json.dumps(self.result, ensure_ascii=False),
            "provider": "test-provider",
            "model": "test-model",
        }


class FakeMemory:
    async def retrieve(self, user_input, scope=None):
        return {"user": []}

    def active_memory_ids(self):
        return set()


class FakeExecutor:
    def __init__(self):
        self.calls = []
        self.answer_calls = []

    async def execute_chat_turn(self, **kwargs):
        self.calls.append(kwargs)
        return {"response": "agent response", "tool_calls": [], "tool_results": [], "provider": "test"}

    async def answer_chat_turn(self, **kwargs):
        self.answer_calls.append(kwargs)
        return {"response": "normal conversational answer", "tool_calls": [], "tool_results": [], "provider": "test"}


class FakeBus:
    async def publish(self, event_type, payload, trace_id=None):
        return None


class FakeTrace:
    def start(self, user_input):
        return "trace-test"

    def event(self, trace_id, event_type, payload):
        return None


class AgentNecessityRoutingTests(unittest.TestCase):
    def make_runtime(self, llm):
        executor = FakeExecutor()
        runtime = ChatRuntime(
            llm=llm,
            memory=FakeMemory(),
            planner=Planner(llm),
            executor=executor,
            event_bus=FakeBus(),
            trace=FakeTrace(),
        )
        return runtime, executor

    def test_clear_content_request_routes_to_self_plan_without_executor_or_extra_llm(self):
        llm = FakeLLM()
        runtime, executor = self.make_runtime(llm)

        result = run(runtime.handle_message("总结这份会议纪要的重点"))

        self.assertEqual(result["decision"], "self_plan")
        self.assertFalse(result["agent_enabled"])
        self.assertEqual(executor.calls, [])
        self.assertEqual(len(executor.answer_calls), 1)
        self.assertEqual(result["response"], "normal conversational answer")
        self.assertEqual(result["plan_steps"], [])
        self.assertEqual(llm.calls, 0)

    def test_self_plan_can_return_steps_for_actual_planning_requests(self):
        llm = FakeLLM()
        runtime, executor = self.make_runtime(llm)

        result = run(runtime.handle_message("帮我制定下周学习计划"))

        self.assertEqual(result["decision"], "self_plan")
        self.assertEqual(len(result["plan_steps"]), 3)
        self.assertEqual(len(executor.answer_calls), 1)
        self.assertEqual(executor.calls, [])

    def test_clear_side_effect_request_routes_to_agent_without_router_model_call(self):
        llm = FakeLLM()
        runtime, executor = self.make_runtime(llm)

        result = run(runtime.handle_message("运行 npm test 并修复失败用例"))

        self.assertEqual(result["decision"], "agent")
        self.assertTrue(result["requires_side_effects"])
        self.assertEqual(len(executor.calls), 1)
        self.assertEqual(llm.calls, 0)

    def test_ambiguous_request_uses_active_model_assessment(self):
        llm = FakeLLM()
        runtime, executor = self.make_runtime(llm)

        result = run(runtime.handle_message("帮我处理一下这个任务"))

        self.assertEqual(result["decision"], "self_plan")
        self.assertEqual(result["route_source"], "model")
        self.assertEqual(llm.calls, 1)
        self.assertEqual(executor.calls, [])
        self.assertEqual(len(executor.answer_calls), 1)

    def test_model_cannot_route_side_effecting_request_away_from_agent(self):
        llm = FakeLLM({
            "decision": "self_plan",
            "confidence": 0.99,
            "reason": "模型误判",
            "requires_side_effects": True,
        })
        runtime, executor = self.make_runtime(llm)

        result = run(runtime.handle_message("帮我处理一下这个任务"))

        self.assertEqual(result["decision"], "agent")
        self.assertEqual(len(executor.calls), 1)

    def test_force_policies_override_automatic_routing(self):
        llm = FakeLLM(error=RuntimeError("model unavailable"))
        runtime, executor = self.make_runtime(llm)

        self_result = run(runtime.handle_message(
            "运行 npm test", routing_policy="force_self_plan"
        ))
        self.assertEqual(self_result["decision"], "self_plan")
        self.assertEqual(self_result["routing_policy"], "force_self_plan")
        self.assertEqual(executor.calls, [])
        self.assertEqual(len(executor.answer_calls), 1)

        agent_result = run(runtime.handle_message(
            "给我一些建议", routing_policy="force_agent"
        ))
        self.assertEqual(agent_result["decision"], "agent")
        self.assertEqual(agent_result["routing_policy"], "force_agent")
        self.assertEqual(len(executor.calls), 1)
        self.assertEqual(llm.calls, 0)

    def test_agent_route_always_produces_a_delegation_plan(self):
        llm = FakeLLM()
        runtime, _ = self.make_runtime(llm)

        result = run(runtime.handle_message("删除旧数据库", routing_policy="force_agent"))

        self.assertEqual(result["decision"], "agent")
        self.assertEqual(result["delegation"]["items"][0]["instruction"], "删除旧数据库")

    def test_model_failure_uses_conservative_self_plan_fallback(self):
        llm = FakeLLM(error=RuntimeError("model unavailable"))
        runtime, executor = self.make_runtime(llm)

        result = run(runtime.handle_message("帮我处理一下"))

        self.assertEqual(result["decision"], "self_plan")
        self.assertEqual(result["route_source"], "fallback")
        self.assertEqual(executor.calls, [])
        self.assertEqual(len(executor.answer_calls), 1)

    def test_text_only_executor_blocks_unexpected_tool_calls(self):
        from lifeos.agent.executor.executor import Executor

        class ToolLLM:
            async def complete(self, _messages, tools=None):
                return {
                    "content": "answer",
                    "tool_calls": [{"name": "delete_file"}],
                    "provider": "test",
                    "model": "test",
                }

        class PermissionSpy:
            calls = 0

            async def review_tool_execution(self, _tool_call):
                self.calls += 1
                return {"decision": "allow", "reason": "test"}

        permissions = PermissionSpy()
        result = run(Executor(ToolLLM(), permission_manager=permissions).answer_chat_turn(
            "总结材料", {}
        ))

        self.assertEqual(result["response"], "answer")
        self.assertEqual(result["tool_results"][0]["status"], "blocked")
        self.assertEqual(permissions.calls, 0)


if __name__ == "__main__":
    unittest.main()
