"""7.7.2 展示旁路在主服务侧的分流与白名单。

两条要守住的性质：
1. 六个展示 kind 只写事件总线，绝不进 AgentContextStore——它们不进 LLM 上下文。
2. detail 只保留枚举字段。Bridge 写错时这一层要能挡住，这是纵深防御。
"""

import json
import socket
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from lifeos.agent.runtime import LifeOSAgent
from lifeos.api.server import LifeOSRequestHandler, ZHUAN_LIU, guo_lu2
from lifeos.llm.client import LLMClient

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _duan() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class BaiMingDanTests(unittest.TestCase):
    def test_zhi_liu_bai_ming_dan_nei_de_jian(self):
        shou, diu = guo_lu2("session.created",
                           {"sessionId": "s-1", "agentId": "claude-code",
                            "cwd": "D:/x", "permissionMode": "manual",
                            "resultText": "Agent 自己写的字", "junk": 1})
        self.assertEqual(shou, {"sessionId": "s-1", "agentId": "claude-code",
                                "cwd": "D:/x", "permissionMode": "manual"})
        self.assertEqual(diu, 2)

    def test_bu_ren_shi_de_kind(self):
        self.assertEqual(guo_lu2("bridge.nope", {"x": 1}), ({}, 1))

    def test_mei_ge_kind_du_you_zi_duan_biao(self):
        """spec 7.1 的表，逐个钉住，防止后续有人往 detail 里塞 Agent 文本。"""
        self.assertEqual(ZHUAN_LIU["bridge.connected"],
                         frozenset({"instanceId", "port", "cliVersion", "sdkVersion"}))
        self.assertEqual(ZHUAN_LIU["bridge.disconnected"],
                         frozenset({"reason", "uptimeSec"}))
        self.assertEqual(ZHUAN_LIU["session.created"],
                         frozenset({"sessionId", "agentId", "cwd", "permissionMode"}))
        self.assertEqual(ZHUAN_LIU["session.closed"],
                         frozenset({"sessionId", "reason", "turnCount", "batchDone"}))
        self.assertEqual(ZHUAN_LIU["permission.resolved"],
                         frozenset({"requestId", "decision", "autoReason", "replayed"}))
        self.assertEqual(ZHUAN_LIU["agent.crashed"],
                         frozenset({"sessionId", "exitCode", "signal"}))
        self.assertEqual(len(ZHUAN_LIU), 6)


class FenLiuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.agent = LifeOSAgent(LLMClient(), storage_dir=cls.dir.name)
        cls.jiu = LifeOSRequestHandler.agent
        LifeOSRequestHandler.agent = cls.agent
        cls.duan = _duan()
        cls.zhu = ThreadingHTTPServer(("127.0.0.1", cls.duan), LifeOSRequestHandler)
        cls.zhu.daemon_threads = True
        threading.Thread(target=cls.zhu.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.zhu.shutdown()
        cls.zhu.server_close()
        LifeOSRequestHandler.agent = cls.jiu
        cls.dir.cleanup()

    def _fa(self, a1):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.duan}/api/agent-events",
            data=json.dumps(a1).encode("utf-8"), method="POST",
            headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def test_zhan_shi_kind_zhi_xie_zong_xian(self):
        s, d = self._fa({"kind": "session.created", "sessionId": "s-9",
                         "detail": {"sessionId": "s-9", "agentId": "claude-code",
                                    "cwd": "D:/x", "permissionMode": "manual"}})
        self.assertEqual(s, 200)
        self.assertEqual(self.agent.agent_context.du("s-9"), [],
                         "展示旁路不得进 LLM 上下文")
        lei = [e.type for e in self.agent.event_bus.all_events()]
        self.assertIn("session.created", lei)
        xi = [e for e in self.agent.event_bus.all_events()
              if e.type == "session.created"][0]
        self.assertEqual(xi.payload["sessionId"], "s-9")

    def test_jue_ce_kind_reng_ran_jin_shang_xia_wen(self):
        s, d = self._fa({"kind": "agent.result", "sessionId": "s-8",
                         "detail": {"resultText": "算完了"}})
        self.assertEqual(s, 200)
        self.assertTrue(self.agent.agent_context.du("s-8"))

    def test_wei_zhi_kind_400(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self._fa({"kind": "bridge.nope", "detail": {}})
        self.assertEqual(e.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
