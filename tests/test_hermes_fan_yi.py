"""hermes 适配器的 L-B（golden）测试。

**这份测试在验什么**：翻译层把 hermes 的 JSONL wire 转成统一事件时，字段名、
分支、id 配对、回合边界判对没有抄错。

**它在不验什么**：golden 的正确性取决于样本抄得对不对，而样本是从真机 stdout
抄的。所以它**只是回归护栏，不是「已验证」**。真验收是 L-C / L-D
（真 spawn `hermes chat -q --format stream-json` 打真回合）。

## 判据落在哪里

golden 的机制是「按序喂一组真机 wire，断言发出的统一事件序列」，所以判据天然
落在**序列**上——包括「哪些事件**不该**发」。每条样本都刻意让两种实现读出不同结果：

| 判据 | 两种实现会分岔在 |
|---|---|
| **`tool_use` 没有 id ⇒ 必须自造**（约束 3） | 两条帧的 `toolUseId` 相同且非空，还是填空串 / 拿工具名当 id（不配对 ⇒ 前端工具卡永远收不了口） |
| **`output` 要解两次 JSON**（约束 4） | `text` 字段是纯正文 `hx`，还是那串原始 `{"output":"hx",…}` |
| **失败判据是外层 `is_error`**（约束 6） | `isError` 为 true 还是 false（样本造「内层 error=null / 外层 true」与反向两条，两侧都钉死） |
| **text 分片只累加不发帧**（约束 5） | 零帧，还是每片一条 text（界面上多条碎消息） |
| **正文取 `result.text` 而非累加器** | 样本刻意让两者**内容不同**，否则两条实现读出来一样 |
| **边界只在 `type=="result"`** | `jie_shou` 对别的 type 返回 None 还是误收口（误收口 ⇒ 结果是空的） |
| **坏行不许吞掉整轮** | 后面那回合有没有收口、正文对不对（不是「有没有发 error 帧」） |
| **stderr 纯文本不许被当 wire** | 那行 `session_id: xxx` 只变成 bad_line error，绝不变成 session 帧 |

**不 sleep 固定时长**：本项目实测 `sleep(2.0)` 在 Windows 上必然 flake。
这里全是纯函数调用（`fan_yi` / `jie_shou`），没有等待、没有子进程。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from lifeos.bridge.adapters.hermes import HermesAdapter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

JIN = Path(__file__).resolve().parent / "golden"


def _du(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _yi_jian() -> HermesAdapter:
    """造一个不 spawn 任何东西的适配器，把事件收进列表。"""
    a = HermesAdapter()
    a.shuju = []  # type: ignore[attr-defined]
    a.hui = lambda lei, can: a.shuju.append((lei, can))  # type: ignore[attr-defined]
    return a


def _nei(an: dict) -> str:
    """造出 `tool_result.output` 的**外层** JSON 串（约束 4 的第一层）。

    ## 真机 wire 的形状

    ```
    "output": "{\\"output\\":\\"hx\\",\\"exit_code\\":0,\\"error\\":null}"
    ```
    外层是一个 JSON 串，解一次得到 `{"output": "hx", …}`。

    ## ⚠ 但光是这样**造不出分岔**（本文件实测踩过）

    内层 `output` 是**纯文本** `hx` 时，`_gong_ju_wen` 的第二次 `_json_wen("hx")`
    解不了会**原样返回 `"hx"`**，与它下面那条兜底 `return str(yi.get("output"))`
    给出**同一个值** ⇒「只解一次」与正确实现读出来完全一样 ⇒ 判据是废的。

    ⇒ **凡是造 `tool_result` 样本，一律过这个函数**（保证外层形状与真机一致）。
    ⇒ **真正承载「解两次」这条判据的样本在**
    `test_gong_ju_guo_de_wen_yao_cong_nei_ceng_json_wen_li_bao_chu_lai`：
    那里内层 `output` 的值**本身还是一个 JSON 串**（`json.dumps("hx")`），
    两种实现才真的分岔。
    """
    return json.dumps(an, ensure_ascii=False)


def _zhao_lie(an: dict, tiao: bool = False) -> list[str]:
    """把 `_zhao_lie` 转成要喂的行。

    元素是 str ⇒ **原样喂**（hermes 的坏行与 stderr 纯文本就是这种）；
    是 dict ⇒ 序列化成一行 JSONL。
    """
    return [x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)
            for x in an["_zhao_lie"]]


class Jin_Liu_Yu_Yan_Tests(unittest.TestCase):
    """golden：hermes wire → 统一事件。"""

    def setUp(self):
        self.bao = _du(JIN / "hermes.json")

    def _dui_bi(self, an: dict, qi_wang: list[dict], ming: str) -> None:
        """喂一组 wire，断言发的事件序列与 golden 一致。

        **每条 case 用全新适配器。** `_zhuan_wen` / `_cuo_wen` / `_dai_pei` /
        `_ci` 都是跨事件累积的状态，共用一个适配器会让上一条 case 的正文与
        待配对队列漏进下一条的结果里——那种失败与真 bug 长得一模一样，
        但成因是测试自己。

        ⚠ 同时清一下**跨 case 会变的东西**：`_fa_le_session`（一次性标志）
        由 `__init__` 置位，不需要额外处理；但 `_jie_shou` 之后累加器会清空，
        所以断言一律用**同一组行**重新喂，不要靠增量。
        """
        a = _yi_jian()
        for xing in _zhao_lie(an):
            a.fan_yi(xing)
        self.assertEqual(len(a.shuju), len(qi_wang),
                         f"{ming}\n  实际：{[k for k, _ in a.shuju]}\n"
                         f"  期望：{[x['kind'] for x in qi_wang]}\n  载荷：{a.shuju}")
        for (lei, can), qiu in zip(a.shuju, qi_wang):
            self.assertEqual(lei, qiu["kind"], ming)
            for k, v in qiu.get("match", {}).items():
                self.assertEqual(can.get(k), v, f"{ming}：字段 {k} 不符")
                self.assertIn(k, can, f"{ming}：字段 {k} 压根没发")

    def test_qu_an_wu_wei_fa_chu_she_yao_de_hang(self):
        """**逐条走完整个 golden。**

        这里有个容易假绿的地方：`assertEqual(len(...), len(qi_wang))`
        在两边都是 0 时也成立，所以「不该发事件」的那些 case 恰恰最承重——
        它们靠**长度不等**分岔（发一条 text 分片、给孤儿 tool_result 填空串、
        把 stderr 纯文本回退解析成 session 帧，全都会让长度不等）。
        """
        zong = 0
        for an in self.bao["cases"]:
            with self.subTest(an=an["_ming"]):
                self._dui_bi(an, an["expect"], an["_ming"])
                if an["expect"]:
                    zong += 1
        self.assertGreaterEqual(zong, 12, "golden 用例太少，跑不到分支")

    # ---------- 约束 3：tool_use 没有 id ----------

    def test_gong_ju_pai_dui_de_liang_tiao_zhuang_wei_xiang_tong(self):
        """**`tool_use` 与 `tool_result` 的 `toolUseId` 必须相同且非空。**

        分岔：填空串 / 拿工具名当 id。hermes 的 wire **根本没有 id 字段**
        （kimi 与 opencode 都有），不配对 ⇒ 前端工具卡永远收不了口，
        用户看到的是一张「转圈转不完」的卡。

        判据落在**两个事件读出来的 id 之间的关系**上，不是「id 是不是
        hermes-1」这种具体值——后者两种实现都能凑出来。
        """
        a = _yi_jian()
        a.fan_yi(json.dumps({"type": "tool_use", "name": "terminal",
                             "input": {"command": "echo hx"}}))
        a.fan_yi(json.dumps({"type": "tool_result", "name": "terminal",
                             "output": _nei({"output": "hx", "exit_code": 0,
                             "error": None}),
                             "is_error": False}))
        yong = [p for k, p in a.shuju if k == "tool_use"]
        guo = [p for k, p in a.shuju if k == "tool_result"]
        self.assertEqual(len(yong), 1, f"tool_use 帧数不对：{a.shuju}")
        self.assertEqual(len(guo), 1, f"tool_result 帧数不对：{a.shuju}")
        self.assertTrue(yong[0]["toolUseId"], "**id 不能是空串**——前端配不上对")
        self.assertEqual(yong[0]["toolUseId"], guo[0]["toolUseId"],
                         "两条帧的 toolUseId 不一致 ⇒ 工具卡收不了口")

    def test_gong_ju_id_bun_neng_tou_chuan_wire_zi_de_id(self):
        """**id 必须自造，不能透传 wire 里的 `id`。**

        本样本**故意**给 `tool_use` 塞一个 wire 上从不存在的 `id` 字段，
        而 `tool_result` 照真机那样**不带 id**（它只给 `name`）。

        分岔：实现改成「wire 有 id 就用 wire 的」⇒ `tool_result` 侧无从对齐
        （它根本没有 id 字段）⇒ 要么配不上对，要么被退化成拿 name 反查。
        判据落在「发出去的 id 与 wire 里那个 id **不相等**」上。

        ⚠ 这不是为了测「wire 上没有 id 就没有 id」——那两种实现读出来一样。
        """
        a = _yi_jian()
        a.fan_yi(json.dumps({"type": "tool_use", "name": "terminal",
                             "id": "WIRE_ZI_DE_ID", "input": {"command": "echo hx"}}))
        a.fan_yi(json.dumps({"type": "tool_result", "name": "terminal",
                             "output": _nei({"output": "hx", "exit_code": 0,
                             "error": None})}))
        yong = [p for k, p in a.shuju if k == "tool_use"]
        guo = [p for k, p in a.shuju if k == "tool_result"]
        self.assertEqual(len(yong), 1, a.shuju)
        self.assertEqual(len(guo), 1, a.shuju)
        self.assertNotEqual(yong[0]["toolUseId"], "WIRE_ZI_DE_ID",
                            "id 是透传 wire 的 —— tool_result 侧根本没有 id，配不上对")
        self.assertEqual(yong[0]["toolUseId"], guo[0]["toolUseId"])

    def test_tong_ming_gong_ju_lian_liang_ci_de_id_buneng_xiang_tong(self):
        """**同名工具的两次调用必须拿到不同 id，且 FIFO 配对。**

        分岔一：id 只按 name 生成 ⇒ 两次调用共用一个 id，界面上两张卡叠一起。
        分岔二：LIFO 配对 ⇒ 第一个结果贴到第二次调用上。
        """
        a = _yi_jian()
        a.fan_yi(json.dumps({"type": "tool_use", "name": "terminal",
                             "input": {"command": "echo A"}}))
        a.fan_yi(json.dumps({"type": "tool_use", "name": "terminal",
                             "input": {"command": "echo B"}}))
        self.assertNotEqual(a.shuju[0][1]["toolUseId"], a.shuju[1][1]["toolUseId"],
                            "同名的两次调用共用了一个 id ⇒ 两张卡叠在一起")
        a.fan_yi(json.dumps({"type": "tool_result", "name": "terminal",
                             "output": _nei({"output": "A", "exit_code": 0,
                             "error": None})}))
        a.fan_yi(json.dumps({"type": "tool_result", "name": "terminal",
                             "output": _nei({"output": "B", "exit_code": 0,
                             "error": None})}))
        guo = [p for k, p in a.shuju if k == "tool_result"]
        self.assertEqual([p["toolUseId"] for p in guo],
                         [a.shuju[0][1]["toolUseId"], a.shuju[1][1]["toolUseId"]],
                         "**不是 FIFO** —— 第一个结果贴到了第二次调用上")
        self.assertEqual([p["text"] for p in guo], ["A", "B"])

    def test_gu_shu_pei_dui_de_tool_result_buneng_fa(self):
        """没有待配对的 `tool_use` ⇒ **一条 tool_result 都不许发**。

        分岔：照样发一条 `toolUseId:""` 的 tool_result（把 `_qu_dai_pei` 的
        空串当合法 id）⇒ 前端拿到一张配不上任何工具卡的孤儿卡。
        """
        a = _yi_jian()
        a.fan_yi(json.dumps({"type": "tool_result", "name": "terminal",
                             "output": _nei({"output": "hx", "exit_code": 0,
                             "error": None})}))
        self.assertEqual(a.shuju, [], "孤儿 tool_result 被发出去了")

    def test_qi_mo_qi_lun_zhuan_cun_juan_xin_de_id_bu_ke_yi_zhong_yong(self):
        """新回合必须重置自造 id 的计数与待配对队列。

        分岔：不重置 ⇒ 上一回合没配对完的 `tool_use` 还在队列里，这一回合的
        `tool_result` 配到上一条 id 上 ⇒ 界面上的工具卡显示成「上一条工具的结果」。
        """
        import asyncio

        async def zhen():
            a = _yi_jian()
            await a._fan_yi_zhun_bei()
            a.fan_yi(json.dumps({"type": "tool_use", "name": "terminal",
                                 "input": {"command": "echo A"}}))
            self.assertIsNotNone(a.jie_shou({"type": "result", "exit_code": 0,
                                             "text": "一"}),
                                 "回合没收口：这条 id 就没有下一回合可泄漏的场合")
            a.shuju.clear()
            await a._fan_yi_zhun_bei()
            a.fan_yi(json.dumps({"type": "tool_result", "name": "terminal",
                                 "output": _nei({"output": "B", "exit_code": 0,
                             "error": None})}))
            self.assertEqual(a.shuju, [],
                             "新回合的 tool_result 配到了上一回合的 tool_use 上")

        asyncio.run(zhen())

    # ---------- 约束 4：output 是双层 JSON ----------

    def test_gong_ju_guo_de_wen_yao_cong_nei_ceng_json_wen_li_bao_chu_lai(self):
        """**内层 `output` 仍是 JSON 串时，正文必须再解一层。**

        分岔：只解一次 ⇒ `text` 变成 `"hx"`（带引号的 JSON 串字面量）
        或整串 `{"output":"hx",…}`，显示在工具卡上。

        ## 为什么样本必须是「三层」而不是「两层」（变异验证实测踩出来的）

        真机 wire（`hermes.py` 文件头那一行）里 `output` 的值是
        `{"output":"hx","exit_code":0,"error":null}` —— 解一次得到 dict，
        它的 `output` 字段是**纯文本** `hx`，`json.loads("hx")` 抛错，
        `_json_wen` 原样返回 `hx`。⇒ **在真机那个样本上，第二次 `_json_wen`
        是空操作**，与它下面那条 `return str(yi.get("output"))` 的兜底
        给出同一个值 ⇒ 拿真机样本去判「解一次 vs 解两次」是**废断言**
        （把第二次解去掉，测试全绿）。

        ⚠ 而「把内层也 `json.dumps` 一次」的双层样本**更糟**：它在**正确
        实现**上就给出 `{"output":"hx",…}` 整串，断言 `text == "hx"` 会假红。

        ⇒ 唯一能造出分岔的形状是本条用的：**内层 `output` 的值本身还是
        一个 JSON 串**（`json.dumps("hx")` = `"\"hx\""`）。此时正确实现
        再解一层拿到 `hx`，只解一次的实现吐 `"hx"`。判据落在 `text`
        **逐字等于 `hx`** 上（不是「非空」）。
        """
        nei = json.dumps("hx")          # 内层 output 的值本身还是 JSON 串
        wai = _nei({"output": nei, "exit_code": 0, "error": None})
        a = _yi_jian()
        a.fan_yi(json.dumps({"type": "tool_use", "name": "terminal",
                             "input": {"command": "echo hx"}}))
        a.fan_yi(json.dumps({"type": "tool_result", "name": "terminal",
                             "output": wai, "is_error": False}))
        guo = [p for k, p in a.shuju if k == "tool_result"]
        self.assertEqual(len(guo), 1, a.shuju)
        self.assertEqual(guo[0]["text"], "hx", "内层 JSON 串没解开")
        # 把「为什么必须三层」钉成断言，免得将来有人把样本改回真机形状：
        # 真机形状下第二次解确实是空操作，那不是本条要守的东西。
        self.assertEqual(json.loads(json.loads(wai)["output"]), "hx")
        # 真机形状（内层是纯文本）本身也必须走通——它靠的是另一条兜底，
        # 本条的样本不能替它担保。
        zhen = _nei({"output": "hx", "exit_code": 0,
                             "error": None})
        self.assertEqual(HermesAdapter._gong_ju_wen(zhen), "hx")

    def test_gong_ju_guo_de_lu__nei_wai_cun_zhe_yang_de_wen_bu_neng_rang_fan_yi_bao_lei(self):
        """`output` 是纯文本时**原样当正文，不许抛**。

        分岔：裸 `json.loads` 抛 `JSONDecodeError` ⇒ 被基类 `_du_zhan` 吞成一条
        `translate_failed`，而那个分支**不调 `_jie_shu_kao_ben`** ⇒ 回合永不收口，
        `fasong()` 挂到 15 分钟看门狗，症状是「Agent 无响应」而不是「翻译出错」。
        """
        a = _yi_jian()
        a.fan_yi(json.dumps({"type": "tool_use", "name": "terminal",
                             "input": {"command": "echo hx"}}))
        a.fan_yi(json.dumps({"type": "tool_result", "name": "terminal",
                             "output": "hx", "is_error": False}))
        guo = [p for k, p in a.shuju if k == "tool_result"]
        self.assertEqual(len(guo), 1, f"tool_result 没发出去：{a.shuju}")
        self.assertEqual(guo[0]["text"], "hx")

    # ---------- 约束 6：失败判据是外层 is_error ----------

    def test_shi_bai_de_pan_ju_shi_wai_ceng_is_error(self):
        """**外层 `is_error` 为 true ⇒ `isError` 必须为 true，即使内层 `error` 是 null。**

        分岔：读内层 `error` ⇒ 报成功，界面上工具卡显示「成功」，
        用户以为命令跑成了。

        ⚠ 这条断言的期望值（「true」）与缺陷实现（读内层）的输出（false）
        正好相反，不是把缺陷写进断言。
        """
        a = _yi_jian()
        a.fan_yi(json.dumps({"type": "tool_use", "name": "terminal",
                             "input": {"command": "exit 1"}}))
        a.fan_yi(json.dumps({
            "type": "tool_result", "name": "terminal",
            "output": _nei({"output": "", "exit_code": 1,
                             "error": None}),
            "is_error": True}))
        guo = [p for k, p in a.shuju if k == "tool_result"]
        self.assertEqual(len(guo), 1, a.shuju)
        self.assertIs(guo[0]["isError"], True,
                      "内层 error 是 null 就判成功 ⇒ 工具卡显示成功，用户以为命令跑成了")

    def test_nei_ceng_error_you_zhi_bing_fou_bu_ying_gai_bian_wai_ceng_pan_ju(self):
        """反向对照：内层 `error` 有值、外层 `is_error` 为 false ⇒ 仍算成功。

        两个字段反向时读内层的实现会在这一条上反过来报错，两侧都钉死才算
        判据落在「读哪个字段」上而不是「恰好蒙对」。
        """
        a = _yi_jian()
        a.fan_yi(json.dumps({"type": "tool_use", "name": "terminal",
                             "input": {"command": "echo hx 2>&1"}}))
        a.fan_yi(json.dumps({
            "type": "tool_result", "name": "terminal",
            "output": _nei({"output": "hx", "exit_code": 0,
                             "error": "command not found: x"}),
            "is_error": False}))
        guo = [p for k, p in a.shuju if k == "tool_result"]
        self.assertEqual(len(guo), 1, a.shuju)
        self.assertIs(guo[0]["isError"], False)

    # ---------- 约束 5：text 分片只累加 ----------

    def test_wen_zen_pi_pian_bu_neng_pian_pian_fa_kuang(self):
        """**text 帧分多片 ⇒ 一条 `text` 帧都不许发。**

        分岔：每片发一条 ⇒ 界面上出现多条碎消息，而真机上两片拼起来才是
        完整答复。判据落在「事件序列里有没有多出来的 text 帧」上
        （长度不等），不是「有没有发过内容」。
        """
        a = _yi_jian()
        for pian in ("\n\n完成 —", " bash 执行 `echo hx`，输出 `hx`。"):
            a.fan_yi(json.dumps({"type": "text", "text": pian}))
        self.assertEqual(a.shuju, [],
                         f"分片被当成了独立消息：{a.shuju}")

    def test_zheng_wen_qu_zi_result_text_bu_shi_lei_jia_qi(self):
        """**权威正文是 `result.text`，累加器只作兜底。**

        分岔：只读累加器。本样本让 `result.text` 与累加器**内容不同**
        （`完整最终答复` vs `\\n\\n完成 — bash 执行 …`），否则两条实现读出来
        一样。
        """
        a = _yi_jian()
        a.fan_yi(json.dumps({"type": "text", "text": "\n\n完成 —"}))
        a.fan_yi(json.dumps({"type": "text", "text": " bash 执行 `echo hx`。"}))
        jie = a.jie_shou({"type": "result", "exit_code": 0, "text": "完整最终答复"})
        self.assertEqual(jie["resultText"], "完整最终答复", "只读了累加器")

    def test_result_text_kong_le_shi_hui_luo_dao_lei_jia_qi(self):
        """`result.text` 为空时回落到累加器（兜底那条路必须还能走通）。"""
        a = _yi_jian()
        a.fan_yi(json.dumps({"type": "text", "text": "正在重试…"}))
        jie = a.jie_shou({"type": "result", "exit_code": 0, "text": ""})
        self.assertEqual(jie["resultText"], "正在重试…")

    # ---------- 回合边界 ----------

    def test_hui_he_bian_jie_que_cai_de_yao_zhi_you_result(self):
        """**边界只在 `type=="result"`。**

        分岔：把判据放宽成「任何一种事件」（或 `system/init`）⇒ 回合刚开始
        就被收走，用户看到空结果。
        """
        a = _yi_jian()
        for zhao in ({"type": "system", "subtype": "init", "session_id": "x"},
                     {"type": "text", "text": "半句"},
                     {"type": "tool_use", "name": "terminal", "input": {}},
                     {"type": "tool_result", "name": "terminal", "output": "x"},
                     {"type": "unknown"},
                     {}):
            self.assertIsNone(a.jie_shou(zhao), f"{zhao} 被误判成回合边界")
        self.assertIsNotNone(a.jie_shou({"type": "result", "exit_code": 0,
                                         "text": "答复"}))

    def test_shi_bai_hui_he_de_san_ge_xin_xi_dou_yao_zheng_que(self):
        """`exit_code != 0` ⇒ `isError` / `subtype` / `errorMessage` 三者一致。

        分岔：只置 `isError` 而 `subtype` 仍是 `completed` ⇒ 上层把失败回合
        当成成功，决策回路把错误正文当正常答复存进 LifeOS 对话上下文。
        ⚠ **必须走 `fan_yi` 而不是直接调 `jie_shou`**：`isError` 与 `subtype`
        两个判据读的是不同的量（`subtype` 看 `_cuo_wen`，而 `_cuo_wen` 是
        `_jie_shu_zhao` 看到非零退出码时才写的）。生产路径上 `jie_shou` 只由
        `fan_yi` 调，绕开它就是在验一条不存在的路径。
        """
        a = _yi_jian()
        a.fan_yi(json.dumps({"type": "result", "exit_code": 2,
                             "text": "认证失败：token 无效", "duration_ms": 500}))
        jie = [p for k, p in a.shuju if k == "result"]
        self.assertEqual(len(jie), 1, f"回合没收口 ⇒ fasong() 挂到看门狗：{a.shuju}")
        self.assertIs(jie[0]["isError"], True)
        self.assertEqual(jie[0]["subtype"], "error")
        self.assertEqual(jie[0]["errorMessage"], "认证失败：token 无效")
        self.assertEqual(jie[0]["resultText"], "认证失败：token 无效",
                         "失败回合的正文不能丢——决策回路靠它告诉用户出了什么事")
        self.assertEqual(jie[0]["durationMs"], 500)

    def test_shi_bai_er_que_wei_shi_bai_de_pan_ju_liang_lu_dou_neng_chu_lai(self):
        """非零退出码但 `text` 为空 ⇒ `errorMessage` 回落成 `hermes 退出码 2`。

        分岔：把空 `text` 当成「没有错误信息」⇒ `errorMessage` 缺失，
        界面只显示一个红色空卡，用户不知道发生了什么；而回合正文还会
        回落到 text 累加器上（`正在重试…`），错误与正文被拆成两处。
        """
        a = _yi_jian()
        a.fan_yi(json.dumps({"type": "text", "text": "正在重试…"}))
        a.fan_yi(json.dumps({"type": "result", "exit_code": 2, "text": "",
                             "duration_ms": 700}))
        jie = [p for k, p in a.shuju if k == "result"]
        self.assertEqual(len(jie), 1, a.shuju)
        self.assertIs(jie[0]["isError"], True)
        self.assertEqual(jie[0]["errorMessage"], "hermes 退出码 2")
        self.assertEqual(jie[0]["resultText"], "正在重试…",
                         "空 result.text 时正文要回落到累加器，不能是空串")

    def test_hui_he_bian_jie_hou_lei_jia_qi_bi_xu_qing_kong(self):
        """回合边界之后累加器必须清空，否则下一回合结果是两条回复拼一起。

        判据落在「第二次 `jie_shou` 的 resultText 上」，不是「有没有被清过」。
        """
        a = _yi_jian()
        a.fan_yi(json.dumps({"type": "text", "text": "第一回合"}))
        a.jie_shou({"type": "result", "exit_code": 0, "text": "第一回合"})
        a.fan_yi(json.dumps({"type": "text", "text": "第二回合"}))
        jie = a.jie_shou({"type": "result", "exit_code": 0, "text": "第二回合"})
        self.assertEqual(jie["resultText"], "第二回合")

    def test_hao_hang_zhi_fa_yi_tiao_error_bu_neng_rang_hui_he_bian_jie(self):
        """坏行不许吞掉整轮：后面的 `result` 照常收口，正文也对。

        判据落在「回合有没有收口 + resultText 对不对」，不是「有没有发 error 帧」
        ——后者两种实现都成立（假绿）。
        """
        a = _yi_jian()
        a.fan_yi("Traceback (most recent call last):")
        a.fan_yi(json.dumps({"type": "result", "exit_code": 0,
                             "text": "回合仍然完成"}))
        jie = [p for k, p in a.shuju if k == "result"]
        self.assertEqual(len(jie), 1, f"回合没收口 ⇒ fasong() 挂到看门狗：{a.shuju}")
        self.assertEqual(jie[0]["resultText"], "回合仍然完成")
        cuo = [p for k, p in a.shuju if k == "error"]
        self.assertEqual(len(cuo), 1, a.shuju)
        self.assertEqual(cuo[0]["code"], "hermes_bad_line")
        self.assertIs(cuo[0]["recoverable"], True)

    # ---------- 约束 2：stderr 纯文本 ----------

    def test_stderr_de_pure_wen_ben_bun_neng_be_dang_cheng_session_zhen(self):
        """**stderr 上那行 `session_id: xxx` 绝不许变成 session 帧。**

        生产路径上它由基类 `_shou_cuo_wei` 攒进 `cuo_wei`、**根本不进 `fan_yi`**；
        这条守的是「万一进来了也不能被当成 wire」：它不是 JSON，只能变成一条
        bad_line error。

        分岔：加一条「按 `key: value` 回退解析去捞 session_id」的兜底 ⇒ 从
        stderr 里凭空造出会话 id，`run.hui_fu` 拿它去 `--resume`，续接到一个
        不存在的会话。判据落在**帧的 kind 上**（error vs session），不是
        「有没有多发一帧」。
        """
        a = _yi_jian()
        a.fan_yi("session_id: 20261005_123701_ebc414")
        a.fan_yi("shell.py:13: SyntaxWarning: invalid escape sequence '\\d'")
        self.assertEqual([k for k, _ in a.shuju], ["error", "error"], a.shuju)
        for _, can in a.shuju:
            self.assertNotIn("claudeSessionId", can)
            self.assertNotEqual(can.get("sessionId"), "20261005_123701_ebc414")

    def test_hui_he_shou_cuo_wei_de_stderr_bu_hui_chan_rao_da_kuan_zheng_wen(self):
        """真机上 stderr 有内容时，正常回合照样是 `completed`。

        分岔：把 `cuo_wei` 非空当成回合失败 ⇒ **每一回合都是 error**——因为
        hermes 每回合都会在 stderr 上打 `session_id:` 那行。
        """
        a = _yi_jian()
        a.cuo_wei = "session_id: 20261005_123701_ebc414\n"
        jie = a.jie_shou({"type": "result", "exit_code": 0, "text": "正常答复"})
        self.assertIs(jie["isError"], False, "stderr 上有内容就判失败")
        self.assertEqual(jie["subtype"], "completed")

    def test_session_zhen_de_ke_yi_du_da_bu_yong_zai_zhuan_fa(self):
        """session 帧只发一次：**判据落在「第二回合的 `--resume` 用的还是同一个 id」上**。

        分岔：每个回合的 `init` 都发一条 session 帧（去掉 `_fa_le_session` 闸）。
        那样本回看每条 case 都还是绿的（`init` 帧的期望就是一条 session），
        只有**跨回合**才分岔 ⇒ 判据必须落在第二次的落盘值上，
        不是「有没有发过 session 帧」。
        """
        a = _yi_jian()
        a.fan_yi(json.dumps({"type": "system", "subtype": "init",
                             "session_id": "shao_1"}))
        a.fan_yi(json.dumps({"type": "result", "exit_code": 0, "text": "一"}))
        a.shuju.clear()
        a.fan_yi(json.dumps({"type": "system", "subtype": "init",
                             "session_id": "shao_1"}))
        a.fan_yi(json.dumps({"type": "result", "exit_code": 0, "text": "二"}))
        session = [p for k, p in a.shuju if k == "session"]
        self.assertEqual(session, [],
                         "**同一个 id 不该反复上报**——落盘会话表被反复回写")
        # 闸不能把 id 也一起丢掉：续接参数（`--resume`）靠的就是它
        self.assertEqual(a.kehu_hui, "shao_1", "session 帧不重复发之后 id 被清掉了")

    def test_kong_session_id_buneng_shang_bao(self):
        """`init` 帧没有 `session_id` ⇒ 一条事件都不许发。

        分岔：发一条 `{"sessionId":"","claudeSessionId":""}` ⇒ 落盘出一个空会话
        id，`run.hui_fu` 恢复时 `--resume ""` 续接到错误的会话，正文串过去。
        判据落在**帧数**上（长度不等）。
        """
        a = _yi_jian()
        a.fan_yi(json.dumps({"type": "system", "subtype": "init"}))
        a.fan_yi(json.dumps({"type": "system", "subtype": "heartbeat"}))
        self.assertEqual(a.shuju, [], f"空 session_id 也上报了：{a.shuju}")


class Ce_Shi_He_Rong_Yue_Tests(unittest.TestCase):
    """L-A 结构：契约字段。"""

    def test_ming_ling_yao_dai_stream_json(self):
        """`--format stream-json` 必须恒带：少了它 stdout 是纯文本，一行 JSON 都收不到。"""
        a = _yi_jian()
        a.kehu_hui = ""
        self.assertEqual(a._zi_ling({}),
                         ["chat", "--format", "stream-json", "-q", ""])
        a._wen = "跑一下 echo"
        self.assertEqual(a._zi_ling({})[-2:], ["-q", "跑一下 echo"])

    def test_zi_ling_ke_xuan_dai_session_id(self):
        """`resume` → `--resume <id>`。

        分岔：不传 `--resume`。hermes 的会话续接全靠它，而 `run.hui_fu`
        恢复时靠的正是 `kehu_hui`（从 `claudeSessionId` 落盘来的那个）。
        """
        a = _yi_jian()
        a.kehu_hui = ""
        self.assertNotIn("--resume", a._zi_ling({}), "没会话时不该有多余参数")
        a.kehu_hui = "20261005_123701_ebc414"
        can = a._zi_ling({})
        self.assertEqual(can[can.index("--resume") + 1], "20261005_123701_ebc414")

    def test_ben_hui_wu_lu_quan_hui_hui(self):
        """**没有权限回路也没有提问回路**（约束：非交互模式下 CLI 自己管权限）。

        分岔：任一个报 True，`/agents` 就给这个 harness 发审批卡，
        `_cheng_bu` 那条路也退化成纯文本——而 hermes 那边根本没人问，
        用户的「批准」点了没反应，回合照常跑完（越权执行）。
        """
        self.assertFalse(HermesAdapter.fangquan())
        self.assertFalse(HermesAdapter.wenti2())

    def test_bu_neng_qie_huan_mo_shi_jiu_bie_ding_yi_gai_moshi(self):
        """一次性进程的档位在 spawn 那一刻写进 argv ⇒ 绝不能定义 `gai_moshi`。

        `http._gai_moshi` 用 `hasattr` 判「这个 harness 能不能切」，定义了它
        就恒为 True，于是界面发出切换请求、`_gai_moshi` 还把新模式**落盘**——
        而 hermes 的进程已经在按旧 argv 跑了，切换只会让用户下次看到
        「dontAsk 模式」的标签，实际那个进程根本没变。
        「方法不存在」就是可用信号。
        """
        self.assertFalse(hasattr(HermesAdapter(), "gai_moshi"))

    def test_moshi_zi_sheng_ming_manual_he_dont_ask(self):
        """`MOSHI_ZI = {"manual", "dontAsk"}`——2026-10-06 真机核实后的声明。

        hermes 非交互模式唯一能兑现的放开档是 `--yolo`（映射 dontAsk）；
        `--safe-mode` 是排障开关，与权限五档无关，不映射。声明非空子集后，
        闸门 1 的 `(zi or MOSHI) & MOSHI` 不再退回全局白名单：
        `acceptEdits/plan/auto` 在建会话时就 400，前端下拉框也只渲染这两档——
        旧状态（空集）会把五档全渲染出来，用户选 plan → 交集为 0 → 400。
        """
        from lifeos.bridge.models import MOSHI
        zi = HermesAdapter.MOSHI_ZI
        self.assertEqual(zi, frozenset({"manual", "dontAsk"}))
        self.assertTrue(zi <= MOSHI, "声明的档必须是全局白名单的子集")
        self.assertIn("manual", zi, "manual 是每家都能兑现的底线档")
        # 抄 `http.py` 闸门 1 的原表达式：非空声明下，交集必须等于声明本身
        # ——上报什么就放行什么，一份能力不许两处漂移。
        self.assertEqual((zi or MOSHI) & MOSHI, zi)

    def test_dont_ask_gua_yolo_manual_bu_gua(self):
        """argv 落点：`dontAsk` → `--yolo`；manual（默认）→ 不加任何旗标。

        分岔：忘了接 `--yolo` ⇒ dontAsk 会话实际每步都被 CLI 自己拦
        （零审批承诺落空）；manual 也挂 ⇒ 连底线档都跑不干净。
        """
        a = _yi_jian()
        self.assertNotIn("--yolo", a._zi_ling({}), "manual 不许带放开旗标")
        a.moshi = "dontAsk"
        can = a._zi_ling({})
        self.assertIn("--yolo", can)
        self.assertLess(can.index("--yolo"), can.index("-q"),
                        "--yolo 必须落在 -q 指令之前（CLI 按位置解析指令）")

    def test_dui_hui_id_shi_claude_session_id(self):
        self.assertEqual(HermesAdapter.dui_hui_id, "claudeSessionId")

    def test_yi_ci_xing_cai_shi_mo_ke_yi_zhong_yong(self):
        """一次性进程：`kaishi()` 不 spawn，进程留到 `fasong()`。

        设错成常驻会让 `kaishi` 就 spawn 一个没人喂的 hermes，
        而 `/agents` 探测与真机行为对不上。
        """
        self.assertTrue(HermesAdapter.yi_ci_xing)

    def test_ban_xiang_wen_tou_shi_yao_yong_version(self):
        """`CE_WU_TOU` 必须覆写成 `--version`（约束：基类默认 `--help`）。

        分岔：用基类的 `--help`。抓版本号靠 `(\\d+\\.\\d+\\.\\d+)` 正则，
        而 `hermes --help` 的正文里没有版本号 ⇒ 正则不匹配 ⇒
        `tanjian()` 把**可执行文件路径**当版本号报给 `/agents`，
        前端 Agent 列表上显示一串 `miniconda3\\Scripts\\hermes.exe`。
        """
        self.assertEqual(HermesAdapter.CE_WU_TOU, ["--version"])

    def test_tan_jian_zhua_de_ban_ban_shi_ben_ji_cheng_lu(self):
        """`tanjian()` 真跑一次本机 hermes，验证抓到的是版本号而不是路径。

        这是**结构契约里唯一一条要真子进程的**：判据落在「正则有没有匹配到
        `0.21.5`」上——用 `--help` 的实现会返回 `C:\\…\\hermes.exe`，
        两者不等 ⇒ 分岔。未装则跳过（本机装了）。
        """
        import asyncio
        import re
        import shutil
        import subprocess

        lu = shutil.which("hermes") or shutil.which("hermes.exe")
        if not lu:
            self.skipTest("本机没装 hermes")
        bao = asyncio.run(HermesAdapter().tanjian())
        self.assertIs(bao["available"], True, bao)
        self.assertIsNotNone(re.fullmatch(r"\d+\.\d+\.\d+", str(bao["version"])),
                             f"版本号抓成了可执行文件路径：{bao}")
        # 同一台机器上 `tanjian` 跑的那条命令，输出里确实有那个版本号
        chu = subprocess.run([lu, "--version"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=15)
        self.assertIsNotNone(re.search(r"(\d+\.\d+\.\d+)", (chu.stdout or "") + (chu.stderr or "")),
                             "本机 hermes --version 的输出里没有版本号，样本口径要更新")


if __name__ == "__main__":
    unittest.main()
