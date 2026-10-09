"""kimi 适配器的 L-B（golden）测试。

**这份测试在验什么**：翻译层把 kimi 的 JSONL wire 转成统一事件时，字段名、
分支优先级、回合边界判对没有抄错。

**它在不验什么**：golden 的正确性取决于样本抄得对不对，而样本是抄的。所以它
只是回归护栏，**不是「已验证」**。真验收是 L-C
（`tests/test_liu_xing_lc_ji_cheng.py::Kimi_LC`，真 spawn
`kimi -p --output-format stream-json` 打真回合）。

## 判据落在哪里

golden 的机制是「喂一行真机 wire，断言发出的统一事件序列」，所以判据天然落在
**序列**上——包括「哪些事件**不该**发」与「它们的先后顺序」。本文件的每条样本
都刻意让两种实现读出不同结果：

| 判据 | 两种实现会分岔在 |
|---|---|
| **回合边界只有 `session.resume_hint`**，`system.version` 不是（约束 3） | 拿 `role=="meta"` 当边界 ⇒ 整段序列里出现**两条** result，第一条 `resultText` 是空串 |
| **session 帧必须在 result 帧之前**，且发 result 时 `kehu_hui` 已写好 | 顺序反了 ⇒ 事件序列变成 `["result","session"]`，且 result 帧发出那一刻会话 id 还是空 |
| `tool_calls[].function.arguments` 是 **JSON 字符串**，要解一次 | 不解 ⇒ `toolInput` 是 str，界面拿不到 `command`；断言落在 `isinstance(toolInput, dict)` 上 |
| `role:"tool"` 靠 `tool_call_id` 与 tool_use **配成同一个 toolUseId** | 不用 id 配对 ⇒ 两张工具卡永远收不了口 |
| 带 `tool_calls` 的 assistant 消息**不产生正文**（content 与 tool_calls 二选一） | 两个都处理 ⇒ 多一条 text 帧，且 `resultText` 里混进工具调用帧的内容 |
| 非 JSON 坏行发一条 `error` 后**回合照样收口** | `fan_yi` 抛异常 ⇒ 基类只发 `translate_failed`、**不调收口**，`fasong()` 挂到 15 分钟看门狗 |
| 解不了的嵌套 JSON 落成 `{"raw": 原串}` 而不是抛 | 抛 ⇒ 同上，回合挂死 |
| `_bu_que_men_can` 补齐 `durationMs`/`numTurns`/`totalCostUsd`/`sessionId` | 不补 ⇒ 上层拿到缺字段的结果 dict；且 `durationMs` 必须**真的从计时器算**（>0），不是硬编码 0 |
| `_fa_session` 幂等：两个回合只发一条 session 帧 | 每回合都发 ⇒ 落盘会话被反复覆写 |
| 回合边界之后累加器清空 | 不清 ⇒ 第二回合 `resultText` 是两条回复拼一起 |

**不 sleep 固定时长**：本项目实测 `sleep(2.0)` 在 Windows 上必然 flake。
这里全是纯函数调用，没有等待。唯一涉及时间的那条用例**直接改 `_zhuan_kaishi`**
而不是等它跑过去。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import unittest
from pathlib import Path

from lifeos.bridge.adapters.kimi import KimiAdapter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

JIN = Path(__file__).resolve().parent / "golden"


def _du(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _zhi_(x: object) -> str:
    """喂给 `fan_yi` 的一行。

    **字符串按原样喂**（那是真机 stdout 上的坏行），其余 `json.dumps`。
    golden 里没有任何「值是 JSON 字符串」的合法样本，所以这个分流不会歧义。
    """
    return x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)


def _yi_jian() -> KimiAdapter:
    """造一个不 spawn 任何东西的适配器，把事件收进列表。

    `hui` 除了记 (kind, payload)，还记下**那一刻的 `kehu_hui`**——
    「session 帧必须在 result 帧之前」那条判据就落在第三个元素上。
    """
    a = KimiAdapter()
    a.shuju: list[tuple[str, dict, str]] = []

    def hui(lei: str, can: dict) -> None:
        a.shuju.append((lei, can, a.kehu_hui))

    a.hui = hui  # type: ignore[attr-defined]
    return a


def _yan(a: KimiAdapter) -> list[str]:
    return [lei for lei, _, _ in a.shuju]


def _zai(a: KimiAdapter, lei: str) -> list[dict]:
    return [can for lei2, can, _ in a.shuju if lei2 == lei]


class Jin_Liu_Yu_Yan_Tests(unittest.TestCase):
    """golden：一行 wire → 统一事件序列。"""

    def setUp(self):
        self.bao = _du(JIN / "kimi.json")

    def _dui_bi(self, an: dict) -> None:
        """喂一条 case 的 wire（含前置行），断言事件序列与 golden 一致。

        **每条 case 用全新适配器。** `_zhuan_wen` / `gong_ju` / `kehu_hui` 是
        跨事件的累积状态，共用一个适配器会让上一条 case 的正文漏进下一条的
        结果里——那种失败与真 bug 长得一模一样，但成因是测试自己。
        """
        a = _yi_jian()
        for zhan in an.get("_zhan_dian", []):
            a.fan_yi(_zhi_(zhan))
        a.shuju.clear()
        a.fan_yi(_zhi_(an["wire"]))
        qi_wang = an["expect"]
        self.assertEqual(_yan(a), [x["kind"] for x in qi_wang],
                         f"{an['_ming']}\n  实际：{_yan(a)}\n"
                         f"  载荷：{a.shuju}")
        for (lei, can, _), qiu in zip(a.shuju, qi_wang):
            self.assertEqual(lei, qiu["kind"], an["_ming"])
            for k, v in qiu.get("match", {}).items():
                self.assertEqual(can.get(k), v, f"{an['_ming']}：字段 {k} 不符")
        # `_fei_bian_jie` / `_shi_bian_jie` 断言的是**边界判定本身**，
        # 判据落在 `jie_shou` 的返回值上（有/没有），不是「事件发了几条」。
        if an.get("_fei_bian_jie"):
            self.assertIsNone(a.jie_shou(an["wire"]),
                              f"{an['_ming']}：被误判成回合边界")
        if an.get("_shi_bian_jie"):
            jie = a.jie_shou(an["wire"])
            self.assertIsNotNone(jie, f"{an['_ming']}：`jie_shou` 没认出回合边界")

    def test_qu_an_wu_wei_fa_chu_she_yao_de_hang(self):
        """**逐条走完整个 golden。**

        这里有个容易假绿的地方：`assertEqual(_yan(a), [...])` 在两边都是空列表时
        也成立，所以「不该发事件」的那几条 case 恰恰最承重——它们靠**长度不等**
        分岔。
        """
        you = 0
        for an in self.bao["cases"]:
            with self.subTest(an=an["_ming"]):
                self._dui_bi(an)
                if an["expect"]:
                    you += 1
        self.assertGreaterEqual(you, 4, "golden 用例太少，跑不到分支")

    def test_wu_wei_fa_chu_de_case_que_zhong_zai_fa_chu_lei(self):
        """「不该发事件」的那几条必须真的有承重：期望为空、且实际长度 > 0 时判 FAIL。

        把这个约束写成用例而不是靠自觉——golden 里如果有人加了一条
        `expect: []` 但实际也发了一帧，5.1 说的假绿就回来了。
        """
        kong = [an for an in self.bao["cases"] if not an["expect"]]
        self.assertGreaterEqual(len(kong), 3, "没有「不该发事件」的样本，跑不到静默分支")
        for an in kong:
            with self.subTest(an=an["_ming"]):
                a = _yi_jian()
                for zhan in an.get("_zhan_dian", []):
                    a.fan_yi(_zhi_(zhan))
                a.shuju.clear()
                a.fan_yi(_zhi_(an["wire"]))
                self.assertEqual(a.shuju, [], f"{an['_ming']}：静默分支发起了事件")


class Zhuan_Quan_Lie_xiu_Tests(unittest.TestCase):
    """golden：整段回合 wire → 事件序列 + 每次收口的结果 dict。

    **这一层比单行 case 更承重**：单行 case 看不出「回合边界判错」的后果
    （判错时那一行照样翻译对，只是收口早了），要看整段序列里 result 的**条数**
    与**每条的内容**才看得出来。
    """

    def setUp(self):
        self.bao = _du(JIN / "kimi.json")

    def _zou(self, an: dict) -> tuple[list[str], list[dict]]:
        a = _yi_jian()
        for qun in an["_dao_yan_lie_xiu"]:
            for hang in qun:
                a.fan_yi(_zhi_(hang))
        return _yan(a), _zai(a, "result")

    def test_qu_an_lie_xiu(self):
        for an in self.bao["zhuan_quan_lie_xiu"]:
            with self.subTest(an=an["_ming"]):
                yan, jie = self._zou(an)
                self.assertEqual(yan, an["_shi_ji_yan_chu"],
                                 f"{an['_ming']}\n  实际：{yan}")
                self.assertEqual(len(jie), len(an["_jie_shou"]),
                                 f"{an['_ming']}：result 帧数不对（判据就落在"
                                 f"「收了几次口」上）\n  载荷：{jie}")
                for qi, huo in zip(jie, an["_jie_shou"]):
                    for k, v in huo.items():
                        self.assertEqual(qi.get(k), v,
                                         f"{an['_ming']}：result 字段 {k} 不符")

    def test_hui_he_wu_jie_cu_bie_luo_guo_liang_dao_dao(self):
        """**收口一次都不能多。**（约束 3 的正面判据）

        分岔：把边界判据写成「`role=="meta`」而不看 `type`。那么开头那条
        `system.version` 就会收一次口，`_qing_kong` 把累加器清空 ⇒
        1) 整段序列里出现**两条** result；
        2) 第一条的 `resultText` 是**空串**（正文还没来就被清掉了）。

        两条判据各自都够分岔：条数落在「收了几次」，内容落在「第一次收口时
        正文在不在」。这里两条都断言。
        """
        an = self.bao["zhuan_quan_lie_xiu"][0]
        _, jie = self._zou(an)
        self.assertEqual(len(jie), 1, f"收了 {len(jie)} 次口，边界判宽了")
        self.assertEqual(jie[0]["resultText"], "完成。",
                         "第一次收口时正文已经被清掉——开头那条 system.version "
                         "被当成了回合边界")

    def test_hui_he_shou_kou_zhi_you_resume_hint(self):
        """**`jie_shou` 只认 `role=="meta"` 且 `type=="session.resume_hint"`。**

        逐个喂「长得像但不是边界」的那些 wire，断言返回 `None`。判据落在返回值
        上（有/没有），不是「有没有发事件」。

        ⚠ **`role` 与 `type` 缺一不可，两条都是真机样本：**
        `system.version` 是**有** role 的 meta（约束 3，点名的那条），
        缺 role 那条是防御性——CLI 换版本时少给一个字段，这里一并守住。
        """
        a = _yi_jian()
        fei_bian_jie = [
            {"role": "meta", "type": "system.version", "version": "2.1.1"},
            {"role": "meta", "type": "unknown.future_type", "session_id": "s"},
            {"type": "session.resume_hint", "session_id": "s"},     # 缺 role
            {"role": "assistant", "type": "session.resume_hint"},    # role 不对
            {"role": "assistant", "content": "完成。"},
            {"role": "assistant", "tool_calls": []},
            {"role": "tool", "tool_call_id": "x", "content": "y"},
            {"role": "", "type": "session.resume_hint"},             # role 空
        ]
        for wire in fei_bian_jie:
            self.assertIsNone(a.jie_shou(wire), f"{wire} 被误判成回合边界")
        # 真的边界认得出来，且正文与 session_id 都在。
        a.fan_yi(json.dumps({"role": "assistant", "content": "正文"},
                            ensure_ascii=False))
        jie = a.jie_shou({"role": "meta", "type": "session.resume_hint",
                          "session_id": "s"})
        self.assertIsNotNone(jie, "真的边界反而没认出来")
        self.assertEqual(jie["resultText"], "正文")
        self.assertEqual(jie["sessionId"], "s")

    def test_session_zhen_you_xian_fa_result_zai_hou(self):
        """**session 帧必须在 result 帧之前**（约束 4 的承重点）。

        分岔：`_yuan_xin_xi` 里先 `jie_shou` 再 `_fa_session`。那么
        1) 事件序列变成 `["result","session"]`；
        2) **result 帧发出那一刻 `kehu_hui` 还是空的**——落盘/前端拿到的会话
           是空的，`run.hui_fu` 恢复时没有 `-r` 可续。

        判据落在「发 result 那一刻 `kehu_hui` 是什么」上，而不是「事后
        `kehu_hui` 对不对」——后者两种实现读出来一样。
        """
        a = _yi_jian()
        for hang in ({"role": "assistant", "content": "完成。"},
                     {"role": "meta", "type": "session.resume_hint",
                      "session_id": "session_xxx"}):
            a.fan_yi(json.dumps(hang, ensure_ascii=False))
        lei = _yan(a)
        self.assertEqual(lei, ["text", "session", "result"], f"顺序错：{lei}")
        res = [(can, sid) for k, can, sid in a.shuju if k == "result"][0]
        self.assertEqual(res[1], "session_xxx",
                         "result 帧发出时会话 id 还没写上——先收口后报 session，"
                         "第一回合的会话会丢")
        self.assertEqual(res[0].get("sessionId"), "session_xxx")

    def test_session_zhen_zhi_fa_yi_ci(self):
        """**同一会话的后续回合不再发 session 帧**（`_fa_le_session` 幂等）。

        分岔：每个回合都发一次 ⇒ 落盘会话被反复覆写（而 id 其实没变，
        真实后果是每次收口都多一次写盘 + 前端多一次跳转）。
        """
        a = _yi_jian()
        for _ in range(2):
            a.fan_yi(json.dumps({"role": "assistant", "content": "x"},
                                ensure_ascii=False))
            a.fan_yi(json.dumps({"role": "meta", "type": "session.resume_hint",
                                 "session_id": "session_xxx"},
                                ensure_ascii=False))
        self.assertEqual(len(_zai(a, "session")), 1,
                         f"session 帧发了 {_zai(a, 'session').__len__()} 次")
        self.assertEqual(len(_zai(a, "result")), 2, "两回合该各收一次口")


class Wen_De_Fen_Zhi_Tests(unittest.TestCase):
    """文本归集：content 与 tool_calls 二选一、工具往返配对、坏行不许吞掉整轮。"""

    def test_gong_ju_arguments_shi_zi_fu_chu_xu_jie_yi_ci(self):
        """**`arguments` 是 JSON 字符串，必须解一次**（kimi.py 文件头标注）。

        判据落在 **`toolInput` 的类型**上：解了是 dict，不解是 str。
        两种实现都「发了一条 tool_use」，只断言事件条数与 toolUseId 两边都成立
        ⇒ 那是废断言。
        """
        a = _yi_jian()
        a.fan_yi(json.dumps({"role": "assistant", "tool_calls": [
            {"type": "function", "id": "t1",
             "function": {"name": "Bash", "arguments": "{\"command\":\"echo hi\"}"}}]}))
        shu = _zai(a, "tool_use")
        self.assertEqual(len(shu), 1)
        self.assertIsInstance(shu[0]["toolInput"], dict,
                              "toolInput 还是字符串——嵌套 JSON 没解，"
                              "界面拿不到 command")
        self.assertEqual(shu[0]["toolInput"], {"command": "echo hi"})

    def test_jie_biao_de_nei_qian_json_luo_cheng_raw_bu_qi_pao(self):
        """解不了的嵌套 JSON **不许抛**——落成 `{"raw": 原串}`。

        分岔：直接 `json.loads` 不包 try。抛出去 ⇒ 基类读循环
        （`chuan_shu.py:330-333`）只发一帧 `translate_failed`、**不收口回合**
        ⇒ `fasong()` 挂到 15 分钟看门狗，症状是「Agent 无响应」而不是
        「翻译出错」。单测里"抛了"很容易漏，所以显式断言事件序列里**没有**
        `translate_failed`，且回合照样收口。
        """
        a = _yi_jian()
        a.fan_yi(json.dumps({"role": "assistant", "tool_calls": [
            {"type": "function", "id": "t1",
             "function": {"name": "Bash", "arguments": "{这不是 JSON"}}]}))
        self.assertNotIn("translate_failed", _yan(a), "嵌套 JSON 解析抛异常了")
        shu = _zai(a, "tool_use")
        self.assertEqual(len(shu), 1, "工具调用被整条丢掉了")
        self.assertEqual(shu[0]["toolInput"], {"raw": "{这不是 JSON"})

    def test_dai_tool_calls_de_fu_zhu_bu_sheng_cheng_zheng_wen(self):
        """**带 `tool_calls` 的 assistant 消息不产生 text**（content 与 tool_calls 二选一）。

        分岔：两个分支都执行（只把事件类型写对）。那种实现单测里事件看起来
        正常，只有 `resultText` 被污染——而决策回路就是靠这个字段把结果送回
        LifeOS 对话上下文。

        ⚠ 真机 wire 上两者不会同时出现，所以本条样本是**合成的**：
        它守的是适配器写下的优先级（tool_calls 赢），不是对 wire 的断言。
        """
        a = _yi_jian()
        a.fan_yi(json.dumps({"role": "assistant",
                             "content": "这条 content 真机上不会出现",
                             "tool_calls": [
                                 {"type": "function", "id": "t1",
                                  "function": {"name": "Bash",
                                               "arguments": "{\"command\":\"echo hi\"}"}}]}))
        self.assertEqual(_yan(a), ["tool_use"],
                         "带 tool_calls 的帧多发了一条 text")
        a.fan_yi(json.dumps({"role": "meta", "type": "session.resume_hint",
                             "session_id": "s"}))
        self.assertEqual(_zai(a, "result")[0]["resultText"], "",
                         "工具调用帧的内容漏进了正文")


class Huan_Jie_Shou_Kou_Tests(unittest.TestCase):
    """收口：`_bu_que_men_can` 补默认字段 + 累加器清空。"""

    def test_bu_que_men_can_bu_qi_lei(self):
        """结果 dict 必须带上 `durationMs` / `numTurns` / `totalCostUsd` / `sessionId`。

        判据落在**键存在 + 类型对**上：`_jie_shu_bian_jie` 只组了四个字段，
        剩下这几个是 `_bu_que_men_can` 补的。不补 ⇒ 上层拿到的 dict 缺字段，
        而缺字段与「值为 0」在很多下游读法里都悄悄过去了。
        """
        a = _yi_jian()
        a.fan_yi(json.dumps({"role": "assistant", "content": "完成。"},
                            ensure_ascii=False))
        jie = a.jie_shou({"role": "meta", "type": "session.resume_hint",
                          "session_id": "session_xxx"})
        self.assertIsNotNone(jie)
        for k in ("durationMs", "numTurns", "totalCostUsd", "sessionId",
                  "resultText", "isError", "subtype"):
            self.assertIn(k, jie, f"结果 dict 缺字段 {k}")
        self.assertIsInstance(jie["durationMs"], int)
        self.assertIsInstance(jie["totalCostUsd"], float)
        self.assertEqual(jie["numTurns"], 1)
        self.assertEqual(jie["sessionId"], "session_xxx")
        self.assertFalse(jie["isError"])
        self.assertEqual(jie["subtype"], "completed")

    def test_durationMs_yao_zhen_de_cong_ji_shi_qi_kao_chu_lai(self):
        """`durationMs` 必须**真的从计时器算**，不是硬编码 0。

        ⚠ **不能 sleep**：本项目实测固定时长 sleep 在 Windows 上必然 flake。
        这里直接把 `_zhuan_kaishi` 拨到 1.5 秒前，判据落在「算出来的值落在
        1500 上下」这个量上——硬编码 0 与「没设计时器」两种实现都会 FAIL。
        """
        a = _yi_jian()
        a._zhuan_kaishi = time.monotonic() - 1.5   # type: ignore[attr-defined]
        jie = a.jie_shou({"role": "meta", "type": "session.resume_hint"})
        self.assertIsNotNone(jie)
        self.assertGreaterEqual(jie["durationMs"], 1500,
                                "durationMs 没有从计时器算（硬编码 0？）")

    def test_hui_he_zhi_hou_zheng_wen_Bei_qing_kong(self):
        """回合边界之后累加器必须清空，否则下一回合的结果是两条回复拼一起。

        判据落在「第二次收口的 `resultText`」上，不是「有没有被清过」——
        后者两种实现读出来一样。
        """
        a = _yi_jian()
        a.fan_yi(json.dumps({"role": "assistant", "content": "第一回合"},
                            ensure_ascii=False))
        a.fan_yi(json.dumps({"role": "meta", "type": "session.resume_hint",
                             "session_id": "s"}))
        a.fan_yi(json.dumps({"role": "assistant", "content": "第二回合"},
                            ensure_ascii=False))
        jie = a.jie_shou({"role": "meta", "type": "session.resume_hint"})
        self.assertEqual(jie["resultText"], "第二回合", "上一回合的正文漏进第二回合")

    def test_fan_yi_mian_de_ju_zhen_bu_diao_jie_shou(self):
        """**非边界行不许碰收口。**

        分岔：在 `fan_yi` 里顺手调 `_jie_shu_kao_ben`（pi 的教训：基类读循环
        不自动调，但适配器自己调早了也一样）。那会在回合刚开始就把 Future
        唤醒，`fasong()` 秒回，`paichu` 于是判这条指令完成——而正文还没来。
        判据落在「`fasong()` 挂的那个 Future 有没有被提前 set_result」上。
        """

        async def zhen():
            a = _yi_jian()
            a.loop = asyncio.get_running_loop()
            fu = a.loop.create_future()
            a._xu_hao = 1                    # type: ignore[attr-defined]
            a._jie_shu[1] = fu               # type: ignore[attr-defined]
            for hang in ({"role": "meta", "type": "system.version"},
                         {"role": "assistant", "content": "还在跑…"},
                         {"role": "tool", "tool_call_id": "t1", "content": "x"},
                         "坏行 :("):
                a.fan_yi(json.dumps(hang, ensure_ascii=False)
                         if not isinstance(hang, str) else hang)
                await asyncio.sleep(0)
                self.assertFalse(fu.done(),
                                 f"{hang} 之后回合就被判结束了——fasong() 会秒回，"
                                 "而正文还没到")
            a.fan_yi(json.dumps({"role": "meta", "type": "session.resume_hint",
                                 "session_id": "s"}))
            self.assertTrue(fu.done(), "回合边界没有唤醒 fasong")

        asyncio.run(zhen())


class Ce_Shi_He_Rong_Yue_Tests(unittest.TestCase):
    """L-A 结构：argv 与能力契约。"""

    def test_ce_wu_tou_yao_ban_de_can_shi_ban_not_can_shi(self):
        """`CE_WU_TOU` 必须是 `["--version"]`。

        分岔：留基类默认的 `["--help"]`。抓版本号靠 `(\\d+\\.\\d+\\.\\d+)` 正则，
        `kimi --help` 的正文里没有版本号 ⇒ `tanjian()` 把**可执行文件路径**
        当版本号返回（实测抓到 `C:\\...\\kimi.CMD`），界面上显示成一串路径。
        """
        self.assertEqual(KimiAdapter.CE_WU_TOU, ["--version"])

    def test_zi_ling_heng_dai_output_format_lie_xu_jie_bu_dai_fang_wen(self):
        """argv：`--output-format stream-json` **恒带**，`-r` 只在有续接 id 时加。

        分岔：漏掉 `--output-format` ⇒ CLI 走 text 输出，stdout 上没有 JSON，
        `fan_yi` 一行都收不到，回合永远收不了口。
        分岔：`--print`（cc-connect 用的那个）本机 2.1.1 已删 ⇒ 直接
        `unknown option`。
        """
        a = _yi_jian()
        a._wen = "你好"                       # type: ignore[attr-defined]
        a.kehu_hui = ""
        self.assertEqual(a._zi_ling({}),
                         ["--output-format", "stream-json", "-p", "你好"])
        a.kehu_hui = "session_xxx"
        self.assertEqual(a._zi_ling({}),
                         ["--output-format", "stream-json", "-r", "session_xxx",
                          "-p", "你好"])
        self.assertNotIn("--print", a._zi_ling({}), "新版已删掉 --print")
        self.assertNotIn("--plan", a._zi_ling({}),
                         "--plan 不能与 -p 组合（真机：Cannot combine）")

    def test_shi_yi_ci_xing_bu_qi_spawn_zao_kaishi(self):
        """一次性进程：`kaishi()` 不 spawn，第一条指令才起进程。"""
        self.assertTrue(KimiAdapter.yi_ci_xing)

    def test_neng_li_gong_gao_ming_que_wei_fen_shou_dou_fou_jiang(self):
        """`fangquan` / `wenti2` 都报 False——非交互模式下 CLI 自己管权限。

        真机实测：kimi 在 `-p` 模式下跑 `rm -f zzz_t.txt` 全程零审批事件。

        分岔：任一个报 True ⇒ `/agents` 给这个 harness 发审批卡，但对方根本不会
        问，用户点了「批准」也只是一个永远兑现不了的承诺。
        """
        self.assertFalse(KimiAdapter.fangquan())
        self.assertFalse(KimiAdapter.wenti2())

    def test_moshi_zi_zhi_you_manual_wu_tou_ban_fa_dai_bu_liao(self):
        """`MOSHI_ZI` 只声明 `manual`——kimi 的权限旗标在 `-p` 模式全军覆没。

        2026-10-06 真机逐个核实，三个旗标在 `-p` 下全部当场报错：
        `--plan` / `-y` / `--auto` 都是 `Cannot combine --prompt with …`。
        ⇒ 无头模式没有可切换的权限面，声明任何宽松档都是 UI 承诺兑现不了的
        能力。判据落在「上报的模式集」上：非空（下拉框不能全空）、
        只含 manual、⊆ 全局白名单——与 `{"manual","dontAsk"}` 这种错误声明
        在第一个断言上就分岔。
        """
        from lifeos.bridge.models import MOSHI
        zi = KimiAdapter.MOSHI_ZI
        self.assertEqual(zi, frozenset({"manual"}),
                         "kimi 只能如实声明 manual（三个权限旗标 -p 全拒）")
        self.assertTrue(zi <= set(MOSHI), "声明的模式越界了")
        self.assertEqual(sorted((zi or MOSHI) & MOSHI), ["manual"],
                         "上报给前端的下拉框不该再出现五档")

    def test_wu_tou_mo_shi_bu_hui_tou_dai_ren_he_qi_zhi(self):
        """permissionMode 就算被设成宽松值，argv 也不许多出任何旗标。

        kimi 没有可用的权限旗标（见上一条）。分岔：有人照着 opencode/hermes
        的样子给 kimi 也接一个 `--yolo`/`--auto` ⇒ 真机 `Cannot combine`，
        每一条指令都起不来。判据：把 `moshi` 硬设成 `dontAsk`，argv 必须与
        manual 完全一致。
        """
        a = _yi_jian()
        a._wen = "你好"                       # type: ignore[attr-defined]
        a.kehu_hui = ""
        a.moshi = "dontAsk"                   # type: ignore[attr-defined]
        self.assertEqual(a._zi_ling({}),
                         ["--output-format", "stream-json", "-p", "你好"],
                         "kimi 不许给 argv 接任何权限旗标（-p 模式全拒）")

    def test_buneng_qie_huan_mo_shi_bu_jie_ding_yi_gai_moshi(self):
        """kimi 切不出本项目的五档模式 ⇒ **不许定义 `gai_moshi`**。

        `http._gai_moshi` 用 `hasattr` 判「这个 harness 能不能切」，定义了它
        就恒为 True，于是界面发出切换请求、`_gai_moshi` 还把新模式**落盘**——
        用户下次看到「plan 模式」，实际 kimi 从没按 plan 跑过（它连 `--plan`
        都拒绝）。
        """
        self.assertFalse(hasattr(KimiAdapter(), "gai_moshi"))

    def test_dui_hui_id_shi_claude_session_id(self):
        """kimi 的会话 id 落在 `claudeSessionId`——`http._hui_zhuan` 只认这个键。"""
        self.assertEqual(KimiAdapter.dui_hui_id, "claudeSessionId")
        self.assertFalse(KimiAdapter.xu_pei_zhuang, "kimi 不需要 Bridge 写配置文件")


if __name__ == "__main__":
    unittest.main()