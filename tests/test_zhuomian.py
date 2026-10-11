"""桌面化专项（方案 5.1/5.2/4.1）：bridge 看护阈值 / claude 运行时归口 /
桌面壳端口探测。

看护的承重逻辑是那套阈值（3 次失败、5 次/小时、懒启动不陪跑），不是循环
本身——`_yi_bu` 抽成纯函数后阈值可以直接钉死。claude 运行时的三个来源
优先级同理。
"""

from __future__ import annotations

import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from lifeos.api import bridge_admin
from lifeos.api import kanmen
from lifeos.bridge.adapters.claude_code import resolve_claude_runtime
from lifeos.desktop.main import _kong_kou


class KanMenTest(unittest.TestCase):
    def setUp(self):
        self.chong: list[float] = []

    def yi_bu(self, a1: int):
        return kanmen._yi_bu(a1, self.chong)

    def test_lan_qi_dong_bu_pei_pao(self):
        """runtime.json 不存在（没启过 bridge）→ 永不代拉（方案 5.2 懒启动）。"""
        with mock.patch.object(bridge_admin, "du_yunxing", return_value={}):
            dong, shi = self.yi_bu(0)
            self.assertEqual((dong, shi), ("skip", 0))

    def test_jian_kang_qing_ling(self):
        with mock.patch.object(bridge_admin, "du_yunxing", return_value={"port": 8766}), \
             mock.patch.object(kanmen, "_jian_kang", return_value=True):
            dong, shi = self.yi_bu(2)
            self.assertEqual((dong, shi), ("skip", 0))

    def test_san_ci_shi_bai_cai_chong_qi(self):
        with mock.patch.object(bridge_admin, "du_yunxing", return_value={"port": 8766}), \
             mock.patch.object(kanmen, "_jian_kang", return_value=False):
            shi = 0
            for _ in range(kanmen.LIAN_XU - 1):
                dong, shi = self.yi_bu(shi)
                self.assertEqual(dong, "skip")
            dong, shi = self.yi_bu(shi)
            self.assertEqual(dong, "restart")
            self.assertEqual(shi, 0)

    def test_dan_ci_dou_dong_bu_suan_si(self):
        """抖动恢复：失败 2 次后恢复健康，计数必须清零而不是攒着。"""
        with mock.patch.object(bridge_admin, "du_yunxing", return_value={"port": 8766}):
            with mock.patch.object(kanmen, "_jian_kang", return_value=False):
                _, shi = self.yi_bu(0)
                _, shi = self.yi_bu(shi)
            with mock.patch.object(kanmen, "_jian_kang", return_value=True):
                dong, shi = self.yi_bu(shi)
                self.assertEqual((dong, shi), ("skip", 0))

    def test_mei_xiao_shi_e_du(self):
        """1 小时内重启满 5 次 → 之后宁可让它死着也不无限白杀（方案 5.2）。"""
        import time as _t
        xian = _t.time()
        self.chong = [xian - i * 60 for i in range(kanmen.MEI_XIAO_SHI)]
        with mock.patch.object(bridge_admin, "du_yunxing", return_value={"port": 8766}), \
             mock.patch.object(kanmen, "_jian_kang", return_value=False):
            dong, _ = self.yi_bu(kanmen.LIAN_XU)
            self.assertEqual(dong, "skip")


