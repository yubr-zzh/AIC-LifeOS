"""`device_status` 帧的两个生产者与常驻合成流（spec 9.4、15.3.4、15.6、风险 3）。"""

from __future__ import annotations

import base64
import http.client
import json
import logging
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from lifeos.api import bridge_admin, server
from lifeos.api.devices import PeiMa, SheBiao
from lifeos.api.tunnel_gw import TunnelGw, WuDui, he_cheng_zhen, xie_zhen
from lifeos.api.server import LiAnHTTPServer, LifeOSRequestHandler
from gong_ju import deng_dai, duan_ke


def _kong() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    p = s.getsockname()[1]
    s.close()
    return p


def _deng_eof(a1, a2=4.0) -> bool:
    """等对端把连接关掉。读到 EOF 返回 True。"""
    zhan = time.monotonic() + a2
    while time.monotonic() < zhan:
        try:
            a1.settimeout(max(0.1, zhan - time.monotonic()))
            if a1.recv(65536) == b"":
                return True
        except (TimeoutError, socket.timeout):
            return False
        except OSError:
            return False
    return False


class HeChengZhenTest(unittest.TestCase):
    def test_he_cheng_zhen_de_xing_zhuang(self):
        f = he_cheng_zhen("dev-0000000000ab", "offline", "设备离线")
        self.assertEqual(f["type"], "device_status")
        self.assertIsNone(f["sessionId"])
        # spec 9.4：合成帧 streamSeq 恒 0（ZongXian 的首帧是 1，0 是空号）
        self.assertEqual(f["streamSeq"], 0)
        self.assertEqual(f["state"], "offline")
        self.assertEqual(f["deviceId"], "dev-0000000000ab")
        self.assertEqual(f["error"], "设备离线")
        self.assertIsInstance(f["since"], int)

    def test_he_cheng_zhen_mei_you_id(self):
        """合成帧不在 Bridge 的序号空间里，不能给它编号。"""
        f = he_cheng_zhen("dev-0000000000ab", "offline", None)
        xian = xie_zhen(f)
        self.assertNotIn("id:", xian)
        self.assertIn("event: device_status", xian)
        self.assertIn("data: ", xian)
        self.assertTrue(xian.endswith("\n\n"))

    def test_zhen_xiang_dai_hao(self):
        """真帧照常带 `id:`——合成帧的特殊处理不许外溢到它身上。"""
        xian = xie_zhen({"type": "state", "sessionId": "s-1", "streamSeq": 5,
                         "state": "working"})
        self.assertTrue(xian.startswith("id: 5\n"))
        self.assertIn("event: state", xian)

    def test_xian_zhen_ye_neng_cheng_gong(self):
        """`xie_zhen` 必须能吃真帧的形状——它不只服务合成帧。"""
        f = {"type": "result", "sessionId": "s-1", "streamSeq": 7, "text": "完成"}
        xian = xie_zhen(f)
        self.assertTrue(xian.startswith("id: 7\n"))
        self.assertIn('"text": "完成"', xian)


