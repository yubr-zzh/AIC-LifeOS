import asyncio
import json
import unittest

from lifeos.agent.chat.runtime import ChatRuntime
from lifeos.agent.planner.planner import Planner


def run(coro):
    return asyncio.run(coro)


class FakeLLM:
    def __init__(self, needs_agent, *, reason="由模型判断", requires_side_effects=None):
        self.needs_agent = needs_agent
        self.reason = reason
        self.requires_side_effects = requires_side_effects

    async def complete(self, messages, tools=None):
        return {
            "content": json.dumps(
                {
                    "decision": "agent" if self.needs_agent else "self_plan",
                    "confidence": 0.93,
                    "reason": self.reason,
                    "requires_side_effects": self.needs_agent if self.requires_side_effects is None else self.requires_side_effects,
                    "signals": ["model:test"],
                    "steps": [
                        {"title": "步骤一", "detail": "说明一", "time": "今天"},
                        {"title": "步骤二", "detail": "说明二", "time": "明天"},
                    ],
                },
                ensure_ascii=False,
            ),
            "provider": "test",
            "model": "test-model",
        }


class FailingLLM:
    async def complete(self, messages, tools=None):
        raise RuntimeError("model unavailable")


class FakePlugin:
    async def classify(self, payload):
        return {
            "decision": "agent",
            "confidence": 0.91,
            "reason": "外部路由器识别为执行任务",
            "requires_side_effects": True,
            "signals": ["plugin:test"],
            "steps": [{"title": "插件步骤", "detail": "执行", "time": "现在"}],
        }


class FakeMemory:
    async def retrieve(self, user_input):
        return []


class FakeExecutor:
    def __init__(self):
        self.called = False

    async def execute_chat_turn(self, **kwargs):
        self.called = True
        planning = kwargs.get("planning") or {}
        return {
            "response": "agent response",
            "tool_calls": [],
            "tool_results": [],
            "provider": "test",
            "model": "test-model",
            "decision": planning.get("decision"),
            "decision_reason": planning.get("reason"),
            "decision_confidence": planning.get("confidence"),
            "plan_steps": planning.get("steps", []),
        }


class FakeBus:
    def __init__(self):
        self.events = []

    async def publish(self, event_type, payload, trace_id=None):
        self.events.append((event_type, payload, trace_id))


class FakeTrace:
    def start(self, user_input):
        return "trace-test"

    def event(self, trace_id, event_type, payload):
        pass


class AgentNecessityRoutingTests(unittest.TestCase):
    def runtime(self, needs_agent):
        executor = FakeExecutor()
        planner = Planner(FakeLLM(needs_agent))
        runtime = ChatRuntime(
            llm=FakeLLM(needs_agent),
            memory=FakeMemory(),
            planner=planner,
            executor=executor,
            event_bus=FakeBus(),
            trace=FakeTrace(),
        )
        return runtime, executor

    def test_self_plan_never_reaches_executor(self):
        runtime, executor = self.runtime(False)
        result = run(runtime.handle_message("帮我处理一下这个任务"))
        self.assertEqual(result["decision"], "self_plan")
        self.assertFalse(executor.called)
        self.assertEqual(result["tool_calls"], [])
        self.assertEqual([step["title"] for step in result["plan_steps"]], ["步骤一", "步骤二"])

    def test_agent_decision_still_reaches_executor(self):
        runtime, executor = self.runtime(True)
        result = run(runtime.handle_message("帮我处理一下这个事情"))
        self.assertEqual(result["decision"], "agent")
        self.assertTrue(executor.called)
        self.assertEqual(result["response"], "agent response")

    def test_rule_matrix_routes_execution_requests_to_agent(self):
        planner = Planner(FailingLLM())
        prompts = [
            "读取项目文件并修复构建错误",
            "运行 npm test 并把失败用例修好",
            "把这份报价同步到数据库",
            "下载网页内容并保存到本地文件",
            "部署这个服务到服务器",
            "给客户发送确认邮件",
            "删除临时目录和缓存文件",
            "帮我写代码并生成一个脚本",
            "整理项目文件并移动目录",
        ]
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                result = run(planner.analyze(prompt, []))
                self.assertEqual(result["decision"], "agent")
                self.assertTrue(result["agent_enabled"])
                self.assertTrue(result["requires_side_effects"])
                self.assertIn(result["route_source"], {"rules", "user_override"})

    def test_rule_matrix_routes_content_requests_to_self_plan(self):
        planner = Planner(FailingLLM())
        prompts = [
            "帮我制定下周学习计划",
            "总结这份会议纪要的重点",
            "解释一下这个概念",
            "给我三个写作选题建议",
            "复盘这周的进展",
            "比较两个方案并给出建议",
            "把这些经历整理成心得",
        ]
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                result = run(planner.analyze(prompt, []))
                self.assertEqual(result["decision"], "self_plan")
                self.assertFalse(result["agent_enabled"])
                self.assertFalse(result["requires_side_effects"])
                self.assertEqual(result["route_source"], "rules")

    def test_side_effect_flag_overrides_conflicting_model_decision(self):
        planner = Planner(FakeLLM(False, reason="模型误判为自规划", requires_side_effects=True))
        result = run(planner.analyze("帮我处理一下这个任务", []))
        self.assertEqual(result["decision"], "agent")
        self.assertTrue(result["requires_side_effects"])

    def test_external_plugin_can_route_before_model(self):
        planner = Planner(FailingLLM(), plugin=FakePlugin())
        result = run(planner.analyze("帮我处理一下这个任务", []))
        self.assertEqual(result["decision"], "agent")
        self.assertEqual(result["route_source"], "external_plugin")
        self.assertIn("plugin:test", result["route_signals"])

    def test_force_policies_are_explicit(self):
        planner = Planner(FailingLLM())
        forced_self = run(planner.analyze("运行部署脚本", [], routing_policy="force_self_plan"))
        forced_agent = run(planner.analyze("帮我写一份计划", [], routing_policy="force_agent"))
        self.assertEqual(forced_self["decision"], "self_plan")
        self.assertEqual(forced_self["route_source"], "user_override")
        self.assertEqual(forced_agent["decision"], "agent")
        self.assertEqual(forced_agent["route_source"], "user_override")


if __name__ == "__main__":
    unittest.main()
