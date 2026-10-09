"""网关的请求转发、流式帧与 close（spec 6.2、6.3、Review Focus 1/2/3）。"""

from __future__ import annotations

import base64
import json
import logging
import os
import queue
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from lifeos.api.devices import SheBiao
from lifeos.api.tunnel_gw import DENG_LI, XIYI, WuDui, jie, zhen
from lifeos.api import tunnel_gw
from lifeos.api.tunnel_gw import TunnelGw
from lifeos.bridge import tunnel
from lifeos.bridge.events import ZongXian
from gong_ju import deng_dai, duan_ke, wei_bian


class JiaQiao:
    """假 Bridge。测试用的最小隧道客户端——**刻意不复用生产代码**，
    这样网关的测试不会被 `tunnel.py` 的实现带偏。"""

    def __init__(self, duan, ma, xing_wei=None, hello=True):
        self.k = connect(
            f"ws://127.0.0.1:{duan}/bridge/tunnel",
            additional_headers={"Authorization": f"Bearer {ma}",
                                "X-Protocol-Version": XIYI,
                                "X-Instance-Id": "i-test"},
            proxy=None, ping_interval=15, ping_timeout=45, max_size=1 << 20,
            open_timeout=5)
        self.k.recv()  # welcome
        self.shou_dao: list[dict] = []
        self.ting = False
        self.xing_wei = xing_wei or (lambda q, x: None)
        if hello:
            self.k.send(zhen("hello", instanceId="i-test", streamEpoch=3,
                             version="2.0", cliVersion="2.1.283", sessions=1))
        self.tiao = threading.Thread(target=self._shou, daemon=True)
        self.tiao.start()

    def _shou(self):
        while not self.ting:
            try:
                x = jie(self.k.recv(timeout=0.5))
            except TimeoutError:
                continue
            except (ConnectionClosed, Exception):  # noqa: BLE001
                # 连接关了就是结束了。**正常关闭（1000 OK）也走这里**，
                # 不捕的话 pytest 把它算成「未捕获的线程异常」打一整段
                # traceback——那是收尾噪声，不是缺陷，却会把真失败埋掉。
                return
            if x is None:
                return
            self.shou_dao.append(x)
            # **回调也要在 try 里。** `xing_wei` 会往连接上 send（比如回响应），
            # 而用例可能刚好在这一刻把连接关了——`ConnectionClosedOK` 从回调
            # 里穿出去，落在 try 之外，pytest 判成「未捕获的线程异常」打一段
            # traceback。那是收尾竞态，不是缺陷，却会把真失败埋在这一片噪声里。
            try:
                self.xing_wei(self, x)
            except (ConnectionClosed, Exception):  # noqa: BLE001
                return

    def hui(self, xing, **a):
        self.k.send(zhen(xing, **a))

    def guan(self):
        self.ting = True
        try:
            self.k.close()
        except Exception:  # noqa: BLE001
            pass

    def deng_ge(self, xing, shu=1, chao=5.0):
        try:
            deng_dai(lambda: len([x for x in self.shou_dao if x["t"] == xing]) >= shu,
                     chao=chao, msg=lambda: [x["t"] for x in self.shou_dao])
        except AssertionError:
            return False
        return True


def hui_dan(zhuang=200, body='{"ok":true}', tou=None, b64=False):
    def f(q, x):
        if x["t"] != "request":
            return
        q.hui("response", id=x["id"], status=zhuang,
              headers=tou or {"content-type": "application/json"},
              body=body, b64=b64)
    return f


