"""阶段 5 落盘层：三类文件、降级、上限（方案 5.1/5.2/5.5/10.7）。

这个文件只测 Cun 本身。落盘时机、恢复、重放在后续任务的测试里。
"""

import logging
import sys
import tempfile
import unittest
from pathlib import Path

from lifeos.bridge.cun import JUE_JING, WEN_ZUI, Cun

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class CunTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.gen = Path(self.dir.name)
        self.c = Cun(self.gen)

    def tearDown(self):
        self.dir.cleanup()

    def _hui(self, a1="s-1", a2="ended"):
        return {"sessionId": a1, "agentId": "claude-code", "cwd": "D:/x",
                "state": a2, "batchTotal": 1, "batchDone": 1}

    def _xiang(self, a1, a2=None, a3="text"):
        return {"messageId": f"m-{a1}", "sessionId": "s-1", "seq": a1,
                "role": "assistant", "kind": a3, "text": f"第{a1}条"}

    def test_sessions_xie_du(self):
        self.c.xie_hui([self._hui(), self._hui("s-2", "idle")])
        # 模拟重启：换一个实例读同一个目录
        self.assertEqual(len(Cun(self.gen).du_hui()), 2)
        self.assertEqual(self.c.du_hui()[0]["state"], "ended")

    def test_sessions_shi_quan_liang_chong_xie(self):
        """全量重写必须覆盖旧内容，不是追加——否则删掉的会话一直活着。"""
        self.c.xie_hui([self._hui(), self._hui("s-2")])
        self.c.xie_hui([self._hui()])
        self.assertEqual(len(self.c.du_hui()), 1)

    def test_decisions_zhui_jia_yu_cha(self):
        self.c.jue_cun({"requestId": "toolu_A", "sessionId": "s-1",
                        "decision": "user_allow", "autoReason": None,
                        "inputHash": "aaa", "at": 1.0})
        self.c.jue_cun({"requestId": "toolu_B", "sessionId": "s-1",
                        "decision": "auto_deny", "autoReason": "timeout",
                        "inputHash": "bbb", "at": 2.0})
        self.assertEqual(len(self.c.jue_qu()), 2)
        self.assertEqual(len(self.c.jue_qu("s-1", "toolu_A")), 1)
        self.assertEqual(self.c.jue_qu("s-1", "toolu_A")[0]["decision"], "user_allow")
        self.assertEqual(self.c.jue_qu("s-1", "toolu_nope"), [])
        self.assertEqual(self.c.jue_qu("s-2"), [])

    def test_xiang_zhui_jia_an_hui_hua_du(self):
        self.c.xiang_cun(self._xiang(1))
        self.c.xiang_cun(self._xiang(2))
        self.c.xiang_cun(self._xiang(3, 3, "tool_use"))
        self.c.xiang_qu("s-2")  # 不存在的会话不能抛
        self.assertEqual([m["seq"] for m in self.c.xiang_qu("s-1")], [1, 2, 3])

    def test_text_zhi_liu_200(self):
        """上限只发生在读取时。追加路径上裁剪的话，「截断」与「损坏」
        在文件里长得一模一样，恢复时无法区分。"""
        for i in range(1, 206):
            self.c.xiang_cun(self._xiang(i))
        for i in range(206, 209):
            self.c.xiang_cun(self._xiang(i, i, "tool_use"))
        lie = self.c.xiang_qu("s-1")
        self.assertEqual(len(lie), WEN_ZUI + 3)
        self.assertEqual(lie[0]["seq"], 6)      # 最早的 text 被裁掉
        self.assertEqual(lie[-1]["kind"], "tool_use")
        # 文件本身一条都没少
        self.assertEqual(len(self.c.xiang_qu("s-1", 10 ** 9)), 208)

    def test_wen_jian_bu_cun_zai(self):
        self.assertEqual(self.c.du_hui(), [])
        self.assertEqual(self.c.jue_qu(), [])
        self.assertEqual(self.c.xiang_qu("s-1"), [])

    def test_json_huai_ke_ji_xu_qi_dong(self):
        self.c.xie_hui([self._hui()])
        self.c.hui_wen.write_text('{"sessionId": "s-1", ', encoding="utf-8")  # 写坏
        self.assertEqual(self.c.du_hui(), [])   # 不抛异常，按空处理
        self.assertEqual(self.c.hui_wen.exists(), True)

    def test_dan_hang_huai_tiao_guo(self):
        self.c.jue_cun({"requestId": "toolu_A", "sessionId": "s-1",
                        "decision": "user_allow", "inputHash": "aaa", "at": 1.0})
        with self.c.jue_wen.open("a", encoding="utf-8") as f:
            f.write('{"requestId": "toolu_B", "sessionId": \n')  # 中间插一行坏的
        self.c.jue_cun({"requestId": "toolu_C", "sessionId": "s-1",
                        "decision": "auto_deny", "inputHash": "ccc", "at": 3.0})
        self.assertEqual([x["requestId"] for x in self.c.jue_qu()],
                         ["toolu_A", "toolu_C"])

    def test_sid_he_fa(self):
        """sid 直接拼进路径。不校验的话一个 `../..` 就写到 .lifeos 外面去了。"""
        self.c.xiang_cun({"messageId": "m-1", "sessionId": "../evil",
                          "seq": 1, "kind": "text"})
        self.c.xiang_cun({"messageId": "m-2", "sessionId": "",
                          "seq": 1, "kind": "text"})
        self.c.xiang_cun({"messageId": "m-3", "sessionId": "s/1",
                          "seq": 1, "kind": "text"})
        self.assertEqual(list(self.c.xiang_jia.glob("*.jsonl")), [])
        self.assertFalse((self.gen.parent / "evil.jsonl").exists())

    def test_duan_ju(self):
        """decisions.jsonl 是 R3 的安全冗余，删一条就少一层保护。只告警，不删。"""
        ri = []
        c = Cun(self.gen, logging.Logger("t", level=logging.WARNING))
        c.ri.handlers.clear()
        c.ri.addHandler(type("H", (logging.Handler,),
                             {"emit": lambda s, r: ri.append(r.getMessage())})())
        for i in range(10_002):
            c.jue_cun({"requestId": f"t{i}", "sessionId": "s-1",
                       "decision": "auto_deny", "inputHash": "x", "at": 1.0})
        self.assertEqual(len(c.jue_qu()), 10_002)
        # 钉的是「阈值被说出来」。原来写死 "10000" 是不行的：
        # 告警文案里的条数是 10001、10002，那串数字根本不会出现。
        self.assertTrue(any(str(JUE_JING) in x for x in ri),
                        f"超过 {JUE_JING} 条时必须告警，实际日志：{ri}")


if __name__ == "__main__":
    unittest.main()
