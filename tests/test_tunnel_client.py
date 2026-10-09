"""出站隧道客户端（spec 6.2–6.6、7.3、Review Focus / 风险 4）。"""

from __future__ import annotations

import functools
import json
import logging
import os
import socket
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from websockets.datastructures import Headers
from websockets.http11 import Response
from websockets.sync.server import serve

from lifeos.bridge import jiaojie, pipei, run, tunnel
from lifeos.bridge.events import ZongXian
from gong_ju import deng_dai, duan_ke, wei_bian


def _kong() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    p = s.getsockname()[1]
    s.close()
    return p


class BenDiFu(BaseHTTPRequestHandler):
    """假的 Bridge 本地服务。只实现 /health 与 /stream。"""

    # `zhen_shu` / `yan_chi` 是**每台服务器一份的配置**，走构造参数进来，
    # 不再是类属性。原来它们是类属性、跨用例共享：两条用例并跑或顺序一变就
    # 互相污染，`setUp` 里那句「恢复默认值」只在顺序执行时碰巧救回来。
    def __init__(self, *a1, zhen_shu: int = 3, yan_chi: float = 0.0, **a2):
        self.zhen_shu = zhen_shu
        self.yan_chi = yan_chi
        self.tou: dict | None = None   # 最近一次收到的请求头，每个连接一份
        super().__init__(*a1, **a2)

    def do_GET(self):
        if self.path.startswith("/tou"):
            # 回显请求头：给「隧道客户端往回环调用补了哪些头」一个观察点。
            # 用它而不是让 fake 自己断言，是为了让断言留在测试里。
            self.tou = dict(self.headers.items())
            shu = json.dumps(self.tou).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(shu)))
            self.end_headers()
            self.wfile.write(shu)
            return
        if self.path.startswith("/stream"):
            if not self.headers.get("x-bridge-token"):
                self.send_response(401)
                self.send_header("content-length", "0")
                self.end_headers()
                return
            self.tou = dict(self.headers.items())
            self.send_response(200)
            self.send_header("content-type", "text/event-stream; charset=utf-8")
            self.send_header("transfer-encoding", "chunked")
            self.end_headers()
            for i in range(1, self.zhen_shu + 1):
                zhen = (f"id: {i}\nevent: message\ndata: "
                        + json.dumps({"type": "message", "sessionId": "s-1",
                                      "streamSeq": i}) + "\n\n").encode()
                self.wfile.write(f"{len(zhen):X}\r\n".encode() + zhen + b"\r\n")
                self.wfile.flush()
                # 帧间间隔是**这条假流的配置**，不是测试在等什么，
                # 所以它保留固定时长，只是从类属性挪成了构造参数。
                if self.yan_chi:
                    time.sleep(self.yan_chi)
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            return
        if self.path.startswith("/nope"):
            # 未知路径返回 404：给「上游 4xx 也要原样搬回去」这条用例一个输入。
            self.send_response(404)
            self.send_header("content-length", "0")
            self.end_headers()
            return
        shu = b'{"ok":true}'
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(shu)))
        self.end_headers()
        self.wfile.write(shu)

    def log_message(self, *a):
        pass


