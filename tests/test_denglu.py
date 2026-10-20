"""登录体系（方案 6.1/6.2，验收清单 6.7 的可自动化部分）。

守的回归：
1. **未初始化不设闸**——无账户时所有端点照旧放行，既有形态一行不改；
2. 建了账户，闸落下：无会话 401，带会话 Cookie 放行；
3. setup 幂等保护：已有账户再 setup → 403；
4. 登录失败限速：连续 5 次失败锁 60 秒，锁内正确口令也 429；
5. 改口令吊销其他会话，当前会话保留；无 CSRF → 403；
6. **盘上无明文**：accounts.json 无口令、sessions/ 无 token 原文。
"""

from __future__ import annotations

import base64
import http.client
import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path

from lifeos.api import yonghu
from lifeos.api.server import LiAnHTTPServer, LifeOSRequestHandler


def _kong() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    p = s.getsockname()[1]
    s.close()
    return p


class DengLuJiLei(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        gen = Path(tmp.name)
        yonghu.zhuang(
            yonghu.ZhangHuBiao(gen / "accounts.json"),
            yonghu.HuiHuaBiao(gen / "sessions"))
        self.addCleanup(yonghu.zhuang, None, None)
        with yonghu._CUO_SUO:
            yonghu._CUO.clear()
        self.gen = gen
        self.duan = _kong()
        self.fu = LiAnHTTPServer(("127.0.0.1", self.duan), LifeOSRequestHandler)
        threading.Thread(target=self.fu.serve_forever, daemon=True).start()
        self.addCleanup(self.fu.shutdown)
        self.addCleanup(self.fu.server_close)

    def qing(self, a1: str, a2: str, a3=None, a4: str | None = None,
             a5: dict | None = None):
        """返回 (status, body, headers)。"""
        tou = dict(a5 or {})
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
        return status, (json.loads(raw) if raw else {}), headers

    def _ling_cong(self, headers: dict) -> str:
        cookie = headers.get("set-cookie", "")
        for kuai in cookie.split(";"):
            ming, _, zhi = kuai.strip().partition("=")
            if ming == yonghu.COOKIES_MING:
                return zhi
        self.fail(f"响应没有会话 Cookie：{cookie!r}")

    def deng_ru(self, a1: str = "admin", a2: str = "password123") -> str:
        _, _, tou = self.qing("POST", "/api/auth/login",
                              {"username": a1, "password": a2})
        return self._ling_cong(tou)


class ChuShiHuaTest(DengLuJiLei):
    def test_wei_chu_shi_hua_bu_she_zha(self):
        """无账户：所有端点照旧放行（既有测试不回归的保障）。"""
        status, _, _ = self.qing("GET", "/events")
        self.assertEqual(status, 200)
        _, ma, _ = self.qing("GET", "/api/auth/status")
        status, shen, _ = self.qing("POST", "/api/settings/delegation",
                                    {"enabled": True}, a5={"X-LifeOS-CSRF": ma["csrf"]})
        self.assertEqual(status, 200)
        self.assertTrue(shen["enabled"])
        status, shen, _ = self.qing("GET", "/api/auth/status")
        self.assertEqual(status, 200)
        self.assertFalse(shen["initialized"])
        self.assertFalse(shen["authenticated"])

    def test_setup_hou_zha_luo_xia(self):
        status, shen, tou = self.qing("POST", "/api/auth/setup",
                                      {"username": "admin", "password": "password123"})
        self.assertEqual(status, 200, shen)
        self.assertIn("httponly", tou["set-cookie"].lower())
        self.assertIn("samesite=strict", tou["set-cookie"].lower())
        ling = self._ling_cong(tou)
        # 带会话放行
        status, _, _ = self.qing("GET", "/events", a4=ling)
        self.assertEqual(status, 200)
        # 无会话 401
        status, shen, _ = self.qing("GET", "/events")
        self.assertEqual(status, 401)
        self.assertEqual(shen["error"]["code"], "unauthorized")

    def test_setup_yi_chu_shi_hua_403(self):
        self.qing("POST", "/api/auth/setup",
                  {"username": "admin", "password": "password123"})
        status, _, _ = self.qing("POST", "/api/auth/setup",
                                 {"username": "other", "password": "password456"})
        self.assertEqual(status, 403)

    def test_kou_ling_tai_duan_400(self):
        status, _, _ = self.qing("POST", "/api/auth/setup",
                                 {"username": "admin", "password": "short"})
        self.assertEqual(status, 400)


class DengLuTest(DengLuJiLei):
    def setUp(self):
        super().setUp()
        self.qing("POST", "/api/auth/setup",
                  {"username": "admin", "password": "password123"})

    def test_cuo_wu_wen_an_tong_yi(self):
        """错误文案统一，不区分用户名/口令哪个错（防枚举，方案 6.4）。"""
        for ming in ("admin", "nobody"):
            status, shen, _ = self.qing("POST", "/api/auth/login",
                                        {"username": ming, "password": "wrong-pass"})
            self.assertEqual(status, 401)
            self.assertEqual(shen["error"]["message"], "用户名或密码不正确")

    def test_wu_ci_shi_bai_suo_ding(self):
        for _ in range(5):
            status, _, _ = self.qing("POST", "/api/auth/login",
                                     {"username": "admin", "password": "wrong-pass"})
            self.assertEqual(status, 401)
        status, _, tou = self.qing("POST", "/api/auth/login",
                                   {"username": "admin", "password": "password123"})
        self.assertEqual(status, 429)
        self.assertIn("retry-after", tou)

    def test_hui_hua_fang_xing(self):
        ling = self.deng_ru()
        status, shen, _ = self.qing("GET", "/api/auth/status", a4=ling)
        self.assertTrue(shen["authenticated"])
        self.assertEqual(shen["username"], "admin")
        status, _, _ = self.qing("GET", "/events", a4=ling)
        self.assertEqual(status, 200)

    def test_pan_shang_wu_ming_wen(self):
        """盘上无明文：口令不进 accounts.json，token 不进 sessions/（方案 6.1）。"""
        ling = self.deng_ru()
        zhang_wen = self.gen / "accounts.json"
        if zhang_wen.exists():
            self.assertNotIn("password123", zhang_wen.read_text(encoding="utf-8"))
        for wen in (self.gen / "sessions").glob("*.json"):
            self.assertNotIn(ling, wen.read_text(encoding="utf-8"))

    def test_deng_chu_hui_hua_shi_xiao(self):
        ling = self.deng_ru()
        status, _, _ = self.qing("POST", "/api/auth/logout", {}, a4=ling)
        self.assertEqual(status, 200)
        status, _, _ = self.qing("GET", "/events", a4=ling)
        self.assertEqual(status, 401)


class KouLingTest(DengLuJiLei):
    def setUp(self):
        super().setUp()
        self.qing("POST", "/api/auth/setup",
                  {"username": "admin", "password": "password123"})

    def _ma(self) -> str:
        _, shen, _ = self.qing("GET", "/api/auth/status", a4=self.ling)
        return shen["csrf"]

    def test_gai_kou_ling_diao_xiao_qi_ta_hui_hua(self):
        self.ling = self.deng_ru()
        ling_b = self.deng_ru()
        status, shen, _ = self.qing(
            "PUT", "/api/auth/password",
            {"old_password": "password123", "new_password": "newpass45678"},
            a4=self.ling, a5={"X-LifeOS-CSRF": self._ma()})
        self.assertEqual(status, 200, shen)
        # setup 自动登录的会话 + ling_b 都被吊销，当前会话保留。
        self.assertEqual(shen["revoked"], 2)
        # 当前会话保留
        status, _, _ = self.qing("GET", "/events", a4=self.ling)
        self.assertEqual(status, 200)
        # 其他会话吊销
        status, _, _ = self.qing("GET", "/events", a4=ling_b)
        self.assertEqual(status, 401)

    def test_gai_kou_ling_que_csrf_403(self):
        self.ling = self.deng_ru()
        status, _, _ = self.qing("PUT", "/api/auth/password",
                                 {"old_password": "password123",
                                  "new_password": "newpass45678"}, a4=self.ling)
        self.assertEqual(status, 403)

    def test_gai_kou_ling_jiu_kou_ling_cuo_400(self):
        self.ling = self.deng_ru()
        status, _, _ = self.qing(
            "PUT", "/api/auth/password",
            {"old_password": "wrong-pass", "new_password": "newpass45678"},
            a4=self.ling, a5={"X-LifeOS-CSRF": self._ma()})
        self.assertEqual(status, 400)

    def test_gai_mi_ma_hou_xin_mi_ma_ke_deng_lu(self):
        self.ling = self.deng_ru()
        status, shen, _ = self.qing(
            "PUT", "/api/auth/password",
            {"old_password": "password123", "new_password": "newpass45678"},
            a4=self.ling, a5={"X-LifeOS-CSRF": self._ma()})
        self.assertEqual(status, 200, shen)
        status, _, tou = self.qing(
            "POST", "/api/auth/login",
            {"username": "admin", "password": "newpass45678"})
        self.assertEqual(status, 200)
        self.assertTrue(self._ling_cong(tou))


class TouXiangTest(DengLuJiLei):
    def setUp(self):
        super().setUp()
        self.qing("POST", "/api/auth/setup",
                  {"username": "admin", "password": "password123"})
        self.ling = self.deng_ru()

    def _ma(self) -> str:
        _, shen, _ = self.qing("GET", "/api/auth/status", a4=self.ling)
        return shen["csrf"]

    def test_tou_xiang_ke_bao_cun_qing_chu_bing_sui_zhuang_tai_fan_hui(self):
        avatar = "data:image/png;base64," + base64.b64encode(b"avatar-bytes").decode("ascii")
        status, shen, _ = self.qing(
            "PUT", "/api/auth/profile", {"avatar": avatar},
            a4=self.ling, a5={"X-LifeOS-CSRF": self._ma()})
        self.assertEqual(status, 200, shen)
        self.assertEqual(shen["avatar"], avatar)
        _, zhuang, _ = self.qing("GET", "/api/auth/status", a4=self.ling)
        self.assertEqual(zhuang["avatar"], avatar)

        status, shen, _ = self.qing(
            "PUT", "/api/auth/profile", {"avatar": None},
            a4=self.ling, a5={"X-LifeOS-CSRF": self._ma()})
        self.assertEqual(status, 200, shen)
        self.assertIsNone(shen["avatar"])
        _, zhuang, _ = self.qing("GET", "/api/auth/status", a4=self.ling)
        self.assertIsNone(zhuang["avatar"])

    def test_tou_xiang_ge_shi_cuo_wu_400(self):
        status, _, _ = self.qing(
            "PUT", "/api/auth/profile", {"avatar": "not-an-image"},
            a4=self.ling, a5={"X-LifeOS-CSRF": self._ma()})
        self.assertEqual(status, 400)


class HuiHuaLieBiaoTest(DengLuJiLei):
    def setUp(self):
        super().setUp()
        self.qing("POST", "/api/auth/setup",
                  {"username": "admin", "password": "password123"})
        self.ling = self.deng_ru()

    def test_lie_chu_yu_diao_xiao(self):
        ling_b = self.deng_ru()
        status, shen, _ = self.qing("GET", "/api/auth/sessions", a4=self.ling)
        self.assertEqual(status, 200)
        rows = shen["sessions"]
        # 3 条：setup 自动登录的会话 + 两次显式登录。
        self.assertEqual(len(rows), 3)
        # 列表只给前缀、不标身份，所以逐个吊销全部非当前会话（含 ling_b）。
        # CSRF 是一次性的，每次 DELETE 都要现取一枚。
        for x in [r for r in rows if not r["current"]]:
            _, ma, _ = self.qing("GET", "/api/auth/status", a4=self.ling)
            status, shen, _ = self.qing("DELETE", "/api/auth/sessions",
                                        {"tokenHash": x["tokenHash"]},
                                        a4=self.ling,
                                        a5={"X-LifeOS-CSRF": ma["csrf"]})
            self.assertEqual(status, 200, shen)
            self.assertEqual(shen["revoked"], 1)
        status, _, _ = self.qing("GET", "/events", a4=ling_b)
        self.assertEqual(status, 401)
        status, _, _ = self.qing("GET", "/events", a4=self.ling)
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