class WangFanTest(unittest.TestCase):
    def setUp(self):
        self.mu = tempfile.TemporaryDirectory()
        self.biao = SheBiao(Path(self.mu.name) / "devices.json", logging.getLogger("test.gw"))
        self.gw = TunnelGw(self.biao, "127.0.0.1", 0, logging.getLogger("test.gw"))
        self.gw.qi_dong()
        self.duan = self.gw.duan_kou()
        self.jia = self.biao.jia("local", "本机", "i-test")

    def tearDown(self):
        self.gw.ting_zhi()
        self.mu.cleanup()

    def test_qing_wang_fan(self):
        q = JiaQiao(self.duan, self.jia["deviceToken"], hui_dan())
        try:
            r = self.gw.qing(self.jia["deviceId"],
                             {"method": "GET", "path": "/health", "query": "",
                              "headers": {}, "body": None})
            self.assertEqual(r["status"], 200)
            self.assertEqual(json.loads(r["body"]), {"ok": True})
        finally:
            q.guan()

    def test_wu_dui_shi_bao_agent_unavailable(self):
        with self.assertRaises(WuDui) as c:
            self.gw.qing(self.jia["deviceId"],
                         {"method": "GET", "path": "/health", "query": "",
                          "headers": {}, "body": None}, a3=0.5)
        self.assertEqual(c.exception.code, "agent_unavailable")

    def test_qing_chao_shi(self):
        q = JiaQiao(self.duan, self.jia["deviceToken"])  # 不应答
        try:
            with self.assertRaises(WuDui):
                self.gw.qing(self.jia["deviceId"],
                             {"method": "GET", "path": "/health", "query": "",
                              "headers": {}, "body": None}, a3=0.5)
        finally:
            q.guan()

    def test_duan_xian_huan_xing_deng_dai(self):
        """Review Focus 1：隧道在等待期间断了，等待方必须被唤醒，不能永远挂着。"""
        q = JiaQiao(self.duan, self.jia["deviceToken"])  # 收到 request 但不应答

        def sha():
            # 固定 0.4 秒是在猜「这会儿请求该在飞了」。它在飞是有痕迹的：进了
            # 网关的在途表 `d.deng`。等那个痕迹再断线，断才真落在「等待期间」；
            # 否则请求可能还没排进去就断了，测到的是另一条分支。
            def zai_tu() -> int:
                dui = self.gw.ren_wu(self.jia["deviceId"])
                return len(dui.deng) if dui is not None else -1

            deng_dai(lambda: zai_tu() >= 1, chao=5.0, msg=zai_tu)
            q.guan()

        threading.Thread(target=sha, daemon=True).start()
        kai = time.time()
        with self.assertRaises(WuDui):
            self.gw.qing(self.jia["deviceId"],
                         {"method": "GET", "path": "/health", "query": "",
                          "headers": {}, "body": None}, a3=10.0)
        # 必须是被唤醒的（<2s），不是等满 10s 超时
        self.assertLess(time.time() - kai, 2.0)

    def test_b64_fen_zhi(self):
        """Review Focus 3：非 UTF-8 的响应体走 base64 分支。"""
        yuan = b"\x00\x01\xff\xfe\x80PNG"
        q = JiaQiao(self.duan, self.jia["deviceToken"],
                    hui_dan(body=base64.b64encode(yuan).decode("ascii"), b64=True))
        try:
            r = self.gw.qing(self.jia["deviceId"],
                             {"method": "GET", "path": "/pair", "query": "",
                              "headers": {}, "body": None})
            self.assertTrue(r["b64"])
            self.assertEqual(base64.b64decode(r["body"]), yuan)
        finally:
            q.guan()

    def test_qing_ba_qing_qiu_yuan_yang_song_chu_qu(self):
        q = JiaQiao(self.duan, self.jia["deviceToken"], hui_dan())
        try:
            self.gw.qing(self.jia["deviceId"],
                         {"method": "POST", "path": "/permissions/p-1",
                          "query": "token=abc", "headers": {"x-bridge-token": "abc"},
                          "body": '{"decision":"allow"}'})
            q.deng_ge("request")
            x = [y for y in q.shou_dao if y["t"] == "request"][0]
            self.assertEqual(x["method"], "POST")
            self.assertEqual(x["path"], "/permissions/p-1")
            self.assertEqual(x["query"], "token=abc")
            self.assertEqual(x["headers"], {"x-bridge-token": "abc"})
            self.assertEqual(x["body"], '{"decision":"allow"}')
        finally:
            q.guan()

    def test_ying_da_bu_he_fa_status_shi_wu_dui(self):
        """Important：Bridge 回的 status 不是数字时，`qing` 与 `kai_liu` 都必须抛
        WuDui 并摘掉队列——漏非 WuDui 异常会让任务 8 的 `except WuDui` 接不住（500
        而不是约定的 502），不摘队列则每条吃掉 64 个在途名额里的一个，攒满后整台
        设备被自己的 Bridge 拖死到重连为止。
        """
        q = JiaQiao(self.duan, self.jia["deviceToken"], hui_dan(zhuang="不是数字"))
        try:
            d = self.gw.ren_wu(self.jia["deviceId"])
            self.assertIsNotNone(d)
            miao = {"method": "GET", "path": "/x", "query": "",
                    "headers": {}, "body": None}
            for cheng in (self.gw.qing, self.gw.kai_liu):
                with self.subTest(cheng=cheng.__name__):
                    with self.assertRaises(WuDui) as c:
                        cheng(self.jia["deviceId"], miao, a3=5.0)
                    self.assertEqual(c.exception.code, "agent_unavailable")
            self.assertEqual(d.deng, {}, "队列没摘，在途名额泄漏")
        finally:
            q.guan()

    def test_ying_da_bu_he_fa_tou_shi_wu_dui(self):
        """同上，换成 headers 不是映射（`dict()` 抛 TypeError 的那条路）。"""
        q = JiaQiao(self.duan, self.jia["deviceToken"], hui_dan(tou=["x"]))
        try:
            d = self.gw.ren_wu(self.jia["deviceId"])
            self.assertIsNotNone(d)
            miao = {"method": "GET", "path": "/x", "query": "",
                    "headers": {}, "body": None}
            for cheng in (self.gw.qing, self.gw.kai_liu):
                with self.subTest(cheng=cheng.__name__):
                    with self.assertRaises(WuDui) as c:
                        cheng(self.jia["deviceId"], miao, a3=5.0)
                    self.assertEqual(c.exception.code, "agent_unavailable")
            self.assertEqual(d.deng, {}, "队列没摘，在途名额泄漏")
        finally:
            q.guan()

    def _deng_duan_kai(self, a1):
        """轮询等隧道被拆掉：表被摘 + Bridge 侧接收线程退出。**不 sleep 等固定时长。**

        判据同 `test_chao_da_duan_kai`：只摘表不断线是「消息被静默丢掉、隧道照旧」，
        那正是本任务要消灭的形状。
        """
        deng_dai(lambda: self.gw.ren_wu(self.jia["deviceId"]) is None, chao=5.0,
                 msg=lambda: self.gw.ren_wu(self.jia["deviceId"]))
        self.assertIsNone(self.gw.ren_wu(self.jia["deviceId"]),
                          "隧道没被拆掉")
        deng_dai(lambda: not a1.tiao.is_alive(), chao=5.0,
                 msg=lambda: a1.tiao.is_alive())
        self.assertFalse(a1.tiao.is_alive(), "线上没断：Bridge 侧连接还活着")

    def test_ji_xing_id_duan_kai(self):
        """Ruling 2b 的第一半：`id` 畸形 → warning + 断开，不降级。

        `x-1` 不合 `^r-[0-9a-f]{8}$`，是**我们不可能发出的 id** ⇒ 两端实现不一致。
        **必须与 `test_he_fa_id_cha_bu_dao_jing_mo` 成对**：只写这一条的话，
        一个「任何 id 都断开」的退化实现也能过。
        """
        q = JiaQiao(self.duan, self.jia["deviceToken"])
        try:
            q.hui("frame", id="x-1", frame={"type": "message"})
            self._deng_duan_kai(q)
            # 拆掉之后请求应当立刻失败，而不是挂到自己的超时
            with self.assertRaises(WuDui) as c:
                self.gw.qing(self.jia["deviceId"],
                             {"method": "GET", "path": "/x", "query": "",
                              "headers": {}, "body": None}, a3=0.5)
            self.assertEqual(c.exception.code, "agent_unavailable")
        finally:
            q.guan()

    def test_hello_shu_zi_bu_he_fa_duan_kai(self):
        """缺陷域一次收完：`hello` 的整数字段坏值 → 点名的 warning + 断开。

        `streamEpoch` 与 `sessions` 是同一个 `int(x.get(k) or 0)` 形状、同一条
        不变式（**入站字段的取值必须在解析处被校验**）下的两个点，症状一样
        （隧道莫名断、日志难读），所以一起收。不校的话 ValueError 会冲出
        `_fen_fa`，被 `_lai` 的兜底 except 记成一句笼统的「隧道异常退出」。

        warning 要点名是哪个字段——这正是它比那句笼统话强的地方，断言里钉住。
        """
        for duan_zi in ("streamEpoch", "sessions"):
            with self.subTest(duan_zi=duan_zi):
                # JiaQiao 自己会发 hello，这里关掉，换一条坏字段的
                q = JiaQiao(self.duan, self.jia["deviceToken"], hello=False)
                try:
                    hao = {"instanceId": "i-test", "streamEpoch": 3,
                           "version": "2.0", "cliVersion": "2.1.283", "sessions": 1}
                    hao[duan_zi] = "abc"
                    with self.assertLogs("test.gw", level="WARNING") as ri:
                        q.k.send(zhen("hello", **hao))
                        self._deng_duan_kai(q)
                    self.assertIn(f"hello.{duan_zi} 不是数字", "\n".join(ri.output))
                finally:
                    q.guan()

    def test_zhen_bu_shi_dui_xiang_duan_kai(self):
        """I-1 第一半：`frame` 根本不是对象（`data: 42` 那种）。"""
        q = JiaQiao(self.duan, self.jia["deviceToken"])
        try:
            q.hui("frame", id="r-1a2b3c4d", frame=42)
            self._deng_duan_kai(q)
        finally:
            q.guan()

    def test_zhen_que_xin_feng_jian_duan_kai(self):
        """I-1 第二半：`frame` 是 dict 但缺 `type` / `streamSeq`。

        这一半**今天就能从完全合法的 SSE 走到**：`_fa_zhen` 把 `json.loads` 的
        结果原样塞进 frame，`data: {"foo":1}` 就是这种帧。我们自己的 Bridge 不会
        发（`events.py` 恒带这两个键），对端 Bridge 坏了就能走到——穿过只校
        `isinstance` 的守卫，让 `xie_zhen` KeyError，而 `_dai_liu` 只 except
        `WuDui`，异常逃出去后前端连 offline 帧都拿不到。

        **与 `test_zhen_bu_shi_dui_xiang_duan_kai` 成对**：一条钉「不是对象」，
        一条钉「是对象但写不出去」。缺任一条，只校其中一半的实现都能过。
        """
        q = JiaQiao(self.duan, self.jia["deviceToken"])
        try:
            q.hui("frame", id="r-1a2b3c4d", frame={"foo": 1})
            self._deng_duan_kai(q)
            # 有 type 没 streamSeq 也同样写不出去（`xie_zhen` 要写 `id:` 行）
            q2 = JiaQiao(self.duan, self.jia["deviceToken"])
            try:
                q2.hui("frame", id="r-1a2b3c4d", frame={"type": "message"})
                self._deng_duan_kai(q2)
            finally:
                q2.guan()
        finally:
            q.guan()

    def test_he_fa_id_cha_bu_dao_jing_mo(self):
        """Ruling 2b 的第二半：`id` 合法但 `deng` 表里没有 → **静默忽略**。

        这是正常路径：请求超时后 `_zhai` 已摘表，迟到的 frame / close / response
        无处可去。把它当错误断开，会把「一次普通超时」升级成「整条隧道拆掉重建」——
        前端看到的是无谓的重连 + snapshot，代价远大于收益。

        「没被断开」的判据不是「没记 warning」，而是**隧道还能用**：先正常请求
        拿到响应 → 发一个形状合法、表里没有的 id → 再正常请求一次仍然拿到响应。
        **与 `test_ji_xing_id_duan_kai` 成对**：那一条钉「该断的要断」，这一条钉
        「不该断的不能断」。

        **承重的是最后那个 `qing`**。紧跟三次无同步 `q.hui()` 之后的那句
        `assertIsNotNone` 只是快检——网关可能还没读到那些消息就断言完了。把它当
        「没被断开」的判据去加固是加固错了地方（M-5）。
        """
        q = JiaQiao(self.duan, self.jia["deviceToken"], hui_dan())
        try:
            miao = {"method": "GET", "path": "/x", "query": "",
                    "headers": {}, "body": None}
            r = self.gw.qing(self.jia["deviceId"], miao, a3=5.0)
            self.assertEqual(r["status"], 200)
            d = self.gw.ren_wu(self.jia["deviceId"])
            # M-4：先确认这个假 id 没撞上真在途的 rid。撞上的概率是 2⁻³²，
            # 但「表里没有」这条前提不该靠运气。同形状的响应也照样查不到。
            self.assertNotIn("r-abcdef12", d.deng)
            # 三类消息各发一个「合格式、表里没有」的 id——三条都过 `_yan_hao`。
            # frame 必须带全信封键（type/streamSeq），否则被测的是 I-1 那半守卫，
            # 不是「id 查不到表静默忽略」这一条。
            q.hui("frame", id="r-abcdef12",
                  frame={"type": "message", "sessionId": "s-1", "streamSeq": 1})
            q.hui("close", id="r-abcdef12", why="late")
            q.hui("response", id="r-abcdef12", status=200,
                  headers={"content-type": "application/json"}, body="", b64=False)
            self.assertIsNotNone(self.gw.ren_wu(self.jia["deviceId"]),
                                 "迟到的帧把隧道拆了")
            r = self.gw.qing(self.jia["deviceId"], miao, a3=5.0)
            self.assertEqual(r["status"], 200, "迟到的帧之后隧道就不能用了")
        finally:
            q.guan()

    def test_ying_da_que_jian_shi_wu_dui(self):
        """I-2：response 少发一个键 → `WuDui` 并摘队列，**这是有意收紧**。

        改前 `bool(x.get("b64"))` 会给缺键兜底成 False 照走；现在契约层五键全验，
        缺一即拒。收紧是对外行为变更（`tunnel.py` 三条 response 构造路径五个键恒在，
        故实际无回归），必须显式钉住——否则将来谁嫌严把 `_yao` 放宽，没有测试会发现。
        与 `test_ying_da_bu_he_fa_status_shi_wu_dui` / `..._tou_shi_wu_dui` 同形。
        """

        def f(q, x):
            if x["t"] != "request":
                return
            q.hui("response", id=x["id"], status=200,
                  headers={"content-type": "application/json"}, body='{"ok":true}')
            # 注意：没有 b64

        q = JiaQiao(self.duan, self.jia["deviceToken"], f)
        try:
            d = self.gw.ren_wu(self.jia["deviceId"])
            self.assertIsNotNone(d)
            miao = {"method": "GET", "path": "/x", "query": "",
                    "headers": {}, "body": None}
            for cheng in (self.gw.qing, self.gw.kai_liu):
                with self.subTest(cheng=cheng.__name__):
                    with self.assertRaises(WuDui) as c:
                        cheng(self.jia["deviceId"], miao, a3=5.0)
                    self.assertEqual(c.exception.code, "agent_unavailable")
            self.assertEqual(d.deng, {}, "队列没摘，在途名额泄漏")
        finally:
            q.guan()

    def test_zai_tu_shang_xian(self):
        """M3：一条隧道上同时挂着的在途请求上限（DENG_LI）生效。"""
        q = JiaQiao(self.duan, self.jia["deviceToken"])  # 不应答
        try:
            d = self.gw.ren_wu(self.jia["deviceId"])
            self.assertIsNotNone(d)
            for i in range(DENG_LI):
                d.deng[f"r-{i}"] = queue.Queue()
            with self.assertRaises(WuDui) as c:
                self.gw.qing(self.jia["deviceId"],
                             {"method": "GET", "path": "/health", "query": "",
                              "headers": {}, "body": None}, a3=0.5)
            self.assertEqual(c.exception.code, "agent_unavailable")
            self.assertEqual(c.exception.message, "设备上在途请求过多")
        finally:
            q.guan()

    def test_zai_tu_shang_xian_shi_yuan_zi_de(self):
        """M2/M3：并发抢最后一个名额时，在途数**任何时候**都不越过 `DENG_LI`。

        预填 `DENG_LI - 1` 个名额，8 个线程同时抢最后一个：判与插在同一把锁内时，
        恰好 7 个被拒、峰值不越界；锁没盖住判定与插入时，多个线程会各自判过
        `63 < 64` 再一起插进去。
        （8 个线程其实很难挤进那个窗口，所以这条更像不变量回归；真正逐字节锁住
        「插入前的重查」的是 `test_ren_wu_fang_xing_hou_sui_dao_cai_si`。）
        """
        q = JiaQiao(self.duan, self.jia["deviceToken"])  # 不应答
        cuo: list[str] = []
        feng: list[int] = []
        try:
            d = self.gw.ren_wu(self.jia["deviceId"])
            self.assertIsNotNone(d)
            for i in range(DENG_LI - 1):
                d.deng[f"r-{i}"] = queue.Queue()

            def qiang():
                try:
                    self.gw.qing(self.jia["deviceId"],
                                 {"method": "GET", "path": "/health", "query": "",
                                  "headers": {}, "body": None}, a3=0.5)
                except WuDui as e:  # noqa: BLE001 - 抢输的那 7 个走这里
                    cuo.append(e.message)

            xian = [threading.Thread(target=qiang) for _ in range(8)]
            for t in xian:
                t.start()
            while any(t.is_alive() for t in xian):
                feng.append(len(d.deng))
                # **这是采样间隔，不是等待**：这条要的是「8 个线程抢同一批名额的
                # 过程中，在途数有没有越过上限」——只能反复取样。缩短它只会多烧
                # CPU，缩短不了这条用例的耗时（耗时由线程本身决定）。
                time.sleep(0.01)
            for t in xian:
                t.join(timeout=5)
            self.assertLessEqual(max(feng), DENG_LI, "在途上限被越过")
            self.assertEqual(cuo.count("设备上在途请求过多"), 7)
            # 抢到的那条超时后自己摘掉，预填的 63 条留着——没有额外泄漏。
            self.assertEqual(len(d.deng), DENG_LI - 1)
        finally:
            q.guan()

    def test_song_zai_sui_dao_si_hou_bu_cha_ru(self):
        """M2 的顺序洞：`ren_wu()` 放行之后隧道才死，`_song` 必须在**插入前重查**
        `sheng`——否则那条队列被插进一张已经 `clear()` 过的表里，永远等不到唤醒，
        只能挂到自己的超时。

        直接调 `_song` 而不是走 `qing`：那个窗口只能在竞态中落到，`ren_wu()` 正常
        路径下会把死隧道滤掉，所以「插入前的重查」本身就是可测的那个单元。
        这里只把 `sheng` 置 False（连接对象还活着），于是重查是唯一的拦截点——
        少了它，`fa_wen` 会成功、`_song` 会静默返回一条死队列。
        """
        q = JiaQiao(self.duan, self.jia["deviceToken"])  # 不应答
        try:
            d = self.gw.ren_wu(self.jia["deviceId"])
            self.assertIsNotNone(d)
            d.sheng = False  # 模拟 `_lai` 的 finally 已经跑过
            kai = time.time()
            with self.assertRaises(WuDui) as c:
                self.gw._song(d, {"method": "GET", "path": "/health", "query": "",
                                  "headers": {}, "body": None}, 1.0, False)
            self.assertEqual(c.exception.code, "agent_unavailable")
            self.assertEqual(c.exception.message, "隧道已断开")
            self.assertLess(time.time() - kai, 0.5, "没有立刻拒绝，是发出去等了")
            self.assertEqual(d.deng, {}, "死队列被插进了表里")
        finally:
            q.guan()


