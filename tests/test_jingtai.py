"""打包前置重构（方案 4.2）：静态托管 / .lifeos 根显式化 / Origin 注入。

守的回归：
1. 静态托管：`/` 出 index.html、SPA fallback 只给无扩展名路径、
   带扩展名找不到 404、路径穿越被挡、/api/* 不被兜底吞掉；
2. 静态资源豁免登录闸（页面壳要能渲染登录页），API 照旧要会话；
3. gen_mulu：LIFEOS_HOME 优先，缺省回落 ./lifeOS；
4. Origin 运行时注入：jia_yuan 同步主服务白名单与 bridge/auth 白名单。
"""

from __future__ import annotations

import http.client
import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path

from lifeos.api import server as fu_wu
from lifeos.api import yonghu
from lifeos.api.server import LiAnHTTPServer, LifeOSRequestHandler
from lifeos.bridge import auth as qiao_ren_zheng
from lifeos.gen import gen_mulu


def _kong() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    p = s.getsockname()[1]
    s.close()
    return p


class JingTaiJiLei(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.gen = Path(tmp.name)
        self.dist = self.gen / "dist"
        (self.dist / "assets").mkdir(parents=True)
        (self.dist / "index.html").write_text("<html>lifeos-spa</html>", encoding="utf-8")
        (self.dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
        LifeOSRequestHandler.JING_TAI = self.dist
        self.addCleanup(setattr, LifeOSRequestHandler, "JING_TAI", None)
        self.duan = _kong()
        self.fu = LiAnHTTPServer(("127.0.0.1", self.duan), LifeOSRequestHandler)
        threading.Thread(target=self.fu.serve_forever, daemon=True).start()
        self.addCleanup(self.fu.shutdown)
        self.addCleanup(self.fu.server_close)

    def qing(self, a1: str, a2: str, a3=None, a4: str | None = None):
        tou = {}
        data = None
        if a3 is not None:
            data = json.dumps(a3).encode("utf-8")
            tou["content-type"] = "application/json"
        if a4:
            tou["Cookie"] = f"{yonghu.COOKIES_MING}={a4}"
        conn = http.client.HTTPConnection("127.0.0.1", self.duan, timeout=10)
        try:
            conn.request(a1, a2, data, tou)
            resp = conn.getresponse()
            raw = resp.read()
            status = resp.status
            headers = {k.lower(): v for k, v in resp.getheaders()}
        finally:
            conn.close()
        return status, raw, headers


class JingTaiTest(JingTaiJiLei):
    def test_gen_chu_index(self):
        status, raw, tou = self.qing("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"lifeos-spa", raw)
        self.assertTrue(tou["content-type"].startswith("text/html"))
        self.assertEqual(tou["cache-control"], "no-cache")

    def test_jing_tai_zi_yuan(self):
        status, raw, tou = self.qing("GET", "/assets/app.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", tou["content-type"])

    def test_spa_hui_luo_zhi_wu_kuo_zhan_ming(self):
        status, raw, _ = self.qing("GET", "/some/route")
        self.assertEqual(status, 200)
        self.assertIn(b"lifeos-spa", raw)

    def test_dai_kuo_zhan_ming_zhao_bu_dao_404(self):
        status, _, _ = self.qing("GET", "/missing.js")
        self.assertEqual(status, 404)

    def test_lu_jing_chuan_yue_bei_dang(self):
        status, _, _ = self.qing("GET", "/../secrets.txt")
        self.assertIn(status, (400, 404))

    def test_wei_zhi_api_bu_bei_dun_di(self):
        """打错的 /api 路由必须 404，不能被 SPA fallback 伪装成页面。"""
        status, _, _ = self.qing("GET", "/api/definitely-not-a-route")
        self.assertEqual(status, 404)

    def test_yi_you_duan_dian_you_xian(self):
        """/events 是既有路由，不能被静态兜底抢走。"""
        status, _, _ = self.qing("GET", "/events")
        self.assertEqual(status, 200)


class ZhaYuJingTaiTest(JingTaiJiLei):
    def setUp(self):
        super().setUp()
        zhang = yonghu.ZhangHuBiao(self.gen / "accounts.json")
        hui = yonghu.HuiHuaBiao(self.gen / "sessions")
        yonghu.zhuang(zhang, hui)
        self.addCleanup(yonghu.zhuang, None, None)
        zhang.chuang("admin", "password123")

    def test_jing_tai_mian_deng_lu_api_yao_hui_hua(self):
        """静态资源豁免（页面壳要能渲染登录页），API 照旧 401（方案 6.2）。"""
        status, _, _ = self.qing("GET", "/")
        self.assertEqual(status, 200)
        status, _, _ = self.qing("GET", "/login")
        self.assertEqual(status, 200)
        status, _, _ = self.qing("GET", "/events")
        self.assertEqual(status, 401)


class GenMuluTest(unittest.TestCase):
    def test_lifeos_home_you_xian(self):
        with unittest.mock.patch.dict("os.environ", {"LIFEOS_HOME": r"D:\tmp\LifeOS"}):
            self.assertEqual(gen_mulu(), Path(r"D:\tmp\LifeOS"))

    def test_que_sheng_hui_luo_dang_qian_mu_lu(self):
        env = {k: v for k, v in __import__("os").environ.items() if k != "LIFEOS_HOME"}
        with unittest.mock.patch.dict("os.environ", env, clear=True):
            self.assertEqual(gen_mulu(), Path(".") / "lifeOS")


class YuanZhuRuTest(unittest.TestCase):
    def test_jia_yuan_tong_bu_liang_bian_bai_ming_dan(self):
        xin = "http://127.0.0.1:9999"
        try:
            fu_wu.jia_yuan(xin)
            self.assertIn(xin, fu_wu.YUAN_BAI)
            self.assertIn(xin, qiao_ren_zheng.huo_yuan_bai())
            # bridge 侧白名单也认它
            qiao_ren_zheng.yuanbai(xin)
        finally:
            if xin in fu_wu.YUAN_BAI:
                fu_wu.YUAN_BAI.remove(xin)
            qiao_ren_zheng.E_WAI.discard(xin)

    def test_wei_zhu_ru_ren_jiu_403(self):
        try:
            with self.assertRaises(qiao_ren_zheng.WeiQuan):
                qiao_ren_zheng.yuanbai("http://evil.example.com:1")
        finally:
            qiao_ren_zheng.E_WAI.discard("http://evil.example.com:1")


import unittest.mock  # noqa: E402  (GenMuluTest 用到，放底部避免顶部噪音)

if __name__ == "__main__":
    unittest.main()
