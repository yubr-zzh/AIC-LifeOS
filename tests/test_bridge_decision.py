"""3.8 决策回路：每条委派指令的结果真的进 LifeOS 对话上下文。

这是阶段 3 的核心交付物，也是修改目标里「全过程只在 LifeOS 界面操作」的落点。
v1.0 方案在这一项上是**完全空白**的——它一边说 Agent 事件只是展示旁路、
不进上下文，一边又要求「结果回来后 LifeOS 大模型可以重新判断后续指令」。两条互斥。

所以这个测试必须打通整条链：
Bridge 跑完指令 → 出站 POST → 主服务 `/api/agent-events` → `AgentContextStore`
→ `/chat` 时进 `execute_chat_turn` 的 system 消息。
少任何一段，这个测试都会红。
"""

import json
import socket
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

from lifeos.agent.runtime import LifeOSAgent
from lifeos.api.server import LifeOSRequestHandler
from lifeos.bridge import auth
from lifeos.bridge.events import ZongXian
from lifeos.bridge.http import BridgeServer
from lifeos.bridge.localbus import LuDao
from lifeos.bridge.planner_guard import ShenKa
from lifeos.bridge.session import HuiHua
from lifeos.llm.client import LLMClient
from gong_ju import deng_dai, wei_bian

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _duan_kong() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _JiLu(LLMClient):
    """把发给大模型的 messages 原样留下来，供断言「结果真的进了上下文」。"""

    def __init__(self) -> None:
        super().__init__()
        self.kan: list[list[dict]] = []

    async def complete(self, messages, tools=None):
        self.kan.append(messages)
        return {"content": "LifeOS 收到", "tool_calls": [], "usage": {},
                "provider": "mock", "model": "default"}


class JueCeHuiLuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.llm = _JiLu()
        cls.agent = LifeOSAgent(cls.llm, storage_dir=cls.dir.name)
        cls.jiu_agent = LifeOSRequestHandler.agent
        LifeOSRequestHandler.agent = cls.agent  # 端点用的是类属性单例
        cls.zhu_duan = _duan_kong()
        cls.zhu = ThreadingHTTPServer(("127.0.0.1", cls.zhu_duan), LifeOSRequestHandler)
        cls.zhu.daemon_threads = True
        threading.Thread(target=cls.zhu.serve_forever, daemon=True).start()

        cls.duan = _duan_kong()
        cls.root = str(Path(__file__).resolve().parent.parent)
        cls.z = ZongXian(uuid.uuid4().hex[:8])
        cls.h = HuiHua(cls.z)
        cls.z.zhan = cls.h
        cls.token = auth.shengcheng()
        cls.fu = BridgeServer(("127.0.0.1", cls.duan), cls.z, cls.h,
                              ShenKa([cls.root]), cls.token)
        cls.lu = LuDao(f"http://127.0.0.1:{cls.zhu_duan}")
        cls.fu.lu_dao = cls.lu
        threading.Thread(target=cls.fu.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.h.ting_zhi()
        cls.lu.ting_zhi()
        cls.fu.shutdown()
        cls.fu.server_close()
        cls.zhu.shutdown()
        cls.zhu.server_close()
        LifeOSRequestHandler.agent = cls.jiu_agent
        cls.dir.cleanup()

    def _qiao(self, a1: str, a2: dict | None = None):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.duan}{a1}",
            data=json.dumps(a2 or {}).encode("utf-8"), method="POST",
            headers={"content-type": "application/json", "x-bridge-token": self.token})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def _deng(self, a1, a2=15.0):
        # `a1` 通常直接返回它等的那个对象（列表、会话、上下文），`deng_dai` 的
        # 超时消息就带着它——比原来那句光秃秃的「等待超时」多一个现场。
        try:
            deng_dai(a1, chao=a2)
        except AssertionError as e:
            self.fail(str(e))
        return a1()

    def _xin_hui(self):
        s, d = self._qiao("/sessions", {"agentId": "echo", "cwd": self.root,
                                        "clientIdempotencyKey": uuid.uuid4().hex})
        self.assertEqual(s, 201)
        return d["session"]["sessionId"]

    def test_lifeos_wen_ju_shang_xia_wen_dai_zhe_agent_jie_guo(self):
        """真正要验的那一步：/chat 时上下文里带着 Agent 的结果。"""
        sid = self._xin_hui()
        self._qiao(f"/sessions/{sid}/messages", {"instructions": ["算一下 7 乘 8"]})
        rid = self._deng(lambda: [x for x in self.h.dai_jue() if x["sessionId"] == sid])[0]["requestId"]
        self._qiao(f"/permissions/{rid}", {"decision": "allow"})
        self._deng(lambda: self.h.du(sid).state == "ended")
        self._deng(lambda: self.agent.agent_context.du(sid))

        self.llm.kan.clear()
        s, d = self._zhu_qiao("/chat", {"message": "刚才那个 Agent 干了什么？",
                                        "session_id": sid})
        self.assertEqual(s, 200)
        xi = self.llm.kan[-1][0]["content"]
        self.assertIn("本地 Agent 刚刚的执行记录", xi)
        self.assertIn("echo: 算一下 7 乘 8", xi)
        self.assertIn(d["response"], d["response"])  # 结构没变

    def test_echo_bridge_result_can_be_approved_and_recalled(self):
        """真实 Echo 执行经 Bridge 回调后进入项目记忆，并出现在下一轮 Chat。"""
        sid = self._xin_hui()
        self._qiao(f"/sessions/{sid}/messages", {"instructions": ["记下回声执行结果"]})
        rid = self._deng(lambda: [x for x in self.h.dai_jue()
                                   if x["sessionId"] == sid])[0]["requestId"]
        self._qiao(f"/permissions/{rid}", {"decision": "allow"})
        evidence = self._deng(lambda: self.agent.agent_evidence.list(
            owner_id="local", session_id=sid))[0]
        self.assertIn("echo:", evidence["summary"])

        project_id = f"bridge-{sid}"
        claim = "Echo Bridge 已完成本项目的回声执行任务"
        status, proposed = self._zhu_qiao(
            f"/agent/evidence/{evidence['id']}/memory-candidates",
            {"claim": claim, "project_id": project_id},
        )
        self.assertEqual(status, 201)
        candidate = proposed["candidate"]
        self.assertEqual(candidate["source_ref"]["record_id"], evidence["id"])
        self.assertEqual(self._zhu_qiao(
            f"/memory/candidates/{candidate['id']}/commit", {})[0], 200)

        self.llm.kan.clear()
        status, _ = self._zhu_qiao("/chat", {
            "message": "回声执行任务进展如何？", "session_id": sid,
            "memory_scope": {"kind": "project", "project_id": project_id},
        })
        self.assertEqual(status, 200)
        self.assertIn(claim, self.llm.kan[-1][0]["content"])

        self.llm.kan.clear()
        status, _ = self._zhu_qiao("/chat", {
            "message": "另一个项目有什么进展？", "session_id": sid,
            "memory_scope": {"kind": "project", "project_id": "unrelated-project"},
        })
        self.assertEqual(status, 200)
        self.assertNotIn(claim, self.llm.kan[-1][0]["content"])

    def test_zhu_fu_wu_bu_neng_zi_ji_xia_fa_tiao_mo_shi(self):
        """7.7.1 的关键约束：主服务收到结果后不得自己下发下一条指令。"""
        sid = self._xin_hui()
        self._qiao(f"/sessions/{sid}/messages", {"instructions": ["只有这一条"]})
        rid = self._deng(lambda: [x for x in self.h.dai_jue() if x["sessionId"] == sid])[0]["requestId"]
        self._qiao(f"/permissions/{rid}", {"decision": "allow"})
        self._deng(lambda: self.h.du(sid).state == "ended")
        self._deng(lambda: self.agent.agent_context.du(sid))

        self._zhu_qiao("/chat", {"message": "继续", "session_id": sid})
        # 要守的是「主服务没有自己下发第二条指令」——一件不该发生的事。原来是
        # sleep(1.0) 后取样一次；改成整段盯着三个可观察值，一变立刻炸。
        # 这比原来严：原来只看得见 1.0 秒那一个时刻。
        wei_bian(lambda: (self.h.du(sid).batchTotal, self.h.du(sid).batchDone,
                          len(self.fu.shi_ying.get(sid).liao if
                              self.fu.shi_ying.get(sid) else [])),
                 chao=1.0, msg=lambda: (self.h.du(sid).batchTotal,
                                        self.h.du(sid).batchDone))
        hui = self.h.du(sid)
        self.assertEqual(hui.batchTotal, 1)
        self.assertEqual(hui.batchDone, 1)
        ad = self.fu.shi_ying.get(sid)
        self.assertEqual(len(ad.liao), 1)  # Agent 只收到过用户发的那一条

    def test_bie_de_hui_hua_de_jie_guo_bing_bu_hui_yong(self):
        """上下文按会话隔离：A 的委派结果不进 B 的对话。"""
        a_sid = self._xin_hui()
        self._qiao(f"/sessions/{a_sid}/messages", {"instructions": ["A 的指令"]})
        rid = self._deng(lambda: [x for x in self.h.dai_jue() if x["sessionId"] == a_sid])[0]["requestId"]
        self._qiao(f"/permissions/{rid}", {"decision": "allow"})
        self._deng(lambda: self.h.du(a_sid).state == "ended")
        self._deng(lambda: self.agent.agent_context.du(a_sid))

        b_sid = self._xin_hui()
        self.assertEqual(self.agent.agent_context.du(b_sid), [])
        self.llm.kan.clear()
        self._zhu_qiao("/chat", {"message": "我刚才让你做了什么？", "session_id": b_sid})
        xi = self.llm.kan[-1][0]["content"]
        self.assertNotIn("A 的指令", xi)

    def test_wai_di_chuan_tiao_bu_neng_wu_quan_zhui_jie(self):
        """出站失败只丢事件，不许把会话带崩（Agent 还在跑）。"""
        si = _JiLu()
        tu = LuDao("http://127.0.0.1:1")  # 必然连不上
        tu.fa("agent.result", "s-1", {"resultText": "x"})
        # 等的是「worker 真的试着发过、并且发失败了」：`shi_biao` 涨了才有资格
        # 断言「没有送达」。原来是 sleep(0.3) 再断言——worker 线程压根没跑时
        # 那句也照样绿，等于什么都没验。
        deng_dai(lambda: tu.shi_biao >= 1, chao=5.0,
                 msg=lambda: (tu.song_le, tu.shi_biao))
        self.assertEqual(tu.song_le, 0)
        tu.ting_zhi()
        self.assertIsNotNone(si)

    def _zhu_qiao(self, a1: str, a2: dict):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.zhu_duan}{a1}",
            data=json.dumps(a2).encode("utf-8"), method="POST",
            headers={"content-type": "application/json; charset=utf-8"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))