class LiuTest(unittest.TestCase):
    def setUp(self):
        self.mu = tempfile.TemporaryDirectory()
        self.biao = SheBiao(Path(self.mu.name) / "devices.json", logging.getLogger("test.gw"))
        self.gw = TunnelGw(self.biao, "127.0.0.1", 0, logging.getLogger("test.gw"))
        self.gw.qi_dong()
        self.duan = self.gw.duan_kou()
        self.jia = self.biao.jia("local", "本机", "i-test")

    def tearDown(self):
        self.gw.ting_zhi()
        self.mu.cleanup()

    def _liu_xing_wei(self, shu=3):
        def f(q, x):
            if x["t"] != "request":
                return
            q.hui("response", id=x["id"], status=200,
                  headers={"content-type": "text/event-stream; charset=utf-8"},
                  body="", b64=False)
            for i in range(1, shu + 1):
                q.hui("frame", id=x["id"], frame={"type": "message",
                                                  "sessionId": "s-1", "streamSeq": i})
        return f

    def test_liu_zhen_shun_xu_bing_jie_shu(self):
        q = JiaQiao(self.duan, self.jia["deviceToken"], self._liu_xing_wei(3))
        try:
            tou, liu = self.gw.kai_liu(self.jia["deviceId"],
                                       {"method": "GET", "path": "/stream",
                                        "query": "", "headers": {}, "body": None})
            self.assertEqual(tou["status"], 200)
            xu = []
            for _ in range(3):
                z = liu.zhen(a1=3.0)
                self.assertIsNotNone(z)
                xu.append(z["streamSeq"])
            self.assertEqual(xu, [1, 2, 3])
            liu.guan()
        finally:
            q.guan()

    def test_guan_fa_close_gei_bridge(self):
        """Review Focus / spec 6.3：浏览器断开时网关必须让 Bridge 关掉那条本地连接。"""
        q = JiaQiao(self.duan, self.jia["deviceToken"], self._liu_xing_wei(1))
        try:
            tou, liu = self.gw.kai_liu(self.jia["deviceId"],
                                       {"method": "GET", "path": "/stream",
                                        "query": "", "headers": {}, "body": None})
            liu.zhen(a1=3.0)
            liu.guan()
            self.assertTrue(q.deng_ge("close"), "Bridge 没收到 close")
        finally:
            q.guan()

    def test_guan_shi_mi_deng(self):
        q = JiaQiao(self.duan, self.jia["deviceToken"], self._liu_xing_wei(1))
        try:
            tou, liu = self.gw.kai_liu(self.jia["deviceId"],
                                       {"method": "GET", "path": "/stream",
                                        "query": "", "headers": {}, "body": None})
            liu.guan()
            liu.guan()  # 第二次不能抛
        finally:
            q.guan()

    def test_liu_zai_sui_dao_duan_shi_fan_hui_none(self):
        q = JiaQiao(self.duan, self.jia["deviceToken"], self._liu_xing_wei(1))
        tou, liu = self.gw.kai_liu(self.jia["deviceId"],
                                   {"method": "GET", "path": "/stream",
                                    "query": "", "headers": {}, "body": None})
        liu.zhen(a1=3.0)
        q.guan()
        self.assertIsNone(liu.zhen(a1=5.0))

    def test_liu_zai_bridge_fa_close_shi_jie_shu(self):
        """M4a / spec 6.3：`close` 是**双向**的——Bridge 发 close 也必须让网关这条路
        结束，而且是立刻结束（不是等满 `zhen(a1=...)` 的超时）。"""
        def f(q, x):
            if x["t"] != "request":
                return
            q.hui("response", id=x["id"], status=200,
                  headers={"content-type": "text/event-stream"}, body="", b64=False)
            q.hui("close", id=x["id"], why="done")

        q = JiaQiao(self.duan, self.jia["deviceToken"], f)
        try:
            tou, liu = self.gw.kai_liu(self.jia["deviceId"],
                                       {"method": "GET", "path": "/stream",
                                        "query": "", "headers": {}, "body": None})
            kai = time.time()
            self.assertIsNone(liu.zhen(a1=5.0))
            self.assertLess(time.time() - kai, 2.0)
            liu.guan()
        finally:
            q.guan()

    def test_liu_zhi_chi_with(self):
        """Interfaces：`Liu` 支持 `with`——出块即 guan，close 走到 Bridge。"""
        q = JiaQiao(self.duan, self.jia["deviceToken"], self._liu_xing_wei(1))
        try:
            tou, liu = self.gw.kai_liu(self.jia["deviceId"],
                                       {"method": "GET", "path": "/stream",
                                        "query": "", "headers": {}, "body": None})
            with liu:
                self.assertIsNotNone(liu.zhen(a1=3.0))
            self.assertTrue(q.deng_ge("close"), "with 退出没给 Bridge 发 close")
        finally:
            q.guan()


