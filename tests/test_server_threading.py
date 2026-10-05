"""主服务的线程化与 `/agent-api/*` 的逐连接 HTTP/1.1（spec 9.2、10.4 第 1、2 条）。

**这些断言守的是两条已经踩过的坑，都不是「跑通就算过」：**

1. **keep-alive 必须限定在 `/agent-api/*`。** 全局 `protocol_version = "HTTP/1.1"`
   会让 `test_pipei::test_pai_code_dai_body_bu_duan_lian_jie` 守的那个 RST 回归
   不复现（HTTP/1.0 下服务端响应完就关连接，正是那个 bug 的触发条件；
   一旦不关连接，断言从此什么都不证明）。所以这里正反两面都断言：老端点
   **仍然**是 HTTP/1.0，`/agent-api/*` 才是 HTTP/1.1。
2. **`/agent-api/*` 的每一个响应都要自带 content-length。** 漏一个，
   keep-alive 下下一个请求的解析就错位，症状是「偶发 400 或串响应」。
"""

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
from unittest import mock

from lifeos.api import bridge_admin
from lifeos.api.devices import PeiMa, SheBiao
from lifeos.api.server import NI_MING, LiAnHTTPServer, LifeOSRequestHandler
from lifeos.api.tunnel_gw import TunnelGw, XianLiu
from gong_ju import deng_dai, duan_ke


def _kong() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    p = s.getsockname()[1]
    s.close()
    return p


class JiaQiao:
    """假网关。只实现反代真正调得到的那几个方法。

    **刻意不复用 `TunnelGw`**：这里要验的是「主服务怎么搬上游的响应」，
    让真网关参与会把隧道协议的问题带进同一个断言里。
    """

    def __init__(self, a1=200, a2=None):
        self.hui = a1
        self.tou = a2
        self.shou_dao = []
        self.xian = XianLiu()

    def zhuang_tai(self, a1):
        return "connected"

    def qing(self, a1, a2, a3=30.0):
        self.shou_dao.append(a2)
        return {"status": self.hui, "headers": self.tou or {},
                "body": json.dumps({"ok": True, "path": a2["path"]}), "b64": False}

    def xian_liu(self, a1, a2, a3):
        """限流这一层**交给真的 `XianLiu`**。

        刻意不写「永远放行」：那会让本文件里每一条反代用例都在一个限流
        形同虚设的网关下跑，限流真坏掉时它们照样全绿（限流由
        `tests/test_gw_liuliang.py::FanDaiCeShi` 守）。
        """
        return TunnelGw.xian_liu(self, a1, a2, a3)


class Qiao:
    """一个能连着发多条请求的连接。**不复用 fixture**，每条用例自己 close。"""

    def __init__(self, a1):
        self.c = http.client.HTTPConnection("127.0.0.1", a1, timeout=5)

    def fa(self, a1, a2="GET", a3=None, a4=None):
        self.c.request(a2, a1,
                       body=None if a3 is None else json.dumps(a3),
                       headers=a4 or {})
        r = self.c.getresponse()
        b = r.read()
        return r, b

    def close(self):
        self.c.close()


class XianChengHuaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mu = tempfile.TemporaryDirectory()
        # `bridge_admin` 的装配是模块级全局，测试之间会互相踩。存旧值、收尾复原。
        cls.yuan = (bridge_admin.SHE, bridge_admin.GW, bridge_admin.MA)
        cls.biao = SheBiao(Path(cls.mu.name) / "devices.json", logging.getLogger("test.thread"))
        cls.gw = JiaQiao()
        bridge_admin.zhuang(cls.biao, cls.gw, PeiMa())
        cls.sheId = bridge_admin.pai_dui(bridge_admin.sheng_ma()["code"], "测试机", "i-thr")["deviceId"]
        cls.duan = _kong()
        cls.fu = LiAnHTTPServer(("127.0.0.1", cls.duan), LifeOSRequestHandler)
        threading.Thread(target=cls.fu.serve_forever, daemon=True).start()
        # 构造完就已经 bind+listen，等端口真的连得上，别按固定时长猜。
        deng_dai(lambda: duan_ke(cls.duan), chao=5.0,
                 msg=f"端口 {cls.duan} 连不上")

    @classmethod
    def tearDownClass(cls):
        cls.fu.shutdown()
        cls.fu.server_close()
        bridge_admin.zhuang(*cls.yuan)
        cls.mu.cleanup()

    def _ma(self):
        """领一枚新的 CSRF token（`yong_ma` 一次性，用过即换）。"""
        k = Qiao(self.duan)
        try:
            return json.loads(k.fa("/api/bridge/info")[1])["csrf"]
        finally:
            k.close()

    # ---------- 协议版本的作用域 ----------

    def test_lao_duan_dian_ren_geng_http10(self):
        """老端点必须仍是 HTTP/1.0：响应完就关连接。

        这条是 `test_pipei::test_pai_code_dai_body_bu_duan_lian_jie` 的前提。
        它哪天绿了而那条测试变红，就说明全局 keep-alive 漏进来了。
        """
        k = Qiao(self.duan)
        try:
            r, _ = k.fa("/api/settings/delegation")
            self.assertEqual(r.version, 10)
        finally:
            k.close()

    def test_agent_api_cai_yong_http11(self):
        """`/agent-api/*` 逐连接提版本。**不写回类属性**——写回去就是全局。"""
        k = Qiao(self.duan)
        try:
            r, b = k.fa("/agent-api/agents")
            self.assertEqual(r.version, 11)
            self.assertEqual(r.status, 200)
            self.assertEqual(json.loads(b)["ok"], True)
        finally:
            k.close()

    def test_liu_cheng_hua_pei_zhi(self):
        """`ThreadingHTTPServer`（10.4 第 1 条）+ 允许复用端口。"""
        self.assertTrue(issubclass(LiAnHTTPServer, __import__(
            "http.server", fromlist=["ThreadingHTTPServer"]).ThreadingHTTPServer))
        self.assertTrue(LiAnHTTPServer.daemon_threads)
        self.assertTrue(LiAnHTTPServer.allow_reuse_address)

    # ---------- keep-alive 下逐端点验（spec 9.2 的连带责任） ----------

    def test_tong_lian_liang_ge_qing_qiu_dou_zheng_que(self):
        """HTTP/1.1 下同一个连接发两次；任何一处漏写 content-length 都会串响应。"""
        k = Qiao(self.duan)
        try:
            r1, b1 = k.fa("/agent-api/agents")
            self.assertEqual(r1.status, 200)
            r2, b2 = k.fa("/agent-api/agents")
            self.assertEqual(r2.status, 200)
            self.assertEqual(r2.version, 11)
            self.assertEqual(json.loads(b1), json.loads(b2))
        finally:
            k.close()

    def test_502_ye_yao_you_content_length(self):
        """没有网关的 502 路径同样要写 content-length（`_send_json` 之外的分支）。"""
        bridge_admin.zhuang(self.biao, None, bridge_admin.MA)
        try:
            k = Qiao(self.duan)
            try:
                r1, b1 = k.fa("/agent-api/agents")
                self.assertEqual(r1.status, 502)
                self.assertEqual(int(r1.getheader("content-length")), len(b1))
                # 同一个连接上再发一条。解析没错位才会走到这里拿到 502。
                r2, _ = k.fa("/agent-api/agents")
                self.assertEqual(r2.status, 502)
            finally:
                k.close()
        finally:
            bridge_admin.zhuang(self.biao, self.gw, bridge_admin.MA)

    def test_mei_you_she_bei_ye_yao_you_content_length(self):
        """没有配对设备的 502 路径（第三条 `_send_json` 之外的分支）。"""
        biao = SheBiao(Path(self.mu.name) / "empty.json", logging.getLogger("test.thread2"))
        bridge_admin.zhuang(biao, self.gw, bridge_admin.MA)
        try:
            k = Qiao(self.duan)
            try:
                r1, b1 = k.fa("/agent-api/agents")
                self.assertEqual(r1.status, 502)
                self.assertEqual(int(r1.getheader("content-length")), len(b1))
                r2, _ = k.fa("/agent-api/agents")
                self.assertEqual(r2.status, 502)
            finally:
                k.close()
        finally:
            bridge_admin.zhuang(self.biao, self.gw, bridge_admin.MA)

    def test_nei_rong_chang_du_zi_ji_chong_suan(self):
        """**上游的 content-length 一律丢掉、自己重算。**

        照抄上游的会在 base64 或编码差异下写成错的长度，keep-alive 下直接串响应。
        这里让上游报一个故意错的长度，返回值必须仍与实际字节数相等。
        """
        gw = JiaQiao(200, {"content-type": "application/json", "content-length": "9999",
                           "transfer-encoding": "chunked", "connection": "keep-alive"})
        bridge_admin.zhuang(self.biao, gw, bridge_admin.MA)
        try:
            k = Qiao(self.duan)
            try:
                r, b = k.fa("/agent-api/agents")
                self.assertEqual(int(r.getheader("content-length")), len(b))
                self.assertIsNone(r.getheader("transfer-encoding"))
                self.assertIsNone(r.getheader("connection"))
                # 下一个请求解析不出错位
                r2, _ = k.fa("/agent-api/agents")
                self.assertEqual(r2.status, 200)
            finally:
                k.close()
        finally:
            bridge_admin.zhuang(self.biao, self.gw, bridge_admin.MA)

    def test_b64_xiang_ying_chong_jie_ma(self):
        """Bridge 对非 UTF-8 的响应体走 base64（`tunnel.py:_fa_xiang`）。
        反代必须解回来，否则前端拿到的是一坨 base64 文本。"""
        zheng = b"\xff\xfe\x00binary"
        gw = mock.Mock()
        gw.zhuang_tai.return_value = "connected"
        # `Mock` 会凭空造出任何属性：`xian_liu` 不显式给就会返回一个 Mock，
        # `int(Mock)` 当场 TypeError。**这正是「假对象自带了判据要用的东西」
        # 那种假绿的来源**——所以这里把返回值钉成 None（放行）。
        gw.xian_liu.return_value = None
        gw.qing.return_value = {
            "status": 200, "headers": {"content-type": "application/octet-stream"},
            "body": base64.b64encode(zheng).decode("ascii"), "b64": True}
        bridge_admin.zhuang(self.biao, gw, bridge_admin.MA)
        try:
            k = Qiao(self.duan)
            try:
                r, b = k.fa("/agent-api/agents")
                self.assertEqual(b, zheng)
                self.assertEqual(int(r.getheader("content-length")), len(zheng))
            finally:
                k.close()
        finally:
            bridge_admin.zhuang(self.biao, self.gw, bridge_admin.MA)

    def test_zhuan_fa_chang_lan_dai_body(self):
        """请求体必须转过去。**`do_POST` 入口已经把它读进 `self._body` 了**，
        再读一次 `rfile` 只会拿到空串 ⇒ 转发出去的 body 永远是空的。"""
        k = Qiao(self.duan)
        try:
            ma = json.loads(k.fa("/api/bridge/info")[1])["csrf"]
            shen = {"cwd": "D:/tmp", "permissionMode": "default"}
            r, b = k.fa("/agent-api/sessions", "POST", shen,
                        {"content-type": "application/json", "x-lifeos-csrf": ma})
            self.assertEqual(r.status, 200)
        finally:
            k.close()
        song = self.gw.shou_dao[-1]
        self.assertEqual(song["method"], "POST")
        self.assertEqual(song["path"], "/sessions")
        self.assertEqual(json.loads(song["body"]), shen)

    def test_wu_ti_de_get_biao_bu_neng_duo_ci(self):
        """**带体的 GET 不得把 rfile 读两次。**

        `do_GET` 没有 `_du_wan` 预读，`_ti_zi()` 的回退分支每次都去读——写成
        `self._ti_zi().decode() if self._ti_zi() else None` 就读了两次。第二次
        永远等不到 `content-length` 个字节（客户端只发了一份），整个请求挂到
        客户端超时，而不是回响应。

        判据用**声明了长度的 GET**：声明 0 字节那条走 `n=0` 的短路，压根不读
        rfile，验不到这条 bug。
        """
        k = Qiao(self.duan)
        try:
            r, b = k.fa("/agent-api/agents", "GET", None, None)
            self.assertEqual(r.status, 200)
        finally:
            k.close()
        self.assertIsNone(self.gw.shou_dao[-1]["body"])

    def test_dai_ti_de_get_body_zhi_du_yi_ci(self):
        """带体的 GET：body 要转过去，且**只读一次** rfile。"""
        k = Qiao(self.duan)
        try:
            k.c.request("GET", "/agent-api/agents", body=b"x" * 5)
            r = k.c.getresponse()
            b = r.read()
            self.assertEqual(r.status, 200)
            self.assertEqual(json.loads(b)["ok"], True)
        finally:
            k.close()
        self.assertEqual(self.gw.shou_dao[-1]["body"], "xxxxx")

    def test_zhuan_fa_chuan_yu_bu_dai_zhao_bu_dong_de_tou(self):
        """Host / content-length / Origin / CSRF 这些不能转过去：
        它们要么由隧道客户端重建，要么根本不是给 Bridge 的。"""
        k = Qiao(self.duan)
        try:
            ma = json.loads(k.fa("/api/bridge/info")[1])["csrf"]
            k.fa("/agent-api/agents?lastEventId=7", "POST", {},
                 {"content-type": "application/json", "x-lifeos-csrf": ma,
                  "Origin": "http://127.0.0.1:5173"})
        finally:
            k.close()
        tou = self.gw.shou_dao[-1]["headers"]
        self.assertEqual(self.gw.shou_dao[-1]["query"], "lastEventId=7")
        for k2 in ("host", "content-length", "origin", "x-lifeos-csrf", "connection"):
            self.assertNotIn(k2, tou)

    def test_gao_lou_dong_tiao_dao_zhao_bu_dong_de_wu_ding_fen_liu(self):
        """**`GET` 不收 CSRF。** `agentClient.get` 的 GET 不带这个头，
        `EventSource` 连自定义 header 都不支持——照抄 `_fangxing()` 会让真实
        界面 100% 403（spec 9.3 把 CSRF 限定在 POST/PUT/PATCH/DELETE）。"""
        k = Qiao(self.duan)
        try:
            r, _ = k.fa("/agent-api/agents")
            self.assertEqual(r.status, 200)
        finally:
            k.close()

    def test_gai_bian_tai_fang_fa_que_csrf(self):
        k = Qiao(self.duan)
        try:
            r, b = k.fa("/agent-api/sessions", "POST", {})
            self.assertEqual(r.status, 403)
            self.assertEqual(json.loads(b)["error"]["code"], "forbidden")
        finally:
            k.close()

    # ---------- 03 域：请求体预读与非法 UTF-8 边界 ----------

    def test_get_dai_ti_de_ting_zhi_zhi_du_yi_ci(self):
        """**带体的 GET 在拒绝路径上也必须先读净 body。**

        判据是「同连接下一条请求仍成功」——比数 socket 读了几次更可靠：
        `/agent-api/*` 是 HTTP/1.1 keep-alive，多读一次会把 body 字节留在
        收缓冲里，下一条请求的请求行解析拿到的是 body 而不是 `GET /...`，
        症状是偶发 501 `'{"x":1}GET ...'`。

        **两条路径都要走**。只测成功路径的话，回退分支（`_ti_zi()` 直接读
        rfile）恰好也只读一次，测试照样绿——而真正缺预读的是拒绝路径：
        无网关 502 与限流 429 都在 `_ti_zi()` 之前就 return 了，body 压根
        没被读，连接带着脏字节关掉。
        """
        yuan_gw = bridge_admin.GW
        try:
            for mo, shou_qi in ((502, lambda: None), (200, lambda: "q")):
                with self.subTest(mo=mo):
                    bridge_admin.GW = yuan_gw
                    if shou_qi() == "q":
                        # 限流打满：自己换一副干净限流器，不污染 setUpClass 的共享对象
                        yuan_xian, self.gw.xian = self.gw.xian, XianLiu()
                        try:
                            for _ in range(40):
                                if self.gw.xian_liu("__p__", NI_MING, "/sessions") is not None:
                                    break
                            self._de_429()
                        finally:
                            self.gw.xian = yuan_xian
                    else:
                        bridge_admin.GW = None
                        self._de_502()
        finally:
            bridge_admin.GW = yuan_gw

    def _de_502(self):
        """带体 GET 打到「无网关」拒绝路径：502 之后连接必须还能继续用。"""
        k = Qiao(self.duan)
        try:
            k.c.request("GET", "/agent-api/agents", body=b'{"x":1}')
            r = k.c.getresponse()
            b = r.read()
            self.assertEqual(r.status, 502)
            self.assertEqual(json.loads(b)["error"]["code"], "agent_unavailable")
            r2, b2 = k.fa("/agent-api/agents")
            self.assertEqual(r2.status, 502)
        finally:
            k.close()

    def _de_429(self):
        """带体 POST 打到 429 拒绝路径：429 之后连接必须还能继续用。"""
        k = Qiao(self.duan)
        try:
            k.c.request("POST", "/agent-api/sessions", body=b'{"cwd":"D:/x"}',
                        headers={"content-type": "application/json",
                                 "x-lifeos-csrf": self._ma()})
            r = k.c.getresponse()
            b = r.read()
            self.assertEqual(r.status, 429)
            self.assertEqual(json.loads(b)["error"]["code"], "rate_limited")
            r2, _ = k.fa("/agent-api/agents")
            self.assertNotEqual(r2.status, 501, "body 被当成了请求行")
        finally:
            k.close()

    def test_fei_fa_e_utf8_de_get_hui_400(self):
        """非法 UTF-8 的请求体在主服务边界就是 400，**不冲出 handler**。

        现状是 `_dai_li` 直接 `fan.decode("utf-8")`，非 UTF-8 字节抛
        `UnicodeDecodeError`。异常从 handler 穿出去，客户端拿到的是
        连接重置而不是那个错误码——「稳定 400」这条不变式现在不成立。
        """
        k = Qiao(self.duan)
        try:
            k.c.request("GET", "/agent-api/agents", body=bytes([0xff, 0xfe, 0xfd]))
            r = k.c.getresponse()
            b = r.read()
        finally:
            k.close()
        self.assertEqual(r.status, 400)
        self.assertEqual(json.loads(b)["error"]["code"], "invalid_request")
        # content-length 必须与实际响应体字节数一致，否则 keep-alive 下
        # 下一个请求的解析从错位开始。
        self.assertEqual(int(r.getheader("content-length")), len(b))

    def test_fei_fa_e_utf8_zhi_hou_lian_jie_ren_geng_yong(self):
        """400 之后同一连接必须还能用：脏字节不能污染下一条请求。

        这是「稳定 400」的另一半。只看状态码不够——响应头少写
        `content-length`、或者 handler 抛异常把连接搞成 RST，状态码那
        一栏照样可能好看，但连接已经废了。
        """
        k = Qiao(self.duan)
        try:
            k.c.request("GET", "/agent-api/agents", body=bytes([0xff, 0xfe]))
            r = k.c.getresponse()
            r.read()
            self.assertEqual(r.status, 400)
            r2, b2 = k.fa("/agent-api/agents")
            self.assertEqual(r2.status, 200)
            self.assertEqual(json.loads(b2)["ok"], True)
        finally:
            k.close()

    def test_wu_wang_guan_de_jue_jing_lu_ye_yao_xian_du_jing(self):
        """429 拒绝路径同样先读净请求体再响应（守住现有行为）。

        **自己换一副干净的限流器**，不打 `self.gw.xian`：那是 `setUpClass`
        里的共享对象，把它打满会让同类的其他用例一起 429，用例之间从此
        互相影响——先红的那条不一定还是同一个缺陷。
        """
        xian = self.gw.xian
        self.gw.xian = XianLiu()
        try:
            for _ in range(40):
                if self.gw.xian_liu("__probe__", NI_MING, "/sessions") is not None:
                    break
            k = Qiao(self.duan)
            try:
                k.c.request("POST", "/agent-api/sessions", body=b'{"cwd":"D:/x"}',
                            headers={"content-type": "application/json",
                                     "x-lifeos-csrf": self._ma()})
                r = k.c.getresponse()
                b = r.read()
                self.assertEqual(r.status, 429)
                self.assertEqual(json.loads(b)["error"]["code"], "rate_limited")
                # 拒绝后连接还能继续用：body 没被留在收缓冲里。判据是解析
                # **没被脏字节带歪**——绝不该是 501 `'{"cwd":...}POST'` 那种
                # 「把 body 当请求行」。
                r2, _ = k.fa("/agent-api/agents")
                self.assertNotEqual(r2.status, 501)
            finally:
                k.close()
        finally:
            self.gw.xian = xian

    def test_wu_ti_de_get_xing_wei_bian(self):
        """无体 GET（content-length 缺失或 0）行为不变：body 转发成 null。"""
        for tou in ({}, {"content-length": "0"}):
            k = Qiao(self.duan)
            try:
                r, _ = k.fa("/agent-api/agents", "GET", None, tou)
                self.assertEqual(r.status, 200)
            finally:
                k.close()
        self.assertIsNone(self.gw.shou_dao[-1]["body"])

    def test_he_fa_e_utf8_de_po_zheng_chang_shen_bu_bian(self):
        """合法 UTF-8 body 的转发结构一个字段都不许变（防「顺手改了协议」）。"""
        k = Qiao(self.duan)
        try:
            k.c.request("POST", "/agent-api/sessions",
                        body=json.dumps({"cwd": "D:/tmp", "note": "中文"}, ensure_ascii=False).encode("utf-8"),
                        headers={"content-type": "application/json",
                                 "x-lifeos-csrf": self._ma()})
            r = k.c.getresponse()
            r.read()
            self.assertEqual(r.status, 200)
        finally:
            k.close()
        song = self.gw.shou_dao[-1]
        self.assertEqual(song["method"], "POST")
        self.assertEqual(song["path"], "/sessions")
        self.assertEqual(json.loads(song["body"]),
                         {"cwd": "D:/tmp", "note": "中文"})
        self.assertNotIn("b64", song)
        self.assertNotIn("bodyB64", song)

    # ---------- 并发 ----------

    def test_man_qing_qiu_bu_du_sai_kuai_qing_qiu(self):
        """一条慢请求不能把整个主服务冻住（4.4 / 10.4 第 1 条）。"""

        jin = threading.Event()

        def man(a1):
            jin.set()        # 「真的进到 handler 里了」——原来这句是靠睡眠 0.2 秒猜的
            # **这条 2 秒是慢请求本身**，是刺激的一部分（占住服务线程），
            # 不是测试在等什么，必须留。
            time.sleep(2.0)
            a1._send_json({"markdown": "man"})

        k = Qiao(self.duan)
        try:
            with mock.patch.object(LifeOSRequestHandler, "_handle_export_markdown", man):
                t = threading.Thread(target=lambda: Qiao(self.duan).fa("/memory/markdown"),
                                     daemon=True)
                t.start()
                # 等慢请求真的进到那个 handler 里。原来固定 sleep 0.2 猜；桩子
                # 进门第一行就置位，等这个置位才真的能断言「快请求是在慢请求占住
                # 服务线程期间返回的」——猜短了这条就退化成了「慢请求还没开始」。
                deng_dai(jin.is_set, chao=5.0, msg="慢请求没进到 handler 里")
                kai = time.time()
                r, _ = k.fa("/api/settings/delegation")
                self.assertEqual(r.status, 200)
                self.assertLess(time.time() - kai, 1.0)
                t.join(timeout=10)
        finally:
            k.close()