class WangUrlTest(unittest.TestCase):
    """网关出站地址必须与主服务的监听端口同源（spec 第 106 行的铁律）。

    这条守的是一个哑弹：`LIFEOS_GW_PORT` 设了之后只有服务端听新端口，
    Bridge 还打写死的 8771 ⇒ 无限重连且**一声不响**。运维视角看是
    「明明改了端口，Bridge 就是连不上，日志里什么都不说」。
    """

    def test_gw_duan_kou_shuo_ling(self):
        with mock.patch.dict(os.environ, {"LIFEOS_GW_PORT": "9771"}):
            self.assertEqual(run.wang_url(), "ws://127.0.0.1:9771/bridge/tunnel")

    def test_gw_duan_kou_mo_ren(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("LIFEOS_GW_PORT", None)
            self.assertEqual(run.wang_url(), "ws://127.0.0.1:8771/bridge/tunnel")

    def test_wang_url_zhun_ru_cfg(self):
        """`SuiDao` 必须真的拿到这个地址——不能只算了没人用。"""
        sd = tunnel.SuiDao(None, {"url": run.wang_url()})
        self.assertEqual(sd.url, run.wang_url())


class SuiDaoTest(unittest.TestCase):
    def setUp(self):
        self.ben = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(BenDiFu))
        self.ben_duan = self.ben.socket.getsockname()[1]
        threading.Thread(target=self.ben.serve_forever, daemon=True).start()

        self.suo = threading.RLock()
        self.wang_shou: list[dict] = []
        self.wang_lian: list = []
        self.wang_duan = 0
        self.wang = None
        self.qian_zi = 0

        self.zong = ZongXian("test", 1)
        self.sd = None

    def qi_ben(self, zhen_shu: int = 3, yan_chi: float = 0.0):
        """按本条用例的配置换一台假本地服务（配置走构造参数，不再是类属性）。"""
        self.ben.shutdown()
        self.ben.server_close()
        self.ben = ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(BenDiFu, zhen_shu=zhen_shu,
                                                yan_chi=yan_chi))
        self.ben_duan = self.ben.socket.getsockname()[1]
        threading.Thread(target=self.ben.serve_forever, daemon=True).start()

    def tearDown(self):
        if self.sd is not None:
            self.sd.ting_zhi()
        if self.wang is not None:
            self.wang.shutdown()
        self.ben.shutdown()

    # ---- 测试用的真网关 ----
    def qi_wang(self, shou_men=None):
        """起一个真 websockets 网关。`shou_men` 返回 Response 就拒绝握手。"""

        def lai(a1):
            with self.suo:
                self.wang_shou.append({"t": "__lian__"})
                self.wang_lian.append(a1)
            try:
                # recv 的超时必须在这个 while 里面接：外层接住 `continue` 是不合法的
                while True:
                    try:
                        x = json.loads(a1.recv(timeout=0.5))
                    except TimeoutError:
                        continue
                    with self.suo:
                        self.wang_shou.append(x)
            except Exception:  # noqa: BLE001
                return

        def men(a1, a2):
            if shou_men is not None:
                r = shou_men(a2)
                if r is not None:
                    return r
            return None

        self.wang = serve(lai, "127.0.0.1", 0, process_request=men,
                          ping_interval=15, ping_timeout=45, max_size=1 << 20,
                          compression=None)
        self.wang_duan = self.wang.socket.getsockname()[1]
        threading.Thread(target=self.wang.serve_forever, daemon=True).start()
        # `serve()` 返回时 socket 已经 bind+listen，所以「连得上」就是服务起来的
        # 证据。等这个证据，别按固定时长猜。
        deng_dai(lambda: duan_ke(self.wang_duan), chao=5.0,
                 msg=f"网关端口 {self.wang_duan} 连不上")

    def guan_lian(self):
        """真的把网关侧的活连接关掉，让客户端那边出现一次真断线。

        `Server.shutdown()` 只停 accept 循环，**已建立的连接照跑**，
        客户端根本收不到断开——只靠它测不到任何断线行为。
        """
        with self.suo:
            lian = list(self.wang_lian)
        for c in lian:
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass
        self.wang.shutdown()

    def qi_sd(self, url=None):
        self.sd = tunnel.SuiDao(None, {
            "deviceToken": "dt_dev-0000000000ab_" + "1" * 64,
            "instanceId": "i-test", "port": self.ben_duan, "token": "t" * 64,
            "zong": self.zong, "root": Path(tempfile.mkdtemp()),
            "url": url or f"ws://127.0.0.1:{self.wang_duan}/bridge/tunnel",
            "cliVersion": "2.1.283",
        })
        self.sd.qi_dong()
        return self.sd

    def shou_dao(self, xing, chao=5.0):
        def tiao():
            with self.suo:
                return [y for y in self.wang_shou if y.get("t") == xing]

        try:
            deng_dai(tiao, chao=chao, msg=tiao)
        except AssertionError as e:
            # 不再返回空列表让调用方自己 `assertTrue`：超时要带着「收到了哪些帧」
            # 一起炸，否则排查时只看到一句空列表。
            raise AssertionError(f"没等到 {xing}：{e}") from None
        return tiao()

    def fa_qing_qiu(self, rid, path="/health", method="GET", query="", body=None):
        """从网关侧发一个 request。**这里直接操纵 sd 的连接对象**——
        测试要能精确控制时机，所以不走真实网关的转发路径。"""
        self.sd._fen({"t": "request", "id": rid, "method": method, "path": path,
                      "query": query, "headers": {}, "body": body})

    # ---- 用例 ----
    def test_lian_shang_hou_fa_hello(self):
        self.qi_wang()
        self.qi_sd()
        hello = self.shou_dao("hello")
        self.assertTrue(hello, "没有发出 hello")
        self.assertEqual(hello[0]["instanceId"], "i-test")
        self.assertEqual(self.sd.zhuang_tai(), "connected")

    def test_qing_qiu_wang_fan(self):
        self.qi_wang()
        self.qi_sd()
        self.shou_dao("hello")
        self.fa_qing_qiu("r-1", "/health")
        x = self.shou_dao("response")
        self.assertTrue(x)
        self.assertEqual(x[0]["id"], "r-1")
        self.assertEqual(x[0]["status"], 200)
        self.assertEqual(json.loads(x[0]["body"]), {"ok": True})
        self.assertFalse(x[0]["b64"])

    def test_ben_di_fan_hui_4xx_ye_yao_yuan_yang_ban_hui_qu(self):
        """上游的 4xx 是**有效响应**，要原样搬回网关，不能当成传输错误吞掉。"""
        self.qi_wang()
        self.qi_sd()
        self.shou_dao("hello")
        self.fa_qing_qiu("r-1", "/nope")
        x = self.shou_dao("response")
        self.assertEqual(x[0]["status"], 404)
        self.assertEqual(x[0]["id"], "r-1")

    def test_liu_zhen_zhuan_fa(self):
        self.qi_wang()
        self.qi_sd()
        self.shou_dao("hello")
        self.fa_qing_qiu("r-1", "/stream", query="lastEventId=0")
        tou = self.shou_dao("response")
        self.assertEqual(tou[0]["status"], 200)
        self.assertIn("text/event-stream", tou[0]["headers"].get("content-type", ""))
        # 本地发了 3 帧，最后一条 close 表示流结束。等的是「3 帧都到了」这个
        # 可观察状态，不是等 3 帧该花的那段时间。
        def zhen_shu() -> int:
            with self.suo:
                return len([y for y in self.wang_shou if y.get("t") == "frame"])

        deng_dai(lambda: zhen_shu() >= 3, chao=10.0,
                 msg=lambda: [y.get("t") for y in self.wang_shou])
        with self.suo:
            zhen = [y for y in self.wang_shou if y.get("t") == "frame"]
        xu = [y["frame"]["streamSeq"] for y in zhen]
        self.assertEqual(xu, [1, 2, 3])
        # 流自然结束时，Bridge 要主动告诉网关「这个 requestId 结束了」
        guan = self.shou_dao("close", chao=3.0)
        self.assertTrue(guan, "流结束后没有发 close")

    def test_liu_zhen_zhu_kuai_bu_neng_zan_pi(self):
        """SSE 帧必须**逐帧**转出，不能攒批（真机验收第 3 步挡死的正是这条）。

        原实现 `_liu` 用 `a2.read(4096)`，而 `http.client.HTTPResponse.read(amt)`
        会**攒满 amt 字节才返回**。Bridge 的 SSE 是 chunked 逐帧一个 chunk，
        安静会话下首帧 `snapshot` 与审批卡一帧都搬不回来——**不报错，帧只是不来**。
        控制器最小复现实测：`read(4096)` 首帧 3.00s 才到，`read1(4096)` 0.00s。

        **为什么上一轮 442 条全绿而这条路是死的**：`test_liu_zhen_zhuan_fa` 用的假流
        是 `yan_chi=0.0`（三帧背靠背写完，约 240 字节），`read(4096)` 阻塞到 EOF 后
        一次性返回，三帧一起被切出来转发。它断言的 `[1,2,3]` 顺序照样成立——
        **它只验帧的内容与顺序，没有任何一条断言验帧什么时候到。**

        本用例的断言**不含任何时长阈值**：轮询等「已收到 1 或 2 帧」这个中间态被
        观测到。逐帧转时 n 会停在 1 约 0.8 秒（桩在 t=0 / 0.8 / 1.6 各发一帧）；
        攒批时 n 从 0 一步跳到 3，那个中间态永远观测不到。
        """
        self.qi_ben(zhen_shu=3, yan_chi=0.8)
        self.qi_wang()
        self.qi_sd()
        self.shou_dao("hello")
        self.fa_qing_qiu("r-1", "/stream", query="lastEventId=0")
        tou = self.shou_dao("response")
        self.assertEqual(tou[0]["status"], 200)

        def zhen_shu() -> int:
            with self.suo:
                return len([y for y in self.wang_shou if y.get("t") == "frame"])

        # 攒满 4096 或流结束才返回的实现，帧数会是 0 → 3，等不到 1 或 2。
        deng_dai(lambda: 1 <= zhen_shu() <= 2, chao=6.0, msg=zhen_shu)
        self.assertLess(zhen_shu(), 3, "三帧一起到，不是在逐帧转")
        # 顺序仍然不许变（这一条与 test_liu_zhen_zhuan_fa 同一性质）
        deng_dai(lambda: zhen_shu() >= 3, chao=10.0, msg=zhen_shu)
        with self.suo:
            xu = [y["frame"]["streamSeq"] for y in self.wang_shou if y.get("t") == "frame"]
        self.assertEqual(xu, [1, 2, 3])

    def test_close_guan_diao_ben_di_lian_jie(self):
        """风险 4：网关发 close 时，本地那条长连接必须被关掉（不能等 15 秒心跳）。"""
        self.qi_ben(zhen_shu=50, yan_chi=0.05)
        self.qi_wang()
        self.qi_sd()
        self.shou_dao("hello")
        self.fa_qing_qiu("r-1", "/stream")
        self.shou_dao("response")
        # 固定 0.3s 是在猜「本地长连接这会儿该建好了」。它建好是有痕迹的：
        # 进了 `_liu_biao`。等那个痕迹，别猜。
        deng_dai(lambda: "r-1" in self.sd._liu_biao, chao=5.0,
                 msg=lambda: sorted(self.sd._liu_biao))
        kai = time.time()
        self.sd._fen({"t": "close", "id": "r-1", "why": "client_gone"})
        try:
            deng_dai(lambda: "r-1" not in self.sd._liu_biao, chao=3.0,
                     msg=lambda: sorted(self.sd._liu_biao))
        except AssertionError:
            pass   # 下面两句就是原本的结论，超时了照样要红
        self.assertLess(time.time() - kai, 2.0, "本地长连接没被关掉")
        self.assertNotIn("r-1", self.sd._liu_biao)

    def test_401_ting_zhi_chong_lian(self):
        """spec 6.5：令牌失效必须停止重连，不能每 30 秒打一次网关。"""
        def men(a2):
            return Response(401, "Unauthorized", Headers({"content-type": "text/plain"}), b"no")

        self.qi_wang(shou_men=men)
        self.qi_sd()
        deng_dai(lambda: self.sd.zhuang_tai() == "error", chao=5.0,
                 msg=lambda: self.sd.zhuang_tai())
        self.assertEqual(self.sd.zhuang_tai(), "error")
        # brief 契约：deng_dao() 是「等到连上**或进入 error**」。
        self.assertTrue(self.sd.deng_dao(0.1), "进了 error 却没让 deng_dao() 放行")
        ci = self.sd.chong_lian_ci()
        # 要守的是「401 之后没有再连过」。原来是 sleep(2.5) 后取样一次，只在
        # 2.5 秒那一个时刻看得见；改成整段盯着重连计数，一涨立刻炸。
        # 窗口不必长：`_huan` 里 `self._ci += 1` 写在退避**之前**，坏实现会让
        # 计数在毫秒级涨，1.5 秒够它涨十几轮。
        wei_bian(lambda: self.sd.chong_lian_ci(), chao=1.5,
                 msg=lambda: self.sd.chong_lian_ci())
        self.assertEqual(self.sd.chong_lian_ci(), ci, "401 之后又重连了")

    def test_bye_hou_ting_zhi_chong_lian(self):
        """网关发 bye（解绑）→ 停止重连并进 error。

        这条链路跨三个函数：`_fen` 置 `_jie_bang` 并 `k.close()`；接收循环里的
        `recv` 随即抛 ConnectionClosed 穿出 `_lian`；标志必须**活过** `_lian`
        的返回，被 `_huan` 循环体里那个判断接住。只判在 `_lian` 里面没用——
        下一次连接开头那句 `self._jie_bang = False` 会先把标志抹掉。
        """
        self.qi_wang()
        self.qi_sd()
        self.assertTrue(self.shou_dao("hello"), "没连上，这条测不到 bye")
        self.sd._fen({"t": "bye", "reason": "unpaired"})
        deng_dai(lambda: self.sd.zhuang_tai() == "error", chao=3.0,
                 msg=lambda: self.sd.zhuang_tai())
        self.assertEqual(self.sd.zhuang_tai(), "error", "收到 bye 之后没有停止重连")
        self.assertTrue(self.sd.deng_dao(0.1), "进了 error 却没让 deng_dao() 放行")
        ci = self.sd.chong_lian_ci()
        # 同 `test_401_ting_zhi_chong_lian`：整段盯计数，不是睡满后取样一次。
        wei_bian(lambda: self.sd.chong_lian_ci(), chao=1.5,
                 msg=lambda: self.sd.chong_lian_ci())
        self.assertEqual(self.sd.chong_lian_ci(), ci, "bye 之后还在重连")

    def test_tui_bi_hou_chong_lian(self):
        """网关起不来时退避重连；网关起来后能连上。"""
        duan = _kong()
        self.sd = tunnel.SuiDao(None, {
            "deviceToken": "dt_dev-0000000000ab_" + "1" * 64,
            "instanceId": "i-test", "port": self.ben_duan, "token": "t" * 64,
            "zong": self.zong, "root": Path(tempfile.mkdtemp()),
            "url": f"ws://127.0.0.1:{duan}/bridge/tunnel"})
        self.sd.qi_dong()
        # 本机 Windows 上 connect 一个已关闭的回环端口要 ~2.05 秒才拿到
        # ConnectionRefused——**`sleep(2.0)` 必然 flake 的就是这一条**。
        # 等的是「重连计数涨到 1」这个状态，不是等 2.0 秒。
        deng_dai(lambda: self.sd.chong_lian_ci() >= 1, chao=15.0,
                 msg=lambda: self.sd.chong_lian_ci())
        self.assertGreaterEqual(self.sd.chong_lian_ci(), 1)
        self.assertNotEqual(self.sd.zhuang_tai(), "connected")
        # 网关起来 → 应当连上。先让 qi_wang 用这个端口。
        # handler 必须挂着不返回：返回即 close，connected 只存在几毫秒，测不到。
        def lai(a1):
            try:
                while True:
                    a1.recv(timeout=0.5)
            except Exception:  # noqa: BLE001
                return

        self.wang = serve(lai, "127.0.0.1", duan, ping_interval=15,
                          ping_timeout=45, max_size=1 << 20, compression=None)
        threading.Thread(target=self.wang.serve_forever, daemon=True).start()
        deng_dai(lambda: self.sd.zhuang_tai() == "connected", chao=30.0,
                 msg=lambda: self.sd.zhuang_tai())
        self.assertEqual(self.sd.zhuang_tai(), "connected")

    def test_wang_guan_diao_hou_zhuang_tai_bian_hua_you_device_status(self):
        self.qi_wang()
        ding = self.zong.dingyue("d-test", "local")
        self.qi_sd()
        self.shou_dao("hello")
        self.guan_lian()
        zhuang: list[str] = []

        def tiao() -> bool:
            while not ding.que.empty():
                x = ding.que.get_nowait()
                if x["type"] == "device_status":
                    zhuang.append(x["state"])
            return "offline" in zhuang or "connecting" in zhuang

        deng_dai(tiao, chao=5.0, msg=lambda: list(zhuang))
        self.assertTrue(any(s in zhuang for s in ("offline", "connecting")),
                        f"没发出 device_status，收到的是 {zhuang}")
        # 断线是常态。断了以后 `deng_dao()` 必须放行：不清的话在途请求线程会
        # 拿着上一条已关闭的连接去 send，异常被静默吞掉，调用方干等到超时。
        # **锚点用 `chong_lian_ci()`**：上面那个循环会被「连接前」那条 connecting
        # 帧直接短路（它在任何断线之前就发出来了），不能在还连着的时候下判断。
        # 涨到 1 正是 `_lian` 返回之后、finally 已经跑过的那一刻。
        deng_dai(lambda: self.sd.chong_lian_ci() >= 1, chao=5.0,
                 msg=lambda: self.sd.chong_lian_ci())
        self.assertGreaterEqual(self.sd.chong_lian_ci(), 1, "网关掉了却没有触发重连")
        self.assertFalse(self.sd.deng_dao(0.1), "连接已经断了，deng_dao() 还粘着")

    def test_mei_you_deviceToken_shi_error(self):
        self.sd = tunnel.SuiDao(None, {"deviceToken": "", "instanceId": "i",
                                       "port": self.ben_duan, "token": "t",
                                       "zong": self.zong, "root": Path(".")})
        self.sd.qi_dong()
        self.assertEqual(self.sd.zhuang_tai(), "error")

    def test_token_bu_jin_rizhi(self):
        import io
        lu = io.StringIO()
        h = logging.StreamHandler(lu)
        logging.getLogger("bridge.tunnel").addHandler(h)
        try:
            self.qi_wang()
            self.qi_sd()
            self.shou_dao("hello")
            self.assertNotIn("dt_dev-0000000000ab_" + "1" * 64, lu.getvalue())
        finally:
            logging.getLogger("bridge.tunnel").removeHandler(h)

    # ---- 任务 7 补：token 绝不能进 websockets 库的 DEBUG 日志 ----
    def test_ke_bu_neng_b_wu_deng_lu_qian_mian(self):
        """DEBUG 级下 `websockets.client` 会把每个请求头打进日志
        （client.py 的 `logger.debug("> %s: %s")`），其中就有
        `Authorization: Bearer <deviceToken 原文>`。网关侧任务 3 已用同样的
        办法钉住 server 端，客户端这一侧归本任务。"""
        import io
        lu = io.StringIO()
        h = logging.StreamHandler(lu)
        lg = logging.getLogger("websockets.client")
        yuan = lg.level
        lg.addHandler(h)
        lg.setLevel(logging.DEBUG)   # 故意开到 DEBUG：这一刻最危险
        try:
            self.qi_wang()
            self.qi_sd()
            self.assertTrue(self.shou_dao("hello"), "没连上，这条用例测不到握手头")
        finally:
            lg.setLevel(yuan)
            lg.removeHandler(h)
        self.assertNotIn("dt_dev-0000000000ab_" + "1" * 64, lu.getvalue(),
                         "设备令牌被 websockets 客户端的 DEBUG 日志打出来了")

    # ---- Review Focus / Global Constraints：SuiDao 的 connect() 必须传 proxy=None ----
    def test_dai_li_shi_ye_neng_lian(self):
        """本机常设 `HTTP_PROXY`。不显式关掉的话 websockets 会把回环连接送去
        代理，而这里那个代理（127.0.0.1:1）连不上刚起的端口 → 永远连不上。

        **必须让真正的 `SuiDao` 跑在这份环境里**：直接 `websockets.connect(proxy=None)`
        测的是库的参数，不是 `tunnel.py` 传没传——把 `tunnel.py` 里的 `proxy=None`
        删掉，那样的测试在任何没设代理的机器上照样绿。
        """
        self.qi_wang()
        with mock.patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:1",
                                          "HTTPS_PROXY": "http://127.0.0.1:1"}):
            self.qi_sd()
            # hello 到达 = connect() 在这段环境里跑完了，所以窗口不会关得太早。
            self.assertTrue(self.shou_dao("hello"),
                            "设了代理就连不上——SuiDao 的 connect() 没传 proxy=None")

    # ---- 任务 7 补：xuan() 的承重契约 ----
    def test_xuan_chu_lai_de_shu_zi_gu_lan_bu_hui_pian(self):
        j = jiaojie.xuan("tunnel", None, {"a": 1})
        self.assertIsInstance(j, tunnel.SuiDao)
        self.assertIsNone(j.fu)
        self.assertEqual(j.cfg, {"a": 1})

    def test_wang_que_diao_super_de_shi_hou_xuan_jiang_ben_shang_zhao_bu_dao(self):
        """钉住那行断言本身：忘了调 `super().__init__()` 必须在 `xuan()` 当场炸，
        而不是等真机上用到才变成 None。"""
        class Gua(jiaojie.JiaoJie):
            def __init__(self, a1, a2):
                self.pei_zhi = a2   # 名字写错，也没调父类构造

            def qi_dong(self):
                return

            def ting_zhi(self):
                return

            def zhuang_tai(self):
                return "local"

        jiaojie.zhu_ce("gua", Gua)
        try:
            with self.assertRaises(AssertionError):
                jiaojie.xuan("gua", None, {})
        finally:
            jiaojie.ZHU_CE.pop("gua", None)

    # ---- 任务 7 补：隧道状态落 runtime.json，走的是与 bao_xie 同一把锁 ----
    def test_zhuang_tai_xie_jin_yun_wen_bu_mo_diao_qi_ta_yao_jian(self):
        gen = Path(tempfile.mkdtemp()) / ".lifeos" / "bridge" / "runtime.json"
        gen.parent.mkdir(parents=True, exist_ok=True)
        gen.write_text(json.dumps({"deviceId": "dev-1", "deviceToken": "dt_x",
                                   "port": 8766, "pids": [{"pid": 7}]}),
                       encoding="utf-8")
        self.qi_wang()
        self.sd = tunnel.SuiDao(None, {
            "deviceToken": "dt_dev-0000000000ab_" + "1" * 64,
            "instanceId": "i-test", "port": self.ben_duan, "token": "t" * 64,
            "zong": self.zong, "root": Path(tempfile.mkdtemp()),
            "yun_wen": gen,
            "url": f"ws://127.0.0.1:{self.wang_duan}/bridge/tunnel"})
        self.sd.qi_dong()
        self.assertTrue(self.shou_dao("hello"), "没连上，测不到落盘")
        # hello 到达 ≠ 落盘完成：客户端是先 send(hello) 再 _bao_zt() → write_json。
        # 读一次就断言是 read-after-signal 竞态（Windows 上一回写被 Defender 拖一下
        # 就 KeyError），必须轮询。轮询条件要卡在**要断言的那个值**上：
        # 只判「有 tunnelState」会停在 `_huan` 开头写的那个 `connecting` 上。
        # 轮询条件卡在**要断言的那个值**上：只判「有 tunnelState」会停在
        # `_huan` 开头写的那个 `connecting` 上。
        deng_dai(lambda: json.loads(gen.read_text(encoding="utf-8"))
                 .get("tunnelState") == "connected", chao=5.0)
        yun = json.loads(gen.read_text(encoding="utf-8"))
        self.assertEqual(yun.get("tunnelState"), "connected")
        # 别的写者（配对、子进程记录）的键一个都不能少——runtime.json 是多写者文件
        self.assertEqual(yun["deviceToken"], "dt_x")
        self.assertEqual(yun["deviceId"], "dev-1")
        self.assertEqual(yun["pids"], [{"pid": 7}])


    # ---- 02 域：540 秒真机里那 42 帧重复 connecting 的缩小复现 ----
    # 必须走真握手 + 真掐断：缺陷恰恰发生在「网关整个死掉、connect()
    # 必然 refused」这条路径上，mock 掉 `_lian` 测不到真实形态。
    def test_wan_zhong_zhi_bo_yi_ci_lian_hao(self):
        """540 秒真机里那 42 帧重复 `connecting` 的缩小复现。

        走真握手 + 真掐断，**不 mock `_lian`**：缺陷恰恰发生在「网关整个
        死掉、`connect()` 必然 refused」这条路径上，mock 掉就测不到真实形态。
        判据是帧的 `(state, error)` 序列，不是帧数——去重键含 `error`，
        「连接中」与「连接失败」来回交替是真信息，**不该**被合并成一条。
        """
        ZHAN = 4  # 期望的重连轮数：够触发退避又不至于拖长用例
        self.qi_wang()
        ding = self.zong.dingyue("d-540", "local")
        self.qi_sd()
        self.shou_dao("hello")
        deng_dai(lambda: self.sd.zhuang_tai() == "connected", chao=20.0,
                 msg=lambda: self.sd.zhuang_tai())
        # 掐掉**整个网关**（含 accept 循环与端口）。只关活连接是不够的：
        # 那样 Bridge 下一轮会重连成功，测的就不是断线重连这个形态了。
        with self.suo:
            for c in list(self.wang_lian):
                try:
                    c.close()
                except Exception:  # noqa: BLE001
                    pass
        self.wang.shutdown()
        zhan = socket.socket()
        zhan.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        zhan.bind(("127.0.0.1", self.wang_duan))
        zhan.listen(0)          # 占住端口但从不 accept
        self.addCleanup(zhan.close)
        deng_dai(lambda: self.sd.chong_lian_ci() >= ZHAN, chao=90.0,
                 msg=lambda: f"只重连了 {self.sd.chong_lian_ci()} 轮")

        zhen = []
        while not ding.que.empty():
            x = ding.que.get_nowait()
            if x["type"] == "device_status":
                zhen.append((x["state"], x["error"]))
        # 4 轮重连只有 3 帧：首帧 connecting、连上、断线。**每轮开头那句
        # connecting 不再发**，剩下的 connecting/有错 由去重吃掉重复的。
        # 修之前这里是 9 帧（4 轮 × 2 + 1），且 state 全是 connecting。
        self.assertEqual(zhen, [("connecting", None),
                                ("connected", None),
                                ("connecting", "连接中断，正在重连")],
                         f"4 轮重连发了 {len(zhen)} 帧：{zhen}")
        self.assertEqual(self.zong.xu_hao(), 3, "每帧必须各占一个 streamSeq")

