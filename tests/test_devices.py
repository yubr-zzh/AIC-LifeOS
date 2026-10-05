"""设备注册表与配对码（spec 8.1、8.2、11.1）。"""

from __future__ import annotations

import logging
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from lifeos.api import dangqian
from lifeos.api.devices import PeiMa, SheBiao
from gong_ju import deng_dai


class DangQianTest(unittest.TestCase):
    def test_moren_shi_local(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LIFEOS_USER", None)
            self.assertEqual(dangqian.dang_qian_yong_hu(), "local")

    def test_huan_jing_bian_liang_sheng_xiao(self):
        with mock.patch.dict(os.environ, {"LIFEOS_USER": "u-abc_1"}):
            self.assertEqual(dangqian.dang_qian_yong_hu(), "u-abc_1")

    def test_fei_fa_uid_bei_ju(self):
        # uid 拼进 CLAUDE_CONFIG_DIR 的路径，`../` 能写到别的目录去。
        for huai in ["../..", "..", ".", "", "a/b", "a\\b", "a" * 65, "a b"]:
            with self.subTest(huai=huai):
                with mock.patch.dict(os.environ, {"LIFEOS_USER": huai}):
                    with self.assertRaises(dangqian.YongHuFeiFa):
                        dangqian.dang_qian_yong_hu()


class SheBiaoTest(unittest.TestCase):
    def setUp(self):
        self.mu = tempfile.TemporaryDirectory()
        self.wen = Path(self.mu.name) / "devices.json"
        self.biao = SheBiao(self.wen, logging.getLogger("test.devices"))

    def tearDown(self):
        self.mu.cleanup()

    def test_jia_hou_neng_ren(self):
        ji = self.biao.jia("local", "本机", "i-abc")
        self.assertTrue(ji["deviceId"].startswith("dev-"))
        zhao, yuan = self.biao.ren(ji["deviceToken"])
        self.assertEqual(yuan, "ok")
        self.assertEqual(zhao["deviceId"], ji["deviceId"])

    def test_token_wei_zao_bei_ju(self):
        ji = self.biao.jia("local", "本机", "i-abc")
        # 改末位一个字符。sha256 摘要不符 → 401，不能认。
        hua = ji["deviceToken"][:-1] + ("0" if ji["deviceToken"][-1] != "0" else "1")
        zhao, yuan = self.biao.ren(hua)
        self.assertIsNone(zhao)
        self.assertEqual(yuan, "bad")

    def test_token_ge_shi_bu_dui_bei_ju(self):
        for huai in ["", "abc", "dt_x", "dt_a_b_c", "xx_dev-000000000000_00"]:
            with self.subTest(huai=huai):
                zhao, yuan = self.biao.ren(huai)
                self.assertIsNone(zhao)
                self.assertEqual(yuan, "bad")

    def test_jie_bang_hou_ren_bu_liao(self):
        ji = self.biao.jia("local", "本机", "i-abc")
        self.assertTrue(self.biao.jie(ji["deviceId"]))
        zhao, yuan = self.biao.ren(ji["deviceToken"])
        self.assertIsNone(zhao)
        self.assertEqual(yuan, "revoked")
        # 幂等：再解绑一次返回 False，不抛
        self.assertFalse(self.biao.jie(ji["deviceId"]))

    def test_luo_pan_li_mei_you_mingwen_token(self):
        ji = self.biao.jia("local", "本机", "i-abc")
        wen = self.wen.read_text(encoding="utf-8")
        self.assertNotIn(ji["deviceToken"], wen)
        self.assertIn("tokenHash", wen)

    def test_lie_bu_han_hash(self):
        self.biao.jia("local", "本机", "i-abc")
        lie = self.biao.lie()
        self.assertEqual(len(lie), 1)
        self.assertNotIn("tokenHash", lie[0])
        self.assertNotIn("deviceToken", lie[0])

    def test_lie_an_uid_guo_lu(self):
        self.biao.jia("local", "A", "i-a")
        self.biao.jia("bob", "B", "i-b")
        self.assertEqual(len(self.biao.lie("local")), 1)
        self.assertEqual(len(self.biao.lie()), 2)

    def test_du_dao_huai_json_jiang_ji_wei_kong(self):
        self.wen.write_text("{ 这不是 JSON", encoding="utf-8")
        biao = SheBiao(self.wen, logging.getLogger("test.devices"))
        self.assertEqual(biao.lie(), [])
        # 降级后仍然能用 —— 绝不让主服务起不来
        biao.jia("local", "本机", "i-abc")
        self.assertEqual(len(biao.lie()), 1)

    def test_luo_pan_ke_chong_du(self):
        ji = self.biao.jia("local", "本机", "i-abc")
        biao2 = SheBiao(self.wen, logging.getLogger("test.devices"))
        self.assertEqual(biao2.zhao(ji["deviceId"])["userId"], "local")
        self.assertEqual(biao2.ren(ji["deviceToken"])[1], "ok")

    def _ri(self, a1):
        """抓日志。SheBiao 构造时就读盘，所以 logger 必须在构造之前就位。"""
        ri = logging.Logger("test.devices.capture", level=logging.WARNING)
        ri.handlers.clear()
        ri.addHandler(type("H", (logging.Handler,),
                           {"emit": lambda s, r: a1.append(r.getMessage())})())
        return ri

    def test_luo_pan_li_hash_xing_zhuang_bu_dui_bei_ju(self):
        """deviceId 合法但 tokenHash 畸形（中文串 / 布尔）。

        不过滤的话记录会进内存，随后 `ren()` 的 hmac.compare_digest 对非 ASCII
        抛 TypeError、对 int 抛 TypeError —— 网关握手会变成 500 而不是 401
        （`ren()` 只承诺返回 "ok"/"bad"/"revoked"，不承诺不抛）。
        """
        self.wen.write_text(
            '{"schemaVersion": 1, "devices": ['
            '{"deviceId": "dev-000000000001", "userId": "local",'
            ' "tokenHash": "中文中文"},'
            '{"deviceId": "dev-000000000002", "userId": "local", "tokenHash": true}]}',
            encoding="utf-8")
        ri = []
        biao = SheBiao(self.wen, self._ri(ri))
        self.assertEqual(biao.lie(), [])
        # 降级必须留痕：静默丢掉畸形记录，出问题时没人知道设备为什么连不上
        self.assertTrue(ri, "畸形记录被跳过时必须告警")
        zhao, yuan = biao.ren("dt_dev-000000000001_" + "0" * 64)
        self.assertIsNone(zhao)
        self.assertEqual(yuan, "bad")

    def test_jie_bang_hou_wei_zao_token_shi_bad(self):
        """已解绑 + 错 token → 401 语义（"bad"），不是 "revoked"。

        spec 6.1 的握手校验顺序是 token(401) 在已解绑(403) 之前：先判 revoked
        的话，知道 deviceId 的人拿任何垃圾 token 都能问出「这台已解绑」。
        """
        ji = self.biao.jia("local", "本机", "i-abc")
        self.assertTrue(self.biao.jie(ji["deviceId"]))
        zhao, yuan = self.biao.ren("dt_" + ji["deviceId"] + "_" + "0" * 64)
        self.assertIsNone(zhao)
        self.assertEqual(yuan, "bad")

    def test_luo_pan_li_hash_zheng_shu_bei_ju(self):
        """tokenHash 是「恰好 64 位的整数」时也要挡掉。

        `str()` 只参与正则匹配，存进表里的仍是原值：不查类型的话这个 int 能过筛，
        随后 `hmac.compare_digest(int, str)` 抛 TypeError —— 又是 500 而不是 401。
        """
        self.wen.write_text(
            '{"schemaVersion": 1, "devices": ['
            '{"deviceId": "dev-000000000003", "userId": "local", "tokenHash": '
            + "1" * 64 + '}]}',
            encoding="utf-8")
        ri = []
        biao = SheBiao(self.wen, self._ri(ri))
        self.assertEqual(biao.lie(), [])
        self.assertTrue(ri, "畸形记录被跳过时必须告警")
        zhao, yuan = biao.ren("dt_dev-000000000003_" + "0" * 64)
        self.assertIsNone(zhao)
        self.assertEqual(yuan, "bad")


class PeiMaTest(unittest.TestCase):
    def test_sheng_chu_lai_de_ma_xing_zhuang(self):
        ma = PeiMa()
        xin = ma.sheng("local")
        self.assertRegex(xin["code"], r"^[A-Z2-9]{3}-[A-Z2-9]{3}$")
        self.assertGreater(xin["expiresAt"], int(time.time() * 1000))

    def test_dui_hou_ji_zuo_fei(self):
        ma = PeiMa()
        xin = ma.sheng("local")
        self.assertEqual(ma.dui(xin["code"]), "local")
        # 一次性：第二次拿不到（防重放）
        self.assertIsNone(ma.dui(xin["code"]))

    def test_guo_qi_na_bu_dao(self):
        ma = PeiMa(a1=0.01)
        xin = ma.sheng("local")
        # 「过期了」本身就是状态变了：同一个码从查得到变成查不到。等这个变化，
        # 不是等 0.05 秒——TTL 一改，固定时长就白等或者不够。
        deng_dai(lambda: ma.dui(xin["code"]) is None, chao=2.0)
        self.assertIsNone(ma.dui(xin["code"]))

    def test_bu_cun_zai_de_ma_he_guo_qi_de_ma_fan_hui_yi_yang(self):
        # spec 8.1：三种失败返回同一句话，不做探测预言机
        ma = PeiMa()
        self.assertIsNone(ma.dui("AAA-BBB"))

    def test_da_xiao_xie_yu_kong_ge_rong_cuo(self):
        ma = PeiMa()
        xin = ma.sheng("local")
        self.assertEqual(ma.dui(" " + xin["code"].lower() + " "), "local")
