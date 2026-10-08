"""opencode 适配器的 L-B（golden）测试。

**这份测试在验什么**：翻译层把 opencode 的 JSONL wire 转成统一事件时，
字段名、分支优先级、回合边界判对没有抄错。opencode 此前是三家里唯一
没有 L-B 护栏的——它恰恰又是边界最特别的一家：
**两条收口路径**（`step_finish+stop` 与 `type=error`）加一条
「长得像边界但绝不是边界」的 `step_finish+tool-calls`。

**它在不验什么**：golden 的正确性取决于样本抄得对不对，而样本是抄的。
所以它只是回归护栏，**不是「已验证」**。真验收是 L-C
（`tests/test_liu_xing_lc_ji_cheng.py::Opencode_LC`，真 spawn
`opencode run --format json` 打真回合）。

## 判据落在哪里

| 判据 | 两种实现会分岔在 |
|---|---|
| 回合边界**只有** `step_finish + reason=="stop"`；`reason=="tool-calls"` 每调一次工具出现一次（约束 2） | 拿 `step_finish` 本身当边界 ⇒ 第一次工具调用后回合就被收走，后面的正文全丢 |
| `type=="error"` 本身就是边界（约束 3：它后面**没有** step_finish） | 等 step_finish ⇒ `fasong()` 挂死到 15 分钟看门狗 |
| error 帧必须**先于** result 帧发出 | 反过来 ⇒ 界面上「跑完了」出现在「出错了」之前 |
| `tool_use` 与 `tool_result` 合并在同一条 wire 里，按 `state.status` 拆发（约束 4） | running 时也发 tool_result ⇒ 空的工具结果，工具卡收空口 |
| session id 每行都有 ⇒ **第一行就报 session**（约束 5） | 拖到回合末尾 ⇒ 第一回合里 Bridge 迟迟拿不到会话 id |
| 非 JSON 坏行发一条 `error` 后回合照样能收口 | `fan_yi` 抛异常 ⇒ 基类只发 translate_failed、不调收口 |
| 回合边界之后累加器清空、session 帧只发一次 | 不清 ⇒ 第二回合 `resultText` 是两条回复拼一起 |
| `_bu_que_men_can` 补齐 `durationMs`/`numTurns`/`totalCostUsd` | 不补 ⇒ 上层拿到缺字段的结果 dict |

**不 sleep 固定时长**：本项目实测 `sleep(2.0)` 在 Windows 上必然 flake。
这里全是纯函数调用，没有等待。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from lifeos.bridge.adapters.opencode import OpencodeAdapter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

JIN = Path(__file__).resolve().parent / "golden"


def _du(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _zhi_(x: object) -> str:
    """喂给 `fan_yi` 的一行。

    **字符串按原样喂**（那是真机 stdout 上的坏行），其余 `json.dumps`。
    """
    return x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)


def _yi_jian() -> OpencodeAdapter:
    """造一个不 spawn 任何东西的适配器，把事件收进列表。

    `hui` 除了记 (kind, payload)，还记下**那一刻的 `kehu_hui`**——
    「session 帧必须在 result 帧之前」那条判据就落在第三个元素上。
    """
    a = OpencodeAdapter()
    a.shuju: list[tuple[str, dict, str]] = []

    def hui(lei: str, can: dict) -> None:
        a.shuju.append((lei, can, a.kehu_hui))

    a.hui = hui  # type: ignore[attr-defined]
    return a


def _yan(a: OpencodeAdapter) -> list[str]:
    return [lei for lei, _, _ in a.shuju]


def _zai(a: OpencodeAdapter, lei: str) -> list[dict]:
    return [can for lei2, can, _ in a.shuju if lei2 == lei]


class Jin_Liu_Yu_Yan_Tests(unittest.TestCase):
    """golden：一行 wire → 统一事件序列。"""

    def setUp(self):
        self.bao = _du(JIN / "opencode.json")

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
        分岔。这条用例同时钉住 golden 本体不许被清空：case 数少于 9 就说明
        有人删了护栏（本文件写死时是 9 条）。
        """
        self.assertGreaterEqual(len(self.bao["cases"]), 9)
        for an in self.bao["cases"]:
            with self.subTest(an["_ming"]):
                self._dui_bi(an)