class ChaoDaTest(unittest.TestCase):
    def setUp(self):
        self.mu = tempfile.TemporaryDirectory()
        self.biao = SheBiao(Path(self.mu.name) / "devices.json", logging.getLogger("test.gw"))
        self.gw = TunnelGw(self.biao, "127.0.0.1", 0, logging.getLogger("test.gw"))
        self.gw.qi_dong()
        self.duan = self.gw.duan_kou()
        self.jia = self.biao.jia("local", "本机", "i-test")

    def tearDown(self):
        self.gw.ting_zhi()
        self.mu.cleanup()

    def test_chao_da_duan_kai(self):
        """Review Focus 2：超过 1 MiB 的消息要断开而不是截断（spec 6.6）。

        「没截断」由 `fa_wen` 返回 False 证明；**「断开了」要另外证**——Bridge 侧
        必须真看到连接结束，否则线上可能是「一个超限消息被静默丢掉、隧道照旧」。
        """
        q = JiaQiao(self.duan, self.jia["deviceToken"], hui_dan())
        try:
            d = self.gw.ren_wu(self.jia["deviceId"])
            self.assertIsNotNone(d)
            da = zhen("frame", id="r-1", frame={"pad": "x" * (2 << 20)})
            self.assertFalse(d.fa_wen(json.loads(da)))
            self.assertFalse(d.sheng)
            deng_dai(lambda: not q.tiao.is_alive(), chao=5.0,
                     msg=lambda: q.tiao.is_alive())
            self.assertFalse(q.tiao.is_alive(), "线上没断：Bridge 侧连接还活着")
        finally:
            q.guan()