class HuiQuanLaiYuanTouTest(unittest.TestCase):
    """`_da` 的回环调用必须带 `x-lifeos-source`（spec 10.1 的 SSE 连接数按来源计）。

    **不补这个头的话，公网形态下那条「每用户 8 条 SSE」永远数不到上限。**
    浏览器 → 主服务 → 隧道 → `_da` → 回环，浏览器自己不会发这个头，
    全仓库只有 `tunnel.py:_da` 这一处能补上——它在中间，恰好知道 userId。

    判据用 fake 回显回来的真实请求头，不用「断言 `SuiDao` 有某个属性」。
    """

    def _tou(self, a1: dict, b1: dict | None = None) -> dict:
        return json.loads(tunnel.SuiDao(None, a1)._da(
            {"path": "/tou", "method": "GET", "headers": b1 or {}}).read().decode("utf-8"))

    def _sd(self, **a2) -> dict:
        d = {"deviceToken": "dt_dev-0000000000ab_" + "1" * 64,
             "instanceId": "i-t", "port": 1, "token": "t" * 64,
             "url": "ws://127.0.0.1:1/bridge/tunnel", "cliVersion": "2.1.283"}
        d.update(a2)
        return d

    def _qi_fu(self):
        fu = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(BenDiFu))
        threading.Thread(target=fu.serve_forever, daemon=True).start()
        self.addCleanup(fu.server_close)
        self.addCleanup(fu.shutdown)
        return fu.socket.getsockname()[1]

    def test_dai_shang_lai_yuan_tou(self):
        duan = self._qi_fu()
        tou = self._tou(self._sd(port=duan, userId="u-alice"))
        self.assertEqual(tou.get("X-Lifeos-Source") or tou.get("x-lifeos-source"),
                         "u-alice")

    def test_mei_yong_hu_luo_hui_local(self):
        """cfg 里没有 `userId` 时落回 `local`——**不能落成 `None` 或空串**。

        落成 `None` 的话它与真 `local` 是两个来源：本机形态（未配对）会
        记到 `None` 上，于是那条上限在开发机上永远数不到。
        """
        duan = self._qi_fu()
        tou = self._tou(self._sd(port=duan))
        self.assertEqual(tou.get("X-Lifeos-Source") or tou.get("x-lifeos-source"),
                         "local")

    def test_yong_hu_ming_bu_bei_browser_tou_gai_dian(self):
        """浏览器传来的 `x-lifeos-source` 不作数，一律用 cfg 里的 userId。

        不覆盖的理由是安全边界：来源只用来数连接，配上它就等于让前端自己
        声明「我是哪个用户」——一个脚本开 8 条再换个名字就绕过了上限。

        **必须真的传一个浏览器会带来的同名头进去。** 上一版传的是空字典，
        根本没有浏览器头可覆盖，于是「覆盖」这件事完全没被验证：把
        `tou["x-lifeos-source"] = ...` 改成 `tou.setdefault(...)`（即不再
        覆盖）后，20 条测试**全绿**（评审的变异验证结果）。
        """
        duan = self._qi_fu()
        tou = self._tou(self._sd(port=duan, userId="u-alice"),
                        {"x-lifeos-source": "attacker-guessed-name"})
        self.assertEqual(tou.get("X-Lifeos-Source") or tou.get("x-lifeos-source"),
                         "u-alice", "cfg 里的 userId 被浏览器带来的头顶掉了")