class ZhiLiuTest(unittest.TestCase):
    """`_dai_liu`：在线走真隧道，离线走常驻合成流。"""

    def setUp(self):
        self.mu = tempfile.TemporaryDirectory()
        self.yuan = (bridge_admin.SHE, bridge_admin.GW, bridge_admin.MA)
        self.biao = SheBiao(Path(self.mu.name) / "devices.json", logging.getLogger("test.ds"))
        self.biao.jia("local", "测试机", "i-ds")
        self.sheId = next(x["deviceId"] for x in self.biao.lie())
        self.duan = _kong()
        self.fu = LiAnHTTPServer(("127.0.0.1", self.duan), LifeOSRequestHandler)
        threading.Thread(target=self.fu.serve_forever, daemon=True).start()
        # 等服务真的能连上，别按固定时长猜。
        deng_dai(lambda: duan_ke(self.duan), chao=5.0,
                 msg=f"端口 {self.duan} 连不上")

    def tearDown(self):
        self.fu.shutdown()
        self.fu.server_close()
        bridge_admin.zhuang(*self.yuan)
        self.mu.cleanup()

    def _zhuang(self, a1):
        bridge_admin.zhuang(self.biao, a1, PeiMa())

    def _xiang(self, a1="/agent-api/stream", a2=8.0, a3=1):
        """裸 socket 读 chunked SSE，攒够 a3 条 `data:` 帧或超时。

        **必须带 `Sec-Fetch-Site: same-origin`。** 无来源头的 `/agent-api/stream`
        一律 403（评审第 8 条：不开来源判定时任何人都能开无限条长连接，每条占一个
        线程）。这一组用例测的是合成流与逐帧转发，**不是鉴权**——补上来源头只是把
        它们还原成浏览器形态，不改动它们真正要断言的东西。
        """
        s = socket.create_connection(("127.0.0.1", self.duan), timeout=a2)
        try:
            s.sendall((f"GET {a1} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                       f"Sec-Fetch-Site: same-origin\r\n"
                       f"Accept: text/event-stream\r\n\r\n").encode())
            fan = b""
            zhan = time.monotonic() + a2
            while time.monotonic() < zhan and fan.count(b"data: ") < a3:
                try:
                    s.settimeout(max(0.1, zhan - time.monotonic()))
                    yi = s.recv(65536)
                except (TimeoutError, socket.timeout, OSError):
                    break
                if not yi:
                    break
                fan += yi
            return fan
        finally:
            s.close()

    def _zhen(self, a1: bytes) -> list[dict]:
        out = []
        for m in a1.decode("utf-8", "replace").split("\n\n"):
            ju = [ln[5:].lstrip() for ln in m.split("\n") if ln.startswith("data:")]
            if ju:
                out.append(json.loads("".join(ju)))
        return out

    def test_liu_tou_ya_you_sse_de_tou(self):
        """9.2 第 4 条：`x-accel-buffering: no` 少一行，反代就会攒缓冲，
        症状是「界面不卡了但一直不出帧」。"""
        gw = _GongGuan()
        self._zhuang(gw)
        zhen = self._xiang(a2=5.0)
        tou = zhen.split(b"\r\n\r\n", 1)[0].decode("latin-1")
        self.assertIn("200", tou)
        self.assertIn("text/event-stream", tou)
        self.assertIn("x-accel-buffering: no", tou)
        self.assertIn("transfer-encoding: chunked", tou)
        self.assertNotIn("content-length", tou.lower())

    def test_she_bei_bu_zai_xian_gei_she_cheng_liu(self):
        """设备离线时给常驻合成流：首帧 offline，不回 503。"""
        self._zhuang(_GongGuan(zhuang="offline"))
        fan = self._xiang(a2=5.0)
        zhen = self._zhen(fan)
        self.assertEqual(len(zhen), 1)
        self.assertEqual(zhen[0]["type"], "device_status")
        self.assertEqual(zhen[0]["state"], "offline")
        self.assertEqual(zhen[0]["streamSeq"], 0)
        self.assertEqual(zhen[0]["deviceId"], self.sheId)
        self.assertNotIn(b"id: 0", fan)

    def test_xian_zhen_zhuan_yu_bu_gai_xie(self):
        """9.2 第 5 条：真帧逐帧原样转出，一个字节都不改。"""
        gw = _GongGuan(zhen=[
            {"type": "snapshot", "sessionId": None, "streamSeq": 1, "instanceId": "i-1"},
            {"type": "state", "sessionId": "s-1", "streamSeq": 2, "state": "working"},
        ])
        self._zhuang(gw)
        fan = self._xiang(a2=5.0, a3=2)
        zhen = self._zhen(fan)
        self.assertEqual([x["streamSeq"] for x in zhen], [1, 2])
        self.assertIn(b"id: 1\n", fan)
        self.assertIn(b"id: 2\n", fan)

    def test_sui_dong_jie_lie_hou_gei_yi_tiao_offline(self):
        """15.3.4 第 1 条：隧道断了，在途的流各收一条 offline 才关。"""
        gw = _GongGuan(zhen=[{"type": "state", "sessionId": "s-1", "streamSeq": 3,
                              "state": "working"}],
                       zhuang=lambda: "offline" if gw.chen_lei else "connected")
        self._zhuang(gw)
        fan = self._xiang(a2=5.0, a3=2)
        zhen = self._zhen(fan)
        self.assertEqual(zhen[-1]["type"], "device_status")
        self.assertEqual(zhen[-1]["state"], "offline")
        self.assertEqual(zhen[-1]["error"], "隧道中断")
        self.assertEqual(zhen[-1]["streamSeq"], 0)

    def test_wu_dui_luo_dao_he_cheng_liu(self):
        """握手那一刻隧道就断了：`kai_liu` 抛 `WuDui`，先给一条 offline 帧
        再转常驻合成流——**不抛 503 给浏览器**（spec 9.4 的理由）。"""
        # **第一次问要答 connected**：答 offline 就直接进合成流，`kai_liu` 压根
        # 不会被调，这条用例就验不到 `WuDui` 那条路了。
        ci = [0]

        def zhuang_tai(a1):
            ci[0] += 1
            return "connected" if ci[0] == 1 else "offline"

        gw = _GongGuan(wu_dui=True)
        gw.zhuang_tai = zhuang_tai
        self._zhuang(gw)
        fan = self._xiang(a2=3.0)
        zhen = self._zhen(fan)
        self.assertEqual(len(zhen), 1)
        self.assertEqual(zhen[0]["type"], "device_status")
        self.assertEqual(zhen[0]["state"], "offline")
        self.assertEqual(zhen[0]["error"], "隧道已断开")
        # 首帧之后不重复发 offline（`a4=False` 那条路），只挂着等心跳。
        # **表里有它**才是「转成了常驻合成流」——15 秒的心跳之外没有别的证据。
        # 所以等的是「进了合成流表」这个状态，不是等 0.3 秒。
        deng_dai(lambda: self.sheId in gw._hc_biao, chao=5.0,
                 msg=lambda: list(gw._hc_biao))
        with gw._hc_suo:
            self.assertEqual(len(gw._hc_biao), 1)

    def test_he_cheng_liu_zhi_bao_zui_xin_yi_tiao(self):
        """风险 3：同一设备只保留最新一条合成流，旧的立刻关。
        **不清的话浏览器反复重连会攒到 8 条上限，真隧道回来时反而连不上。**"""
        gw = _GongGuan(zhuang="offline")
        self._zhuang(gw)
        a1 = socket.create_connection(("127.0.0.1", self.duan), timeout=5)
        a2 = socket.create_connection(("127.0.0.1", self.duan), timeout=5)
        try:
            tou = (b"GET /agent-api/stream HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                   b"Sec-Fetch-Site: same-origin\r\n\r\n")
            a1.sendall(tou)
            # 等第一条进合成流——「在表里」就是它进来了，看得见。
            deng_dai(lambda: self.sheId in gw._hc_biao, chao=5.0,
                     msg=lambda: list(gw._hc_biao))
            with gw._hc_suo:
                lao = gw._hc_biao[self.sheId]
            self.assertFalse(lao.is_set())
            a2.sendall(tou)
            # 等旧的那条被唤醒：`lao.is_set()` 就是它被唤醒后线程会退出合成流的
            # 那个事件。等这个事件，不是等 0.6 秒。
            deng_dai(lao.is_set, chao=5.0, msg=lambda: lao.is_set())
            # 旧的那条被唤醒（它的事件置位 ⇒ 它那个线程会退出合成流），
            # 表里换成了新的那一条。
            self.assertTrue(lao.is_set())
            with gw._hc_suo:
                biao = dict(gw._hc_biao)
            self.assertEqual(len(biao), 1)
            self.assertNotIn(lao, biao.values())
        finally:
            a1.close()
            a2.close()

    def test_he_cheng_liu_wu_deng_qi_ta_she_bei(self):
        """唤醒一条不能碰另一条设备的流。`du_she()` 一次只给一台（1.4），
        所以这里绕过 HTTP 层直接灌两个 deviceId。"""
        gw = _GongGuan(zhuang="offline")
        self._zhuang(gw)
        for she in ("dev-0000000000a1", "dev-0000000000a2"):
            threading.Thread(
                target=lambda s=she: server.LifeOSRequestHandler._he_cheng_liu(
                    None, gw, s, lambda a: True, True),
                daemon=True).start()
        # 两条都进表了再往下走——「表里有两条」看得见，不用睡 0.5 秒。
        deng_dai(lambda: len(gw._hc_biao) >= 2, chao=5.0,
                 msg=lambda: list(gw._hc_biao))
        with gw._hc_suo:
            biao = dict(gw._hc_biao)
        self.assertEqual(len(biao), 2)
        with gw._hc_suo:
            biao["dev-0000000000a1"].set()
        # 等被唤醒的那条从表里摘掉。
        deng_dai(lambda: "dev-0000000000a1" not in gw._hc_biao, chao=5.0,
                 msg=lambda: list(gw._hc_biao))
        with gw._hc_suo:
            self.assertNotIn("dev-0000000000a1", gw._hc_biao)
            self.assertIn("dev-0000000000a2", gw._hc_biao)

    def test_zhuang_mian_ze_chi_you_de_he_cheng_liu_suo(self):
        """**锁与表由 `zhuang()` 建，不许 `_he_cheng_liu` 自己 `getattr` 兜底。**

        兜底里的 `threading.Lock()` 每次求值都是**一把新锁**：`try` 那处与
        `finally` 那处拿到的不是同一把，表会被并发合成流写坏。所以这条用一个
        **自己没有这两个属性**的网关——正是 `TunnelGw` 的初始形状。
        """
        gw = _WuZhuang()
        self.assertFalse(hasattr(gw, "_hc_suo"))
        self._zhuang(gw)
        self.assertIsInstance(gw._hc_suo, type(threading.Lock()))
        self.assertEqual(gw._hc_biao, {})
        for she in ("dev-0000000000a1",):
            threading.Thread(
                target=lambda s=she: server.LifeOSRequestHandler._he_cheng_liu(
                    None, gw, s, lambda a: True, True),
                daemon=True).start()
        # 等表里正好只有这一台——「表长成了」看得见。
        deng_dai(lambda: list(gw._hc_biao) == ["dev-0000000000a1"], chao=5.0,
                 msg=lambda: list(gw._hc_biao))
        with gw._hc_suo:
            self.assertEqual(list(gw._hc_biao), ["dev-0000000000a1"])


class _Lian:
    """一条裸 socket 连接，外加**已经读走的响应头**。

    **为什么非要包一层：`socket.socket` 挂了 `__slots__`，不能挂自定义属性。**
    CPython 的 socket 对象定义了 `__slots__ = ['__weakref__', '_io_refs', '_closed']`
    且**没有 `__dict__`**——`s._yong_tou = fan` 会抛
    `AttributeError: 'socket' object has no attribute '_yong_tou' and no __dict__`。
    用 `dict` 旁挂、`WeakKeyDictionary`、或者退回「只读一次」都各有代价：
    前两者让断言与 socket 的对应关系变成隐式的，后者退回「同一份字节读两遍」
    那个更坏的坑（见 `_da_kai` 的说明）。

    `recv` / `settimeout` / `close` 直接转发，调用方拿它当 socket 用即可。
    """

    def __init__(self, a1, a2: bytes):
        self.s = a1
        self.yong_tou = a2      # 已读走的响应头（含结尾空行）

    def settimeout(self, a1):
        self.s.settimeout(a1)

    def recv(self, a1):
        return self.s.recv(a1)

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass


class ZhuFuLiuShuTest(ZhiLiuTest):
    """主服务代理层也要对 SSE 连接数负责（阶段六收口 06 域）。

    **Bridge 那层的 8 条上限拦不住这一层。** 它数的是「到达 Bridge 的连接」，
    而主服务的每条代理流自己占一个 `ThreadingHTTPServer` 线程——开满
    Bridge 的额度之前，主服务这边已经先被线程数拖住了。伪造一个
    `x-lifeos-source` 就能绕开 Bridge 的按来源计数，而主服务此前**根本没有
    计数**。

    **可信来源只取自进程内配置。** 接入登录之前，「当前用户」就是一个进程内
    常量；浏览器自报的头是数据，不是身份——拿它当认证身份等于没有认证。
    """

    def _liu_shu(self):
        """当前占着的代理流**连接数**。**读 `bridge_admin.GW` 而不是 `self.gw`**——
        生产代码用的是那个模块级全局；两者不是同一个对象时，这条会一直返回
        兜底的 0，于是「开了 8 条」与「计数是 0」同时成立，测试永远绿。

        **数连接数，不是桶数。** 表是 `{来源键: {token…}}`，同来源的 8 条连接
        只占 1 个桶；直接 `len(表)` 的话恒为 1，于是「开到上限」永远等不到，
        而真出了「计数为 1」也不会有人发现——上限形同虚设而测试全绿。
        """
        gw = bridge_admin.GW
        with gw._dl_suo:
            return sum(len(v) for v in gw._dai_liu_biao.values())

    def setUp(self):
        super().setUp()
        # **本组用例默认用「在线」形态。** 离线形态下 `_he_cheng_liu` 的
        # 「同设备只保留最新一条」会把并发压到恒定 1 条（`ZhiLiuTest` 里那条
        # 用例守的正是这个行为），于是上限永远碰不到，429 那几条用例改成
        # 「怎么都撞不到上限」也照样绿。要验上限就必须让 8 条流真的并存。
        # 合成流那一条用例自己换回离线形态。
        self.gw = _GongGuan(zhuang="connected", xin_zhen=True, zhen=[{"type": "state",
                                                                      "sessionId": "s-1",
                                                                      "streamSeq": 1,
                                                                      "state": "working"}])
        self._zhuang(self.gw)

    def tearDown(self):
        # **先把挂着等帧的流全部放走，再关服务。** 否则那些 handler 线程
        # 还会阻塞在假隧道的 `zhen()` 里，`server_close()` 之后用例已经
        # 结束，下一条用例的端口/线程被它们的收尾动作串扰（症状是后面
        # 出现与本用例无关的 flake）。
        gw = getattr(self, "gw", None)
        if gw is not None:
            gw.fang_shi.set()
        super().tearDown()

    def _zhuang(self, a1):
        bridge_admin.zhuang(self.biao, a1, PeiMa())

    def _guan_bo(self, lian) -> None:
        """模拟浏览器断开：直接关掉客户端 socket。

        **不要去摘任何登记表。** 断开必须由生产代码自己的写失败路径感知到，
        假网关若提前知道了这件事，这条不变式就绕过了真实机制。
        """
        for s in lian:
            try:
                s.close()
            except OSError:
                pass

    def _da_kai(self, a1=1, tou=None, liu_zhuan=False):
        """开 a1 条 `/agent-api/stream` 裸连接，返回它们的 `_Lian` 列表。

        **读完响应头才算这条开起来了。** 只 `sendall` 就返回的话，服务端线程
        可能还没跑到登记那一步，调用方紧接着断言「开了 N 条」就会看到 0——
        于是这条测试测的是「客户端发得快不快」，不是「名额有没有被占」。

        **读走的响应头要留着。** 后面再用 `_du_liu` 读同一条连接的话，
        状态行已经被这里消费掉了，再读只能读到响应体——断言拿到的是
        `''`／`'{"code":'` 这种碎片，看着像被测代码没返回 429，根因却在
        「同一份字节读了两遍」。所以把头缓存到 `_Lian.yong_tou`，`_du_liu` 优先用它。

        **被拒的连接照样发完就返回。** 429 那条在服务端是「登记失败即回响应」，
        不进 `_dai_liu`，可客户端这边分不清 200 与 429——都得读完头才知道。
        """
        out = []
        for _ in range(a1):
            s = socket.create_connection(("127.0.0.1", self.duan), timeout=5)
            cr = chr(13) + chr(10)
            tou_lian = ('Host: 127.0.0.1' + cr
                       + 'Sec-Fetch-Site: same-origin' + cr
                       + 'Accept: text/event-stream' + cr
                       + (tou or '') + cr)
            s.sendall(("GET /agent-api/stream HTTP/1.1" + cr + tou_lian).encode())
            fan = b""
            zhan = time.monotonic() + 5.0
            while time.monotonic() < zhan and b"\r\n\r\n" not in fan:
                try:
                    s.settimeout(max(0.1, zhan - time.monotonic()))
                    fan += s.recv(65536)
                except (TimeoutError, socket.timeout, OSError):
                    break
            # 只留到头部结束的那一段，别把响应体一起带走。
            if b"\r\n\r\n" in fan:
                fan = fan.split(b"\r\n\r\n", 1)[0] + b"\r\n\r\n"
            out.append(_Lian(s, fan))
        return out

    def test_dao_shang_xian_di_nai_tiao_hui_429(self):
        """开到上限后第 N+1 条 429，且带 `Retry-After`。"""
        shang = server.ZUI_DAI_LIU
        lian = self._da_kai(shang)
        try:
            deng_dai(lambda: self._liu_shu() >= shang, chao=10.0,
                     msg=lambda: f"只开了 {self._liu_shu()} 条")
            duo = self._da_kai(1)
            try:
                r, tou = self._du_liu(duo[0])
                self.assertEqual(r, 429)
                # **头名不区分大小写，断言却区分了。** `_du_liu` 把键统一转成
                # 小写，而本项目的约定也是小写 `retry-after`（`server.py:335`
                # 那条 429 与 `test_gw_liuliang` 都是）。这里按小写查——写
                # `Retry-After` 会恒为 None，读起来像「服务端没带这个头」。
                self.assertIsNotNone(tou.get("retry-after"), "429 没带 Retry-After")
                # 超限的那条不许占名额
                self.assertEqual(self._liu_shu(), shang)
            finally:
                self._guan_bo(duo)
        finally:
            self._guan_bo(lian)

    def _du_liu(self, s, a2=3.0):
        """读一条 `/stream` 响应，返回 (状态码, 响应头)。**状态码是 int。**

        **不能用 `fan.split(b" ")[1]` 切状态行。** 那是按「第一个空格前是状态行」
        猜的，可这里读回来的是一段流：SSE 连接被拒时服务端回的是 JSON 错误体，
        它的字节里也有空格，切出来是 `{"code":` 这种碎片——症状是断言
        `'?' != 429`／`'{"code":' != '429'`，看着像被测代码返回了怪状态码，
        根因却在解析器。**按 HTTP 的行结构读**：第一行是状态行，之后到空行为止
        是响应头。`_da_kai` 已经读走过的头部优先复用（同一份字节不读两遍）。

        **状态码统一转成 `int`。** 切出来的是字节里的字符串，与断言里的整数
        永不相等——`'429' != 429` 是绿的失败现场，看上去像服务端没按预期拒绝，
        实际只是类型不同（这一条真被咬过一次：日志里明明是 429，断言却红）。
        解析失败返回 `0`，让「没读到状态行」与「状态码是 0」分开可辨。
        """
        fan = getattr(s, "yong_tou", b"")
        if not fan:
            s.settimeout(a2)
            fan = b""
            zhan = time.monotonic() + a2
            while time.monotonic() < zhan:
                try:
                    yi = s.recv(65536)
                except (TimeoutError, socket.timeout, OSError):
                    break
                if not yi:
                    break
                fan += yi
                if b"\r\n\r\n" in fan:
                    break
        # `readline` 逐行切，避免响应体里恰好有空格时被 split 误伤。
        lei = fan.split(b"\r\n")
        zhuang = 0
        tou = {}
        for ln in lei:
            shu = ln.decode("latin-1")
            if not shu:
                break                      # 空行 = 头部结束，剩下的都是体
            if not zhuang and shu.startswith("HTTP/"):
                _, zhuang, *_ = shu.split(" ")
                try:
                    zhuang = int(zhuang)
                except ValueError:
                    zhuang = 0
                continue
            if ":" in shu:
                k, v = shu.split(":", 1)
                tou[k.strip().lower()] = v.strip()
        return zhuang, tou

    def test_wei_dao_shang_xian_neng_zheng_chang_establish(self):
        """未到上限时正常建立代理流（对照组，否则上面那条是「一律 429」也绿）。"""
        s = self._da_kai(1)[0]
        try:
            zhen = self._xiang()
            self.assertTrue(zhen, "流没读到任何字节")
        finally:
            self._guan_bo([s])
        # **等释放，不能直接断言。** `_xiang()` 读完就自己关了连接并返回，
        # 而服务端的收尾发生在另一个线程上——从「客户端已关」到「名额已释放」
        # 有真实的时间差，这里抢跑就会拿到还没释放的旧值（实测 2 != 0，
        # 上一批连接的额度还挂着）。抢跑型的断言会把「等一下就好」误报成
        # 「名额泄漏」，而后者是本域真正要守的东西。
        deng_dai(lambda: self._liu_shu() == 0, chao=15.0,
                 msg=lambda: f"断开后还占着 {self._liu_shu()} 条名额")
        lian = self._da_kai(1)
        try:
            deng_dai(lambda: self._liu_shu() == 1, chao=10.0,
                     msg=lambda: f"开了 {self._liu_shu()} 条")
        finally:
            self._guan_bo(lian)

    def test_zheng_chang_jie_shu_shifang_ming_e(self):
        """正常结束释放名额 → 释放后能再建满上限条。"""
        shang = server.ZUI_DAI_LIU
        lian = self._da_kai(shang)
        try:
            deng_dai(lambda: self._liu_shu() >= shang, chao=10.0,
                     msg=lambda: f"只开了 {self._liu_shu()} 条")
        finally:
            self._guan_bo(lian)
        # 浏览器断开后名额必须回来。判据是计数归零，不是睡一会儿再试。
        deng_dai(lambda: self._liu_shu() == 0, chao=15.0,
                 msg=lambda: f"断开后还占着 {self._liu_shu()} 条名额")
        zai = self._da_kai(shang)
        try:
            deng_dai(lambda: self._liu_shu() >= shang, chao=10.0,
                     msg=lambda: f"释放后只开到 {self._liu_shu()} 条")
        finally:
            self._guan_bo(zai)

    def test_yi_chang_tui_chu_ye_shifang_ming_e(self):
        """**handler 抛异常也释放名额**——漏了这一条，异常一次泄漏一条，
        开够次数之后主服务对谁都返回 429，且再也回不来。"""
        wen_you = []

        def yi_chang_zhui_chu():
            """装在假网关上：第一次握手时炸，模拟 `_dai_liu` 内部抛异常。"""
            if not wen_you:
                wen_you.append(1)
                raise RuntimeError("故意的：模拟 handler 内部炸了")

        self.gw.kai_liu = lambda *a, **kw: yi_chang_zhui_chu()
        s = self._da_kai(1)[0]
        try:
            s.settimeout(3.0)
            try:
                s.recv(4096)
            except (TimeoutError, socket.timeout, OSError):
                pass
        finally:
            self._guan_bo([s])
        # 前提：异常真的发生了。否则下面这条「计数归零」在**根本没炸**的
        # 情况下也成立——一条正常结束的流本来就会释放，用例就退化成
        # 「正常结束会释放」的重复，绿得毫无信息。
        self.assertEqual(len(wen_you), 1, "异常压根没被触发，这条用例是空跑的")
        deng_dai(lambda: self._liu_shu() == 0, chao=15.0,
                 msg=lambda: f"异常退出后还占着 {self._liu_shu()} 条名额")

    def test_lai_yuan_b_tong_hu_zi_bu_xiang_ying(self):
        """**伪造 `x-lifeos-source` 头不能改变可信计数。**

        头是浏览器自报的数据。拿它当身份，等于任何人发个头就能换一个独立的
        计数桶——上限立刻形同虚设。判据是：伪造头之后仍落在同一个桶里。
        """
        shang = server.ZUI_DAI_LIU
        lian = self._da_kai(shang, tou="x-lifeos-source: \xe4\xbd\xa0\xe5\xa5\xbd\r\n")
        try:
            deng_dai(lambda: self._liu_shu() >= shang, chao=10.0,
                     msg=lambda: f"只开了 {self._liu_shu()} 条")
            duo = self._da_kai(1, tou="x-lifeos-source: wu_qian_de_hao\r\n")
            try:
                zhuang, _ = self._du_liu(duo[0])
                self.assertEqual(zhuang, 429,
                                 "换个伪造的来源头就绕过了上限——那等于没有上限")
            finally:
                self._guan_bo(duo)
        finally:
            self._guan_bo(lian)

    def test_he_cheng_liu_ji_shu_zhu_fu_liu_shu(self):
        """合成离线流**算进**主服务连接数，且同一设备只保留最新一条。

        **本组其余用例是在线形态，这条必须换回离线。** 合成流的
        「同设备只保留最新一条」是风险 3 的护栏，而它只在离线形态下发生。
        """
        self.gw.zhuang_liu = "offline"   # 同设备顶掉旧流那条只在离线时发生
        lian = self._da_kai(1)
        try:
            deng_dai(lambda: self._liu_shu() == 1, chao=10.0,
                     msg=lambda: f"合成流占了 {self._liu_shu()} 条")
            deng_dai(lambda: self.sheId in self.gw._hc_biao, chao=5.0,
                     msg=lambda: list(self.gw._hc_biao))
            # 同设备第二条：旧的被唤醒、表里换新的。**旧的那条退出时会释放
            # 它自己那枚 token，新的一条仍占着——主服务侧必须仍是 1 条。**
            # 这里守的是「释放只删自己那枚」：若释放按来源键整桶删，
            # 计数会掉到 0，额度凭空多出来。
            lian2 = self._da_kai(1)
            try:
                deng_dai(lambda: self.sheId in self.gw._hc_biao, chao=5.0,
                         msg=lambda: list(self.gw._hc_biao))
                deng_dai(lambda: self._liu_shu() == 1, chao=10.0,
                         msg=lambda: f"替换后占了 {self._liu_shu()} 条（应仍是 1）")
                with self.gw._hc_suo:
                    self.assertEqual(len(self.gw._hc_biao), 1)
            finally:
                self._guan_bo(lian2)
        finally:
            self._guan_bo(lian)


class _GongGuan:
    """假网关。`kai_liu` 返回一个可脚本化的 `Liu` 替身。

    `zhuang` 收字符串或可调用对象：可调用是给「帧放完之后线路才断」那种时序用的
    （`zhuang_tai` 每次问一次，直接给字符串验不到断开那一刻的行为差异）。

    `xin_zhen=True` 让 `Liu.zhen()` **持续产出心跳帧**而不是发完就结束，
    模拟真隧道「Agent 还在干活，帧源源不断」的样子。不开这个开关时它发完
    队列里的帧就返回 None（流随即结束）——`ZhiLiuTest` 那几组用例要的正是
    「读完就结束」，不能被这个语义波及。

    **持续产帧不是为了让用例好过，而是为了让「浏览器断开后名额要回来」
    走真实路径。** 生产里主服务是靠**写失败**发现对端走了（`server.py:_dai_liu`
    的 `xie()` 捕 `BrokenPipeError`/`ConnectionResetError` 后返回 False，流随即
    结束、调用点的 `finally` 释放名额）。假隧道要是发完一帧就安静阻塞，
    写失败永远不发生，于是这条不变式根本没被测到——用例只能去验「探测到断开」
    这个生产里并不存在的机制。
    """

    def __init__(self, zhuang="connected", zhen=None, wu_dui=False, xin_zhen=False):
        self.zhuang_liu = zhuang   # 线路状态
        self.zhen = zhen or []     # 要逐帧转出的真帧（发完即空）
        self.wu_dui = wu_dui       # kai_liu 抛 WuDui
        self.xin_zhen = xin_zhen   # 队列空后继续产心跳帧
        self.chen_lei = 0          # 已被取走的帧数
        self.fang_shi = threading.Event()   # 让所有挂着的流立刻结束
        self._hc_suo = threading.Lock()
        self._hc_biao = {}

    def zhuang_tai(self, a1):
        return self.zhuang_liu() if callable(self.zhuang_liu) else self.zhuang_liu

    def qing(self, a1, a2, a3=30.0):
        raise WuDui("agent_unavailable", "设备不在线")

    def kai_liu(self, a1, a2, a3=30.0):
        if self.wu_dui:
            raise WuDui("agent_unavailable", "隧道已断开")
        return ({"status": 200, "headers": {"content-type": "text/event-stream"}},
                _Liu(self))

    def xian_liu(self, a1, a2, a3):
        """限流放行。本文件的用例全走 `/stream`（本来就不受限流），
        给它只是为了别在将来某个用例改打别的端点时炸成 AttributeError。"""
        return None


class _WuZhuang:
    """裸网关：`TunnelGw` 装配前的初始形状，**没有** `_hc_suo` / `_hc_biao`。"""

    def zhuang_tai(self, a1):
        return "offline"

    def qing(self, a1, a2, a3=30.0):
        raise WuDui("agent_unavailable", "设备不在线")

    def kai_liu(self, a1, a2, a3=30.0):
        raise WuDui("agent_unavailable", "设备不在线")

    def xian_liu(self, a1, a2, a3):
        return None


class _Liu:
    def __init__(self, a1):
        self.gw = a1

    def zhen(self, a1=60.0):
        if self.gw.fang_shi.is_set():
            return None
        if self.gw.zhen:
            self.gw.chen_lei += 1
            return self.gw.zhen.pop(0)
        if not self.gw.xin_zhen:
            return None
        # 队列空了就继续产心跳帧。**间隔要够短**，断开的客户端要能等到
        # 下一帧触发真实的写失败（生产里靠它收尾并释放名额），等 60 秒
        # 超时的话「断开后名额要回来」这条压根验不到。
        if self.gw.fang_shi.wait(0.05):
            return None
        return {"type": "state", "sessionId": "s-1", "streamSeq": 0,
                "state": "working"}

    def guan(self):
        pass