class ClaudeYunXingShiTest(unittest.TestCase):
    def test_yong_hu_xian_shi_zhi_ding_you_xian(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "claude.exe"
            exe.write_bytes(b"")
            env = {"LIFEOS_CLAUDE_PATH": str(exe)}
            with mock.patch.dict("os.environ", env, clear=False):
                lu, zeng = resolve_claude_runtime()
                self.assertEqual(lu, str(exe))
                self.assertEqual(zeng, {})

    def test_bang_kun_mu_lu_ci_xuan(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "claude.exe"
            exe.write_bytes(b"")
            env = {"LIFEOS_BUNDLED_NODE": tmp,
                   "LIFEOS_CLAUDE_PATH": r"C:\definitely\not\here\claude.exe"}
            with mock.patch.dict("os.environ", env, clear=False):
                lu, _ = resolve_claude_runtime()
                self.assertEqual(lu, str(exe))

    def test_dou_mei_you_jiao_hui_sdk(self):
        env = {"LIFEOS_CLAUDE_PATH": r"C:\definitely\not\here\claude.exe",
               "LIFEOS_BUNDLED_NODE": r"C:\also\not\here"}
        with mock.patch.dict("os.environ", env, clear=False):
            with mock.patch.object(__import__("sys"), "frozen", False, create=True):
                lu, zeng = resolve_claude_runtime()
                self.assertIsNone(lu)
                self.assertEqual(zeng, {})


class KouTanCeTest(unittest.TestCase):
    def test_cong_kong_xian_kou_qi_zhao(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        zhan = s.getsockname()[1]
        s.close()
        self.assertEqual(_kong_kou(zhan, zhan + 5), zhan)

    def test_bei_zhan_zi_dong_shang_yi(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        zhan = s.getsockname()[1]
        self.assertEqual(_kong_kou(zhan, zhan + 5), zhan + 1)
        s.close()


class _JiaBridge:
    """假 Bridge：记下每个请求的 method/path/关键头，回一段 JSON。

    桌面直连代理（_dai_li_ben_di）的断言对象是「请求怎么被搬运」，
    真 Bridge 会把探测、鉴权那一堆变量带进来，不用它。
    """

    def __init__(self):
        import http.server
        self.shou_dao: list[dict] = []

        zhe = self

        class ChuLi(http.server.BaseHTTPRequestHandler):
            def _ji(self):
                zhang = int(self.headers.get("content-length") or 0)
                ti = self.rfile.read(zhang) if zhang else b""
                zhe.shou_dao.append({
                    "method": self.command,
                    "path": self.path,
                    "token": self.headers.get("X-Bridge-Token"),
                    "body": json.loads(ti) if ti else None,
                })
                hui = json.dumps({"ok": True}).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(hui)))
                self.end_headers()
                self.wfile.write(hui)

            do_GET = do_POST = _ji

            def log_message(self, *a):
                pass

        self.fu = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ChuLi)
        self.duan = self.fu.server_address[1]
        threading.Thread(target=self.fu.serve_forever, daemon=True).start()

    def ting(self):
        self.fu.shutdown()
        self.fu.server_close()


class ZhuoMianZhiLianTest(unittest.TestCase):
    """桌面直连代理的两条承重契约（2026-10-11 真机两病灶的回归钉）：

    1. **query 必须跟路走**——老写法只转发 `a1.path`，`/trust-check?path=…`
       到了 Bridge 手里只剩 `/trust-check`，回 400「path 不能为空」，
       桌面壳选完目录工作目录永远填不上。
    2. **不吃隧道形态的 CSRF 闸**——控制台的 /agent-api/* 调用按契约不带
       `X-LifeOS-CSRF`，桌面直连若照吃闸，会话建立、目录信任全部 403
       「CSRF token 无效或已用过」。桌面态的 CSRF 防线是登录闸 +
       SameSite=Strict 会话（见 server.py `_dai_li` 的注释），
       这里钉住「不带 CSRF 头的 POST 必须通」。
    """

    @classmethod
    def setUpClass(cls):
        import http.client
        cls.http = http.client

    def setUp(self):
        import logging
        from lifeos.api.devices import PeiMa, SheBiao
        from lifeos.api.server import LiAnHTTPServer, LifeOSRequestHandler
        self.jia = _JiaBridge()
        self.yuan = (bridge_admin.SHE, bridge_admin.GW, bridge_admin.MA)
        with tempfile.TemporaryDirectory() as tmp:
            biao = SheBiao(Path(tmp) / "devices.json", logging.getLogger("test.zm"))
            bridge_admin.zhuang(biao, None, PeiMa())
        self.huan = mock.patch.dict("os.environ", {"LIFEOS_DESKTOP": "1"}, clear=False)
        with self.huan:
            self.duan = _kong_kou(9300, 9320)
            self.fu = LiAnHTTPServer(("127.0.0.1", self.duan), LifeOSRequestHandler)
        threading.Thread(target=self.fu.serve_forever, daemon=True).start()

    def tearDown(self):
        self.fu.shutdown()
        self.fu.server_close()
        bridge_admin.zhuang(*self.yuan)
        self.jia.ting()

    def _fa(self, lu, fa="GET", ti=None, tou=None):
        c = self.http.HTTPConnection("127.0.0.1", self.duan, timeout=5)
        try:
            c.request(fa, lu,
                      body=None if ti is None else json.dumps(ti),
                      headers=tou or {})
            r = c.getresponse()
            return r.status, json.loads(r.read())
        finally:
            c.close()

    def test_query_geng_lu_zou(self):
        """`/trust-check?path=…` 的 query 必须原样到 Bridge，token 头照注入。"""
        with (mock.patch.object(bridge_admin, "du_yunxing",
                                return_value={"port": self.jia.duan, "token": "T"}),
              self.huan):
            zi, _ = self._fa("/agent-api/trust-check?path=D%3A%5Ctmp")
            self.assertEqual(zi, 200)
            self.assertEqual(self.jia.shou_dao[-1]["path"],
                             "/trust-check?path=D%3A%5Ctmp")
            self.assertEqual(self.jia.shou_dao[-1]["token"], "T")

    def test_post_bu_chi_csrf_zha(self):
        """桌面直连的 POST 不带 CSRF 头也必须通（登录闸在挡，token 闸不归它）。"""
        with (mock.patch.object(bridge_admin, "du_yunxing",
                                return_value={"port": self.jia.duan, "token": "T"}),
              self.huan):
            zi, _ = self._fa("/agent-api/sessions", fa="POST",
                             ti={"agentId": "claude-code", "cwd": "D:/x"})
            self.assertEqual(zi, 200)
            self.assertEqual(self.jia.shou_dao[-1]["body"],
                             {"agentId": "claude-code", "cwd": "D:/x"})

    def test_bridge_mei_qi_lai_hui_502(self):
        with (mock.patch.object(bridge_admin, "du_yunxing", return_value={}),
              self.huan):
            zi, xiang = self._fa("/agent-api/agents")
            self.assertEqual(zi, 502)
            self.assertEqual(xiang["error"]["code"], "agent_unavailable")


if __name__ == "__main__":
    unittest.main()