class HuiQuanLaiYuanTest(unittest.TestCase):
    """`/api/bridge/pair` 的回环来源闸门**不是空转**（spec 8.3、11.4）。

    评审担心的是「任务 8 上了本地代理前置之后每个调用方都显示 127.0.0.1」。
    本类的存在就是为了把这条担心钉死：它绑 `0.0.0.0` 起服务，从真实 LAN 地址
    连进来必须拿到 403。哪天有人把 `/api/bridge/*` 也挂到反代上，这条会红。
    """

    def setUp(self):
        self.mu = tempfile.TemporaryDirectory()
        self.yuan = (bridge_admin.SHE, bridge_admin.GW, bridge_admin.MA)
        bridge_admin.zhuang(SheBiao(Path(self.mu.name) / "d.json", logging.getLogger("t.hq")),
                            None, PeiMa())
        # 绑 0.0.0.0 而不是 127.0.0.1：绑回环的话 LAN 地址根本连不上，
        # 测的就不是来源闸门而是防火墙。
        self.duan = _kong()
        self.fu = LiAnHTTPServer(("0.0.0.0", self.duan), LifeOSRequestHandler)
        threading.Thread(target=self.fu.serve_forever, daemon=True).start()
        # 服务绑的是 0.0.0.0，回环一样连得通（`duan_ke` 探的是 TCP 层，
        # 跟本组要测的来源闸门是两回事），所以这个等法在这里同样成立。
        deng_dai(lambda: duan_ke(self.duan), chao=5.0,
                 msg=f"端口 {self.duan} 连不上")

    def tearDown(self):
        self.fu.shutdown()
        self.fu.server_close()
        bridge_admin.zhuang(*self.yuan)
        self.mu.cleanup()

    def test_fei_hui_huan_lai_yuan_pei_dong_bei_jue(self):
        lan = _fei_hui_huan()
        if lan is None:
            self.skipTest("这台机器没有非回环地址，验不了来源闸门")
        k = http.client.HTTPConnection(lan, self.duan, timeout=5)
        try:
            k.request("POST", "/api/bridge/pair", body=json.dumps({"code": "X"}),
                      headers={"content-type": "application/json"})
            r = k.getresponse()
            d = json.loads(r.read())
        finally:
            k.close()
        self.assertEqual(r.status, 403)
        self.assertEqual(d["error"]["code"], "forbidden")

    def test_hui_huan_lai_yuan_ke_yong(self):
        """对照组：同一个端点从回环进来不被这条闸拦（否则上面那条是假绿）。"""
        k = http.client.HTTPConnection("127.0.0.1", self.duan, timeout=5)
        try:
            k.request("POST", "/api/bridge/pair", body=json.dumps({"code": "XXX-XXX"}),
                      headers={"content-type": "application/json"})
            r = k.getresponse()
            d = json.loads(r.read())
        finally:
            k.close()
        self.assertEqual(r.status, 400)   # 过了来源闸，卡在配对码无效
        self.assertEqual(d["error"]["code"], "invalid_request")


def _fei_hui_huan() -> str | None:
    """本机第一个非回环 IPv4。都没有返回 None。"""
    try:
        for x in socket.gethostbyname_ex(socket.gethostname())[2]:
            if not x.startswith("127."):
                return x
    except OSError:
        pass
    return None
