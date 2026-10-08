"""任务 3 codex 适配器的 L-B（golden）测试。

**这份测试在验什么**：翻译层把 wire 格式转成统一事件时，字段名、分支、kind
映射、回合边界判对没有抄错。

**它在不验什么**（方案 6.2 写得很清楚）：golden 的正确性取决于样本抄得对不对，
而样本是我抄的。所以它只是回归护栏，**不是「已验证」**。
真验收是 L-C（`tests/test_codex_lc_ji_cheng.py`，真 spawn codex 打一次真回合）
与 L-D（`tools/verify_v3_harness.py`）。

## 判据落在哪里

golden 的机制是「喂一行真机 wire，断言发出的统一事件序列」。
所以判据天然落在**序列**上——包括「哪些事件**不该**发」：

| 判据 | 两种实现会分岔在 |
|---|---|
| `turn/completed` 判回合边界 | `fasong()` 会不会返回（判错 ⇒ 挂死到看门狗） |
| `thread/status/changed{idle}` 不发事件 | 界面会不会先显示「空闲」再显示「已完成」 |
| 失败回合要 error **和** result 两条 | 只发一条 ⇒ 决策回路收不到结果 / 状态机不知道失败 |
| `item/completed{userMessage}` 不回显 | 界面会不会把用户输入再显示一遍 |
| 70+ 种无关通知被忽略 | 有没有造出谁都不用的假字段 |

**不 sleep 固定时长**：本项目实测 `sleep(2.0)` 在 Windows 上必然 flake。
这里全是纯函数调用，没有等待。
"""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

from lifeos.bridge.adapters.chuan_shu import ZiChengAdapter
from lifeos.bridge.adapters.codex import CodexAdapter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

JIN = Path(__file__).resolve().parent / "golden"