class WenJiaSuoTest(unittest.TestCase):
    """runtime.json 的读-改-写必须整段在一把锁里。"""

    def _yun(self, gen: Path) -> dict:
        return run.zao_yun({}, 8766, "t" * 64, "i-1", 1, None, None)

    def test_du_gai_xie_bi_zai_tong_yi_ba_suo_li(self):
        """`bao_xie` 是读-改-写。两个 HTTP 线程同时 spawn 不同会话时，
        各读一份旧值、后写的把先写的键抹掉——丢一次 pids 就留一个拿不到
        回收的孤儿 `claude`。各模块自己上一把锁仍然是两个临界区，
        所以锁只有 `pipei.XIE_SUO` 这一把。

        钉法：把读的那一步变慢，逼第二个线程插进第一个的读与写之间。
        """
        gen = Path(tempfile.mkdtemp())   # 项目根。bao_xie 收的是根，不是文件路径
        wen = run.wen_jia_ming(gen)
        run.bao_xie(gen, self._yun(wen), [], False)

        shi: list[str] = []
        zhen_du = pipei.du
        zhen_xie = pipei.write_json

        def du(a1):
            shi.append("du")
            # **这是把读-改-写临界区撑开的刺激，不是测试在等什么**，所以固定
            # 时长必须留着。缩短它会让「没有这把锁时第二个线程一定挤进来」
            # 这个前提重新变成运气。
            time.sleep(0.02)
            return zhen_du(a1)

        def xie(a1, a2):
            shi.append("xie")
            return zhen_xie(a1, a2)

        tiao = [threading.Thread(target=run.bao_xie,
                                 args=(gen, {**self._yun(wen), f"k{i}": i}, [], False))
                for i in range(6)]
        with mock.patch.object(pipei, "du", du), mock.patch.object(pipei, "write_json", xie):
            for t in tiao:
                t.start()
            for t in tiao:
                t.join(10)
        self.assertEqual(len(shi), 12, "不是所有线程都跑完了")
        for i in range(len(shi) - 1):
            self.assertNotEqual((shi[i], shi[i + 1]), ("du", "du"),
                                "两个线程同时在读 runtime.json——读-改-写没锁在一处")
        yun = json.loads(wen.read_text(encoding="utf-8"))
        for i in range(6):
            self.assertEqual(yun.get(f"k{i}"), i, f"k{i} 被别的线程写丢了")


