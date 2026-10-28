"""P0-A：工具调用状态字段、权限请求的 toolUseId、中断语义。

这几条是 Agent 侧栏折叠渲染的前提：
- `AgentMessage.state` 让前端知道「执行中 / 已完成 / 已中断」
- `PermissionRequest.toolUseId` 让审批卡与工具调用显式关联
- 中断时补 `tool_cancelled`，而不是伪造一条失败的 tool_result
"""

import sys
import unittest
import uuid

from lifeos.bridge.events import ZongXian
from lifeos.bridge.models import (
    TOOL_STATE,
    AgentMessage,
    AgentSession,
    PermissionRequest,
)
from lifeos.bridge.session import HuiHua

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class ModelTests(unittest.TestCase):
    def test_agent_message_keeps_state(self):
        """state 必须能落进 to_dict，否则前端永远看不到执行中。"""
        m = AgentMessage(messageId="m-1", sessionId="s", seq=1, role="assistant",
                         kind="tool_use", toolUseId="t-1", state="executing")
        self.assertEqual(m.to_dict()["state"], "executing")

    def test_old_message_without_state_still_works(self):
        """老消息没有 state：反序列化/构造不能报错。"""
        m = AgentMessage(messageId="m-1", sessionId="s", seq=1, role="assistant",
                         kind="tool_use", toolUseId="t-1")
        self.assertEqual(m.to_dict()["state"], "")

    def test_permission_request_has_tool_use_id(self):
        q = PermissionRequest(requestId="r-1", sessionId="s", toolName="Bash",
                              toolInput={}, toolUseId="t-1")
        self.assertEqual(q.to_dict()["toolUseId"], "t-1")

    def test_permission_request_defaults_to_empty(self):
        """既有构造点不传也不能炸。"""
        q = PermissionRequest(requestId="r-1", sessionId="s", toolName="Bash",
                              toolInput={})
        self.assertEqual(q.toolUseId, "")

    def test_tool_state_values_are_lowercase_snake(self):
        """前端判别联合逐字匹配，大小写错了会静默降级。"""
        for s in TOOL_STATE:
            self.assertEqual(s, s.lower())
            self.assertNotIn(" ", s)


class InterruptTests(unittest.TestCase):
    def setUp(self):
        self.z = ZongXian(uuid.uuid4().hex[:8])
        self.h = HuiHua(self.z)
        self.z.zhan = self.h
        self.h.jian(AgentSession(sessionId="s-1", agentId="echo", agentLabel="echo",
                                 cwd="."))

    def test_zhong_duan_marks_executing_call_cancelled(self):
        """中断时给执行中的调用补 tool_cancelled，且消息落盘。"""
        self.h.tian_jia("s-1", "assistant", "tool_use",
                        toolUseId="t-1", toolName="Bash", toolInput={"command": "sleep 40"},
                        state="executing")
        self.h.zhong_duan("s-1")

        lie = self.h._xiang["s-1"]
        gua = [m for m in lie if m.kind == "tool_cancelled"]
        self.assertEqual(len(gua), 1)
        self.assertEqual(gua[0].toolUseId, "t-1")
        self.assertEqual(gua[0].state, "cancelled")
        # 不是伪造的失败结果
        self.assertEqual([m for m in lie if m.kind == "tool_result"], [])

    def test_zhong_duan_ignores_completed_call(self):
        """已经有 tool_result 的调用不该再补 cancelled。

        tool_use 自己的 state 不会因为结果到达而改变，所以必须显式查
        「这个 toolUseId 是否已经有结局」，否则中断会把已经跑完的调用
        也标成「已中断」。
        """
        self.h.tian_jia("s-1", "assistant", "tool_use",
                        toolUseId="t-1", toolName="Bash", toolInput={},
                        state="executing")
        self.h.tian_jia("s-1", "user", "tool_result",
                        toolUseId="t-1", text="ok", state="completed")
        self.h.zhong_duan("s-1")
        gua = [m for m in self.h._xiang["s-1"] if m.kind == "tool_cancelled"]
        self.assertEqual(len(gua), 0)

    def test_zhong_duan_marks_awaiting_confirmation(self):
        self.h.tian_jia("s-1", "assistant", "tool_use",
                        toolUseId="t-2", toolName="Write", toolInput={},
                        state="awaiting_confirmation")
        self.h.zhong_duan("s-1")
        gua = [m for m in self.h._xiang["s-1"] if m.kind == "tool_cancelled"]
        self.assertEqual(len(gua), 1)
        self.assertEqual(gua[0].toolUseId, "t-2")


if __name__ == "__main__":
    unittest.main()
