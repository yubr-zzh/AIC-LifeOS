"""3.2：result 与 permission_resolved 本来是帧、不是消息。

后果是恢复后的历史比重启前少两类：用户看不到这次跑完的结果是什么，
也不知道刚才那条命令是被谁批准的、为什么。8.6 的「取消与拒绝在审计上
必须可区分」也无从谈起。
"""

import sys
import unittest
import uuid
from pathlib import Path

from lifeos.bridge.arbiter import ShenQing
from lifeos.bridge.events import ZongXian
from lifeos.bridge.http import BridgeServer
from lifeos.bridge.models import AgentSession
from lifeos.bridge.planner_guard import ShenKa
from lifeos.bridge.session import HuiHua

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class XiangShiTests(unittest.TestCase):
    def setUp(self):
        self.z = ZongXian(uuid.uuid4().hex[:8])
        self.h = HuiHua(self.z)
        self.z.zhan = self.h
        self.root = str(Path(__file__).resolve().parent.parent)
        self.token = "t" * 64
        self.fu = BridgeServer(("127.0.0.1", 0), self.z, self.h,
                               ShenKa([self.root]), self.token)
        self.q = self.fu.shen_qing
        self.h.jian(AgentSession(sessionId="s-1", agentId="echo", agentLabel="echo",
                                 cwd=self.root, alive=True))

    def tearDown(self):
        self.h.ting_zhi()
        self.fu.server_close()

    def _lei(self, a1):
        return [m.kind for m in self.h._xiang["s-1"]]

    def test_result_cheng_wei_xiao_xi(self):
        fa = self.fu._hui_zhuan("s-1")
        fa("result", {"subtype": "success", "resultText": "算完了", "isError": False,
                      "durationMs": 10, "numTurns": 1, "totalCostUsd": 0.01})
        self.assertIn("result", self._lei("s-1"))
        xiao = [m for m in self.h._xiang["s-1"] if m.kind == "result"][0]
        self.assertEqual(xiao.text, "算完了")
        self.assertEqual(xiao.role, "system")

    def test_jue_ding_cheng_wei_xiao_xi(self):
        import asyncio
        fu = asyncio.new_event_loop().create_future()
        d = self.q.jia("s-1", "echo", "toolu_1", "Bash", {"command": "ls"}, fu)
        self.q.shou(d, "user_allow")
        self.assertIn("permission_resolved", self._lei("s-1"))
        xiao = [m for m in self.h._xiang["s-1"] if m.kind == "permission_resolved"][0]
        self.assertIn("用户手动批准", xiao.text)
        self.assertTrue(fu.done())

    def test_qu_xiao_yu_ju_jue_ke_qu_bie(self):
        """8.6：autoReason=timeout 与 user_deny 落盘后必须是不同的字符串。"""
        import asyncio
        for rid, jue, yuan in (("toolu_a", "user_deny", None),
                               ("toolu_b", "auto_deny", "timeout"),
                               ("toolu_c", "auto_deny", "deny_baseline")):
            fu = asyncio.new_event_loop().create_future()
            d = self.q.jia("s-1", "echo", rid, "Bash", {"command": rid}, fu)
            self.q.shou(d, jue, a6=yuan)
        # 决定摘要落在 text 上，不在 toolName 上——这条消息不是工具调用
        wen = {m.text for m in self.h._xiang["s-1"]
               if m.kind == "permission_resolved"}
        self.assertEqual(len(wen), 3, f"三种决定摘要撞了：{wen}")


if __name__ == "__main__":
    unittest.main()
