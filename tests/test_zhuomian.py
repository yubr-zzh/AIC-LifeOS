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


if __name__ == "__main__":
    unittest.main()
