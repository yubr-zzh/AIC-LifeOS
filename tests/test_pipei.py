"""配对四步与设备管理端点（spec 8.1、8.3）。"""

from __future__ import annotations

import json
import logging
import http.client
import socket
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from lifeos.bridge import pipei, run
from lifeos.api import bridge_admin
from lifeos.api.devices import PeiMa, SheBiao
from lifeos.api.server import LifeOSRequestHandler


class JiaGw:
    """假网关：只实现设备列表要用的那一个方法。"""

    def __init__(self, a1):
        self.lian = a1

    def zhuang_tai(self, a1):
        return "connected" if a1 in self.lian else "offline"


class ZhuangPeiTest(unittest.TestCase):
    def setUp(self):
        self.mu = tempfile.TemporaryDirectory()
        self.biao = SheBiao(Path(self.mu.name) / "devices.json", logging.getLogger("test.pair"))
        self.ma = PeiMa()
        bridge_admin.zhuang(self.biao, None, self.ma)

    def tearDown(self):
        self.mu.cleanup()

    def test_sheng_ma_zai_dui_dao_she_bei(self):
        xin = bridge_admin.sheng_ma()
        self.assertRegex(xin["code"], r"^[A-Z2-9]{3}-[A-Z2-9]{3}$")
        ji = bridge_admin.pai_dui(xin["code"], "本机", "i-abc")
        self.assertTrue(ji["deviceId"].startswith("dev-"))
        self.assertTrue(ji["deviceToken"].startswith("dt_"))
        self.assertEqual(ji["userId"], bridge_admin.dang_qian_yong_hu())

    def test_ma_yi_ci_xing(self):
        xin = bridge_admin.sheng_ma()
        bridge_admin.pai_dui(xin["code"], "本机", "i-abc")
        with self.assertRaises(ValueError):
            bridge_admin.pai_dui(xin["code"], "本机", "i-abc")

    def test_ma_bu_dui_bao_valueerror(self):
        with self.assertRaises(ValueError):
            bridge_admin.pai_dui("XXX-XXX", "本机", "i-abc")

    def test_she_lie_bu_han_mingwen_token(self):
        xin = bridge_admin.sheng_ma()
        bridge_admin.pai_dui(xin["code"], "本机", "i-abc")
        # 用 dang_qian_yong_hu() 而不是字面量 "local"：否则非默认 LIFEOS_USER 下
        # 列表返空，下面两条 assertNotIn 会空洞通过。
        lie = bridge_admin.she_lie(bridge_admin.dang_qian_yong_hu())
        self.assertEqual(len(lie), 1)
        wen = json.dumps(lie)
        self.assertNotIn("dt_", wen)
        self.assertNotIn("deviceToken", wen)

    def test_online_lai_zi_wang_guan(self):
        """`online` 不在 devices.json 里，是 `she_lie` 现问网关得到（8.3）。"""
        # **两台必须属于不同用户**：2026-09-29 起「新配对顶掉旧设备」，
        # 同一用户再配一台会让前一台 revoked，那时这条用例的前提
        # （同用户两台并存、一在线一离线）就不可达了——而它断言的只是
        # `online`，`online` 来自网关、与 revoked 无关，所以照样会绿。
        # **那是假绿**：断言过得去，可达状态已经没了。
        ji1 = bridge_admin.pai_dui(self.ma.sheng("u-1")["code"], "本机", "i-abc")
        ji2 = bridge_admin.pai_dui(self.ma.sheng("u-2")["code"], "另一台", "i-def")
        bridge_admin.zhuang(self.biao, JiaGw({ji1["deviceId"]}), self.ma)
        lie = {x["deviceId"]: x for x in bridge_admin.she_lie()}
        self.assertTrue(lie[ji1["deviceId"]]["online"])
        self.assertFalse(lie[ji2["deviceId"]]["online"])

    def test_xin_pei_dui_ding_diao_jiu_de(self):
        """一台设备对一个账号（1.4）：新配对必须顶掉旧设备。

        不改的行为：旧设备永远占据 `/agent-api/*` 的代理目标（`du_she()` 取
        第一台未解绑设备，`lie()` 是配对先后序），而新 Bridge 带新 token
        ⇒ 网关按旧 deviceId 查不到 ⇒ 全线 502，症状伪装成「隧道 connected
        却全部不在线」。用户 2026-09-29 裁定：新配对顶掉旧设备。
        """
        jiu = bridge_admin.pai_dui(bridge_admin.sheng_ma()["code"], "旧机", "i-old")
        # 假网关要在**第二次配对之前**装上：顶掉的动作发生在配对那一刻，
        # 之后装就看不到 duan 了（setUp 装的是 None，正是「没有网关」的形态）。
        gw = mock.Mock()
        bridge_admin.zhuang(self.biao, gw, self.ma)
        xin = bridge_admin.pai_dui(bridge_admin.sheng_ma()["code"], "新机", "i-new")

        # 1. 代理目标换成新的
        self.assertEqual(bridge_admin.du_she()["deviceId"], xin["deviceId"])
        # 2. 旧令牌立即失效，语义是 revoked 而不是 bad（6.1 的顺序）
        zhao, yuan = self.biao.ren(jiu["deviceToken"])
        self.assertIsNone(zhao)
        self.assertEqual(yuan, "revoked")
        # 3. 记录不删（15.5：前端要看得见「已解绑」），只是不再是代理目标
        self.assertIn(jiu["deviceId"], {x["deviceId"] for x in bridge_admin.she_lie()})
        # 4. 旧设备的隧道立即断开，与 jie_bang() 同一套动作
        gw.duan.assert_called_once_with(jiu["deviceId"])
        # 5. 新令牌照旧可用
        self.assertEqual(self.biao.ren(xin["deviceToken"])[1], "ok")

    def test_pei_dui_bu_ying_xiang_bie_de_yong_hu(self):
        """顶掉只作用于同一账号。别人的设备不许被这台的新配对解绑。"""
        bridge_admin.pai_dui(self.ma.sheng("u-1")["code"], "我的旧机", "i-1")
        ta = bridge_admin.pai_dui(self.ma.sheng("u-2")["code"], "别人的机", "i-2")
        bridge_admin.pai_dui(self.ma.sheng("u-1")["code"], "我的新机", "i-3")
        self.assertEqual(self.biao.ren(ta["deviceToken"])[1], "ok",
                         "顶掉越界到了别的用户")
        self.assertEqual(len([x for x in bridge_admin.she_lie("u-2")
                              if not x.get("revoked")]), 1)

    def test_jie_bang_hou_bu_neng_zai_ren(self):
        xin = bridge_admin.sheng_ma()
        ji = bridge_admin.pai_dui(xin["code"], "本机", "i-abc")
        r = bridge_admin.jie_bang(ji["deviceId"])
        self.assertTrue(r["ok"])
        zhao, yuan = self.biao.ren(ji["deviceToken"])
        self.assertIsNone(zhao)
        self.assertEqual(yuan, "revoked")

    def test_jie_bang_hui_duan_diao_sui_dao(self):
        xin = bridge_admin.sheng_ma()
        ji = bridge_admin.pai_dui(xin["code"], "本机", "i-abc")
        gw = mock.Mock()
        bridge_admin.zhuang(self.biao, gw, self.ma)
        bridge_admin.jie_bang(ji["deviceId"])
        gw.duan.assert_called_once_with(ji["deviceId"])

    def test_xinxi_dai_shang_sui_dao_zhuang_tai(self):
        xin = bridge_admin.xinxi()
        self.assertIn("tunnelState", xin)
        self.assertIn("deviceId", xin)
        self.assertNotIn("token", xin)
        self.assertNotIn("deviceToken", xin)


