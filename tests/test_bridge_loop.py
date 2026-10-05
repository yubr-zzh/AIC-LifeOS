"""端到端回路测试：Agent 挂起 → 用户在 HTTP 上决定 → Agent 恢复。

这条链路上有真实的并发：回合跑在 `_pao` 线程的 event loop 里，
审批请求走 HTTP 线程，收口在另一个线程发生。所以这个测试同时也在验证
`arbiter._jiao_hui` 的跨线程交回是否正确——如果那里写错，
表现为「用户点了允许，Agent 一直挂着不动，最后超时自动拒绝」。
"""

import json
import socket
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from lifeos.bridge import auth
from lifeos.bridge.events import ZongXian
from lifeos.bridge.http import BridgeServer
from lifeos.bridge.planner_guard import ShenKa
from lifeos.bridge.session import HuiHua
from gong_ju import deng_dai, wei_bian

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _qi() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LoopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.z = ZongXian(uuid.uuid4().hex[:8])
        cls.h = HuiHua(cls.z)
        cls.z.zhan = cls.h
        cls.token = auth.shengcheng()
        cls.duan = _qi()
        cls.root = str(Path(__file__).resolve().parent.parent)
        cls.fu = BridgeServer(("127.0.0.1", cls.duan), cls.z, cls.h,
                              ShenKa([cls.root]), cls.token)
        threading.Thread(target=cls.fu.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.fu.shutdown()
        cls.fu.server_close()

    def _dui(self, a1: str, a2: dict | None = None):
        shu = json.dumps(a2 or {}).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.duan}{a1}", data=shu, method="POST",
            headers={"content-type": "application/json", "x-bridge-token": self.token})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def _song(self, a1: str, a2: bytes, a3=None):
        """发一次 POST，返回 (状态码, 响应正文)。

        a2 是请求体，**分两段**发：先发头，`sleep` 一下，再发体。
        `urllib.request` 一次发完的话两段会被并进同一个 TCP 段，body 字节顺手
        进了服务端 rfile 的缓冲区，就复现不出这条 bug——头与体分两段到达正是
        浏览器 fetch 的常态。

        a3 为 None 时自建连接（用完即关）；传连接进来则复用它。
        """
        s = a3 or socket.create_connection(("127.0.0.1", self.duan), timeout=10)
        try:
            s.sendall((f"POST {a1} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                       f"content-type: application/json\r\n"
                       f"content-length: {len(a2)}\r\n"
                       f"x-bridge-token: {self.token}\r\n\r\n").encode())
            # **这一段 sleep 是刺激的一部分，不是测试在等什么**：它逼
            # body 落到读头之后才到，复现「头与体分两段到达」这个浏览器常态。
            # 去掉它，这条 bug 就复现不出来了。
            time.sleep(0.02)
            s.sendall(a2)
            # Bridge 是 HTTP/1.1 keep-alive，响应后不关连接：按 content-length
            # 读满就收工，读到 EOF 会一直等下去。
            tou = b""
            while b"\r\n\r\n" not in tou:
                yi = s.recv(65536)
                if not yi:
                    break
                tou += yi
            _, _, yu = tou.partition(b"\r\n\r\n")
            n = 0
            for line in tou.split(b"\r\n")[1:]:
                if line.lower().startswith(b"content-length:"):
                    n = int(line.split(b":", 1)[1])
            while len(yu) < n:
                yi = s.recv(65536)
                if not yi:
                    break
                yu += yi
            return int(tou.split(b" ")[1]), yu
        finally:
            if a3 is None:
                s.close()

    def test_guan_bi_dai_body_bu_duan_lian_jie(self):
        """`_guan_bi` 从不读请求体，那几个字节就留在 socket 收缓冲里。

        Bridge 是 HTTP/1.1 keep-alive，响应后**不关连接**，所以这里的症状不是
        RST，而是**下一个请求被这段残留顶掉**：服务端把它当请求行读，得到 400
        再关连接。同一条连接上连发两次 close，第二次必须仍是合法的 404
        （会话已关），不能是 400。

        `_song` 强制头与体分两段发，所以这条是**确定性**触发。
        """
        cuo = []
        for i in range(5):
            sid = self._xin_hui(f"loop-duan-{i}")
            s = socket.create_connection(("127.0.0.1", self.duan), timeout=10)
            try:
                st1, _ = self._song(f"/sessions/{sid}/close", b'{"a":"b"}', s)
                st2, _ = self._song(f"/sessions/{sid}/close", b"{}", s)
            except OSError as exc:
                cuo.append(f"第 {i} 次连接被断：{exc!r}")
                continue
            finally:
                s.close()
            if st1 != 200:
                cuo.append(f"第 {i} 次首次 close 状态码 {st1}")
            if st2 != 404:
                cuo.append(f"第 {i} 次复用连接第二次 close 状态码 {st2}（应为 404）")
        self.assertEqual(cuo, [])

    def _chao_xian(self, a1: str, a2: str) -> str:
        """声明 2 MiB、正文只发 4 KiB 就不发了，返回状态码。

        **只发 4 KiB 是这条的关键**：缓冲的实现会卡在 `rfile.read` 上等剩下的
        字节，压根回不了响应。所以「等到了响应」本身就是「没缓冲」的证据，
        状态码则钉住超限时每条路径各自的老行为。
        """
        s = socket.create_connection(("127.0.0.1", self.duan), timeout=3)
        try:
            s.sendall((f"POST {a1} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                       f"content-type: application/json\r\n"
                       f"content-length: {2 << 20}\r\n{a2}\r\n").encode())
            s.sendall(b" " * 4096)
            fan = b""
            while b"\r\n\r\n" not in fan:
                yi = s.recv(65536)
                if not yi:
                    break
                fan += yi
            return fan.split(b" ")[1].decode() if fan else "等不到响应"
        except OSError as exc:
            return f"等不到响应（{type(exc).__name__}）"
        finally:
            s.close()

    def test_chao_xian_qing_qiu_ti_bu_huan_chong(self):
        """超 1 MiB 的体入口不缓冲，各路径的状态码与修复前一致。

        入口统一读体之后 `_du_wan` 里的 `rfile.read(self._chang())` 没有上限：
        未认证的客户端在认证之前就能让服务端按它声明的大小分配内存
        （ThreadingHTTPServer 每连接一线程），1 MiB 也从内存上限退化成事后提醒。

        修法不是在这里抛 413——那会把认证闸门挡在后面，未认证的超限请求从
        401 变成 413。超限时**不读、不缓存**，让每条路径自己落回修复前的老
        行为：未认证 → `_shou_quan` 的 401；已认证 → `_du_json` 的 413。
        """
        self.assertEqual(self._chao_xian("/sessions", ""), "401")
        self.assertEqual(self._chao_xian("/sessions", f"x-bridge-token: {self.token}\r\n"), "413")

    def _deng(self, a1: str, a2: float = 12.0):
        """轮询直到条件成立。返回条件给出的那个对象（现场一起带出）。"""
        try:
            deng_dai(a1, chao=a2)
        except AssertionError as e:
            self.fail(f"等待超时（{a2}s）：{e}")
        return a1()

    def _wo_de(self, a1: str) -> list:
        """只看本会话的挂起项。各测试共用一个 Bridge，别人的残留不算。"""
        return [x for x in self.h.dai_jue() if x["sessionId"] == a1]

    def _wo_de_wen(self, a1: str) -> list:
        return [x for x in self.h.dai_wen() if x["sessionId"] == a1]

    def _xin_hui(self, a1: str):
        s, d = self._dui("/sessions", {"agentId": "echo", "cwd": self.root,
                                       "clientIdempotencyKey": uuid.uuid4().hex})
        self.assertEqual(s, 201)
        return d["session"]["sessionId"]

    def test_wan_zheng_hui_luo(self):
        """两条指令：第一条要审批，第二条要提问，两处都由用户点按后恢复。"""
        sid = self._xin_hui("loop-1")
        s, _ = self._dui(f"/sessions/{sid}/messages", {"instructions": ["第一条指令", "第二条指令"]})
        self.assertEqual(s, 202)

        # 1. 挂起在审批上
        dai = self._deng(lambda: self._wo_de(sid))
        self.assertEqual(len(dai), 1)
        rid = dai[0]["requestId"]
        self.assertEqual(dai[0]["toolName"], "Bash")
        self.assertFalse(dai[0]["inputTruncated"])
        self._deng(lambda: self.h.du(sid).state == "attention")

        # 2. 用户点「允许」
        s, d = self._dui(f"/permissions/{rid}", {"decision": "allow"})
        self.assertEqual(s, 200)
        self.assertEqual(d["decision"], "user_allow")

        # 3. Agent 真的恢复了，并继续跑到第二条指令的提问上
        wen = self._deng(lambda: self._wo_de_wen(sid))
        self.assertEqual(len(wen), 1)
        self._deng(lambda: self.h.du(sid).state == "waiting_input")

        # 4. 用户回答提问
        qid = wen[0]["questionId"]
        s, d = self._dui(f"/questions/{qid}",
                         {"answers": [{"questionId": "q1", "values": ["B 直接写代码"]}]})
        self.assertEqual(s, 200)
        self.assertEqual(d["state"], "answered")

        # 5. 整批跑完，会话 ended
        self._deng(lambda: self.h.du(sid).state == "ended")
        hui = self.h.du(sid)
        self.assertEqual(hui.batchDone, 2)
        self.assertEqual(hui.batchTotal, 2)
        self.assertEqual(hui.turnCount, 2)

        # 6. 适配器侧确实拿到了两个结果（不是被丢弃了）
        ad = self.fu.shi_ying.get(sid)
        self.assertIsNotNone(ad)
        self.assertEqual(len(ad.jie_da), 2)
        self.assertIn("B 直接写代码", ad.jie_da[1])  # 答案以 deny+message 回传

    def test_jue_ding_shou_dao_le_chen_dian_zhong_zhi(self):
        """用户点「拒绝」时，Agent 收到的是拒绝，回合继续走到下一条。"""
        sid = self._xin_hui("loop-2")
        self._dui(f"/sessions/{sid}/messages", {"instructions": ["第一条指令", "第二条指令"]})
        rid = self._deng(lambda: self._wo_de(sid))[0]["requestId"]
        s, d = self._dui(f"/permissions/{rid}", {"decision": "deny", "message": "这条不许跑"})
        self.assertEqual(s, 200)
        self.assertEqual(d["decision"], "user_deny")
        wen = self._deng(lambda: self._wo_de_wen(sid))
        self.assertEqual(len(wen), 1)
        ad = self.fu.shi_ying.get(sid)
        self.assertIn("这条不许跑", ad.jie_da[0])

    def test_jue_ding_liu_guo_le_que_ting_bu_le(self):
        """断连不 resolve 任何挂起的审批（方案 8.4 的 R1）。"""
        sid = self._xin_hui("loop-3")
        self._dui(f"/sessions/{sid}/messages", {"instructions": ["第一条指令"]})
        self._deng(lambda: self._wo_de(sid))
        # 先等状态落到 attention 再取基线：否则 `wei_bian` 会把「状态的正常
        # 推进」当成变化，红得没有意义。
        deng_dai(lambda: self.h.du(sid).state == "attention", chao=8.0,
                 msg=lambda: self.h.du(sid).state)
        # 会话仍挂着，没有被自动拒绝。这是「不该发生的事」：原来 sleep(1.0)
        # 后取样一次，改成整段盯着挂起数与状态，一变立刻炸。
        wei_bian(lambda: (len(self._wo_de(sid)), self.h.du(sid).state), chao=1.0,
                 msg=lambda: self._wo_de(sid))
        self.assertEqual(len(self._wo_de(sid)), 1)
        self.assertEqual(self.h.du(sid).state, "attention")

    def test_ting_luo_hou_hui_yuan_sheng_de_zhong_zhi(self):
        """中断后，后续指令不再执行。"""
        sid = self._xin_hui("loop-4")
        self._dui(f"/sessions/{sid}/messages", {"instructions": ["第一条指令", "第二条指令", "第三条指令"]})
        self._deng(lambda: self._wo_de(sid))
        s, _ = self._dui(f"/sessions/{sid}/interrupt")
        self.assertEqual(s, 200)
        self._deng(lambda: self.h.du(sid).state in ("idle", "ended"), a2=8.0)
        hui = self.h.du(sid)
        self.assertLess(hui.batchDone, 3)  # 后续指令被停掉
        ad = self.fu.shi_ying.get(sid)
        self.assertLess(len(ad.liao), 3)

    def test_shen_pi_fang_xing_hou_zhuang_tai_hui_dao_working(self):
        """放行之后必须回到 working。

        停在 attention 上的话，界面一直显示「等你操作」而 Agent 实际在跑工具，
        而且 8.7 的停滞超时只认 working/thiming，会彻底失效。
        """
        sid = self._xin_hui("loop-6")
        self._dui(f"/sessions/{sid}/messages", {"instructions": ["第一条指令"]})
        dai = self._deng(lambda: self._wo_de(sid))
        self._deng(lambda: self.h.du(sid).state == "attention")
        self._dui(f"/permissions/{dai[0]['requestId']}", {"decision": "allow"})
        self._deng(lambda: self.h.du(sid).state == "ended")
        # working 只是个很短的窗口，轮询会错过；直接查广播出去的 state 帧——
        # 那才是界面看到的东西。
        zhuang = [f["state"] for _, f in self.h.zong.huan
                  if f["type"] == "state" and f.get("sessionId") == sid]
        self.assertIn("attention", zhuang)
        self.assertIn("working", zhuang)
        self.assertEqual(zhuang[-1], "ended")

    def test_guan_bi_hui_hua(self):
        """关会话要真的关掉：适配器回收、状态机摘除、挂起项清空、返回 200。

        这条是被真机验收逼出来的：`POST /close` 之前一直 500，
        因为它把 BridgeServer 的方法当成了 handler 自己的方法调。
        """
        sid = self._xin_hui("loop-7")
        self._dui(f"/sessions/{sid}/messages", {"instructions": ["第一条指令"]})
        self._deng(lambda: self._wo_de(sid))
        s, r = self._dui(f"/sessions/{sid}/close", {})
        self.assertEqual(s, 200)
        self.assertTrue(r["ok"])
        self.assertIsNone(self.h.du(sid))
        self.assertEqual(self._wo_de(sid), [])
        self.assertIsNone(self.fu.shi_ying.get(sid))
        # Bridge 本身还活着
        s, _ = self._dui(f"/sessions/{sid}/close", {})
        self.assertEqual(s, 404)

    def test_jie_duan_de_zhun_que_xing_bi_li_bu_ke_yi_zhi(self):
        """超长命令被截断后，服务端独立把 allow 改判为拒绝（8.5 第 2 道闸门）。"""
        from lifeos.bridge.arbiter import DaiJue

        sid = self._xin_hui("loop-5")
        d = DaiJue(requestId="p-trunc", sessionId=sid, agentId="echo", toolName="Bash",
                   toolInput={"command": "x"}, inputTruncated=True)
        with self.fu.shen_qing.suo:
            self.fu.shen_qing._pending["p-trunc"] = d
        s, r = self._dui("/permissions/p-trunc", {"decision": "allow"})
        self.assertEqual(s, 200)
        self.assertEqual(r["decision"], "auto_deny")
        self.assertEqual(r["autoReason"], "truncated")


if __name__ == "__main__":
    unittest.main()