class JieJiaoChaTest(unittest.TestCase):
    """Repair R1：解绑与建隧道交错时，已解绑设备不得留下隧道。"""

    def setUp(self):
        self.mu = tempfile.TemporaryDirectory()
        self.biao = SheBiao(Path(self.mu.name) / "devices.json", logging.getLogger("test.gw"))
        self.gw = TunnelGw(self.biao, "127.0.0.1", 0, logging.getLogger("test.gw"))
        self.gw.qi_dong()
        self.duan = self.gw.duan_kou()
        self.jia = self.biao.jia("local", "本机", "i-test")

    def tearDown(self):
        self.gw.ting_zhi()
        self.mu.cleanup()

    def test_jie_jiao_cha(self):
        """R1：装表那一刻已解绑的设备，不得建起隧道。

        把 `SheBiao.ren` 包一层，让它在**返回 ok 之前**就解绑。这精确命中那个
        交错：握手校验已经放行，`_lai` 装表时设备却已失效。`ren` 与 `jie` 都是
        同步的，`jie()` 必然在装表前跑完，所以这条用例不靠 sleep、不靠概率。

        **为什么复查必须在装表之后**：`jie()` 只拿 `SheBiao.suo`，与网关的
        `self.suo` 无关，`duan()` 又是解绑之后才跑。因此「装表前复查」与装表之间
        仍留着一个可被 `jie()` 插进来的缝（`_xie()` 里的 icacls 与 `os.replace`
        会释放 GIL，字节码级的原子性挡不住它），缝里的设备就会带着一条永久隧道。
        """
        yuan_ren = self.biao.ren

        def ren(ma):
            ji, _ = yuan_ren(ma)
            self.biao.jie(self.jia["deviceId"])  # 校验放行前就解绑
            return ji, "ok"  # 谎报 ok，复现「校验已过、装表时已失效」

        self.biao.ren = ren
        try:
            k = connect(f"ws://127.0.0.1:{self.duan}/bridge/tunnel",
                        additional_headers={
                            "Authorization": f"Bearer {self.jia['deviceToken']}",
                            "X-Protocol-Version": XIYI, "X-Instance-Id": "i-test"},
                        proxy=None, ping_interval=15, ping_timeout=45,
                        max_size=1 << 20, open_timeout=5)
            try:
                zhen_lai = k.recv(timeout=5)
                self.fail(f"已解绑设备拿到了帧（不该收到 welcome）：{zhen_lai}")
            except ConnectionClosed:
                pass  # 期望：连接在发 welcome 之前就被关掉
            except TimeoutError:
                self.fail("连接既没被关也没发帧：网关把这条隧道留下了")
            finally:
                k.close()
            self.assertIsNone(self.gw.ren_wu(self.jia["deviceId"]),
                              "已解绑设备仍留在网关的设备表里")
            # lastSeenAt 的语义是「设备还活着」。给已解绑设备刷新它，
            # 前端就会显示一台早已失效的设备刚刚还在线。
            self.assertEqual(self.biao.zhao(self.jia["deviceId"])["lastSeenAt"], 0,
                             "给已解绑设备刷新了 lastSeenAt")
        finally:
            self.biao.ren = yuan_ren


