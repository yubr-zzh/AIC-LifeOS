"""pi 适配器的 L-B（golden）测试。

**这份测试在验什么**：翻译层把 wire 格式转成统一事件时，字段名、分支、kind
映射、回合边界判对没有抄错。

**它在不验什么**：golden 的正确性取决于样本抄得对不对，而样本是抄的。所以它
只是回归护栏，**不是「已验证」**。真验收是 L-C
（`tests/test_pi_lc_ji_cheng.py`，真 spawn `pi --mode rpc` 打真回合）。

## 判据落在哪里

golden 的机制是「喂一行真机 wire，断言发出的统一事件序列」，所以判据天然落在
**序列**上——包括「哪些事件**不该**发」。本文件的每条样本都刻意让两种实现
读出不同结果：

| 判据 | 两种实现会分岔在 |
|---|---|
| `agent_settled` 才是回合边界（`agent_end` / `turn_end` 都不是） | `fasong()` 会不会提前返回（判错 ⇒ 结果是空的 / 重试场景挂死） |
| `text_delta` 与 `thinking_delta` 分成两个 kind，且 **delta 字符串逐字相同** | 只看 delta 不看 type ⇒ 思考被当成回复正文显示 |
| `text_end` 的 content 与前面的 delta 相同，不许再发 `text` | 界面上会不会出现两条一样的消息 |
| `toolcall_end` 发 tool_use、`tool_execution_start` 不发（同一个 toolUseId） | 同一个工具调用会不会出现两张卡 |
| `message_end{assistant}` 的 content 与 delta 累加器两条路都能出正文 | 只读 delta ⇒ provider 不吐增量时正文为空 |
| 失败回合要 error **和** result 两条 | 只发一条 ⇒ 决策回路收不到结果 / 状态机不知道失败 |
| `message_end{user}` / `{system}` 不回显 | 界面会不会把用户输入与系统提示再显示一遍 |
| fire-and-forget 的五种 extension_ui 一条响应都不许写 | 回写了是无操作，但行为与文档不一致 |

**不 sleep 固定时长**：本项目实测 `sleep(2.0)` 在 Windows 上必然 flake。
这里全是纯函数调用，没有等待。
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

from lifeos.bridge.adapters.pi import PiAdapter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

JIN = Path(__file__).resolve().parent / "golden"


def _du(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _yi_jian() -> PiAdapter:
    """造一个不 spawn 任何东西的适配器，把事件收进列表。"""
    a = PiAdapter()
    a.shuju = []          # type: ignore[attr-defined]
    a.hui = lambda lei, can: a.shuju.append((lei, can))   # type: ignore[attr-defined]
    return a


class _Dai:
    """挂起通道回来的东西。

    **必须复刻真实形状**：`arbiter.shou` 回的是 `PermissionResultAllow` /
    `PermissionResultDeny` 这些 **dataclass 实例**，翻译函数读的是 `.behavior`
    与 `.message` 属性。golden 里带 dict 的那几条走 `_shi_allow` 的 dict 分支，
    这里原样建成 dict，**不能用 dataclass 代替**——那会让它们走另一条分支，
    而症状一模一样（答案解析不出来），成因完全不同。
    """

    def __init__(self, **wu) -> None:
        for k, v in wu.items():
            setattr(self, k, v)


def _dai(an: dict) -> object:
    """按 golden 里 `yong` 的形状造挂起通道的返回值。

    ⚠ **两种形状都是 JSON 对象，要靠键名区分，不能靠 `isinstance(dict)`**：
    `{"behavior": "allow"}` 是 dataclass 形状（`PermissionResultAllow`），
    `{"allowed": true}` 是 dict 形状。分岔点正是 `_shi_allow` 读哪个键，
    造错了就等于没验那条分支。

    `hui_yi` 单独一栏放自然语言答案（`arbiter._du_wen` 拼出来的那个形状），
    翻译函数读的是 `.message`，所以这里一并挂上去。
    """
    yong = an.get("yong")
    hui_yi = an.get("hui_yi")
    if yong is None:
        return None
    if "allowed" in yong:                     # dict 形状：`_shi_allow` 走 dict 分支
        return {"message": hui_yi, **yong}
    return _Dai(message=hui_yi, **yong)        # dataclass 形状


class Jin_Liu_Yu_Yan_Tests(unittest.TestCase):
    """golden：会话事件 → 统一事件。"""

    def setUp(self):
        self.bao = _du(JIN / "pi.json")

    def _dui_bi(self, an: dict, qi_wang: list[dict], ming: str) -> None:
        """喂一条 wire，断言发的事件序列与 golden 一致。

        **每条 case 用全新适配器。** `_zhuan_wen` / `_cuo_wen` 是跨事件的累积
        状态，共用一个适配器会让上一条 case 的正文漏进下一条的结果里——
        那种失败与真 bug 长得一模一样，但成因是测试自己。
        """
        a = _yi_jian()
        for zhan in an.get("_zhan_dian", []):
            a.fan_yi(json.dumps(zhan, ensure_ascii=False))
        a.shuju.clear()
        a.fan_yi(json.dumps(an["wire"], ensure_ascii=False))
        self.assertEqual(len(a.shuju), len(qi_wang),
                         f"{ming}\n  实际：{[k for k, _ in a.shuju]}\n"
                         f"  期望：{[x['kind'] for x in qi_wang]}\n  载荷：{a.shuju}")
        for (lei, can), qiu in zip(a.shuju, qi_wang):
            self.assertEqual(lei, qiu["kind"], ming)
            for k, v in qiu.get("match", {}).items():
                self.assertEqual(can.get(k), v, f"{ming}：字段 {k} 不符")
        for xiu in qi_wang:
            if xiu.get("jie_shou"):
                self.assertIsNotNone(a.jie_shou(an["wire"]),
                                     f"{ming}：`jie_shou` 没认出回合边界")
        # 有 `_jie_shou_zai_hou_mian_ji` 的 case：额外喂一帧，断言回合结果本身。
        if "_jie_shou" in an:
            a.shuju.clear()
            a.fan_yi(json.dumps(an["_jie_shou_zai_hou_mian_ji"], ensure_ascii=False))
            jie = [p for k, p in a.shuju if k == "result"]
            self.assertEqual(len(jie), 1, f"{ming}：回合边界没发 result：{a.shuju}")
            for k, v in an["_jie_shou"].items():
                self.assertEqual(jie[0].get(k), v, f"{ming}：回合结果字段 {k} 不符")
            # 回合边界必须**清空累加器**：再喂一帧 `agent_settled`，第二回合的
            # `resultText` 必须是空的。判据落在「第二次的结果」上而不是
            # 「有没有被清过」——后者两种实现都成立（假绿）。
            # ⚠ 不能断言「第二次一条事件都不发」：回合边界**就该**再发一条
            # result（`_jie_shu_kao_ben` 只在 Future 层幂等，不在事件层），
            # 那是 `paichu` 判定新指令的依据。
            a.shuju.clear()
            a.fan_yi(json.dumps(an["_jie_shou_zai_hou_mian_ji"], ensure_ascii=False))
            er = [p for k, p in a.shuju if k == "result"]
            self.assertEqual(len(er), 1, f"{ming}：第二次 agent_settled 没发 result")
            self.assertEqual(er[0].get("resultText"), "",
                             f"{ming}：上一回合的正文漏进第二回合")

    def test_qu_an_wu_wei_fa_chu_she_yao_de_hang(self):
        """**逐条走完整个 golden。**

        这里有个容易假绿的地方：`assertEqual(len(...), len(qi_wang))`
        在两边都是 0 时也成立，所以「不该发事件」的那些 case 恰恰最承重——
        它们靠**长度不等**分岔。
        """
        zong = 0
        for an in self.bao["cases"]:
            with self.subTest(an=an["_ming"]):
                self._dui_bi(an, an["expect"], an["_ming"])
                if an["expect"]:
                    zong += 1
        self.assertGreaterEqual(zong, 8, "golden 用例太少，跑不到分支")

    def test_hui_he_bian_jie_que_cai_de_yao_zhi_you_agent_settled(self):
        """**`agent_settled` 是唯一的回合边界。**

        分岔一：把判据放宽成「`agent_end`」，那么一次 429 自动重试
        （`agent_end{willRetry:true}` 之后会重新 `agent_start`）就会把回合收走，
        结果是空的。
        分岔二：放宽成「任何 `*_end`」，那么 `turn_end`（一个 run 里能有多次）
        会更早收走。
        """
        a = _yi_jian()
        for wei in ("agent_start", "turn_start", "turn_end", "message_start",
                    "message_end", "agent_end", "auto_retry_start",
                    "compaction_start", "compaction_end"):
            self.assertIsNone(a.jie_shou({"type": wei}), f"{wei} 被误判成回合边界")
        # willRetry=true 的 agent_end 尤其不能当边界
        self.assertIsNone(a.jie_shou({"type": "agent_end", "willRetry": True,
                                      "messages": []}))
        self.assertIsNotNone(a.jie_shou({"type": "agent_settled"}))

    def test_ben_hui_zheng_wen_liang_lu_dou_neng_chu_lai(self):
        """**正文两条路都能出：`text_delta` 累加 与 `message_end.content`。**

        分岔：只读 delta 累加器。真机上 provider 不吐增量时（`message_end`
        直接带着全文、`message_update` 里一条 text_delta 都没有），
        `resultText` 会是空的 ⇒ 3.8 决策回路把空串送回 LifeOS 对话上下文，
        用户看到「Agent 跑完了，但什么都没说」。
        """
        a = _yi_jian()
        for zhai in ("你", "好", "！"):        # 路径一：delta 累加
            a.fan_yi(json.dumps({"type": "message_update",
                                 "assistantMessageEvent": {"type": "text_delta",
                                                            "contentIndex": 0,
                                                            "delta": zhai}}))
        jie = a.jie_shou({"type": "agent_settled"})
        self.assertEqual(jie["resultText"], "你好！")
        self.assertFalse(jie["isError"])

        b = _yi_jian()                        # 路径二：只有 message_end
        b.fan_yi(json.dumps({"type": "message_end",
                             "message": {"role": "assistant",
                                         "content": [{"type": "text", "text": "只有终态"}],
                                         "stopReason": "stop"}}))
        jie = b.jie_shou({"type": "agent_settled"})
        self.assertEqual(jie["resultText"], "只有终态", "只读 delta 累加器会漏掉这一路")

    def test_hui_he_bian_jie_hou_zheng_wen_Bei_qing_kong(self):
        """回合边界之后累加器必须清空，否则下一回合的结果是两条回复拼一起。

        判据落在「第二次 `jie_shou` 的 resultText 上」，不是「有没有被清过」。
        """
        a = _yi_jian()
        a.fan_yi(json.dumps({"type": "message_update",
                             "assistantMessageEvent": {"type": "text_delta",
                                                        "contentIndex": 0,
                                                        "delta": "第一回合"}}))
        a.jie_shou({"type": "agent_settled"})
        a.fan_yi(json.dumps({"type": "message_update",
                             "assistantMessageEvent": {"type": "text_delta",
                                                        "contentIndex": 0,
                                                        "delta": "第二回合"}}))
        jie = a.jie_shou({"type": "agent_settled"})
        self.assertEqual(jie["resultText"], "第二回合")

    def test_si_wei_de_delta_buneng_ji_li_dao_zheng_wen_li(self):
        """**思考的 delta 绝不能混进 `resultText`。**

        分岔：`_zhuan_wen.append` 在两个分支里都执行（只把 kind 写对）。
        单测里 `chunk` 事件看起来完全正常，只有 `resultText` 会被污染——
        而决策回路就是靠这个字段把结果送回 LifeOS 对话上下文。
        """
        a = _yi_jian()
        a.fan_yi(json.dumps({"type": "message_update",
                             "assistantMessageEvent": {"type": "thinking_delta",
                                                        "contentIndex": 0,
                                                        "delta": "想一下"}}))
        a.fan_yi(json.dumps({"type": "message_update",
                             "assistantMessageEvent": {"type": "text_delta",
                                                        "contentIndex": 0,
                                                        "delta": "答案"}}))
        self.assertEqual(a.jie_shou({"type": "agent_settled"})["resultText"], "答案")

    def test_shen_pi_guo_cheng_zhong_fasong_reng_zai_deng(self):
        """审批挂起时 `fasong()` 必须仍在等回合边界（挂起 ≠ 回合结束）。

        分岔：把挂起当成回合结束（调 `_jie_shu_kao_ben`），那么 `fasong()`
        在用户还没点「允许」时就返回了 —— `paichu` 于是判这条指令完成，
        用户看到的审批卡与已完成的指令对不上。而单测里「挂起任务跑完了」
        照样成立，判据必须落在**回合 Future 是否被唤醒**这个量上。
        """
        async def zhen():
            a = _yi_jian()
            kai = []

            async def cheng(lei: str, can: dict):
                kai.append((lei, can))
                return _Dai(behavior="allow", message="用户对问题的回答：\n- Allow")
            a.cheng = cheng  # type: ignore[attr-defined]
            a.loop = asyncio.get_running_loop()
            fa = a.loop.create_future()
            a._xu_hao = 1
            a._jie_shu[1] = fa
            a.fan_yi(json.dumps({"type": "extension_ui_request", "id": "e1",
                                 "method": "confirm", "title": "t",
                                 "message": "m"}))
            await asyncio.sleep(0)
            self.assertEqual(len(kai), 1, "挂起通道没被调")
            self.assertEqual(kai[0][0], "permission")
            self.assertEqual(kai[0][1]["toolName"], "extension_confirm")
            await asyncio.sleep(0)
            self.assertFalse(fa.done(),
                             "**审批还没收口，回合就被判结束了** —— 用户看到的"
                             "审批卡与已完成的指令对不上")
            a.fan_yi(json.dumps({"type": "agent_settled"}))
            self.assertTrue(fa.done(), "回合边界没有唤醒 fasong")

        asyncio.run(zhen())

    def test_guan_bi_shou_tiao_hua_zhe_xiang(self):
        """关连接必须收掉挂起任务，否则协程还握着已拆掉的子进程 stdin。"""
        async def zhen():
            a = _yi_jian()
            a.loop = asyncio.get_running_loop()
            done: list[bool] = []

            async def cheng(lei: str, can: dict):
                try:
                    await asyncio.sleep(3600)
                except asyncio.CancelledError:
                    done.append(True)
                    raise
            a.cheng = cheng  # type: ignore[attr-defined]
            a.fan_yi(json.dumps({"type": "extension_ui_request", "id": "e1",
                                 "method": "confirm", "title": "t", "message": "m"}))
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            self.assertEqual(len(a._dai_dai), 1)
            await a.guan_bi()
            # **必须让出一次控制权再看**：cancel() 只是打了标记，协程要等下一个
            # 挂起点才会真的抛 CancelledError。不让这一步，断言就变成在量
            # 「调度器还没跑到」，测的是一个时序巧合而不是「协程被收掉了」。
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            self.assertEqual(a._dai_dai, set(), "挂起任务没收掉")
            self.assertEqual(done, [True], "挂起协程没被取消")

        asyncio.run(zhen())

    def test_wu_loop_shi_jiang_dai_an_jue_ju_er_bu_bao_po(self):
        """没有 loop 时挂起请求必须**回取消**，且不抛异常。

        分岔：抛异常。`fan_yi` 是同步函数，被 `_du_zhan` 的 `except Exception`
        吞成一条 `translate_failed` 帧，而那个对话框请求**一个响应都没回**——
        pi 那边 Promise 一直挂着，扩展就一直卡住，回合挂到超时。
        """
        a = _yi_jian()
        a.hui_ding = []  # type: ignore[attr-defined]
        a.cheng = None  # type: ignore[attr-defined]

        class Xin:
            def write(_self, shu: bytes) -> None:
                a.hui_ding.append(shu.decode("utf-8"))
        a.jin = type("Jin", (), {"stdin": Xin()})()
        self.assertIsNone(a.loop)
        a.fan_yi(json.dumps({"type": "extension_ui_request", "id": "e1",
                             "method": "confirm", "title": "t", "message": "m"}))
        self.assertEqual(len(a.hui_ding), 1, "没回响应，pi 那边会一直等")
        zhao = json.loads(a.hui_ding[0])
        self.assertEqual(zhao["type"], "extension_ui_response")
        self.assertEqual(zhao["id"], "e1")
        self.assertEqual(zhao.get("cancelled"), True)


class Po_Ru_Yu_Hui_Ying_Tests(unittest.TestCase):
    """golden：extension_ui_request → 挂起通道 → 回同一个 id。"""

    def setUp(self):
        self.bao = _du(JIN / "pi_shen_pi.json")

    def _pai(self, an: dict, *, yong="allow", hui_yi=None):
        """造一个适配器并喂一条 extension_ui_request（**在一个跑着的 loop 里**）。

        挂起通道立刻返回一个定好的对象，写盘被收进 `hui_ding`。
        **不用真子进程**：这里验的是「收到什么、回什么」，stdio 那层由
        `chuan_shu` 的传输层测试与 L-C 真机脚本负责。

        ⚠ **必须在 loop 里调 `fan_yi`**：审批挂起要 `loop.create_task`，
        没有 loop 时适配器走的是「安静退化成取消」那条路（见 `_qi_ren_wu`）。
        那条降级本身是对的（生产路径上 loop 一定在），但在这里会掩盖真行为。
        """
        a = _yi_jian()
        a.hui_ding = []  # type: ignore[attr-defined]

        async def cheng(lei: str, can: dict):
            return _Dai(behavior=yong, message=hui_yi)
        a.cheng = cheng  # type: ignore[attr-defined]

        class Xin:
            def write(_self, shu: bytes) -> None:
                a.hui_ding.append(shu.decode("utf-8"))
        a.jin = type("Jin", (), {"stdin": Xin()})()

        async def zou() -> None:
            a.loop = asyncio.get_running_loop()
            a.fan_yi(json.dumps(an["wire"], ensure_ascii=False))
            for t in list(a._dai_dai):
                await asyncio.wait_for(t, 10.0)
        asyncio.run(zou())
        return a

    def _deng(self, a: PiAdapter) -> list[dict]:
        """适配器已经跑过挂起任务了，这里只是把写盘内容解回 JSON。"""
        return [json.loads(x) for x in a.hui_ding]

    def test_qu_an_shen_pi_wen_ti_dou_you_hui_ying(self):
        for an in self.bao["cases"]:
            if an.get("_zuo_yong") is None:
                continue
            with self.subTest(an=an["_ming"]):
                a = self._pai(an, yong="allow", hui_yi=an["_dao_yan"])
                zhao = self._deng(a)
                self.assertEqual(len(zhao), 1, f"{an['_ming']}：{zhao}")
                self.assertEqual(zhao[0]["type"], "extension_ui_response")
                self.assertEqual(zhao[0]["id"], an["wire"]["id"],
                                 "**必须用同一个 id 回**（对话框配对靠它）")
                for k, v in an["hui_ying"].items():
                    self.assertEqual(zhao[0].get(k), v, f"{an['_ming']}：{zhao[0]}")
                self.assertEqual(set(zhao[0]) - {"type", "id"},
                                 set(an["hui_ying"]),
                                 f"{an['_ming']}：多写了键（pi 认的是 confirmed/"
                                 "value/cancelled 三个平铺字段，套一层它就当没收到）")

    def test_jue_ding_fu_zao_shi_yan_ji_lie_biao(self):
        """allow / deny 映射到 pi 的三种回写形状。

        分岔：把 deny 也写成 `{"value": …}` 或 `{"confirmed": true}`——
        单测「响应发出去了」照样成立，用户却发现「我点了拒绝，命令还是跑了」。
        """
        for an in self.bao["cases"]:
            if an.get("hui_ying_bie") is None:
                continue
            with self.subTest(an=an["_ming"]):
                a = self._pai(an, yong="deny", hui_yi="用户拒绝了")
                zhao = self._deng(a)
                self.assertEqual(len(zhao), 1, f"{an['_ming']}：{zhao}")
                self.assertEqual(zhao[0].get("id"), an["wire"]["id"])
                if an["wire"]["method"] == "confirm":
                    self.assertEqual(zhao[0].get("confirmed"), False, an["_ming"])
                else:
                    self.assertEqual(zhao[0].get("cancelled"), True, an["_ming"])
                    self.assertNotIn("value", zhao[0],
                                     "deny 时回 value=… 等于替用户做了选择")

    def test_bu_hui_ying_de_fang_fa_yi_zi_ke_yi_zhen_de_bu_yao_hui(self):
        """**fire-and-forget 的五种 + 无 id 的请求：一条响应都不许写。**

        分岔：给 fire-and-forget 也回响应。它们在 pi 那边没有挂着的 Promise
        （`dist/modes/rpc/rpc-mode.js` 里这五个方法只 `output(...)`），
        回过去是纯噪声——而判据要落在「写了几条」这个量上，不是「回的内容对不对」。
        """
        for an in self.bao["cases"]:
            if an.get("_zuo_yong") is not None:
                continue
            with self.subTest(an=an["_ming"]):
                a = self._pai(an, yong="allow", hui_yi="随便")
                self.assertEqual(self._deng(a), [], f"{an['_ming']}：不该有响应")

    def test_xuan_xiang_ce_shi(self):
        for an in self.bao["xuan_xiang_ce_shi"]:
            with self.subTest(an=an["_ming"]):
                self.assertEqual(PiAdapter._xuan_xiang(an["options"]),
                                 an["jie_xi"], an["_ming"])

    def test_xuan_jie_xi_ce_shi(self):
        for an in self.bao["xuan_jie_xi_ce_shi"]:
            with self.subTest(an=an["_ming"]):
                self.assertEqual(PiAdapter._xuan_jie_xi(_dai(an), an["xuan_xiang"]),
                                 an["jie_xi"], an["_ming"])

    def test_wen_ben_jie_xi_ce_shi(self):
        for an in self.bao["wen_ben_jie_xi_ce_shi"]:
            with self.subTest(an=an["_ming"]):
                self.assertEqual(PiAdapter._wen_ben_jie_xi(_dai(an)),
                                 an["jie_xi"], an["_ming"])

    def test_jue_ding_ce_shi(self):
        for an in self.bao["jue_ding_ce_shi"]:
            with self.subTest(an=an["_ming"]):
                self.assertEqual(PiAdapter()._jue_ding(_dai(an)), an["jie_xi"], an["_ming"])


class Ce_Shi_He_Rong_Yue_Tests(unittest.TestCase):
    """L-A 结构：契约字段。"""

    def test_qie_ting_de_xian_dai_bi_xie_fa_yao_xie_ming_quan(self):
        """`--mode rpc` 必须显式写，且 `ZHI_LING[0]` **只能是裸名 `pi`**。

        分岔：写 `["pi.cmd", …]`。那是 Windows 上的一处硬编码——macOS / Linux
        上 pi 是无后缀的 sh shim，`pi.cmd` 根本不存在，适配器直接不可用。
        ⚠ **`["pi", …]` 本身不等于错**：真 spawn 时 `create_subprocess_exec`
        不做 PATHEXT 展开，裸名必 `FileNotFoundError`，所以
        `_qi_chi_cheng` 必须在运行时把第 0 位换成解析后的真名
        （见下面 `test_cha_isheng_shi_cheng` 造出分岔的那条）。
        """
        self.assertEqual(PiAdapter.ZHI_LING, ["pi", "--mode", "rpc"])

    def test_cha_isheng_shi_cheng_bu_ke_neng_shi_lu_ming(self):
        """**spawn 的 argv 第 0 位必须已被解析，不能是裸名 `pi`。**

        这才是承重的那一条：基类 `chuan_shu._qi_chi_cheng` 把
        `self.ZHI_LING` 原样交给 `create_subprocess_exec`，而它**不做
        PATHEXT 展开**——Windows 上 npm 装出来的 pi 在磁盘上是
        `…\\npm\\pi.CMD`（`cmd /c node …cli.js` 的包装层），裸名只活在
        npm 的 shim 解析里 ⇒ `create_subprocess_exec("pi")` 直接
        `FileNotFoundError`。症状是假绿：`tanjian()` 显式试过
        `.exe/.cmd/.bat` 后缀，`/agents` 照样报 `available=true`，
        界面表现为「显示可用，一发消息就失败」。

        判据落在「实际交给 `create_subprocess_exec` 的 argv 第 0 位」上——
        **不写死后缀**（Windows 上 `shutil.which` 可能回 `.CMD` 也可能
        `.exe`，换平台又是无后缀；把后缀写进断言就是拿环境当规范）。
        抓 spawn 出去的 argv，而不是断言某个中间变量。
        """
        if not shutil.which("pi"):
            self.skipTest("本机没装 pi")
        a = PiAdapter()
        # 截获真正 spawn 的那一步：走完覆写层，但**不真的起进程**。
        zhuo = {}

        async def _fake(*argv, **kw):
            zhuo["argv"] = list(argv)
            raise RuntimeError("截住 spawn，不真跑")

        with mock.patch("asyncio.create_subprocess_exec", _fake):
            with self.assertRaises(RuntimeError):
                asyncio.run(a._qi_chi_cheng({}))
        self.assertNotEqual(zhuo["argv"][0], "pi",
                            "spawn 用的还是裸名 `pi`，Windows 上必 FileNotFoundError")
        self.assertTrue(os.path.isfile(zhuo["argv"][0]), zhuo["argv"][0])
        self.assertEqual(zhuo["argv"][1:], ["--mode", "rpc"])
        # 覆写没把类属性 `ZHI_LING` 改脏：只赋了实例那份。
        self.assertEqual(PiAdapter.ZHI_LING, ["pi", "--mode", "rpc"])

    def test_shi_chang_zhi_cheng_hai_shi_ke_shi_zhi_cheng(self):
        """rpc 是常驻进程。设错会让 `kaishi()` 不 spawn，第一个用例直接挂。"""
        self.assertFalse(PiAdapter.yi_ci_xing)

    def test_ce_wu_tou_yao_ban_de_can_shi_ban_not_can_shi(self):
        """`CE_WU_TOU` 必须是 `["--version"]`（约束：基类默认 `--help`）。

        分岔：留基类默认的 `["--help"]`。抓版本号靠 `(\\d+\\.\\d+\\.\\d+)` 正则，
        而 `pi.cmd --help` 的正文里没有版本号 ⇒ 正则不匹配 ⇒
        `tanjian()` 把**可执行文件路径**当版本号返回给 `/agents`
        （实测抓到 `C:\\Users\\Liuxj\\AppData\\Roaming\\npm\\pi.cmd`）。
        """
        self.assertEqual(PiAdapter.CE_WU_TOU, ["--version"])

    def test_tan_jian_zhua_de_lai_de_shi_ban_hao_ma_not_lu_jing(self):
        """`tanjian()` 真跑一次本机 pi，验证抓到的是版本号而不是路径。

        判据落在「`version` 读出来是不是 `\\d+\\.\\d+\\.\\d+`」上——
        用 `--help` 的实现返回的是 `…\\npm\\pi.cmd`（带反斜杠），
        两者不等 ⇒ 分岔。这是结构断言够不着的那一半：属性对了不代表
        正则在该 CLI 的输出上真匹配得到。
        """
        import asyncio
        import re
        import shutil

        if not (shutil.which("pi.cmd") or shutil.which("pi.cmd".upper())):
            self.skipTest("本机没装 pi")
        bao = asyncio.run(PiAdapter().tanjian())
        self.assertIs(bao["available"], True, bao)
        self.assertIsNotNone(re.fullmatch(r"\d+\.\d+\.\d+", str(bao["version"])),
                             f"版本号抓成了可执行文件路径：{bao}")

    def test_wei_ren_zhi_de_mo_shi_bei_400(self):
        """pi 没有 claude-code 那种五档模式，只声明能兑现的「手动」一档。

        ⚠ **不能写空集**：空集在 `http._dui_lie` 里被当成「未声明」，
        于是上报全局白名单，前端渲染出 auto / dontAsk 等选下去必然 400 的
        选项（两种死法都要避开）。
        """
        from lifeos.bridge.models import MOSHI
        self.assertEqual(PiAdapter.MOSHI_ZI, frozenset({"manual"}))
        self.assertTrue(PiAdapter.MOSHI_ZI <= MOSHI)

    def test_bu_neng_qie_huan_mo_shi_jiu_bie_ding_yi_gai_moshi(self):
        """pi 切不出权限模式 ⇒ **不许定义 `gai_moshi`**。

        `http._gai_moshi` 用 `hasattr` 判「这个 harness 能不能切」，
        定义了它就恒为 True，于是界面发出切换请求、`_gai_moshi` 还把新模式
        **落盘**——用户下次看到「plan 模式」，实际那个 harness 从没按 plan 跑过。
        「方法不存在」就是可用信号。
        """
        self.assertFalse(hasattr(PiAdapter(), "gai_moshi"))

    def test_dui_hui_id_shi_claudeSessionId(self):
        """`dui_hui_id` 必须是运行时**真的写出去**的那个键。

        分岔：写 `sessionId`。`kaishi()` 发的 session 帧里两个键都带
        （`{"sessionId":…, "claudeSessionId":…}`），但 `http._hui_zhuan` 的
        session 分支**只读 `claudeSessionId`**，落进
        `AgentSession.claudeSessionId`；`AgentSession.sessionId` 那个字段
        被 LifeOS 自己的会话 id 占着。⇒ 报 `sessionId` 就是宣称「会话 id
        存在一个没人写、也没人读的字段里」，读代码的人会以为 resume 走
        `sessionId`，而 `http.xin_jian` 读的是 `hui.claudeSessionId`。
        （这正是 discipline 5.9 那种形态：断言的期望值恰好等于缺陷实现的输出。）
        """
        self.assertEqual(PiAdapter.dui_hui_id, "claudeSessionId")

    def test_neng_li_gong_gao_bing_qie_zhun_ling_shen_pi_yu_wen_ti(self):
        """`fangquan` **False**、`wenti2` True。

        `fangquan` 的分岔：报 True。`http._agents` 据此告诉前端「本 Agent 由
        它自己的界面管权限」，用户于是以为审批受管——而
        `extension_ui_request` 是**扩展的 UI API，不是内置工具的审批闸门**：
        内置 `bash` / `edit` / `write` 真机上全程 0 条请求（见文件头
        「审批回路的真实边界」）。⇒ UI 承诺了一件假事。

        `wenti2` **必须留 True**（与权限闸门是两件事）：`select` / `input` /
        `editor` 三种对话框是真阻塞，pi 把 Promise 挂在
        `pendingExtensionRequests` 上等 `extension_ui_response`，
        不回响应它就一直等，回合挂到超时。报 False 会让 `_cheng_bu` 那条路
        退化成纯文本，扩展侧拿到的 `undefined` 与「用户按了取消」同义。
        """
        self.assertFalse(PiAdapter.fangquan())
        self.assertTrue(PiAdapter.wenti2())

    def test_sha_chan_jin_cheng_zao_hao_diao_taskkill(self):
        """**杀进程必须走 `taskkill /T /F`（Windows 上）。**

        分岔：只用基类的 `jin.kill()`。`pi.cmd` 是 `cmd /c node …` 的包装层，
        kill 它只断掉包装层——实测杀完 `tasklist` 里 node.exe 仍在，
        agent 进程成了孤儿，Bridge 关掉之后还在跑用户项目。
        判据落在「真的调了 taskkill 且带 /T」这个量上。
        """
        import subprocess as sp
        calls: list[list[str]] = []
        yuan = sp.run

        def hou(_argv, **kw):
            calls.append(list(_argv))
            return yuan(["cmd", "/c", "exit", "0"], capture_output=True)

        a = _yi_jian()
        a.jin = type("Jin", (), {"pid": 4321, "stdin": None})()
        sp.run = hou
        try:
            a._sha_chan_jin_cheng()
        finally:
            sp.run = yuan
        self.assertEqual(len(calls), 1, "没调 taskkill：node 会变孤儿")
        self.assertEqual(calls[0][:2], ["taskkill", "/PID"])
        self.assertIn("/T", calls[0], "缺 /T：杀不到 node 子孙")
        self.assertIn("/F", calls[0], "缺 /F：pi 收不到强制终止")

    def test_sha_chan_jin_cheng_mei_you_jin_cheng_shi_bu_yao_diao(self):
        a = _yi_jian()
        a.jin = None
        a._sha_chan_jin_cheng()          # 不该抛

    def test_zi_ling_ke_xuan_dai_session_id_he_model(self):
        """`resume` → `--session-id`，可选 `model` → `--model`。

        分岔：不传 `--session-id`。pi 的会话续接全靠它（`--session-id` 是
        「exact project session ID, creating it if missing」），
        漏了则重启后会话接不上，`run.hui_fu` 靠的正是这个字段。
        """
        a = _yi_jian()
        a.kehu_hui = ""
        self.assertEqual(a._zi_ling({}), [], "没续接就不该有多余参数")
        a.kehu_hui = "01a109dc-1f1e-7154-89aa-33ca7127cb78"
        self.assertEqual(a._zi_ling({}), ["--session-id", a.kehu_hui])
        self.assertEqual(a._zi_ling({"model": "anthropic/claude-opus-4-8"}),
                         ["--session-id", a.kehu_hui, "--model",
                          "anthropic/claude-opus-4-8"])


if __name__ == "__main__":
    unittest.main()