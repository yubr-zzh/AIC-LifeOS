"""10.7 的脱敏：四种模式 + 顺序不能反 + 长度上限。

顺序是这一组的重点：先截断会让正则看不到跨界的密钥——截断点正好落在
`sk-` 与后面的随机串之间时，正则匹配不到，密钥前半段就漏出去了。
"""

import sys
import unittest
from pathlib import Path

from lifeos.bridge.tuomi import tuomi

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class TuomiTests(unittest.TestCase):
    def test_sk(self):
        self.assertNotIn("sk-abc123def456ghi789", tuomi("key=sk-abc123def456ghi789"))

    def test_ghp(self):
        self.assertNotIn("ghp_1234567890abcdefghij", tuomi("GITHUB_TOKEN=ghp_1234567890abcdefghij"))

    def test_akia(self):
        self.assertNotIn("AKIA1234567890ABCDEF", tuomi("AKIA1234567890ABCDEF"))

    def test_fu_hao_fen_ge(self):
        for wen in ("token: abcdef1234567890", "token=abcdef1234567890",
                    "password = hunter2xyz", "api_key: 'a1b2c3d4e5'"):
            self.assertIn("***", tuomi(wen), wen)

    def test_bearer(self):
        wen = tuomi("Authorization: Bearer abcdefghijklmnopqrstuvwx")
        self.assertIn("Bearer ***", wen)
        self.assertNotIn("abcdefghijklmnop", wen)

    def test_si_yao(self):
        wen = tuomi("-----BEGIN RSA PRIVATE KEY-----\nMIIEabc\nDEF\n-----END RSA PRIVATE KEY-----")
        self.assertIn("私钥已抹除", wen)
        self.assertNotIn("MIIEabc", wen)

    def test_jia_lu_jing(self):
        jia = str(Path.home())
        if not jia:
            self.skipTest("取不到家目录")
        wen = tuomi(f"读文件 {jia}/.env 失败")
        self.assertNotIn(jia, wen)
        self.assertIn("~", wen)

    def test_xian_tuomi_zai_jie_duan(self):
        """顺序反了会漏：密钥正好跨截断点时，正则看不见它。"""
        mi = "x" * 1990 + "sk-abc123def456ghi789"
        wen = tuomi(mi)
        self.assertNotIn("sk-abc123def456ghi789", wen)

    def test_chang_du(self):
        wen = tuomi("啊" * 5000)
        self.assertEqual(len(wen), 2000 + len("…（已截断）"))
        self.assertTrue(wen.endswith("…（已截断）"))
        # 2000 是「脱敏后可见字符」的上限，后缀不算在内——算进去就等于
        # 实际只留 1994 个字，而这个数字没人会去核对。
        self.assertTrue(wen.startswith("啊" * 2000))

    def test_kong_yu_fei_zi_fu_chuan(self):
        self.assertEqual(tuomi(None), "")
        self.assertIn("command", tuomi({"command": "ls"}))

    def test_bu_shang_huai_zheng_chang(self):
        wen = "token 用完了，需要重新登录"
        self.assertEqual(tuomi(wen), wen)  # 中文词不误伤


if __name__ == "__main__":
    unittest.main()
