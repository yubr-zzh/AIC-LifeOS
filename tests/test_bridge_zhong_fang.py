"""5：跨重启重放（R3 的另一半）。

进程内那一半由 PendingEntry.resolved 挡着；这一半挡 Bridge 真的死过一次。
退出条件（方案 12.6）就是它：强杀 → 重启 → 已批准的命令不会被重新提问。
"""

import asyncio
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from lifeos.bridge.arbiter import ShenQing, wen_hash
from lifeos.bridge.cun import Cun
from lifeos.bridge.events import ZongXian
from lifeos.bridge.models import AgentSession
from lifeos.bridge.planner_guard import ShenKa
from lifeos.bridge.session import HuiHua

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class ZhongFangTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = str(Path(__file__).resolve().parent.parent)
        self.z = ZongXian(uuid.uuid4().hex[:8])
        self.h = HuiHua(self.z)
        self.z.zhan = self.h
        self.h.jian(AgentSession(sessionId="s-1", agentId="echo",
                                 agentLabel="echo", cwd=self.root))
        self.q = ShenQing(self.h, self.z, ShenKa([self.root]))

    def tearDown(self):
        self.h.ting_zhi()
        self.dir.cleanup()

    def _xin_q(self):
        """换一个 ShenQing = 换一个进程。落盘文件共用同一个目录。"""
        return ShenQing(self.h, self.z, ShenKa([self.root]), 600.0, Cun(Path(self.dir.name)))

    def _ling(self, a1):
        fu = asyncio.new_event_loop().create_future()
        d = a1.jia("s-1", "echo", "toolu_1", "Bash", {"command": "ls -l"}, fu)
        return fu, d

    def test_shou_kou_luo_pan(self):
        """先让第一个「进程」收口一次，decisions.jsonl 里必须有一条。"""
        q1 = self._xin_q()
        fu, d = self._ling(q1)
        q1.shou(d, "user_allow")
        ji = Cun(Path(self.dir.name)).jue_qu("s-1", "toolu_1")
        self.assertEqual(len(ji), 1)
        self.assertEqual(ji[0]["decision"], "user_allow")
        self.assertEqual(ji[0]["inputHash"], wen_hash(d.toolInput))

    def test_zhong_fang_ming_zhong_bu_tan_ka_pian(self):
        q1 = self._xin_q()
        fu, d = self._ling(q1)
        q1.shou(d, "user_allow")
        # 第二个进程：挂起项是空的（_pending 不落盘）
        q2 = self._xin_q()
        self.assertEqual(q2._pending, {})
        fu2, d2 = self._ling(q2)
        self.assertTrue(fu2.done(), "命中重放必须立即 resolve")
        self.assertEqual(d2.decision, "user_allow")
        self.assertEqual(q2._pending, {}, "重放不许进 _pending")
        self.assertEqual(len(self.h.dai_jue()), 0, "重放不许弹卡片")

    def test_zhong_fang_guang_bo_replayed(self):
        q1 = self._xin_q()
        fu, d = self._ling(q1)
        q1.shou(d, "user_allow")
        q2 = self._xin_q()
        with self.z.suo:
            self.z.huan.clear()
        self._ling(q2)
        zhen = [z for _, z in self.z.huan if z["type"] == "permission_resolved"]
        self.assertEqual(len(zhen), 1)
        self.assertTrue(zhen[0]["replayed"])
        self.assertEqual(zhen[0]["decision"], "user_allow")

    def test_auto_deny_bu_sheng_ge(self):
        """5.3：重放只还原「用户当时的判断」，不把自动拒绝改写成允许。"""
        q1 = self._xin_q()
        fu, d = self._ling(q1)
        q1.shou(d, "auto_deny", a3="等待审批超时", a6="timeout")
        q2 = self._xin_q()
        fu2, d2 = self._ling(q2)
        self.assertTrue(fu2.done())
        self.assertEqual(d2.decision, "auto_deny")
        self.assertEqual(d2.autoReason, "timeout")

    def test_inputHash_bu_fu_bu_chong_fang(self):
        """同一个 tool_use_id 复用在不同命令上时，绝不能被当成已批准。"""
        q1 = self._xin_q()
        fu, d = self._ling(q1)
        q1.shou(d, "user_allow")
        q2 = self._xin_q()
        fu2 = asyncio.new_event_loop().create_future()
        d2 = q2.jia("s-1", "echo", "toolu_1", "Bash",
                    {"command": "rm -rf ./build"}, fu2)
        self.assertFalse(fu2.done(), "inputHash 不符必须正常弹卡片")
        self.assertEqual(len(q2._pending), 1)
        self.assertEqual(len(self.h.dai_jue()), 1)
        self.assertEqual(d2.decision, None)

    def test_duan_ju_hou_chong_fang_bu_ming_zhong(self):
        """5.4 的边界：Bridge 在收到收口请求前就死了，重启后重新问——
        宁可多问一次，不可少问一次。"""
        q1 = self._xin_q()
        fu, d = self._ling(q1)   # 只弹卡片，不收口
        q2 = self._xin_q()
        fu2 = asyncio.new_event_loop().create_future()
        q2.jia("s-1", "echo", "toolu_1", "Bash", {"command": "ls -l"}, fu2)
        self.assertFalse(fu2.done())
        self.assertEqual(len(q2._pending), 1)

    def test_duan_ju_hou_de_jue_ding_ye_neng_chong_fang(self):
        """deny 基线命中的决定也落盘，重启后同样的调用仍然被拒。

        这条同时验两件事：一是 deny 基线的决定进得了重放索引，二是它的
        `sessionId` 得是真正的会话 id——`shibai()` 原来把 cwd 当 sessionId 传，
        写进 decisions.jsonl 的键就是一条路径，重放永远查不到。
        """
        q1 = self._xin_q()
        fu = asyncio.new_event_loop().create_future()
        q1.shibai("Write", "s-1", {"file_path": "C:/Windows/System32/x"}, self.root, fu)
        self.assertTrue(fu.done())
        ji = Cun(Path(self.dir.name)).jue_qu("s-1")
        self.assertEqual(len(ji), 1, "deny 基线的决定没落盘")
        self.assertEqual(ji[0]["decision"], "auto_deny")
        self.assertEqual(ji[0]["autoReason"], "deny_baseline")
        # 换一个「进程」，同样的调用仍然被拒
        q2 = self._xin_q()
        self.assertEqual(len(q2.jue_ji), 1)
        fu2 = asyncio.new_event_loop().create_future()
        q2.shibai("Write", "s-1", {"file_path": "C:/Windows/System32/x"}, self.root, fu2)
        self.assertTrue(fu2.done())
        self.assertEqual(q2._pending, {})


if __name__ == "__main__":
    unittest.main()