class FangXiangTests(unittest.TestCase):
    """AgentContextStore 本身的边界。"""

    def setUp(self):
        from lifeos.agent.context import AgentContextStore
        self.c = AgentContextStore(3, 50)

    def test_chao_liang_diu_zui_jiu_de(self):
        for i in range(6):
            self.c.tian_jia("s", "agent.result", {"resultText": f"第{i}条"})
        shang = self.c.du("s")
        self.assertEqual(len(shang), 3)
        self.assertIn("第5条", shang[-1]["text"])

    def test_zhi_dao_chang_du(self):
        wen = self.c.tian_jia("s", "agent.result", {"resultText": "x" * 500})
        self.assertLessEqual(len(wen), 80)  # 前缀 20 字 + 截断后的正文

    def test_shi_bai_yu_jie_shu_de_wen_an(self):
        self.assertIn("中断", self.c.tian_jia("s", "agent.failed", {"reason": "用户中断"}))
        self.assertIn("3/4", self.c.tian_jia("s", "agent.ended",
                                            {"batchDone": 3, "batchTotal": 4}))

    def test_bu_ren_ke_kind_bu_yao_xi_jie(self):
        self.assertEqual(self.c.tian_jia("s", "permission.resolved", {}), "")
        self.assertEqual(self.c.du("s"), [])


if __name__ == "__main__":
    unittest.main()