def _kong() -> int:
    """要一个空闲端口。绑了就听、拿到端口再关——只 bind 在 Windows 上测不出占用。"""
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    p = s.getsockname()[1]
    s.close()
    return p


class ShengChanMoKeYiDaoTest(unittest.TestCase):
    """**生产模块不许从 `tests/` 导入东西。**

    这条不是形式主义。05 域为了让「关闭要能证明已完成」有个条件等待，把测试
    助手 `deng_dai` 直接 import 进 `lifeos/api/tunnel_gw.py`——pytest 下全绿
    （`tests/` 在 `sys.path` 里），真机启动主服务却立刻炸：

        ModuleNotFoundError: No module named 'gong_ju'

    也就是说**整条 05 域的测试都建立在一个真机跑不起来的模块上**，而它在
    阶段六真机验收第一次启动时才暴露。判据做成「起一个子进程按真机方式导入
    生产模块」，而不是扫源码——扫源码抓不到 `importlib`、`__import__` 和
    间接导入，而真机导入抓的是实际结果。
    """

    def test_sheng_chan_mo_ke_yi_dao(self):
        """按真机方式（`python -m lifeos.api.server`）导入，退出码必须 0。"""
        import subprocess
        import sys
        from pathlib import Path
        gen = Path(__file__).resolve().parents[1]
        r = subprocess.run(
            [sys.executable, "-c",
             "import lifeos.api.server, lifeos.api.tunnel_gw, "
             "lifeos.bridge.run, lifeos.bridge.tunnel; print('ok')"],
            cwd=str(gen), capture_output=True, text=True, timeout=120,
            # **清掉 PYTHONPATH**：本仓的 pytest 靠 conftest/rootdir 把 `tests/`
            # 塞进 sys.path，真机启动没有这一步。不清的话这条测试自己就成了
            # 「带着测试路径的导入」，照样绿——正是它要防的那种假绿。
            env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
        )
        self.assertEqual(r.returncode, 0,
                         f"生产模块导入失败（真机启动会炸）：\n{r.stderr[-1500:]}")
        self.assertIn("ok", r.stdout)

    def test_sheng_chan_wu_ce_shi_import(self):
        """源码层面：`lifeos/` 下不得出现 `from gong_ju` / `from test_`。

        与上一条互补：上一条抓实际导入结果，这条在**不依赖子进程**的前提下
        把规则钉在源码上，评审时一眼能看。两条都留——只留源码扫描的话，
        `importlib.import_module("gong_ju")` 这类写法能溜过去。
        """
        gen = Path(__file__).resolve().parents[1] / "lifeos"
        bad = []
        for p in gen.rglob("*.py"):
            for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                t = ln.strip()
                if t.startswith(("from gong_ju", "import gong_ju",
                                 "from test_", "import test_")):
                    bad.append(f"{p.relative_to(gen)}:{i}: {t}")
        self.assertEqual(bad, [], f"生产代码从 tests/ 导入了东西：\n" + "\n".join(bad))


class BuYongStopallTest(unittest.TestCase):
    """**测试里不许调用 `mock.patch.stopall()`。**

    `stopall()` 摘的是**全局**补丁栈：`unittest.mock` 维护一个模块级的
    `_patch._active_patches`，任何 `.start()` 挂上去的补丁都会被它一并停掉，
    无论挂的人是谁。

    危害不在于「今天会摘错东西」——今天全树只有 `test_pingju.py:565` 一个
    `.start()`，摘它没有别的后果。危害在于**新增一个 `.start()` 就会变成跨组
    互相踩**，而症状极难归因：那组测试会在**别的组**的 `tearDownClass` 之后
    读到没打补丁的真实值（真实 `~/.lifeos-bridge/users`、真实时钟、真实环境
    变量），报出来是「某处建出了真实目录」或「耗时突然变成 0」，与这两组
    测试都看不出关系。

    ⇒ 判据是**源码层面禁止**，因为它是规则而不是行为：要判「stopall 有没有
    摘掉别人的补丁」得先知道全局栈里此刻有什么，那正是本条要消除的不确定性。
    正确写法只有一种：`X = mock.patch.object(...).start()` 配 `X.stop()`
    （后进先出，`stop()` 只停自己那一个）。

    **判据必须落在「调用」上而不是「出现过这个词」**：本类的 docstring 与
    注释里到处写着 `stopall()`，按词扫会把自己判红——那是一条恒真的测试。
    调用与散文里提到它的区别只有一个：前面有没有 `patch.`。
    """

    def test_ce_shi_li_mei_you_diao_stopall(self):
        gen = Path(__file__).resolve().parents[1] / "tests"
        bad = []
        for p in sorted(gen.rglob("*.py")):
            for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                t = ln.strip().lstrip("#").strip()
                if re.match(r"(?:mock\.)?patch\.stopall\s*\(", t):
                    bad.append(f"{p.relative_to(gen)}:{i}: {ln.strip()}")
        self.assertEqual(bad, [], "测试里调了 mock.patch.stopall()，"
                                   "改用自己那个补丁对象的 .stop()：\n" + "\n".join(bad))