class DuanDianTest(unittest.TestCase):
    """HTTP 层的三个端点：CSRF 闸、配对码一次性、列表不漏凭据。

    上面那组测的是 `bridge_admin` 的函数；这里测「接线」——端点分支、鉴权
    差异（pair 走配对码凭据而不是 CSRF）只有真的发一次请求才验得到。
    """

    @classmethod
    def setUpClass(cls):
        cls.mu = tempfile.TemporaryDirectory()
        cls.biao = SheBiao(Path(cls.mu.name) / "devices.json", logging.getLogger("test.pair.http"))
        bridge_admin.zhuang(cls.biao, None, PeiMa())
        cls.zhu = ThreadingHTTPServer(("127.0.0.1", 0), LifeOSRequestHandler)
        cls.zhu.daemon_threads = True
        cls.duan = cls.zhu.socket.getsockname()[1]
        threading.Thread(target=cls.zhu.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.zhu.shutdown()
        cls.zhu.server_close()
        cls.mu.cleanup()

    def _qing(self, a1, a2="GET", a3=None, a4=None):
        k = http.client.HTTPConnection("127.0.0.1", self.duan, timeout=5)
        # str 原样发（用来造畸形 body），dict 走 json
        k.request(a2, a1,
                  body=None if a3 is None else (a3 if isinstance(a3, str) else json.dumps(a3)),
                  headers={"content-type": "application/json", **(a4 or {})})
        hui = k.getresponse()
        d = json.loads(hui.read().decode("utf-8"))
        k.close()
        return hui.status, d

    def _ma(self):
        """领一枚新的 CSRF token（`yong_ma` 一次性，用过即换）。"""
        return self._qing("/api/bridge/info")[1]["csrf"]

    def test_meiyou_csrf_ju_diao(self):
        for lu, shen in [("/api/bridge/devices", "GET"),
                         ("/api/bridge/pair-code", "POST"),
                         ("/api/bridge/unpair", "POST")]:
            with self.subTest(lu=lu):
                ma, d = self._qing(lu, shen)
                self.assertEqual(ma, 403)
                self.assertEqual(d["error"]["code"], "forbidden")

    def test_kuayuan_laiyuan_ju_diao(self):
        """带合法 CSRF——不然先被 CSRF 闸挡掉，这条对 Origin 检查什么都没验到。"""
        for yuan in ("http://example.com",            # 别人的站
                     "http://127.0.0.1:9999"):        # 本机但端口不在白名单
            with self.subTest(yuan=yuan):
                ma, _ = self._qing("/api/bridge/pair-code", "POST", {},
                                   {"Origin": yuan, "x-lifeos-csrf": self._ma()})
                self.assertEqual(ma, 403)

    def test_huaixing_body_bao_400(self):
        """畸形 / 非对象 body 要回 400，不是 500 也不是直接断连接。"""
        for lu in ("/api/bridge/pair", "/api/bridge/unpair"):
            for a3 in ("null", "[1]", "{oops"):
                with self.subTest(lu=lu, body=a3):
                    ma, d = self._qing(lu, "POST", a3, {"x-lifeos-csrf": self._ma()})
                    self.assertEqual(ma, 400)
                    self.assertEqual(d["error"]["code"], "invalid_request")

    def _song_kong_ti(self, a1, a2):
        """裸 socket 发一个只声明 content-length、正文一个字节都不发的 POST。

        发完头就半关连接（`SHUT_WR`），服务端 `rfile.read(20)` 读到 EOF 立刻
        返回空串——这条路径上「声明的长度」与「读到的字节数」必然分叉，
        所以判据选错了测试就是红的。
        """
        s = socket.create_connection(("127.0.0.1", self.duan), timeout=5)
        try:
            s.sendall((f"POST {a1} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                       f"content-type: application/json\r\n"
                       f"content-length: 20\r\n"
                       f"x-lifeos-csrf: {a2}\r\n\r\n").encode())
            s.shutdown(socket.SHUT_WR)
            fan = b""
            while True:
                yi = s.recv(65536)
                if not yi:
                    break
                fan += yi
            return int(fan.split(b" ")[1])
        finally:
            s.close()

    def test_shen_ming_chang_du_que_mei_fa_ti(self):
        """声明了 20 字节却没有 body 的请求要回 400，不是照常执行端点。

        入口统一读体之后 `_read_json` 的真值判据一度变成「读到的字节数」：
        没读到字节就当 `{}`，端点照常跑——`/api/settings/delegation` 于是静默
        写入 `delegation_enabled=False` 并回 200。判据必须是**声明的长度**。
        """
        yuan = LifeOSRequestHandler.agent.chat.delegation_enabled
        try:
            for lu in ("/api/bridge/unpair", "/api/settings/delegation"):
                with self.subTest(lu=lu):
                    self.assertEqual(self._song_kong_ti(lu, self._ma()), 400)
        finally:
            LifeOSRequestHandler.agent.chat.delegation_enabled = yuan

    def _song(self, a1, a2, a3):
        """裸 socket 发一次 POST，返回状态码。头与 body **分两段**发。

        `http.client` 一次发完的话两段会被并进同一个 TCP 段，body 字节顺手
        进了服务端 rfile 的缓冲区，就复现不出这个 bug。中间 sleep 一下，逼
        body 落到读头之后才到——这正是浏览器 fetch 的常态。
        """
        s = socket.create_connection(("127.0.0.1", self.duan), timeout=5)
        try:
            s.sendall((f"POST {a1} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                       f"content-type: application/json\r\n"
                       f"content-length: {len(a3)}\r\n"
                       f"x-lifeos-csrf: {a2}\r\n\r\n").encode())
            # **这一段 sleep 是刺激的一部分，不是测试在等什么**：它逼 body 落到
            # 读头之后才到，复现「头与体分两段到达」这个浏览器常态。去掉它这条
            # bug 就复现不出来，所以固定时长必须留着。
            time.sleep(0.02)
            s.sendall(a3)
            fan = b""
            while True:
                yi = s.recv(65536)
                if not yi:
                    break
                fan += yi
            return int(fan.split(b" ")[1])
        finally:
            s.close()

    def test_pai_code_dai_body_bu_duan_lian_jie(self):
        """pair-code 从不读请求体。body 字节还躺在 socket 收缓冲里时服务端就关
        连接，Windows 发 RST，客户端拿到 10053/10054 而不是那个 200。

        `_song` 强制 body 另起一个 TCP 段，所以这条是**确定性**触发：
        去掉 `_du_wan()` 后每一次迭代都红，5 次足够，不必靠重复次数买检出力。
        """
        cuo = []
        for i in range(5):
            try:
                ma = self._qing("/api/bridge/info")[1]["csrf"]   # token 一次性
                zhuang = self._song("/api/bridge/pair-code", ma, b'{"a":"b"}')
            except OSError as exc:
                cuo.append(f"第 {i} 次连接被断：{exc!r}")
                continue
            if zhuang != 200:
                cuo.append(f"第 {i} 次状态码 {zhuang}")
        self.assertEqual(cuo, [])

    def test_pair_liu_cheng_yu_yi_ci_xing(self):
        ma, xin = self._qing("/api/bridge/pair-code", "POST", {},
                             {"x-lifeos-csrf": self._ma()})
        self.assertEqual(ma, 200)
        ma, ji = self._qing("/api/bridge/pair", "POST",
                            {"code": xin["code"], "label": "本机", "instanceId": "i-http"})
        self.assertEqual(ma, 200)
        self.assertTrue(ji["deviceToken"].startswith("dt_"))
        # 同一个码再用一次：不存在 / 过期 / 已用过是同一句话、同一个状态码
        ma, zai = self._qing("/api/bridge/pair", "POST", {"code": xin["code"]})
        self.assertEqual(ma, 400)
        self.assertEqual(zai["error"]["code"], "invalid_request")
        ma, lie = self._qing("/api/bridge/devices", "GET", None,
                             {"x-lifeos-csrf": self._ma()})
        self.assertEqual(ma, 200)
        wen = json.dumps(lie, ensure_ascii=False)
        self.assertNotIn("dt_", wen)
        self.assertNotIn("tokenHash", wen)
        self.assertTrue(any(x["deviceId"] == ji["deviceId"] for x in lie["devices"]))


class YunJinDuYiRuKouTest(unittest.TestCase):
    """`runtime.json` 的读改写只有一个入口、一把锁（阶段六收口 04 域）。

    **不锁的症状是丢一次写。** 两个 HTTP 线程同时 spawn 不同会话，各读到
    同一份旧内容，后写的把先写的 `pids` 抹掉，留下一个下次启动也回收不掉
    的孤儿 `claude`。更隐蔽的是「各模块自己上一把锁」——那仍然是两个临界区。
    """

    def setUp(self):
        self.mu = tempfile.TemporaryDirectory()
        self.gen = run.wen_jia_ming(Path(self.mu.name))
        self.mu2 = tempfile.TemporaryDirectory()
        self.yun = run.zao_yun({}, 8766, "a" * 64, "i-abc", 0, "0.2.160", "2.1.283")
        pipei.gai(self.gen, self.yun)

    def tearDown(self):
        self.mu.cleanup()
        self.mu2.cleanup()

    def _du(self):
        return json.loads(self.gen.read_text(encoding="utf-8"))

    def test_san_zu_qian_bing_xie_bu_di_yao_ke(self):
        """配对、PID、隧道状态三组字段并发写，落盘后一个都不丢。"""
        tiao = [
            threading.Thread(target=pipei.gai, args=(
                self.gen, {"deviceId": "d-1", "deviceToken": "dt-1", "userId": "u-1"})),
            threading.Thread(target=run.bao_xie,
                             args=(Path(self.mu2.name), self.yun, [11, 22], False)),
            threading.Thread(target=pipei.gai, args=(self.gen, {"tunnelState": "connected"})),
        ]
        for t in tiao:
            t.start()
        for t in tiao:
            t.join(10)
        yun = self._du()
        self.assertEqual(yun["deviceId"], "d-1")
        self.assertEqual(yun["deviceToken"], "dt-1")
        self.assertEqual(yun["userId"], "u-1")
        self.assertEqual(yun["tunnelState"], "connected")

    def test_mao_de_gai_dai_pids_ye_bu_di_yao_ke(self):
        """**启动初始化与配对并发**，落盘后凭据还在。

        这是 `xie_runtime` 当年那条旁路的真实形状：启动时整份写一份
        「未配对」的快照，同时另一条路径正在写配对凭据。旧实现不过
        `XIE_SUO`、不合并盘上已有键，于是启动那份把刚写进去的
        deviceId/deviceToken 整个盖掉——用户配对刚做完就被退回未配对，
        日志里什么都没有。

        判据用**轮询**而不是一次读：盖掉与没盖掉取决于两个线程谁后落盘，
        一次读可能恰好读到中间态就误判成「没丢」。这里要的是「最终状态
        稳定正确」，所以反复写、最后再断言凭据在。
        """
        for _ in range(30):
            tiao = [
                threading.Thread(target=run.xie_runtime,
                                 args=(Path(self.mu.name), self.yun)),
                threading.Thread(target=pipei.gai, args=(
                    self.gen, {"deviceId": "d-9", "deviceToken": "dt-9", "userId": "u-9"})),
            ]
            for t in tiao:
                t.start()
            for t in tiao:
                t.join(10)
        yun = self._du()
        self.assertEqual(yun.get("deviceId"), "d-9", "配对凭据被启动快照盖掉了")
        self.assertEqual(yun.get("deviceToken"), "dt-9")
        self.assertEqual(yun.get("userId"), "u-9")

    def test_chi_fan_bing_fa_xie_hou_jiang_ran_he_fa_fa_mian(self):
        """反复并发写 200 次后文件仍是合法 JSON，各写者字段语义正确。"""
        cuo = []

        def xie_ma(i):
            cuo.append(threading.Thread(
                target=pipei.gai, args=(self.gen, {"userId": f"u-{i}"})))

        for i in range(200):
            xie_ma(i)
        for t in cuo:
            t.start()
        for t in cuo:
            t.join(20)
        yun = self._du()          # 能读出来 = 仍是合法 JSON
        self.assertTrue(yun["userId"].startswith("u-"))   # 最后一个赢
        self.assertEqual(yun["port"], 8766)               # 别人的键一个没少

    def test_sheng_chan_dai_ma_bie_you_zhi_jie_xie_yun_wen_de(self):
        """**生产代码里不存在绕过唯一入口的 runtime 写路径**（源码扫描）。

        `xie_runtime` 当年是整份 `write_json` 覆盖且不过 `XIE_SUO` 的第二写
        入口。它「只有测试在调」不是理由——一条只在测试里出现的写路径，
        正是下一次有人顺手拿它做初始化时踩坑的形状。这里让它在生产代码里
        彻底消失，而不是留个「大家都别用」的旁路。

        **只查 runtime 的写路径，不查别的落盘。** `cun.py` 直接调
        `write_json` 写 sessions.json 是对的——那是阶段 5 持久化层自己的
        owner，有自己的锁和自己的文件。一刀切禁掉 `write_json(` 会把
        正确的代码也判成违规，这条测试立刻变成谁都不敢动的摆设。
        """
        for f in Path(pipei.__file__).parent.glob("*.py"):
            if f.name == "pipei.py":
                continue          # 唯一入口自己当然要调 write_json
            wen = f.read_text(encoding="utf-8")
            for x in ("xie_runtime(wen_jia_ming(", "xie_runtime(runtime",
                      "write_json(runtime", "write_json(p, a2)"):
                self.assertNotIn(x, wen,
                                 f"{f.name} 里有 {x}，绕过了唯一写入口")
        # 唯一入口真的在锁里：**落盘那一刻 XIE_SUO 必须已被持有**。
        # 判据用 `_is_owned()` 而不是「类名是 RLock」——类型对了但临界区
        # 写错了地方（锁在调用方一层、又开了一把），类型检查照样通过。
        suo_dang_chi = []
        zhen_xie = pipei._xie
        try:
            pipei._xie = lambda p, y: (suo_dang_chi.append(pipei.XIE_SUO._is_owned()),
                                       zhen_xie(p, y))[1]
            pipei.gai(self.gen, {"tunnelState": "connected"})
            pipei.gai_quan(self.gen, {"port": 8766})
        finally:
            pipei._xie = zhen_xie
        self.assertEqual(suo_dang_chi, [True, True], "落盘时没持 XIE_SUO")

    def test_huai_wen_jian_jiang_ji_bing_you_lu_zhi(self):
        """坏文件降级为空对象并留下日志，配对与启动不被挡死。"""
        for huai in (b"{not json", b"", bytes([0xff, 0xfe, 0xfd])):
            self.gen.write_bytes(huai)
            with self.assertLogs("lifeos.bridge.pipei", level="WARNING") as cm:
                yun = pipei.gai(self.gen, {"tunnelState": "connected"})
            self.assertEqual(yun["tunnelState"], "connected")
            self.assertTrue(cm.output, f"坏文件 {huai!r} 没有留下任何日志")

    def test_shou_quan_mei_ci_xie_zhi_hou_dou_zhi_xing(self):
        """`shou_quan` 在每次写之后都执行（token 明文，泄漏即等于被指挥）。"""
        zhao = []
        zhen = pipei.shou_quan
        try:
            pipei.shou_quan = lambda p: zhao.append(p) or zhen(p)
            pipei.gai(self.gen, {"deviceToken": "dt-x"})
            run.bao_xie(Path(self.mu.name), self.yun, [1], False)
            run.xie_runtime(Path(self.mu.name), {**run.duan_runtime(self.gen)})
        finally:
            pipei.shou_quan = zhen
        self.assertEqual(len(zhao), 3, "三条写路径里有哪条没收紧权限")
        for p in zhao:
            self.assertEqual(Path(p), self.gen)