class JieGouTests(unittest.TestCase):
    """不依赖 golden 的结构契约。"""

    def test_moshi_zi_sheng_ming_manual_he_dont_ask(self):
        """`MOSHI_ZI = {"manual", "dontAsk"}`——2026-10-06 真机核实后的声明。

        `--auto` 是 `opencode run` 唯一能兑现的放开档（dontAsk）；
        `--dangerously-skip-permissions` 在本机版本已不存在（约束 1），
        `plan` 走 `--agent plan` 与 permissionMode 不是同一机制，不声明。
        声明非空子集后，闸门 1 的 `(zi or MOSHI) & MOSHI` 不再退回全局白名单：
        旧状态（空集）会把五档全渲染出来，用户选 plan → 交集为 0 → 400。
        """
        from lifeos.bridge.models import MOSHI
        zi = OpencodeAdapter.MOSHI_ZI
        self.assertEqual(zi, frozenset({"manual", "dontAsk"}))
        self.assertTrue(zi <= MOSHI, "声明的档必须是全局白名单的子集")
        self.assertIn("manual", zi, "manual 是每家都能兑现的底线档")
        # 抄 `http.py` 闸门 1 的原表达式：非空声明下，交集必须等于声明本身。
        self.assertEqual((zi or MOSHI) & MOSHI, zi)

    def test_dont_ask_gua_auto_manual_bu_gua(self):
        """argv 落点：`dontAsk` → `--auto`；manual（默认）→ 不加任何旗标。

        分岔：忘了接 `--auto` ⇒ dontAsk 会话实际每步都被 CLI 自己拦
        （零审批承诺落空）；manual 也挂 ⇒ Bridge 在替用户放权。
        """
        a = OpencodeAdapter()
        can = a._zi_ling({})
        self.assertNotIn("--auto", can, "manual 不许带放开旗标")
        a.moshi = "dontAsk"
        can = a._zi_ling({})
        self.assertIn("--auto", can)
        self.assertLess(can.index("--auto"), len(can) - 1,
                        "--auto 必须落在指令之前（最后一个参数是指令）")
        self.assertEqual(can[:3], ["run", "--format", "json"],
                         "--format json 恒带：少了它 stdout 一行 JSON 都收不到")

    def test_bu_neng_qie_huan_mo_shi_jiu_bie_ding_yi_gai_moshi(self):
        """一次性进程的档位在 spawn 那一刻写进 argv ⇒ 绝不能定义 `gai_moshi`。

        `http._gai_moshi` 用 `hasattr` 判「这个 harness 能不能切」，定义了它
        就恒为 True，切换还会被**落盘**——而 opencode 的进程已经在按旧 argv
        跑了。「方法不存在」就是可用信号。
        """
        self.assertFalse(hasattr(OpencodeAdapter(), "gai_moshi"))

    def test_ben_hui_wu_lu_quan_hui_hui(self):
        """**没有权限回路也没有提问回路**（非交互模式下 CLI 自己管权限）。

        分岔：任一个报 True，`/agents` 就给这个 harness 发审批卡，
        而 opencode 那边根本没人问——闸门 0 要求的知情同意也建立在
        这两个 False 上。
        """
        self.assertFalse(OpencodeAdapter.fangquan())
        self.assertFalse(OpencodeAdapter.wenti2())

    def test_xu_jie_yong_yong_session_can_shu(self):
        """续接靠 `--session <id>`：`kehu_hui` 写好后 argv 要带上它。"""
        a = OpencodeAdapter()
        a.kehu_hui = "ses_abc123def456"
        can = a._zi_ling({})
        self.assertEqual(can[can.index("--session") + 1], "ses_abc123def456")

    def test_dui_hui_id_shi_claude_session_id(self):
        """前端契约只认 `claudeSessionId` 这个键（`_fa_session` 的注释）。"""
        self.assertEqual(OpencodeAdapter.dui_hui_id, "claudeSessionId")

    def test_yi_ci_xing_cai_shi_mo_ke_yi_zhong_yong(self):
        """一次性进程：`kaishi()` 不 spawn，进程留到 `fasong()`。"""
        self.assertTrue(OpencodeAdapter.yi_ci_xing)

    def test_ban_xiang_wen_tou_shi_yao_yong_version(self):
        """`CE_WU_TOU` 必须覆写成 `--version`（基类默认 `--help`）。

        分岔：用基类的 `--help`，版本号正则会匹配到 `--print-logs` 里的
        `127.0.0` ⇒ `/agents` 显示一个完全不相干的「版本号」。
        """
        self.assertEqual(OpencodeAdapter.CE_WU_TOU, ["--version"])