def _du(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _yi_jian(**xu) -> CodexAdapter:
    """造一个不 spawn 任何东西的适配器，把事件收进列表。"""
    a = CodexAdapter()
    a.shuju = []          # type: ignore[attr-defined]
    a.hui = lambda lei, can: a.shuju.append((lei, can))   # type: ignore[attr-defined]
    return a


class _Dai:
    """挂起通道回来的东西。

    **必须复刻真实形状**：`arbiter.shou` 回的是 `PermissionResultAllow` /
    `PermissionResultDeny` 这些 **dataclass 实例**，`_huida_jie_xi` 读的是
    `.message` 属性。用 dict 代替会走另一条分支，而症状一模一样
    （答案解析不出来），成因完全不同。
    """

    def __init__(self, behavior: str | None = None,
                 message: str | None = None) -> None:
        if behavior is not None:
            self.behavior = behavior
        self.message = message


class Jin_Liu_Yu_Yan_Tests(unittest.TestCase):
    """golden：通知 → 统一事件。"""

    def setUp(self):
        self.bao = _du(JIN / "codex.json")

    def _dui_bi(self, an: dict, qi_wang: list[dict], ming: str) -> None:
        """喂一条 wire，断言发的事件序列与 golden 一致。

        **每条 case 用全新适配器。** `xiang_id` / `_zhuan_wen` 是跨事件的累积
        状态，共用一个适配器会让「item/started 抓住的 id」串到下一条 case 上
        ——那种失败与真 bug 长得一模一样，但成因是测试自己。
        """
        a = _yi_jian()
        # 同一回合内的前置状态按 case 需要预置（golden 里 delta 的 messageId
        # 依赖它前面的 item/started）。**只预置该 case 声明的**，不共享历史。
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
        if any(x.get("jie_shou") for x in qi_wang):
            self.assertIsNotNone(a.jie_shou(an["wire"]),
                                 f"{ming}：`jie_shou` 没认出回合边界")

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

    def test_hui_he_bian_jie_que_cai_de_shi_ba_zhong(self):
        """`turn/completed` 是**唯一**的回合边界。

        分岔：把 `jie_shou` 的判据放宽成「任何 `turn/` 开头的通知」，
        那么 `turn/started` 会在回合刚开始时就收走 `fasong()`——
        症状是 Agent 刚启动就被判跑完，用户看到空结果。
        """
        a = _yi_jian()
        for wei in ("turn/started", "item/started", "item/completed",
                    "thread/status/changed", "item/agentMessage/delta"):
            zhao = {"method": wei, "params": {"threadId": "t1", "turn": {"id": "tn1"}}}
            self.assertIsNone(a.jie_shou(zhao), f"{wei} 被误判成回合边界")
        zhao = {"method": "turn/completed", "params": {"threadId": "t1",
                                                       "turn": {"id": "tn1", "status": "completed"}}}
        self.assertIsNotNone(a.jie_shou(zhao))

    def test_ben_hui_zheng_wen_cong_delta_lai_bu_ling_chuan_completed(self):
        """`resultText` 必须由 delta 累加得来——`turn/completed` 不带正文。

        分岔：改成只读 `turn.items[].text`，那么推理型回合（只有 reasoning、
        没有 agentMessage）会返回空 `resultText`，而 3.8 决策回路就是靠这个字段
        把结果送回 LifeOS 对话上下文 ⇒ 用户看到「Agent 跑完了，但什么都没说」。
        """
        a = _yi_jian()
        for zhai in ("你", "好", "！"):
            a.fan_yi(json.dumps({"method": "item/agentMessage/delta",
                                 "params": {"delta": zhai, "itemId": "m1"}}))
        jie = a.jie_shou({"method": "turn/completed",
                          "params": {"threadId": "t1", "turn": {"id": "tn1",
                                                                "status": "completed",
                                                                "durationMs": 7}}})
        self.assertEqual(jie["resultText"], "你好！")
        self.assertEqual(jie["durationMs"], 7)

    def test_hui_he_bian_jie_hou_zheng_wen_Bei_qing_kong(self):
        """回合边界之后累加器必须清空，否则下一回合的结果是两条回复拼一起。"""
        a = _yi_jian()
        a.fan_yi(json.dumps({"method": "item/agentMessage/delta",
                             "params": {"delta": "第一回合", "itemId": "m1"}}))
        a.jie_shou({"method": "turn/completed",
                    "params": {"turn": {"status": "completed", "durationMs": 1}}})
        a.fan_yi(json.dumps({"method": "item/agentMessage/delta",
                             "params": {"delta": "第二回合", "itemId": "m2"}}))
        jie = a.jie_shou({"method": "turn/completed",
                          "params": {"turn": {"status": "completed", "durationMs": 1}}})
        self.assertEqual(jie["resultText"], "第二回合")


class Po_Ru_Yu_Hui_Ying_Tests(unittest.TestCase):
    """golden：Server→Client 请求 → 挂起通道 → 回同一个 id。"""

    def setUp(self):
        self.bao = _du(JIN / "codex_shen_pi.json")

    def _pai(self, an: dict, *, yong="allow", hui_yi=None):
        """造一个适配器并喂一条 Server 请求（**在一个跑着的 loop 里**）。

        挂起通道立刻返回一个定好的对象，写盘被收进 `hui_ding`。
        **不用真子进程**：这里验的是「收到什么、回什么」，stdio 那层由
        `chuan_shu` 的传输层测试与 L-C 真机脚本负责。

        ⚠ **必须在 loop 里调 `fan_yi`**：审批挂起要 `loop.create_task`，
        没有 loop 时适配器走的是「安静降级成拒绝」那条路（见 `_qi_ren_wu`）。
        那条降级本身是对的（生产路径上 loop 一定在），但在这里会掩盖真行为。
        """
        a = _yi_jian()
        a.hui_ding = []  # type: ignore[attr-defined]

        async def cheng(lei: str, can: dict):
            return _Dai(yong, hui_yi)
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

    def _deng(self, a: CodexAdapter) -> list[dict]:
        """适配器已经跑过挂起任务了，这里只是把写盘内容解回 JSON。"""
        return [json.loads(x) for x in a.hui_ding]

    def test_wu_loop_shi_jiang_dai_an_jue_ju_er_bu_bao_po(self):
        """没有 loop 时挂起请求必须**回拒绝**，且不抛异常。

        分岔：抛异常。`fan_yi` 是同步函数，被 `_du_zhan` 的 `except Exception`
        吞成一条 `translate_failed` 帧，而那个审批请求**一个都没被回**——
        codex 会一直等 id，回合卡到超时，用户看到的是「Agent 无响应」。
        安静降级成拒绝才是对的：代码x 立刻拿到 decline，回合正常结束。
        """
        a = _yi_jian()
        a.hui_ding = []  # type: ignore[attr-defined]
        a.cheng = None  # type: ignore[attr-defined]

        class Xin:
            def write(_self, shu: bytes) -> None:
                a.hui_ding.append(shu.decode("utf-8"))
        a.jin = type("Jin", (), {"stdin": Xin()})()
        self.assertIsNone(a.loop)
        a.fan_yi(json.dumps({"jsonrpc": "2.0", "id": "7",
                             "method": "item/commandExecution/requestApproval",
                             "params": {"itemId": "cmd1", "command": "ls"}}))
        self.assertEqual(len(a.hui_ding), 1, "没回响应，codex 会一直等")
        zhao = json.loads(a.hui_ding[0])
        self.assertEqual(zhao["result"]["decision"], "decline")
        self.assertEqual(zhao["id"], "7")

    def test_qu_an_shen_pi_wen_ti_dou_you_hui_ying(self):
        for an in self.bao["cases"]:
            if an.get("hui_ying_error_code") is not None:
                continue
            with self.subTest(an=an["_ming"]):
                a = self._pai(an, yong="allow",
                              hui_yi="用户对问题的回答：\n- main")
                zhao = self._deng(a)
                self.assertEqual(len(zhao), 1, f"{an['_ming']}：{zhao}")
                self.assertEqual(zhao[0]["id"], an["wire"]["id"],
                                 "**必须用同一个 id 回**（审批决定原路返回）")
                self.assertEqual(zhao[0].get("result", {}),
                                 an["hui_ying"], an["_ming"])

    def test_jue_ding_fu_zao_shi_yan_ji_lie_biao(self):
        """allow / deny 映射到本机 schema 的枚举。

        分岔：把 `JUECAO` 改成方案第 4.2 节的 `approved` / `abort`——
        codex 收下一个不存在的枚举，整个审批永远收不回来（回合挂到超时），
        而单测里「响应发出去了」照样成立。**这就是 golden 存在的理由。**
        """
        for an in self.bao["cases"]:
            if an.get("hui_ying_bie") is None:
                continue
            with self.subTest(an=an["_ming"]):
                a = self._pai(an, yong="deny")
                zhao = self._deng(a)
                self.assertEqual(zhao[0].get("result", {}), an["hui_ying_bie"],
                                 an["_ming"])

    def test_bu_shi_bie_de_fang_fa_hui_bu_zhidao(self):
        """不认识的 Server 请求必须回 `-32601`，不能静默不回。

        分岔：不回。codex 会一直等那个 id，回合卡到超时，
        用户看到的是「Agent 无响应」而不是「这个功能不支持」。
        """
        an = next(x for x in self.bao["cases"]
                  if x.get("hui_ying_error_code") is not None)
        a = _yi_jian()
        a.hui_ding = []  # type: ignore[attr-defined]

        class Xin:
            def write(_self, shu: bytes) -> None:
                a.hui_ding.append(shu.decode("utf-8"))
        a.jin = type("Jin", (), {"stdin": Xin()})()
        a.fan_yi(json.dumps(an["wire"], ensure_ascii=False))
        self.assertEqual(len(a.hui_ding), 1)
        zhao = json.loads(a.hui_ding[0])
        self.assertEqual(zhao["error"]["code"], -32601)
        self.assertEqual(zhao["id"], an["wire"]["id"])

    def test_jie_xi_ce_shi(self):
        """从 arbiter 的自然语言答案里解析回 codex 的结构化形状。"""
        for an in self.bao["jie_xi_ce_shi"]:
            with self.subTest(an=an["_ming"]):
                class Dai:
                    message = an["hui_yi"]
                self.assertEqual(CodexAdapter._huida_jie_xi(Dai(), an["questions"]),
                                 an["jie_xi"], an["_ming"])

    def test_jue_ding_ce_shi(self):
        for an in self.bao["jue_ding_ce_shi"]:
            with self.subTest(an=an["_ming"]):
                yong = (_Dai(**an["yong"]) if an["yong"] is not None else None)
                self.assertEqual(CodexAdapter()._jue_ding(yong), an["jie_xi"], an["_ming"])

    def test_shen_pi_guo_cheng_zhong_fasong_reng_zai_deng(self):
        """审批挂起时 `fasong()` 必须仍在等回合边界（挂起 ≠ 回合结束）。

        分岔：把挂起当成回合结束（调 `jie_shu_kao_ben`），那么 `fasong()`
        在用户还没点「允许」时就返回了 —— `paichu` 于是判这条指令完成，
        用户看到的审批卡与已完成的指令对不上。而单测里「挂起任务跑完了」
        照样成立，判据必须落在**回合 Future 是否被唤醒**这个量上。

        判法：挂起期间 `_jie_shu` 里必须有 Future；挂起任务跑完后
        `turn/completed` 到达，它才该被唤醒。
        """
        async def zhen():
            a = _yi_jian()
            kai = []

            async def cheng(lei: str, can: dict):
                kai.append((lei, can))
                return _Dai("allow")
            a.cheng = cheng  # type: ignore[attr-defined]
            a.loop = asyncio.get_running_loop()
            # 起一个假回合：让 fasong 挂在一个 Future 上
            fa = a.loop.create_future()
            a._xu_hao = 1
            a._jie_shu[1] = fa
            a.fan_yi(json.dumps({"jsonrpc": "2.0", "id": "7",
                                 "method": "item/commandExecution/requestApproval",
                                 "params": {"itemId": "cmd1", "command": "ls"}}))
            await asyncio.sleep(0)
            self.assertEqual(len(kai), 1, "挂起通道没被调")
            self.assertEqual(kai[0][0], "permission")
            await asyncio.sleep(0)
            self.assertFalse(fa.done(),
                             "**审批还没收口，回合就被判结束了** —— 用户看到的"
                             "审批卡与已完成的指令对不上")
            # 收口之后收到回合边界，回合才该返回
            a.fan_yi(json.dumps({"method": "turn/completed",
                                 "params": {"turn": {"status": "completed"}}}))
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
            a.fan_yi(json.dumps({"jsonrpc": "2.0", "id": "7",
                                 "method": "item/commandExecution/requestApproval",
                                 "params": {"itemId": "cmd1", "command": "ls"}}))
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


class Ce_Shi_He_Rong_Yue_Tests(unittest.TestCase):
    """L-A 结构：注册表、契约字段。"""

    def test_zhu_ce_qi_li_you_codex_ma(self):
        from lifeos.bridge.adapters import ZHU_CE_QI
        self.assertIn("codex", ZHU_CE_QI)
        self.assertIs(ZHU_CE_QI["codex"], CodexAdapter)

    def test_qie_ting_de_xian_dai_bi_xie_fa_yao_xie_ming_quan(self):
        """`--listen stdio://` 必须显式写。传别的值 codex 的 stdio 不响应。"""
        self.assertEqual(CodexAdapter.ZHI_LING,
                         ["codex", "app-server", "--listen", "stdio://"])

    def test_yue_ding_que_dao_yong_yuan_ze_chang_sheng_qu_lan(self):
        """`approvalPolicy` 必须恒为 `on-request`（不发审批请求 ⇒ LifeOS 审批卡永远空着）。"""
        self.assertEqual(CodexAdapter._thread_can("D:/x")["approvalPolicy"], "on-request")
        a = _yi_jian()
        a.kehu_hui = "t1"
        for mo in ("manual", "acceptEdits", "plan"):
            a.moshi = mo
            self.assertEqual(a._turn_can("hi")["approvalPolicy"], "on-request")

    def test_ce_wu_tou_yao_ban_de_can_shi_ban_not_can_shi(self):
        """`CE_WU_TOU` 必须是 `["--version"]`（约束：基类默认 `--help`）。

        分岔：留基类默认的 `["--help"]`。抓版本号靠 `(\\d+\\.\\d+\\.\\d+)` 正则，
        而 `codex --help` 的正文里没有版本号 ⇒ 正则不匹配 ⇒
        `tanjian()` 把**可执行文件路径**当版本号返回（实测抓到 `…\\codex.EXE`）。
        ⚠ **不能写成 `["app-server", "--version"]`**：`tanjian()` 跑的是
        `[可执行文件路径] + CE_WU_TOU`，`ZHI_LING` 里那截 `app-server --listen …`
        不在探测命令里。真机 `codex app-server --version` 直接报
        `unexpected argument '--version'` ⇒ 探测恒 `error`。
        """
        self.assertEqual(CodexAdapter.CE_WU_TOU, ["--version"])

    def test_tan_jian_zhua_de_lai_de_shi_ban_hao_ma_not_lu_jing(self):
        """`tanjian()` 真跑一次本机 codex，验证抓到的是版本号而不是路径。

        判据落在「`version` 读出来是不是 `\\d+\\.\\d+\\.\\d+`」上——
        用 `--help` 的实现返回的是 `C:\\…\\codex.EXE`（带反斜杠），
        两者不等 ⇒ 分岔。结构断言够不着的那一半：属性对了不代表
        正则在该 CLI 的输出上真匹配得到。
        """
        import asyncio
        import re
        import shutil

        if not shutil.which("codex"):
            self.skipTest("本机没装 codex")
        bao = asyncio.run(CodexAdapter().tanjian())
        self.assertIs(bao["available"], True, bao)
        self.assertIsNotNone(re.fullmatch(r"\d+\.\d+\.\d+", str(bao["version"])),
                             f"版本号抓成了可执行文件路径：{bao}")

    def test_wei_ren_zhi_de_mo_shi_bei_400(self):
        """codex 没有 claude-code 那种五档模式，只声明能兑现的三档。"""
        from lifeos.bridge.models import MOSHI
        self.assertEqual(CodexAdapter.MOSHI_ZI, frozenset({"manual", "acceptEdits", "plan"}))
        self.assertTrue(CodexAdapter.MOSHI_ZI <= MOSHI)

    def test_shi_chang_zhi_cheng_hai_shi_ke_shi_zhi_cheng(self):
        """app-server 是常驻进程。设错会让 `kaishi()` 不 spawn。"""
        self.assertFalse(CodexAdapter.yi_ci_xing)

    def test_dui_hui_id_shi_claudeSessionId(self):
        """`dui_hui_id` 必须是运行时**真的写出去**的那个键。

        分岔：写 `threadId`。`kaishi()` 发的 session 帧里两个键都带
        （`{"threadId":…, "claudeSessionId":…}`），但 `http._hui_zhuan` 的
        session 分支**只读 `claudeSessionId`**，落进
        `AgentSession.claudeSessionId`；`AgentSession.sessionId` 那个字段
        被 LifeOS 自己的会话 id 占着。⇒ 报 `threadId` 就是宣称「会话 id
        存在一个没人写、也没人读的字段里」，而 `http.xin_jian` 读的
        `hui.claudeSessionId` 与它对不上，resume 静默失效（不报错，
        只是每次都变成新会话）。
        """
        self.assertEqual(CodexAdapter.dui_hui_id, "claudeSessionId")

    def test_session_zhen_de_fa_chu_lai_de_you_claudeSessionId(self):
        """session 帧里**真的有** `claudeSessionId`，且与 `dui_hui_id` 一致。

        断言落在「运行时发出去的键」上，而不是类属性上——
        `dui_hui_id` 对了但 `kaishi()` 忘了带这个键，resume 照样失效。
        """
        import asyncio

        async def zhen():
            a = _yi_jian()

            async def _wu(*_a, **_kw):
                return None

            async def _fake(_a1, _a2=None, _a3=0.0):
                return {"thread": {"id": "t-42"}}

            with mock.patch.object(ZiChengAdapter, "_qi_chi_cheng", _wu), \
                    mock.patch.object(CodexAdapter, "_shou_zhen", _wu), \
                    mock.patch.object(CodexAdapter, "_qing_qiu", _fake):
                await a.kaishi({})
            return a.shuju

        shuju = asyncio.run(zhen())
        session = [can for lei, can in shuju if lei == "session"]
        self.assertEqual(len(session), 1, shuju)
        self.assertEqual(session[0]["claudeSessionId"], "t-42")
        self.assertEqual(CodexAdapter.dui_hui_id, "claudeSessionId")

    def test_bie_zai_zhuan_can_shang_gong_zuo_he_dai_bu_gong_zuo_bu_yong_hai_suo_dai(self):
        """权限模式真的映射到 sandbox，且**不开** dangerFullAccess。

        分岔：把 acceptEdits 也映射成 readOnly（或者干脆传 dangerFullAccess），
        单测「断言 sandboxPolicy 存在」照样成立，用户却发现切了模式也没用，
        或者反过来发现 Agent 不打招呼就能改文件。
        """
        a = _yi_jian()
        a.kehu_hui = "t1"
        a.moshi = "manual"
        self.assertEqual(a._turn_can("x")["sandboxPolicy"]["type"], "readOnly")
        a.moshi = "plan"
        self.assertEqual(a._turn_can("x")["sandboxPolicy"]["type"], "readOnly")
        a.moshi = "acceptEdits"
        can = a._turn_can("x")
        self.assertEqual(can["sandboxPolicy"]["type"], "workspaceWrite")
        self.assertNotIn("dangerFullAccess", json.dumps(can))
        # thread 级也必须是只读起步
        self.assertEqual(CodexAdapter._thread_can("D:/x")["sandbox"], "read-only")

    def test_gai_moshi_fang_che_di_biao_biao_de_zhi_chi_zhe(self):
        a = _yi_jian()
        self.assertTrue(hasattr(a, "gai_moshi"),
                        "codex 的权限面确实是 sandbox，所以必须能切")
        with self.assertRaises(ValueError):
            asyncio.run(a.gai_moshi("dontAsk"))


if __name__ == "__main__":
    unittest.main()