class GuanBiWanChengTest(unittest.TestCase):
    """关闭要能证明「已完成」，不是「已发起」（阶段六收口 05 域）。

    **原来的 `ting_zhi()` 做不到证明**：`join(timeout=5)` 之后直接置 `None`，
    无论线程退没退出都返回 None。调用方（含 `run.py::main()`）于是只能
    「关完就当关了」——而真实故障是连接处理线程带着旧连接活过关闭，
    换实例重启还会留下持有旧网关的孤儿线程。

    这一组用**条件等待**判定完成，不许固定 sleep：睡满再断言一次只看得见
    窗口末端那一个时刻。
    """

    def setUp(self):
        self.mu = tempfile.TemporaryDirectory()
        self.biao = SheBiao(Path(self.mu.name) / "devices.json", logging.getLogger("t.05"))
        self.gw = TunnelGw(self.biao, "127.0.0.1", 0, logging.getLogger("t.05"))
        self.gw.qi_dong()
        self.duan = self.gw.duan_kou()
        self.jia = self.biao.jia("local", "本机", "i-test")

    def tearDown(self):
        try:
            self.gw.ting_zhi()
        except Exception:  # noqa: BLE001
            pass
        self.mu.cleanup()

    def _qiao(self):
        return JiaQiao(self.duan, self.jia["deviceToken"], hui_dan())

    def _zhen_xiang(self):
        """此刻的关闭诊断：活动连接、线程、在途 request id。"""
        return self.gw.guan_bi_diagnostic()

    def test_ke_hu_duan_zhi_dong_guan_bi(self):
        """客户端主动关闭 → 在途表清空、隧道不可用、handler 线程退出。"""
        q = self._qiao()
        try:
            self.gw.qing(self.jia["deviceId"],
                         {"method": "GET", "path": "/health", "query": "",
                          "headers": {}, "body": None})
            # 在途请求挂起时断开，是「唤醒所有等待方」那条不变式的正题
            hang = threading.Thread(
                target=lambda: self._lan(self.jia["deviceId"], "/slow"),
                daemon=True)
            hang.start()
            deng_dai(lambda: bool(self.gw._zai_dian(self.jia["deviceId"])),
                     chao=5.0, msg="请求没进在途表")
        finally:
            q.guan()
        deng_dai(lambda: self.gw.zhuang_tai(self.jia["deviceId"]) == "offline",
                 chao=10.0, msg=lambda: self._zhen_xiang())
        deng_dai(lambda: self.gw._zai_dian(self.jia["deviceId"]) == {},
                 chao=10.0, msg=lambda: f"在途表没清空：{self._zhen_xiang()}")
        hang.join(10)
        # handler 线程真的退出了：诊断里不该再有这条隧道的活线程
        deng_dai(lambda: not self.gw._huo_lian_zhong(), chao=10.0,
                 msg=lambda: self._zhen_xiang())

    def _lan(self, did, path):
        try:
            self.gw.qing(did, {"method": "GET", "path": path, "query": "",
                               "headers": {}, "body": None})
        except WuDui:
            pass

    def test_fu_wu_duan_guan_bi_hou_ke_hu_bu_za_lian(self):
        """服务端关闭 → 网关完成关闭、客户端侧不再发起新连接。"""
        zhen = self.gw.ting_zhi(wan_cheng=True)
        self.assertFalse(duan_ke(self.duan), "网关端口还在监听")
        # 关闭完成后诊断必须能给出「现在确实没有活动对象」这个结论
        zhen = self.gw.guan_bi_diagnostic()
        self.assertTrue(zhen["guan_bi_wan_cheng"], f"关闭没完成：{zhen}")
        self.assertEqual(zhen["huo_lian_zhong"], 0, f"还有活连接：{zhen}")
        self.assertEqual(zhen["zai_tu_deng"], 0, f"在途表没清空：{zhen}")

    def test_guan_bi_wan_cheng_qian_bu_neng_shou_xin_wo_shou(self):
        """关闭完成后网关不再接受新握手。"""
        self.gw.ting_zhi()
        self.assertFalse(duan_ke(self.duan))
        # 再连必须失败，而不是「连上了但没人管」
        with self.assertRaises(Exception):
            connect(f"ws://127.0.0.1:{self.duan}/bridge/tunnel",
                    additional_headers={"Authorization":
                                       f"Bearer {self.jia['deviceToken']}"},
                    proxy=None, open_timeout=3)

    def test_guan_bi_chao_shi_lu_you_xin_xi(self):
        """**关闭未完成时诊断必须说得出「还剩什么」，不许静默假装成功。**

        造一个退不出去的 handler：把卡接到 `Dui.guan()` 上，它就一直卡在
        关闭握手里。`ting_zhi` 因此在**它自己那条线程上**被堵住——这正是
        「关不掉」的真实形状，也让本用例必须换一个观察位置：

        之前是「等 `ting_zhi` 返回再看它报什么」，可它不返回；而就算放卡后
        它返回了，那时也已经关完、报的是成功——测出来的是「超时了却报成功」
        这条反直觉的假红。正确的读法是**在关闭还在进行的途中**去问诊断：
        这才是调用方真遇到的情况（它不可能阻塞在关网上，只能轮询状态）。

        判据：`guan_bi_wan_cheng` 为假，且 `huo_xian_cheng` / `zai_tu_id` /
        `shuo_ming` 都有内容——「关不掉」这个结论必须配得上排查线索。
        """
        kan = threading.Event()
        kan.set()                            # **一直卡着**，直到诊断读完
        zhen_d = tunnel_gw.Dui.__init__

        def dai_gua(self, a, b, c):
            zhen_d(self, a, b, c)
            self._kan = kan
        q = self._qiao()
        try:
            tunnel_gw.Dui.__init__ = dai_gua
            tiao = threading.Thread(
                target=lambda: self.gw.ting_zhi(chao=0.5, wan_cheng=True), daemon=True)
            tiao.start()
            try:
                deng_dai(lambda: not self.gw.guan_bi_diagnostic()["guan_bi_wan_cheng"],
                         chao=5.0, msg=lambda: self.gw.guan_bi_diagnostic())
                zhen = self.gw.guan_bi_diagnostic()
            finally:
                kan.clear()                   # 放卡，让关闭真的走完
                tiao.join(10)
        finally:
            tunnel_gw.Dui.__init__ = zhen_d
            q.guan()
        self.assertFalse(zhen["guan_bi_wan_cheng"], "没关完却报成功")
        for k in ("huo_lian_zhong", "huo_xian_cheng", "zai_tu_deng", "shuo_ming"):
            self.assertIn(k, zhen, f"诊断缺 {k}")
        self.assertGreaterEqual(zhen["huo_xian_cheng"], 1, f"没报还活着的线程：{zhen}")
        self.assertTrue(zhen["shuo_ming"], "超时诊断没有一句说明")
        # 放卡之后它必须能真的关完——否则「关不掉」就成了永久状态
        self.assertTrue(self.gw.guan_bi_wan_cheng_ma(), f"放卡后仍关不掉：{zhen}")

    def test_bridge_ting_zhi_hou_bu_za_fa_qi_lian_jie(self):
        """Bridge 停止 → 重连线程退出，停止后不再出现新的连接尝试。"""
        duan = _kong()
        jia = self.biao.jia("local", "本机", "i-b")
        zong = ZongXian("t05", 1)
        sd = tunnel.SuiDao(None, {"deviceId": jia["deviceId"], "deviceToken": "dt-x",
                                  "zong": zong,
                                  "url": f"ws://127.0.0.1:{duan}/bridge/tunnel"})
        sd.qi_dong()
        deng_dai(lambda: sd.chong_lian_ci() >= 2, chao=30.0,
                 msg=lambda: f"只重连了 {sd.chong_lian_ci()} 轮")
        zhen = sd.ting_zhi(wan_cheng=True)
        self.assertTrue(zhen["guan_bi_wan_cheng"], f"关闭没完成：{zhen}")
        self.assertIsNone(sd.tiao, "重连线程句柄还在")
        ci = sd.chong_lian_ci()
        # **停止后不得再出现新的连接尝试。** 用 wei_bian 而不是睡满再断言：
        # 睡满只看窗口末端，而重连间隔最长 30 秒，正是最容易漏的形态。
        wei_bian(lambda: sd.chong_lian_ci(), chao=3.0,
                 msg=lambda: f"停止后又重连到 {sd.chong_lian_ci()} 轮（停止时是 {ci}）")

    def test_guan_bi_wu_chi_bu_neng_chi_xiang_dian_jing(self):
        """**accept 线程退不出去时，关闭不许报成功。**

        这是本域的变异锚点。原来 `ting_zhi` 是 `join(timeout=5)` 之后直接
        置 `None`——无论退没退出都返回 None，调用方只能「关完就当关了」。
        真实故障恰恰是 accept 循环卡住、线程带着旧连接活过关闭。

        造法踩过两个坑，都记在这里，因为它们都让测试「看起来在跑」而其实
        什么都没卡住：

        1. 只把 `join` 删掉、把句柄置 `None`，在 Windows 上**测不出差异**——
           `serve_forever` 收到 `shutdown()` 后几乎立刻就返回，观测到的完成
           时刻与 join 完几乎重合。
        2. 事后替换 `fu.serve_forever` 属性**无效**——那个线程在 `qi_dong()`
           里已按当时的属性起跑了，之后再换属性对它没有影响。第一版测试在
           真实实现下依然报「完成」，看着像变异没被覆盖，其实是根本没卡住。

        所以这里绕开 `qi_dong`，自己按「先卡住、再起线程」的顺序装配。
        """
        men = threading.Event()
        mu = tempfile.TemporaryDirectory()
        biao = SheBiao(Path(mu.name) / "d.json", logging.getLogger("t.05c"))
        gw = TunnelGw(biao, "127.0.0.1", 0, logging.getLogger("t.05c"))
        try:
            # 借 setUpClass 已起好的网关实例来拿 serve：这里只要一个
            # 「accept 线程卡住」的隧道网关，端口是不是真的在听无关紧要。
            gw.fu = _FuStub(men)
            gw.tiao = threading.Thread(target=gw.fu.serve_forever,
                                       name="tunnel-gw", daemon=True)
            gw.tiao.start()
            deng_dai(gw.tiao.is_alive, chao=5.0, msg="accept 线程没起来")
            zhen = gw.ting_zhi(chao=0.5, wan_cheng=True)
            self.assertFalse(zhen["guan_bi_wan_cheng"], "accept 线程没退出却报成功")
            self.assertIsNotNone(zhen["ting_zhi_lei_xian_cheng"],
                                 "诊断没指出还活着的那个线程")
            # 放卡之后必须能真的关完——否则「关不掉」就成了永久状态
            men.set()
            deng_dai(gw.guan_bi_wan_cheng_ma, chao=10.0,
                     msg=lambda: gw.guan_bi_diagnostic())
        finally:
            men.set()
            try:
                gw.ting_zhi(chao=5.0, wan_cheng=True)
            except Exception:  # noqa: BLE001
                pass
            mu.cleanup()


class _FuStub:
    """只提供 `serve_forever` 的假 server：卡在 men 上，shutdown 叫不走它。

    **不用真 server。** 真 `serve_forever` 收到 `shutdown()` 后几乎立刻就返回，
    「join 与不 join」观测不到差别——那样这条测试就成了永远绿。
    """

    def __init__(self, men):
        self.men = men

    def serve_forever(self, *a, **kw):
        self.men.wait(30)

    def shutdown(self):
        pass        # 明确叫不走：这就是本用例要造的那条形状

    def socket(self):
        raise AssertionError("这个桩不提供 socket")


class _DaXie:
    """假的在途响应句柄：只记自己被关了没有。"""

    def __init__(self):
        self.guan_le = False
        self.zhan = None

    def close(self):
        self.guan_le = True
        if self.zhan is not None:
            self.zhan.guan = True