class LeiJiaTests(unittest.TestCase):
    """跨回合的累积状态：清空与幂等。"""

    def test_liang_hui_he_lei_jia_qing_kong_session_zhi_fa_yi_ci(self):
        """两个回合：正文各归各的回合，session 帧只发一条。

        分岔：`_qing_kong` 漏调 ⇒ 第二条 result 的 `resultText` 是两条回复
        拼一起；`_fa_le_session` 漏判 ⇒ 落盘会话被反复覆写。
        """
        a = _yi_jian()
        for hang in (
            {"type": "step_start", "sessionID": "ses_x", "part": {"type": "step-start"}},
            {"type": "text", "sessionID": "ses_x", "part": {"type": "text", "text": "第一条"}},
            {"type": "step_finish", "sessionID": "ses_x", "part": {"reason": "stop", "cost": 0.1}},
        ):
            a.fan_yi(json.dumps(hang, ensure_ascii=False))
        self.assertEqual(_zai(a, "result")[0]["resultText"], "第一条")
        for hang in (
            {"type": "text", "sessionID": "ses_x", "part": {"type": "text", "text": "第二条"}},
            {"type": "step_finish", "sessionID": "ses_x", "part": {"reason": "stop", "cost": 0.2}},
        ):
            a.fan_yi(json.dumps(hang, ensure_ascii=False))
        self.assertEqual(_yan(a).count("session"), 1, "session 帧必须幂等")
        self.assertEqual(_yan(a).count("result"), 2)
        self.assertEqual(_zai(a, "result")[1]["resultText"], "第二条",
                         "第二回合的正文混进了第一回合的内容")

    def test_hui_he_shou_cuo_wei_de_xing_zhuang(self):
        """step_finish(stop) 的 result：`isError` 跟着 `_cuo_wen` 走。

        分岔：把 `isError` 写死 False ⇒ error 收口后如果再走 stop 边界
        （防御路径），界面上把错误当成功。
        """
        a = _yi_jian()
        a.fan_yi(json.dumps({"type": "step_finish", "sessionID": "ses_x",
                             "part": {"reason": "stop"}}))
        jie = _zai(a, "result")[0]
        self.assertFalse(jie["isError"])
        self.assertEqual(jie["subtype"], "completed")

    def test_tong_yi_hui_he_de_di_er_tiao_error_bu_zhong_chu_fa(self):
        """**同一回合的第二条 error 不许重复触发收口**（2026-10-06 实测）。

        真机形态：opencode 内部重试会在一回合里连吐多条 `error`（约束 3：
        error 后面没有 step_finish，第一条就已经收口）。`jie_shou` 的
        `_fan_le` 闸在 `_qing_kong()` 里复位——它防的是**同一事件的重入**，
        防不了**清理之后的第二条边界线**。没闸的后果：第二条 error 再发
        `error` 帧 + 再走 `jie_shou` ⇒ 同一回合收到第二个 `result` 帧
        （空正文、isError=True），界面上同一回合收两次口。

        下一回合（新 spawn，`_fan_yi_zhun_bei` 重置）error 必须照常收口——
        「同一条指令重试即正常」靠的就是这个重置。
        """
        import asyncio

        async def xin_yi_hui():
            await a._fan_yi_zhun_bei()

        a = _yi_jian()
        cuo = {"type": "error", "sessionID": "ses_x",
               "error": {"name": "UnknownError", "data": {"message": "boom"}}}
        # 第一条 error：error 帧 + result 帧各一条，isError=True
        a.fan_yi(json.dumps(cuo, ensure_ascii=False))
        self.assertEqual(_yan(a).count("error"), 1, "第一条 error 必须报 error 帧")
        self.assertEqual(_yan(a).count("result"), 1, "第一条 error 必须收口")
        jie = _zai(a, "result")[0]
        self.assertTrue(jie["isError"])
        self.assertEqual(jie.get("errorMessage"), "boom")
        # 同一回合的第二条 error：必须完全安静
        a.fan_yi(json.dumps({**cuo, "error": {"data": {"message": "boom again"}}},
                            ensure_ascii=False))
        self.assertEqual(_yan(a).count("error"), 1,
                         "第二条 error 不许再发 error 帧")
        self.assertEqual(_yan(a).count("result"), 1,
                         "第二条 error 不许再发 result 帧（同一回合收两次口）")
        # 下一回合（新 spawn 重置后）：error 照常收口
        asyncio.run(xin_yi_hui())
        a.fan_yi(json.dumps(cuo, ensure_ascii=False))
        self.assertEqual(_yan(a).count("result"), 2,
                         "重置后的新回合 error 必须照常收口")


if __name__ == "__main__":
    unittest.main()
