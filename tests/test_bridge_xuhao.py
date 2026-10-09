"""3.1：transcript 的 from 语义混用。

前端传的是「已处理的最大 streamSeq」，服务端 juan_biao() 却按会话内 seq 过滤。
全局序号恒 ≥ 会话内序号，所以断线重连补拉恒定拿到空数组：
界面停在断线那一刻，而 Agent 还在跑。这是反例清单第 24 条的残留。
"""

import sys
import unittest
import uuid

from lifeos.bridge.events import ZongXian
from lifeos.bridge.session import HuiHua

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class XuhaoTests(unittest.TestCase):
    def setUp(self):
        self.z = ZongXian(uuid.uuid4().hex[:8])
        self.h = HuiHua(self.z)
        self.z.zhan = self.h
        from lifeos.bridge.models import AgentSession
        self.h.jian(AgentSession(sessionId="s-1", agentId="echo", agentLabel="echo",
                                 cwd="."))

    def test_xun_hao_shi_quan_ju_de(self):
        """xuhao 是 Bridge 级全局序号，会被别的会话推着走。

        先让另一个会话占掉一个全局序号，s-1 的消息序号才会与全局序号分叉。
        不加这一句的话两者恰好相等（单会话单进程时必然如此），
        测出来的「相等」什么都证明不了。
        """
        self.z.fa("state", "s-2", state="idle")     # 全局序号走到 1
        self.h.tian_jia("s-1", "assistant", "text", text="一")
        m = self.h.tian_jia("s-1", "assistant", "text", text="二")
        self.assertEqual(m.seq, 2)
        self.assertEqual(m.xuhao, 3)
        self.assertGreater(m.xuhao, m.seq)

    def test_zhen_li_mian_dai_xuhao(self):
        """帧里的 message 必须自带 xuhao，否则快照与消息帧对不上。"""
        zhen = self.z.fa("message", "s-1", message={"messageId": "m", "seq": 1})
        self.assertEqual(zhen["message"]["xuhao"], zhen["streamSeq"])

    def test_juan_biao_an_xuhao_guo_lu(self):
        """补拉窗口用全局序号，与 chao_le() 的越界判定是同一把尺子。"""
        for i in range(3):
            self.h.tian_jia("s-1", "assistant", "text", text=f"第{i}")
        m = self.h.tian_jia("s-1", "assistant", "text", text="第四")
        # 客户端见过 streamSeq = m.xuhao - 1，只该补回最后那一条
        self.assertEqual([x.text for x in self.h.juan_biao("s-1", m.xuhao - 1)],
                         ["第四"])
        self.assertEqual([x.text for x in self.h.juan_biao("s-1", 0)],
                         ["第0", "第1", "第2", "第四"])

    def test_juan_biao_bu_shi_hui_nei_seq(self):
        """这一条专门钉住「按会话内 seq 过滤」是错的。

        前端传的是全局 streamSeq，全局序号恒 ≥ 会话内序号，所以老实现
        （`m.seq > from`）在断线重连补拉时恒定返回空数组——界面停在断线
        那一刻，而 Agent 还在跑。这里把两者的差值做出来，让老实现必然返回空。
        """
        for i in range(3):
            self.h.tian_jia("s-1", "assistant", "text", text=f"第{i}")
        for _ in range(5):                      # 别的会话把全局序号推远
            self.z.fa("state", "s-2", state="idle")
        m = self.h.tian_jia("s-1", "assistant", "text", text="第四")
        from1 = m.xuhao - 1
        self.assertGreater(from1 - m.seq, 0, "两者没分叉，这一场证明不了什么")
        # 新行为：按全局序号补拉，拿得到
        self.assertEqual([x.text for x in self.h.juan_biao("s-1", from1)], ["第四"])
        # 老行为：按会话内 seq 过滤，上面的 from1 一条都比它大，返回空
        self.assertEqual([x.text for x in self.h._xiang["s-1"] if x.seq > from1], [])


if __name__ == "__main__":
    unittest.main()
