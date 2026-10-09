"""6：懒恢复 + 落盘时机。

两条要守住的性质：
1. **恢复出来的会话不能立刻被闲置看门狗关掉。** 落盘的 updatedAt 是昨天的，
   重置后 8.7 的闲置超时（30 分钟）会立刻判它超时并摘掉会话——
   用户重连看到的是会话凭空消失。
2. **重启后新分配的 seq 不与历史撞号。** 撞号会让前端按 (seq, messageId)
   定位替换时顶掉旧消息。
"""

import asyncio
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from lifeos.bridge.cun import Cun
from lifeos.bridge.events import ZongXian
from lifeos.bridge.http import BridgeServer
from lifeos.bridge.models import AgentMessage, AgentSession, guo_lu1
from lifeos.bridge.planner_guard import ShenKa
from lifeos.bridge.session import HuiHua, LUO_PAN

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class HuiFuTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.gen = Path(self.dir.name)
        self.root = str(Path(__file__).resolve().parent.parent)
        self.z = ZongXian(uuid.uuid4().hex[:8])
        self.h = HuiHua(self.z)
        self.z.zhan = self.h
        self.cun = Cun(self.gen)
        self.h.cun = self.cun
        self.h.jian(AgentSession(sessionId="s-1", agentId="echo", agentLabel="echo",
                                 cwd=self.root, claudeSessionId="cs-1",
                                 state="working", batchTotal=2, batchDone=1))

    def tearDown(self):
        self.h.ting_zhi()
        self.dir.cleanup()

    def test_jian_hui_jiu_luo_pan(self):
        self.assertTrue(self.cun.hui_wen.exists())
        hui = self.cun.du_hui()[0]
        self.assertEqual(hui["sessionId"], "s-1")
        self.assertEqual(hui["claudeSessionId"], "cs-1")

    def test_geng_geng_xin_luo_pan(self):
        self.h.geng("s-1", "ended", "batch_done")
        self.assertEqual(self.cun.du_hui()[0]["state"], "ended")

    def test_message_bai_ming_dan(self):
        """spec 4.4 的表。thinking 与 chunk 明文永不落盘。"""
        for kind in ("tool_use", "tool_result", "text"):
            self.h.tian_jia("s-1", "assistant", kind, text="x")
        for kind in ("thinking", "error", "rate_limit", "context_reset"):
            self.h.tian_jia("s-1", "assistant", kind, text="y")
        lei = {m["kind"] for m in self.cun.xiang_qu("s-1")}
        self.assertEqual(lei, {"tool_use", "tool_result", "text"})
        self.assertTrue(LUO_PAN >= lei)

    def test_hui_fu_bu_bei_xian_zhi_guan_diao(self):
        """恢复时把 updatedAt 重置为当前时刻，否则 8.7 的闲置看门狗
        一启动就会把这个会话关掉。"""
        for rec in self.cun.du_hui():
            rec["updatedAt"] = 1  # 1970 年
        from lifeos.bridge.run import hui_fu
        hui_fu(self.gen, self.h, self.cun)
        s = self.h.du("s-1")
        self.assertIsNotNone(s)
        self.assertGreater(s.updatedAt, 1_000_000_000_000)
        self.assertEqual(s.state, "idle")
        self.assertFalse(s.alive)

    def test_hui_fu_seq_bu_zhuang_hao(self):
        self.h.tian_jia("s-1", "assistant", "text", text="旧")
        self.h.tian_jia("s-1", "assistant", "text", text="旧二")
        from lifeos.bridge.run import hui_fu
        hui_fu(self.gen, self.h, self.cun)
        self.assertEqual(self.h._xu["s-1"], 2)
        m = self.h.tian_jia("s-1", "assistant", "text", text="新")
        self.assertEqual(m.seq, 3)
        self.assertEqual([x.text for x in self.h.juan_biao("s-1", 0)],
                         ["旧", "旧二", "新"])

    def test_hui_fu_bu_fa_zhen(self):
        """恢复过程不发任何 SSE 帧——此刻还没有订阅者。"""
        with self.z.suo:
            self.z.huan.clear()
        from lifeos.bridge.run import hui_fu
        hui_fu(self.gen, self.h, self.cun)
        self.assertEqual(list(self.z.huan), [])

    def test_guo_lu1_diao_diao_wei_zhi_zi_duan(self):
        rec = {"sessionId": "s-1", "evil": 1, "alive": True}
        self.assertEqual(guo_lu1(AgentSession, rec),
                         {"sessionId": "s-1", "alive": True})

    def test_shou_kou_luo_pan_bing_ke_chong_fang(self):
        """Task 8 跳过的那个用例：收口 → 落盘 → 重放命中。"""
        token = "t" * 64
        fu = BridgeServer(("127.0.0.1", 0), self.z, self.h,
                          ShenKa([self.root]), token, self.cun)
        q = fu.shen_qing
        fu2 = asyncio.new_event_loop().create_future()
        d = q.jia("s-1", "echo", "toolu_1", "Bash", {"command": "ls"}, fu2)
        q.shou(d, "user_allow")
        ji = self.cun.jue_qu("s-1", "toolu_1")
        self.assertEqual(len(ji), 1)
        self.assertEqual(ji[0]["decision"], "user_allow")
        fu.server_close()

    def test_hui_fu_ke_du_hui_shao_xi(self):
        """落盘文件被写坏时，Bridge 照样起得来。"""
        self.cun.hui_wen.write_text("半行 json", encoding="utf-8")
        from lifeos.bridge.run import hui_fu
        self.assertEqual(hui_fu(self.gen, self.h, self.cun)["sessions"], 1)


if __name__ == "__main__":
    unittest.main()
