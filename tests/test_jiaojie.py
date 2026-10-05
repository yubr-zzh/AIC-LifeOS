"""传输层接口与 localbus（spec 7.3、7.4）。"""

from __future__ import annotations

import unittest
from unittest import mock

from lifeos.bridge import jiaojie


class XuanTest(unittest.TestCase):
    def test_moren_shi_local(self):
        j = jiaojie.xuan("local", None, {})
        self.assertIsInstance(j, jiaojie.BenDi)
        self.assertEqual(j.zhuang_tai(), "local")

    def test_bu_ren_shi_de_ming_zi_bao_cuo(self):
        with self.assertRaises(ValueError):
            jiaojie.xuan("buzhidao", None, {})

    def test_local_qi_dong_ting_zhi_shi_kong_cao_zuo(self):
        fu = mock.Mock()
        j = jiaojie.xuan("local", fu, {})
        j.qi_dong()   # 不能碰 fu —— 它已经在跑了
        j.ting_zhi()
        fu.assert_not_called()

    def test_ke_yi_zhu_ce_xin_shi_xian(self):
        class Jia(jiaojie.JiaoJie):
            def qi_dong(self):
                self.qilai = True

            def ting_zhi(self):
                pass

            def zhuang_tai(self):
                return "connected"

        jiaojie.zhu_ce("jia", Jia)
        try:
            j = jiaojie.xuan("jia", None, {})
            j.qi_dong()
            self.assertTrue(j.qilai)
            self.assertEqual(j.zhuang_tai(), "connected")
        finally:
            jiaojie.ZHU_CE.pop("jia", None)
