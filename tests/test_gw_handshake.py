"""隧道网关的握手与路由（spec 6.1、6.2、S15）。"""

from __future__ import annotations

import io
import logging
import tempfile
import threading
import time
import unittest
from pathlib import Path

from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.sync.client import connect

from lifeos.api.devices import SheBiao
from lifeos.api.tunnel_gw import XIYI, TunnelGw
from gong_ju import deng_dai, wei_bian


def lian(duan, ma, xy=XIYI, instanceId="i-test"):
    """开一条隧道。**必须 proxy=None** —— 本机设着 HTTP_PROXY（见 Global Constraints）。"""
    return connect(
        f"ws://127.0.0.1:{duan}/bridge/tunnel",
        additional_headers={"Authorization": f"Bearer {ma}",
                            "X-Protocol-Version": xy,
                            "X-Instance-Id": instanceId},
        proxy=None, ping_interval=15, ping_timeout=45, max_size=1 << 20,
        open_timeout=5)


class ShouWoTest(unittest.TestCase):
    def setUp(self):
        self.mu = tempfile.TemporaryDirectory()
        self.biao = SheBiao(Path(self.mu.name) / "devices.json",
                            logging.getLogger("test.gw"))
        self.gw = TunnelGw(self.biao, "127.0.0.1", 0, logging.getLogger("test.gw"))
        self.gw.qi_dong()
        self.duan = self.gw.duan_kou()
        self.jia = self.biao.jia("local", "本机", "i-test")

    def tearDown(self):
        self.gw.ting_zhi()
        self.mu.cleanup()

    def test_zheng_chang_shou_wo(self):
        with lian(self.duan, self.jia["deviceToken"]) as k:
            k.recv(timeout=5)  # welcome
            self.assertIsNotNone(self.gw.ren_wu(self.jia["deviceId"]))

    def test_xie_yi_ban_ben_bu_dui_400(self):
        with self.assertRaises(InvalidStatus) as c:
            lian(self.duan, self.jia["deviceToken"], xy="99")
        self.assertEqual(c.exception.response.status_code, 400)

    def test_ma_bu_dui_401(self):
        with self.assertRaises(InvalidStatus) as c:
            lian(self.duan, "dt_dev-000000000000_" + "0" * 64)
        self.assertEqual(c.exception.response.status_code, 401)

    def test_jie_bang_hou_403(self):
        self.biao.jie(self.jia["deviceId"])
        with self.assertRaises(InvalidStatus) as c:
            lian(self.duan, self.jia["deviceToken"])
        self.assertEqual(c.exception.response.status_code, 403)

    def test_lu_jing_bu_dui_404(self):
        with self.assertRaises(InvalidStatus) as c:
            connect(f"ws://127.0.0.1:{self.duan}/bie_de",
                    additional_headers={"Authorization": f"Bearer {self.jia['deviceToken']}",
                                        "X-Protocol-Version": XIYI},
                    proxy=None, open_timeout=5)
        self.assertEqual(c.exception.response.status_code, 404)

    def test_hou_lian_ti_xian_lian(self):
        """15.3.1 / spec 6.1 第 4 条：一个设备只允许 1 条活动隧道，后连的踢掉先连的。

        **关键是「踢掉」，不只是「换表」。** `self.dui[id] = d` 不管 `_lai` 有没有
        调 `jiu.guan()` 都会发生，所以只断言 `ren_wu(...).lian` 变了等于没断言。

        也不能只断言 k1 读到 `ConnectionClosed`：踢人即使只是把 `sheng` 标成 False，
        旧 handler 也会在 ≤1s 内退出接收循环、由库自己关掉连接，客户端照样读到关闭。
        真正锁住「主动踢」的是 **`di_yi.close_code`**：`_lai` 里踢人先于 `welcome`，
        所以 k2 收到 welcome 时旧连接**必须已经关完**（是时序保证，不是 sleep 竞猜）；
        少了 `jiu.guan()` 这一步，此刻旧 handler 还堵在 `recv(timeout=1.0)` 里，
        `close_code` 仍是 None。
        """
        k1 = lian(self.duan, self.jia["deviceToken"])
        k1.recv(timeout=5)
        di_yi = self.gw.ren_wu(self.jia["deviceId"]).lian
        k2 = lian(self.duan, self.jia["deviceToken"])
        k2.recv(timeout=5)  # welcome：踢人已完成
        self.assertIsNotNone(di_yi.close_code)
        with self.assertRaises(ConnectionClosed):
            k1.recv(timeout=5)
        self.assertIsNot(self.gw.ren_wu(self.jia["deviceId"]).lian, di_yi)
        k1.close()
        k2.close()

    def test_bing_fa_shou_wo(self):
        """Review Focus 5：两个线程同时握手，最终活跃连接必须恰好一条。"""
        cuo = []
        wan: list[int] = []

        def chong():
            try:
                k = lian(self.duan, self.jia["deviceToken"])
                k.recv(timeout=5)
                wan.append(1)
                # **握上了不松手**：两条并发必须同时挂着才抢得出「最终只剩一条」。
                # 这条固定时长是刺激的一部分（保持连接占用），不是测试在等什么。
                time.sleep(1.0)
                k.close()
            except Exception as e:  # noqa: BLE001 - 被踢的那条会抛，属预期
                cuo.append(type(e).__name__)

        xian = [threading.Thread(target=chong) for _ in range(2)]
        for t in xian:
            t.start()
        # 等「两条都落定」：握手成功的记 `wan`，被踢抛异常的记 `cuo`，两边凑够
        # 2 就是并发真的撞完了。原来是固定 sleep 0.6 猜——猜短了下面的断言在
        # 半空中取样，猜长了纯浪费。两种实现（踢人/不踢人）都在这里等得起。
        deng_dai(lambda: len(wan) + len(cuo) >= 2, chao=8.0,
                 msg=lambda: (len(wan), list(cuo)))
        dui = self.gw.ren_wu(self.jia["deviceId"])
        self.assertIsNotNone(dui)
        # 表以 deviceId 为键、单值，所以「表里只有一条」是结构性成立的，抓不到
        # 「换表了但没踢人」——锁住「踢」的断言在 test_hou_lian_ti_xian_lian。
        # 这里能锁的是：并发落下后活下来的那条**确实活着**，且对象不再漂移
        # （`ren_wu` 对 sheng=False 的连接返回 None，若赢家被误踢就会变 None）。
        a = self.gw.ren_wu(self.jia["deviceId"])
        self.assertTrue(a.sheng)
        # 要守的是「赢家的对象不漂移」——一件不该发生的事。原来 sleep 0.3 后
        # 取样一次；改成整段盯着表里那一条，一变立刻炸。
        wei_bian(lambda: self.gw.ren_wu(self.jia["deviceId"]), chao=0.3,
                 msg=lambda: self.gw.ren_wu(self.jia["deviceId"]))
        self.assertIs(a, self.gw.ren_wu(self.jia["deviceId"]))
        for t in xian:
            t.join(timeout=5)

    def test_token_bu_jin_rizhi(self):
        """Review Focus 4 / S13：**捕获区间内真的开隧道**（成功 + 失败握手各一次），
        断言基于真实捕到的日志内容——不是对空串断言。
        """
        ri_lu = io.StringIO()
        h = logging.StreamHandler(ri_lu)
        ri = logging.getLogger("test.gw")
        yuan = ri.level
        ri.addHandler(h)
        ri.setLevel(logging.DEBUG)
        try:
            # 成功握手。正常路径网关一个字都不打，所以逼它打一条：发一条解析不了的
            # 消息，`_shou_huan` 会记 warning（含 deviceId）并断开。
            k = lian(self.duan, self.jia["deviceToken"])
            try:
                k.recv(timeout=5)
                k.send("不是 json")
                # 等日志里真的出现东西再往下断言：原来是 50 次轮询猜多久打出来。
                deng_dai(lambda: ri_lu.getvalue(), chao=5.0,
                         msg=lambda: repr(ri_lu.getvalue()))
            finally:
                k.close()
            # 失败握手路径（401 分支）也走一遍。
            with self.assertRaises(InvalidStatus):
                lian(self.duan, "dt_dev-000000000000_" + "0" * 64)
            h.flush()
            ri_zhi = ri_lu.getvalue()
            # 先确认真捕到了东西，否则下面的 not-in 又是空断言。
            self.assertIn(self.jia["deviceId"], ri_zhi)
            self.assertNotIn(self.jia["deviceToken"], ri_zhi)
        finally:
            ri.setLevel(yuan)
            ri.removeHandler(h)

    def test_websockets_ku_rizhi_bei_ding_zai_info(self):
        """M3 / S13：DEBUG 下 websockets 库会把收到的每个请求头都打进日志
        （`websockets/server.py` 的 `logger.debug("< %s: %s")`），含
        `Authorization: Bearer <deviceToken 原文>`。`qi_dong()` 必须把这个 logger
        钉在 INFO——硬要求不能只靠「别把日志级别调高」维持。
        """
        ri = logging.getLogger("websockets.server")
        yuan = ri.level
        ri.setLevel(logging.DEBUG)  # 模拟「有人把日志级别调到了 DEBUG」
        try:
            gw2 = TunnelGw(self.biao, "127.0.0.1", 0, logging.getLogger("test.gw"))
            gw2.qi_dong()
            try:
                self.assertGreaterEqual(ri.getEffectiveLevel(), logging.INFO)
                k = lian(gw2.duan_kou(), self.jia["deviceToken"])
                k.recv(timeout=5)
                k.close()
            finally:
                gw2.ting_zhi()
        finally:
            ri.setLevel(yuan)

    def test_ting_zhi_guan_diao_huo_yue_sui_dao(self):
        """M2：停网关必须把活动隧道一起收掉。只关监听端口的话，非 daemon 的
        连接处理线程会带着旧连接活过 ting_zhi()，拖住进程退出（阶段 3 的教训）。
        """
        k = lian(self.duan, self.jia["deviceToken"])
        k.recv(timeout=5)
        self.gw.ting_zhi()
        with self.assertRaises(ConnectionClosed):
            k.recv(timeout=5)
        self.assertIsNone(self.gw.ren_wu(self.jia["deviceId"]))
        k.close()

    def test_ting_zhi_hou_duan_kou_bu_zai(self):
        self.gw.ting_zhi()
        with self.assertRaises(Exception):
            lian(self.duan, self.jia["deviceToken"])


class JieBaoTest(unittest.TestCase):
    def test_zhen_he_jie_lai_hui(self):
        from lifeos.api.tunnel_gw import jie, zhen
        s = zhen("request", id="r-1", method="GET", path="/health",
                 query="", headers={}, body=None)
        x = jie(s)
        self.assertEqual(x["t"], "request")
        self.assertEqual(x["path"], "/health")

    def test_jie_bu_he_fa_fan_hui_none(self):
        from lifeos.api.tunnel_gw import jie
        for huai in ["", "不是 json", "[]", '{"t": 1}', "null"]:
            with self.subTest(huai=huai):
                self.assertIsNone(jie(huai))
