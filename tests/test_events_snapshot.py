"""阶段 7 域 E：`snapshot` 有界化与历史按需拉取。

**为什么是这个文件。** `zha_pian()` 原来带全量 `messages`（`quan_liao_xiang()`，
无上限），而 `tunnel.py:457` 与 `tunnel_gw.py:283` 都在单帧超过 `ZUI_DA`（1 MiB）
时**断开隧道**——长会话的症状是反复断开重连。2026-10-02 用户裁定：snapshot 只带
会话元数据 + `pending` + `questions`，**一条消息都不带**，历史全部走 transcript
按需拉。

**判据落在哪。** 前两条守「键在不在」，但真正能分开两种实现的是第三条：
**塞 500 条消息后帧的字节数与塞 1 条时同一量级**。只断言「messages 键没了」的话，
一个把 messages 换成空数组、同时另加一个无界字段的实现照样通过（血泪教训第 5 条）。
取片方向（第 4、5、6 条）成对写：只写一条的话「一律取最早」「一律取末尾」都能过
一半。游标（第 7 条）不许前端自己猜。
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from lifeos.bridge import auth
from lifeos.bridge.events import ZongXian
from lifeos.bridge.http import BridgeServer
from lifeos.bridge.models import AgentSession
from lifeos.bridge.planner_guard import ShenKa
from lifeos.bridge.session import HuiHua
from gong_ju import deng_dai, duan_ke

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _qi(a1: int = 0) -> int:
    """占一个空闲端口再放开。照抄 `tests/test_bridge_transport.py` 的同名函数。"""
    with socket.socket() as s:
        s.bind(("127.0.0.1", a1))
        return s.getsockname()[1]


class ZhaPianTests(unittest.TestCase):
    """快照不再带消息，且字节数与会话长度无关（不依赖 HTTP）。"""

    def setUp(self):
        self.z = ZongXian(uuid.uuid4().hex[:8])
        self.h = HuiHua(self.z)
        self.z.zhan = self.h
        self.h.jian(AgentSession(sessionId="s-1", agentId="echo", agentLabel="echo",
                                 cwd=str(Path.cwd())))

    def _tiao(self, a1: int) -> None:
        for i in range(a1):
            self.h.tian_jia("s-1", "assistant", "text", text=f"第{i}条" * 8)

    def test_zha_pian_bu_dai_xiao_xi(self):
        self._tiao(3)
        zha = self.z.zha_pian()
        self.assertNotIn("messages", zha, "快照还在带消息")
        # 会话、挂起项这两个键必须还在——它们是快照真正的职责
        self.assertIn("sessions", zha)
        self.assertIn("pending", zha)
        self.assertIn("questions", zha)

    def test_duibu_de_zha_pian_ye_bu_dai_xiao_xi(self):
        """`duibu` 自己拼了一个 `{"type": "snapshot", **zha_pian()}`，是第二条独立路径。

        改 `zha_pian()` 会自动带上这里，但两条路径是两行代码，各改各的——
        补发帧走的就是 `duibu`，漏掉它的话断线重连那一帧仍然带全量消息。
        """
        self._tiao(3)
        zhen = self.z.duibu(None)
        self.assertEqual(zhen[0]["type"], "snapshot")
        self.assertNotIn("messages", zhen[0], "补发路径的快照还在带消息")

    def test_zha_pian_bie_de_chang_shu(self):
        """判据落在字节数上：500 条与 1 条的帧大小差 < 4 KiB。

        这条才是真正分开两种实现的那条。前面两条只说「键不在了」，
        一个把 `messages` 换成 `[]` 再另加一个无界字段的实现照样过。
        """
        self._tiao(1)
        xiao = len(json.dumps(self.z.zha_pian(), ensure_ascii=False))
        self._tiao(499)
        da = len(json.dumps(self.z.zha_pian(), ensure_ascii=False))
        self.assertLess(da - xiao, 4096,
                        f"帧随会话长度涨了 {da - xiao} 字节（{xiao} → {da}）："
                        "有字段仍然无界")


class JuanBiaoTests(unittest.TestCase):
    """`juan_biao` 的取片方向。首屏取末尾、增量取最早、向上翻取末尾。"""

    def setUp(self):
        self.z = ZongXian(uuid.uuid4().hex[:8])
        self.h = HuiHua(self.z)
        self.z.zhan = self.h
        self.h.jian(AgentSession(sessionId="s-1", agentId="echo", agentLabel="echo",
                                 cwd=str(Path.cwd())))
        for i in range(10):
            self.h.tian_jia("s-1", "assistant", "text", text=f"第{i}")

    def _xuhao(self) -> list[int]:
        return [m.xuhao for m in self.h._xiang["s-1"]]

    def test_juan_biao_zeng_liang_qie_pian(self):
        """带 `from`：取 `xuhao > from` 里**最早**的 N 条。

        为什么增量必须取最早：一次断线进来 200 条而 limit 是 50，取末尾会把中间
        150 条跳过去——前端既没拿到也不知道漏了，界面上凭空少一大段对话。
        变异：把 `[:a3]` 改成 `[-a3:]`，这条必须红。
        """
        all1 = self._xuhao()
        from1 = all1[1]  # 已收到第 2 条
        # 分岔判据的一半：这批必须是**最早**的 3 条（#3#4#5），不是末尾 3 条
        self.assertEqual([m.text for m in self.h.juan_biao("s-1", from1, 3)],
                         ["第2", "第3", "第4"])

    def test_juan_biao_wei_bu_qie_pian(self):
        """带 `before`：取 `xuhao < before` 里**末尾**的 N 条（向上翻）。

        变异：把 `[-a3:]` 改成 `[:a3]`，这条必须红。
        """
        all1 = self._xuhao()
        self.assertEqual([m.text for m in self.h.juan_biao("s-1", 0, 3, all1[6])],
                         ["第3", "第4", "第5"])

    def test_juan_biao_shou_ping_qie_pian(self):
        """首屏（`from` / `before` 都缺省）：取**末尾** N 条。

        单独拎出来是因为首屏是用户 99% 走的那条路径，判据要独立落在这上面：
        打开一条 500 条的长会话，看的是最近在说什么，不是会话开头。
        """
        self.assertEqual([m.text for m in self.h.juan_biao("s-1", 0, 4)],
                         ["第6", "第7", "第8", "第9"])

    def test_juan_biao_mo_xing_ren_wei_pian(self):
        """不传 limit 时保持全量行为——守住「加参数不破坏既有调用点」。

        顺带钉住下界是**排他**的（`xuhao > from`）：`from` 就是「已收到的最大
        xuhao」，把这条再发一遍就是重复渲染。变异 `>` 改 `>=` 时这条必须红。
        """
        self.assertEqual(len(self.h.juan_biao("s-1")), 10)
        self.assertEqual(len(self.h.juan_biao("s-1", 0)), 10)
        self.assertEqual([m.text for m in self.h.juan_biao("s-1", self._xuhao()[9])], [])

    def test_juan_biao_qie_pian_bi_pian_duo_shao(self):
        """`from` 与 `before` 同时给：窗口取交集，取片跟 `before` 走。"""
        all1 = self._xuhao()
        # 窗口 = (第3条的 xuhao, 第7条的 xuhao) 开区间 = 第4#5#6条。limit=5 大于
        # 窗口本身，取末尾就是全部三条——要验证的是「limit 不越出窗口」。
        self.assertEqual([m.text for m in self.h.juan_biao("s-1", all1[2], 5, all1[6])],
                         ["第3", "第4", "第5"])
        # limit=2 时必须取窗口里的**末尾**两条（跟 before 走，不是跟 from 走）
        self.assertEqual([m.text for m in self.h.juan_biao("s-1", all1[2], 2, all1[6])],
                         ["第4", "第5"])


class YuanWenTest(unittest.TestCase):
    """`_yuan_wen`：limit 钳制、游标出参、非法参数的处置。真 HTTP。"""

    @classmethod
    def setUpClass(cls):
        cls.z = ZongXian(uuid.uuid4().hex[:8])
        cls.h = HuiHua(cls.z)
        cls.z.zhan = cls.h
        cls.g = ShenKa([str(Path(__file__).resolve().parent.parent)])
        cls.token = auth.shengcheng()
        cls.duan = _qi()
        cls.fu = BridgeServer(("127.0.0.1", cls.duan), cls.z, cls.h, cls.g, cls.token)
        threading.Thread(target=cls.fu.serve_forever, daemon=True).start()
        deng_dai(lambda: duan_ke(cls.duan), chao=5.0, msg=f"端口 {cls.duan} 连不上")
        cls.sid = "s-yw-1"
        cls.h.jian(AgentSession(sessionId=cls.sid, agentId="echo", agentLabel="echo",
                                cwd=str(Path(__file__).resolve().parent.parent)))

    @classmethod
    def tearDownClass(cls):
        cls.fu.shutdown()
        cls.fu.server_close()

    def setUp(self):
        self.h.shan(self.sid)
        self.h.jian(AgentSession(sessionId=self.sid, agentId="echo", agentLabel="echo",
                                 cwd=str(Path(__file__).resolve().parent.parent)))
        for i in range(10):
            self.h.tian_jia(self.sid, "assistant", "text", text=f"第{i}")

    def _get(self, a1: str):
        u = f"http://127.0.0.1:{self.duan}{a1}"
        u += ("&" if "?" in u else "?") + f"token={self.token}"
        try:
            with urllib.request.urlopen(urllib.request.Request(u), timeout=5) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def _quan_wen(self, a1: str = "") -> tuple[int, dict]:
        return self._get(f"/sessions/{self.sid}/transcript{a1}")

    def test_juan_biao_you_biao_chu_can(self):
        """响应带三个游标，`nextFrom` = 末条 xuhao，`prevBefore` = 首条 xuhao。

        前端不许自己猜游标：猜错了就是重复渲染或漏消息。
        """
        s, d = self._quan_wen()
        self.assertEqual(s, 200, d)
        for k in ("nextFrom", "prevBefore", "hasMore"):
            self.assertIn(k, d, f"响应缺游标 {k}")
        self.assertEqual(d["nextFrom"], d["messages"][-1]["xuhao"])
        self.assertEqual(d["prevBefore"], d["messages"][0]["xuhao"])
        self.assertEqual([m["text"] for m in d["messages"]], [f"第{i}" for i in range(10)])
        # 10 条一条没少给（limit 50 > 10），两头都翻不动了
        self.assertFalse(d["hasMore"], "整批都给完了还说没给完")

    def test_juan_biao_qie_pian_le_has_more(self):
        """截断了才 hasMore=true，且它区分「往后还有」与「往前还有」。

        首屏给末尾 50 条时，后面（更早）还有——这是向上翻要用的那个信号。
        """
        for i in range(80):
            self.h.tian_jia(self.sid, "assistant", "text", text=f"多{i}")
        s, d = self._quan_wen()
        self.assertEqual(s, 200)
        self.assertEqual(len(d["messages"]), 50)
        self.assertTrue(d["hasMore"], "只给了末尾 50 条，前面还有 40 条没给")
        # 顺着 hasMore 一直翻到顶，最后一批必须 hasMore=false
        zha = d["prevBefore"]
        for _ in range(10):
            s, d2 = self._quan_wen(f"?before={zha}&limit=50")
            if not d2["messages"]:
                break
            zha = d2["prevBefore"]
        self.assertFalse(d2["hasMore"], "翻到顶了还报 hasMore")

    def test_yuan_wen_xian_zhi_gao_liang(self):
        """limit 默认 50、钳到 [1, 50]。传 99999 只给 50，不报错也不放行。

        钳制是本计划自己加的（`cc-connect` 的 `histLimit` 没有这层），
        少写它等于把 `snapshot` 的爆点原样搬到 HTTP 响应上。
        """
        for i in range(80):
            self.h.tian_jia(self.sid, "assistant", "text", text=f"多{i}")
        s, d = self._quan_wen()
        self.assertEqual(s, 200)
        self.assertEqual(len(d["messages"]), 50, "默认值不是 50")

        s, d = self._quan_wen("?limit=99999")
        self.assertEqual(s, 200, "超大的 limit 报错了")
        self.assertEqual(len(d["messages"]), 50, "limit 没被钳到 50")

        s, d = self._quan_wen("?limit=3")
        self.assertEqual(len(d["messages"]), 3)
        self.assertEqual([m["text"] for m in d["messages"]], ["多77", "多78", "多79"])

    def test_yuan_wen_fei_he_fa_limit_an_que_dian(self):
        """非法 limit 按默认 50 处理，**不报 400**。

        这是补拉通道：前端网络抖动重试时不该整个失败。
        """
        for x in ("limit=abc", "limit=0", "limit=-5", "limit="):
            s, d = self._quan_wen(f"?{x}")
            self.assertEqual(s, 200, f"{x} 让整个补拉失败了：{d}")
            self.assertEqual(len(d["messages"]), 10, f"{x} 没按默认值 50 处理")

    def test_yuan_wen_fei_zheng_shu_you_xiang_400(self):
        """`from` / `before` 非整数仍回 400——那是调用方算错了游标，与重试无关。"""
        for x in ("from=abc", "before=abc"):
            s, d = self._quan_wen(f"?{x}")
            self.assertEqual(s, 400, f"{x} 没回 400：{d}")

    def test_yuan_wen_wei_bu_xiang_shang_hua(self):
        """向上翻：`before` 排他，取窗口里末尾 N 条。"""
        all1 = [m.xuhao for m in self.h._xiang[self.sid]]
        s, d = self._quan_wen(f"?before={all1[6]}&limit=3")
        self.assertEqual(s, 200, d)
        self.assertEqual([m["text"] for m in d["messages"]], ["第3", "第4", "第5"])
        self.assertEqual(d["prevBefore"], all1[3])
        self.assertEqual(d["nextFrom"], all1[5])

    def test_yuan_wen_kong_pian_chu_can(self):
        """空列表：nextFrom 回请求的 from，prevBefore 回 null。"""
        last = max(m.xuhao for m in self.h._xiang[self.sid])
        s, d = self._quan_wen(f"?from={last}")
        self.assertEqual(s, 200, d)
        self.assertEqual(d["messages"], [])
        self.assertEqual(d["nextFrom"], last)
        self.assertIsNone(d["prevBefore"])
        self.assertFalse(d["hasMore"])

    def test_yuan_wen_chao_jie_409_bu_dong(self):
        """`from` 越界的 409 reset_required 是既有正确行为，任务 7 不许碰。"""
        s, d = self._quan_wen("?from=999999")
        self.assertEqual(s, 409, d)
        self.assertEqual(d["error"]["code"], "reset_required")


if __name__ == "__main__":
    unittest.main()