class _JiaoRongZhong:
    """可推进的假 `xianzai`。每次调用前进 1000 毫秒。"""

    def __init__(self) -> None:
        self.n = 0

    def __call__(self) -> int:
        self.n += 1
        return self.n * 1000


class _KuaiTing:
    """假 Event：让重连循环不用真等退避，跑到第 `a1` 轮自己停。"""

    def __init__(self, a1: int) -> None:
        self.zhao = a1
        self.i = 0

    def is_set(self) -> bool:
        return self.i >= self.zhao

    def set(self) -> None:
        self.zhao, self.i = 0, 1

    def clear(self) -> None:
        pass

    def wait(self, a1: float = None) -> bool:
        self.i += 1
        return False


class ZtFaBuQuZhongTests(unittest.TestCase):
    """`_bao_zt` 的去重（spec 阶段六收口 02 域）。

    **去重必须在源头做。** 事件总线只是通道，重复帧一旦发出去就已经污染了
    `streamSeq`、占了重放缓冲、推到了每个订阅者队列里；前端过滤只是把症状
    藏起来。阶段六真机验收在 540 秒内观察到 42 条重复的 `connecting`，
    根因就在 `_huan` 每轮都调 `_bao_zt()` 且它无条件发。

    这组用例直接驱动 `_bao_zt()`，不起真网关：去重是纯函数式的判定，
    用真网关只会引入握手时序噪声。
    """

    def setUp(self):
        self.zong = ZongXian("test", 1)
        self.ding = self.zong.dingyue("d-1", "local")
        self.clock = _JiaoRongZhong()
        self.sd = tunnel.SuiDao(None, {"deviceId": "d-test", "deviceToken": "t",
                                       "zong": self.zong})
        self._patch = mock.patch.object(tunnel, "xianzai", self.clock)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def tearDown(self):
        self.sd.ting_zhi()

    def zhen(self) -> list:
        """取走并清空已投递的 device_status 帧。"""
        jiu = []
        while not self.ding.que.empty():
            x = self.ding.que.get_nowait()
            if x["type"] == "device_status":
                jiu.append(x)
        return jiu

    def test_lian_liang_ci_tong_yi_bu_fa(self):
        """`state` 与 `error` 都没变 → 一条都不许多发。"""
        self.sd._bao_zt()
        self.sd._bao_zt()
        self.assertEqual(len(self.zhen()), 1)
        self.assertEqual(self.zong.xu_hao(), 1, "重复发布必须不占 streamSeq")

    def test_lian_san_ci_zhuang_tai_bu_bian(self):
        """540 秒真机里那串重复 connecting 的等价覆盖（用调用序列模拟）。

        真实 `_huan` 每轮开头都发一次 `connecting`/无错。退避最长 30 秒，
        540 秒能滚十几轮，每轮一条同语义的重复帧。
        """
        for _ in range(12):
            self.sd._bao_zt()
        self.assertEqual(len(self.zhen()), 1)

    def test_error_kong_bian_fei_kong_fa_xin(self):
        """同一状态、错误原因从空变非空 —— 语义变了，必须发。"""
        self.sd._bao_zt()
        self.sd._bao_zt("连接中断，正在重连")
        zhen = self.zhen()
        self.assertEqual(len(zhen), 2)
        self.assertIsNone(zhen[0]["error"])
        self.assertEqual(zhen[1]["error"], "连接中断，正在重连")

    def test_error_a_bian_b_fa_xin(self):
        """一个错误换成另一个错误也是语义变化。把 `error` 省出判定就会漏掉这条。"""
        self.sd._bao_zt("原因甲")
        self.sd._bao_zt("原因乙")
        zhen = self.zhen()
        self.assertEqual(len(zhen), 2)
        self.assertEqual([x["error"] for x in zhen], ["原因甲", "原因乙"])

    def test_zhuang_tai_zhuan_huan_bao_liu(self):
        """四种状态的来回切换一条都不许被去重吃掉。"""
        for zhuang in ("connected", "connecting", "connected"):
            self.sd._zhuang = zhuang
            self.sd._bao_zt()
        zhen = self.zhen()
        self.assertEqual([x["state"] for x in zhen],
                         ["connected", "connecting", "connected"])
        # 去重不许改动 streamSeq 的单调性：三条就是三个号。
        self.assertEqual([x["streamSeq"] for x in zhen], [1, 2, 3])

    def test_bu_fa_zhen_jiu_bu_shu_xin(self):
        """不发帧的调用不许生成新 `since`。

        判据钉在假时钟的调用次数上：`_bao_zt` 每次进来都会求一次 `xianzai`，
        所以「时钟只走了两次」就等于「只有两次真正发布了」。
        """
        self.sd._bao_zt()
        for _ in range(5):
            self.sd._bao_zt()
        self.sd._bao_zt("出错了")
        zhen = self.zhen()
        self.assertEqual(len(zhen), 2)
        self.assertEqual(self.clock.n, 2, "被去重掉的调用不该再求一次时间")
        self.assertEqual([x["since"] for x in zhen], [1000, 2000])

    def test_xin_li_tao_di_yi_ci_bi_fa(self):
        """新实例的第一次发布必发，哪怕与上一个进程最后那条一模一样。

        去重缓存**只在进程内有效**：Bridge 重启后前端还留着上一条 `connected`，
        新进程第一条若被当成重复而吞掉，界面就一直停在旧状态，而服务端日志
        里什么异常都没有。
        """
        self.sd._zhuang = "connected"
        self.sd._bao_zt()
        xin = tunnel.SuiDao(None, {"deviceId": "d-test", "deviceToken": "t",
                                   "zong": self.zong})
        try:
            xin._zhuang = "connected"      # 与上一条同语义，才测得出「会不会被吞」
            xin._bao_zt()
            zhen = self.zhen()
            self.assertEqual(len(zhen), 2, "新实例的第一条被当成重复吞掉了")
            self.assertEqual(zhen[0]["state"], zhen[1]["state"])
        finally:
            xin.ting_zhi()

    def test_ting_zhi_keyuan_zhuan_fa_yi_ci(self):
        """停止时允许补发一次最终状态。

        前端靠这条把「设备离线」显示出来；去重不许把它吃掉。
        """
        self.sd._zhuang = "connected"
        self.sd._bao_zt()
        self.sd._zhuang = "offline"
        self.sd._bao_zt()
        zhen = self.zhen()
        self.assertEqual([x["state"] for x in zhen], ["connected", "offline"])

    def test_chong_lian_xun_huan_xu_lian_fa(self):
        """真跑三轮重连循环，把每帧的 `(state, error)` 都记下来。

        `_lian` 全程失败，所以没有 `connected` 帧。三轮只发两帧：首帧
        `connecting`/无错，以及第一次失败时的 `connecting`/有错。之后每轮
        开头的 `connecting` 不再发、结尾重复的那句被去重吃掉——这正是
        540 秒真机里那 42 帧的来源。
        """
        self.sd._ting = _KuaiTing(3)
        with mock.patch.object(self.sd, "_lian", side_effect=OSError("断了")):
            self.sd._huan()
        zhen = self.zhen()
        self.assertEqual([(x["state"], x["error"]) for x in zhen],
                         [("connecting", None),
                          ("connecting", "连接中断，正在重连")],
                         f"三轮重连发了 {len(zhen)} 帧：{zhen}")

    def test_qu_lun_kai_tou_zhi_fa_yi_ci(self):
        """首帧必发：前端得先看到"开始连接了"，哪怕这一轮很快就失败。"""
        self.sd._ting = _KuaiTing(1)
        with mock.patch.object(self.sd, "_lian", side_effect=OSError("断了")):
            self.sd._huan()
        self.assertEqual([(x["state"], x["error"]) for x in self.zhen()],
                         [("connecting", None),
                          ("connecting", "连接中断，正在重连")])

    def test_tong_yi_lian_hao_de_lun_bu_fa(self):
        """同一语义状态连着来多少次都只发一条（去重的正题）。

        真机那 42 帧是 `error` 交替，去重（键含 `error`）按设计不会吃掉它们——
        「连接中」变成「连接失败」确实是新信息。本条守的是另一半：真正的
        重复（同一语义连着来）一条都不能漏发。
        """
        for _ in range(20):
            self.sd._bao_zt("连接中断，正在重连")
        self.assertEqual(len(self.zhen()), 1)
