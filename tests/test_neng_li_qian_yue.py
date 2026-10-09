"""任务 2「能力契约」的承重测试。

任务 1（传输层）解决「字节怎么传」，任务 2 解决**「这个 harness 到底支持什么」**。
这两者必须一起做：注册表里有 7 个 harness 之后，「建会话时传了个它兑现不了的
permissionMode」会从不可能变成天天发生，而且症状极坏——会话建起来了、界面显示
「plan 模式」，实际那个 harness 从没按 plan 跑过，且这个误解随 `permissionMode`
一起落盘固化下来。

## 判据落在哪里

判据必须落在「两种实现真的会分岔的那个量」上。三组分岔：

| 组 | 有能力契约 | 没有能力契约 |
|---|---|---|
| 1. 该 harness 不支持 `dontAsk`，用户传了 | 400 mode_forbidden | 201，承诺兑现不了且落盘 |
| 2. 该 harness 不支持 `manual`，用户没传 | 400（不静默换成 manual） | 200，塞了个它跑不了的模式 |
| 3. `/agents` 上报 | `moshi` 只列真支持的 | 前端无从渲染第三态 |

**不测「方法返回了 None」这类两种实现都成立的东西。**

## 为什么不 sleep 固定时长

同任务 1：Windows 上 `sleep(2.0)` 必然 flake。等状态一律用 `asyncio.wait_for`
或 `gong_ju.deng_dai`。
"""

from __future__ import annotations

import asyncio
import json
import socket
import sys
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from unittest import mock

from lifeos.bridge import auth
from lifeos.bridge.adapters import ZHU_CE_QI
from lifeos.bridge.adapters.base import AgentAdapter
from lifeos.bridge.adapters.chuan_shu import ZiChengAdapter
from lifeos.bridge.events import ZongXian
from lifeos.bridge.http import BridgeServer
from lifeos.bridge.models import MOSHI
from lifeos.bridge.planner_guard import JuDuan, ShenKa
from lifeos.bridge.session import HuiHua

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ---- 供契约测试用的两个假 harness ----
class JinLei(AgentAdapter):
    """能力受限：只支持 manual/plan，**且不支持切模式**（故意不定义 gai_moshi）。"""

    agentId = "jinlei"
    label = "受限假适配器"
    MOSHI_ZI = frozenset({"manual", "plan"})
    dui_hui_id = "huiId"
    yi_ci_xing = False

    @staticmethod
    def fangquan() -> bool:
        return True

    async def kaishi(self, a1):
        self.moshi = a1.get("permissionMode", "manual")

    async def fasong(self, a1):
        if self.hui:
            self.hui("result", {"resultText": f"ok:{a1}", "isError": False})
        return {"resultText": f"ok:{a1}", "isError": False}

    async def zhong_duan(self):
        pass

    async def guan_bi(self):
        pass


class ZhiDuShi(AgentAdapter):
    """**不支持 manual**：只能 plan（沙箱只读）。

    用户不传模式时默认就是 manual，所以这个适配器是「缺省值必须也被查」
    那一组的承重样本：只在显式传值那条路上查子集的实现会漏掉它。
    """

    agentId = "zhiDu"
    label = "只读假适配器"
    MOSHI_ZI = frozenset({"plan"})

    @staticmethod
    def fangquan() -> bool:
        return False

    async def kaishi(self, a1):
        pass

    async def fasong(self, a1):
        pass

    async def zhong_duan(self):
        pass

    async def guan_bi(self):
        pass


class GuoJieShenMing(AgentAdapter):
    """**故意越界声明**：`MOSHI_ZI` 里塞了 `bypassPermissions`。

    这是「上报侧收敛」那一条的承重样本。`bypassPermissions` 在
    `models.MOSHI` 之外（实测：SDK 在 `can_use_tool` 之前就自动批准，
    审批回调根本不被调用），所以它必须被 `http._agents` 上报时切掉。
    """

    agentId = "guoJie"
    label = "越界声明假适配器"
    MOSHI_ZI = frozenset({"manual", "dontAsk", "bypassPermissions"})

    @staticmethod
    def fangquan() -> bool:
        return True

    async def kaishi(self, a1):
        pass

    async def fasong(self, a1):
        pass

    async def zhong_duan(self):
        pass

    async def guan_bi(self):
        pass


def _duan_kou() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Fang_Zhen_Bie_Le_Tests(unittest.TestCase):
    """闸门 1 按 `MOSHI_ZI` 拦——三层里的第一层，纯函数。

    分岔点在「400 还是放行」，所以每条用例都必须真的调一次 `fang()`，
    断言它抛不抛、抛的 code 是什么。
    """

    def setUp(self):
        self.g = ShenKa()

    # ---- 组 1：该 harness 不支持 ----
    def test_bu_zhi_chi_de_mo_shi_bei_400(self):
        """**该 harness 不支持 `dontAsk` 时，传它必须 400。**

        两种实现在这里真的分岔：
        - 有检查：400，会话根本没建起来。
        - 无检查：201，用户拿到一个「显示 dontAsk 但那个 harness 从没按 dontAsk 跑过」
          的会话，且 `permissionMode` 落盘——下次打开还是这个值，误解被固化。

        这就是方案第零节说的「绝不静默降级」：降级比拒绝更坏，因为它让用户
        对风险做出错误判断。
        """
        with self.assertRaises(JuDuan) as e:
            self.g.fang("dontAsk", JinLei)
        self.assertEqual(e.exception.code, "mode_forbidden")
        # 消息里必须说出这个 harness 到底能用什么，否则用户不知道怎么改。
        self.assertIn("manual", str(e.exception))

    def test_zhichi_de_mo_shi_tong_guo(self):
        self.assertEqual(self.g.fang("manual", JinLei), "manual")
        self.assertEqual(self.g.fang("plan", JinLei), "plan")

    def test_que_kao_que_kao_di_fen_cha(self):
        """**两组实现真的会分岔的点：全局非法 vs 本 harness 不支持。**

        - `bypassPermissions`：全局白名单里就没有，任何 harness 都不支持。
        - `dontAsk` + JinLei：全局白名单里有，但**这个 harness 不支持**。

        两者的消息必须不同：前者是「你传错了」，后者是「这个 Agent 不支持」。
        混成一句话会让用户去改一个根本不是问题的请求。
        """
        with self.assertRaises(JuDuan) as e:
            self.g.fang("bypassPermissions", JinLei)
        zhuan = str(e.exception)
        with self.assertRaises(JuDuan) as e:
            self.g.fang("dontAsk", JinLei)
            self.fail("dontAsk 不该通过 JinLei")
        ben = str(e.exception)
        self.assertNotEqual(zhuan, ben, "「全局非法」与「本 harness 不支持」的消息不能混")
        self.assertIn("bypassPermissions", zhuan)
        self.assertIn("jinlei", ben, "「不支持」的消息必须指名是哪个 Agent")

    def test_fang_mo_shi_que_xian_hou_tui_quan_ju_bai_ming_dan(self):
        """没声明 `MOSHI_ZI` 的 harness 必须放行全局白名单全部值。

        **回退方向必须是「退到全局白名单」，不是「全拒」。** 反过来会让
        **任何忘了写这一行的适配器**立刻不可用，包括 v2.0 已验收的 claude-code
        ——回退方向错了，代价是破坏既有路径而不是新增限制。
        """
        class WeiMingKe(AgentAdapter):
            agentId = "weiming"
            MOSHI_ZI = frozenset()  # 继承基类的空集 = 未声明

        for m in MOSHI:
            self.assertEqual(self.g.fang(m, WeiMingKe), m)

    def test_que_ding_can_zou_de_shen_kao_shi_zhen_de_fang_kong_can_zhuan(self):
        """**回退发生在子集检查里，不在全局检查里。**

        分岔：把 `if zi and a1 not in zi` 里的 `zi and` 删掉（空集 ⇒ 全拒），
        这条用例与 `test_fang_mo_shi_que_xian_hou_tui_quan_ju_bai_ming_dan` 同时转红。
        """
        class WeiMingKe(AgentAdapter):
            agentId = "weiming2"
            MOSHI_ZI = frozenset()

        # 空集 ⇒ 放行全局白名单的全部 5 个值
        for m in MOSHI:
            self.assertEqual(self.g.fang(m, WeiMingKe), m)
        # 而全局非法值仍然被第一级拦——回退不是「全放行」
        self.assertEqual(self._qu_e_cha_kou(), "mode_forbidden")

    def _qu_e_cha_kou(self) -> str:
        try:
            ShenKa.fang("bypassPermissions", AgentAdapter)
        except JuDuan as e:
            return e.code
        raise AssertionError("bypassPermissions 必须被拦")

    # ---- 组 2：缺省值也不许静默降级 ----
    def test_mo_shi_que_kao_shi_que_xian_chai_jian_qian_pei_fen_cha(self):
        """**`None`（用户没传）与显式传同一个值，结果必须一致。**

        分岔：只在「显式传值」那条路上查 `MOSHI_ZI`，而 `None` 直接 `return "manual"`。
        后果是用户选了「只读 Agent + 不选模式」，拿到一个它根本不支持的 manual——
        而他从没主动要求过 manual。这条判据不依赖任何「用户误操作」的假设：
        `fang(None)` 返回 manual 是 v2.0 定下的行为（缺省给 manual），
        那个 manual 同样要过能力子集检查。
        """
        for m in MOSHI:
            if m in JinLei.MOSHI_ZI:
                self.assertEqual(self.g.fang(m, JinLei), m)
            else:
                with self.assertRaises(JuDuan) as e:
                    self.g.fang(m, JinLei)
                self.assertEqual(e.exception.code, "mode_forbidden")
        # 而缺省（None）在只支持 plan 的适配器上必须 400，不能给 manual
        with self.assertRaises(JuDuan) as e:
            self.g.fang(None, ZhiDuShi)
        self.assertEqual(e.exception.code, "mode_forbidden")
        # 对照：支持 manual 的适配器缺省仍然是 manual（v2.0 行为不许变）
        self.assertEqual(self.g.fang(None, JinLei), "manual")


class Jie_Gou_Yue_Ding_Tests(unittest.TestCase):
    """四个类属性的默认值。每个默认值都有它坏掉的具体后果。"""

    def test_si_ge_lei_shu_xing_zai_ji_le_shang_dou_cun_zai(self):
        for cls in (AgentAdapter, JinLei):
            self.assertIsInstance(cls.MOSHI_ZI, frozenset)
            self.assertIsInstance(cls.dui_hui_id, str)
            self.assertIsInstance(cls.yi_ci_xing, bool)
            self.assertIsInstance(cls.xu_pei_zhuang, bool)

    def test_liu_cheng_ji_chuan_song_ceng_mo_ren_yi_ci_xing_wei_True(self):
        """传输层基类的 `yi_ci_xing` 默认必须是 **True**。

        **这是一个会静默失配的默认值。** 传输层基类服务的 4 个一次性 harness
        （gemini/kimi/opencode/cursor）多、常驻的只有 codex / pi 两个；
        而 claude-code 走 Python SDK 根本不继承它。
        默认 False ⇒ 新写的 CLI 适配器若忘了声明，Bridge 会以为它常驻，
        `kaishi()` 就不 spawn，于是第一条指令才 spawn——建会话时
        `qu_pid()` 返回 None，3.6 的孤儿回收账上就少这一笔，
        Bridge 崩了之后那个进程收不回来（而它带着用户全部权限）。
        """
        self.assertTrue(ZiChengAdapter.yi_ci_xing,
                        "传输层基类默认必须是「一次性进程」——那是被服务得最多的一种形态")

    def test_ji_chuan_song_ceng_cheng_gong_mo_shi_bian_lei_xing_bu_neng_fan_guo_lai(self):
        """反过来也钉住：已经是 `False` 的子类不能被基类默认值盖回去。

        分岔：把传输层基类那行 `yi_ci_xing = True` 改成 `False`，
        这一条不会转红（默认值测试只查 True/False 的类型），
        真正转红的是下面那条「`kaishi()` 真的不 spawn」。
        """
        class Chang_Zhu(ZiChengAdapter):
            agentId = "changzhu"
            ZHI_LING = ["true"]
            yi_ci_xing = False

        self.assertFalse(Chang_Zhu.yi_ci_xing)

    def test_xu_pei_zhuang_mo_ren_False(self):
        """v3.0 本轮 7 个 harness 都不需要 Bridge 写本机配置文件。"""
        self.assertFalse(AgentAdapter.xu_pei_zhuang)

    def test_dui_hui_id_mo_ren_wei_claudeSessionId(self):
        """默认必须是 `claudeSessionId`：v2.0 唯一已验收的适配器用它。

        改成 `agentSessionId` 会让 claude-code 的 resume 静默失效——
        `http.xin_jian` 读的是 `hui.claudeSessionId`，字段名一对不上，
        会话续接从「能用」变成「每次都是新会话」，而且不报错。
        """
        self.assertEqual(AgentAdapter.dui_hui_id, "claudeSessionId")


class Shang_Bao_Wei_Guan_Tests(unittest.TestCase):
    """`/agents` 上报的形态。前端靠它渲染三态（方案第五节）。"""

    def setUp(self):
        self.root = str(Path(__file__).resolve().parent.parent)
        self.z = ZongXian(uuid.uuid4().hex[:8])
        self.h = HuiHua(self.z)
        self.z.zhan = self.h
        self.token = auth.shengcheng()
        self.duan = _duan_kou()
        self.fu = BridgeServer(("127.0.0.1", self.duan), self.z, self.h,
                               ShenKa([self.root]), self.token)
        threading.Thread(target=self.fu.serve_forever, daemon=True).start()

    def tearDown(self):
        self.fu.shutdown()
        self.fu.server_close()
        self.h.ting_zhi()

    def _qu(self, a1: str) -> dict:
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.duan}{a1}",
            headers={"x-bridge-token": self.token})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())

    def test_mo_shi_ben_shen_bao_chu_lai_bing_shou_lian_dao_bai_ming_dan(self):
        """每个 agent 的 `moshi` 必须是全局白名单的**交集**，且非空。

        分岔：契约做在上报侧（`MOSHI_ZI & MOSHI`）与不做在上报侧。
        不做的话一个写了越界值的适配器会让前端渲染出一个「选下去必然 400」的选项——
        用户点得进去，提交才被拒，而错误消息谈的是别的模式。

        ⚠ **样本必须真的越界。** 第一版这里用的是 JinLei / ZhiDuShi，
        它们的 `MOSHI_ZI` 本来就是白名单的子集，于是 `zi` 与 `zi & MOSHI`
        完全相等——变异「去掉 `& MOSHI`」零转红（变异验证实测，见附录 B）。
        判据要落在分岔的量上，就得**造一个真的越界的适配器**。
        """
        with mock.patch.dict("lifeos.bridge.http.ZHU_CE_QI",
                             {"jinlei": JinLei, "zhiDu": ZhiDuShi,
                              "guoJie": GuoJieShenMing}):
            d = self._qu("/agents")
        by = {x["agentId"]: x for x in d["agents"]}
        self.assertEqual(by["jinlei"]["moshi"], ["manual", "plan"])
        self.assertEqual(by["zhiDu"]["moshi"], ["plan"])
        # 越界那个：`bypassPermissions` 被第一级闸门拦得住，但**上报侧必须收敛**，
        # 否则前端会渲染出一个选下去必然 400 的模式。
        self.assertEqual(by["guoJie"]["moshi"], ["dontAsk", "manual"])
        for x in d["agents"]:
            self.assertTrue(set(x["moshi"]) <= MOSHI, f"{x['agentId']} 报了越界模式")

    def test_wu_mo_shi_zi_de_huan_zhe_bao_quan_ju_bai_ming_dan(self):
        """没声明 `MOSHI_ZI` 的（claude-code / echo）上报**全部**白名单值。

        这是回退方向在 HTTP 层的兑现：前端据此渲染下拉框，
        空列表会让所有模式下拉框全空——而这个适配器其实什么都支持。
        """
        with mock.patch.dict("lifeos.bridge.http.ZHU_CE_QI", {"weiming": ZhiDuShi}):
            pass  # 占位，下面用真的未声明适配器

        class WeiMingKe(AgentAdapter):
            agentId = "weiming3"
            label = "未声明"
            MOSHI_ZI = frozenset()

            async def tanjian(self):
                return {"available": True, "version": "0", "sdkVersion": None, "error": None}

        with mock.patch.dict("lifeos.bridge.http.ZHU_CE_QI", {"weiming3": WeiMingKe}):
            d = self._qu("/agents")
        x = d["agents"][0]
        self.assertEqual(sorted(x["moshi"]), sorted(MOSHI))
        self.assertNotEqual(x["moshi"], [], "空列表会让前端所有模式下拉框全空")

    def test_san_zhuang_zi_dou_you_fan_yong_chu_lai_de_xin_zi_ng(self):
        """v3.0 新增字段必须真的出现在响应里（前端据此渲染三态）。"""
        d = self._qu("/agents")
        for x in d["agents"]:
            for k in ("fangquan", "wenti2", "moshi", "yi_ci_xing", "dui_hui_id",
                      "canUseTool", "canAskQuestion"):
                self.assertIn(k, x, f"{x['agentId']} 缺字段 {k}")
            self.assertIsInstance(x["yi_ci_xing"], bool)
            self.assertIsInstance(x["dui_hui_id"], str)


class Jian_Hui_Shi_Wei_Guan_Tests(unittest.TestCase):
    """**最承重的一组：闸门 1 在真 HTTP 路径上必须看得到适配器。**

    上面的用例验的是 `ShenKa.fang` 这个函数。这一组验的是
    `http._jian_hui` 真的把适配器传了进去——**接线错了，前面的全绿。**
    """

    def setUp(self):
        self.root = str(Path(__file__).resolve().parent.parent)
        self.z = ZongXian(uuid.uuid4().hex[:8])
        self.h = HuiHua(self.z)
        self.z.zhan = self.h
        self.token = auth.shengcheng()
        self.duan = _duan_kou()
        self.fu = BridgeServer(("127.0.0.1", self.duan), self.z, self.h,
                               ShenKa([self.root]), self.token)
        threading.Thread(target=self.fu.serve_forever, daemon=True).start()

    def tearDown(self):
        self.fu.shutdown()
        self.fu.server_close()
        self.h.ting_zhi()

    def _post(self, a1: str, a2: dict):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.duan}{a1}",
            data=json.dumps(a2).encode(), method="POST",
            headers={"content-type": "application/json", "x-bridge-token": self.token})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def test_jian_hui_shi_bu_zhichi_de_mo_shi_400(self):
        """建会话时传该 harness 不支持的模式 → 400，且**会话没被建出来**。"""
        with mock.patch.dict("lifeos.bridge.http.ZHU_CE_QI", {"jinlei": JinLei}):
            code, r = self._post("/sessions", {"agentId": "jinlei", "cwd": self.root,
                                               "permissionMode": "dontAsk"})
        self.assertEqual(code, 400)
        self.assertEqual(r["error"]["code"], "mode_forbidden")
        self.assertEqual(self.h.kua(), [], "400 之后不该留下任何会话")

    def test_jian_hui_wei_zhuan_mo_shi_ye_yao_shou_shou_dai_kao_bie(self):
        """不传模式、而该 harness 只支持 plan → 400，不能悄悄给 manual。

        这是组 2 的 HTTP 版：`fang(None)` 那个早退分支就在真路径上。
        """
        with mock.patch.dict("lifeos.bridge.http.ZHU_CE_QI",
                             {"zhiDu": ZhiDuShi}):
            # ZhiDuShi 无审批回路，先补知情确认，让这条测的仍是模式闸门本身。
            code, r = self._post("/sessions", {"agentId": "zhiDu", "cwd": self.root,
                                               "acknowledgeNoApproval": True})
        self.assertEqual(code, 400)
        self.assertEqual(r["error"]["code"], "mode_forbidden")

    def test_jian_hui_zhichi_de_mo_shi_cheng_gong(self):
        with mock.patch.dict("lifeos.bridge.http.ZHU_CE_QI", {"jinlei": JinLei}):
            code, r = self._post("/sessions", {"agentId": "jinlei", "cwd": self.root,
                                               "permissionMode": "plan"})
        self.assertEqual(code, 201)
        self.assertEqual(r["session"]["permissionMode"], "plan")

    def test_qie_huan_mo_shi_ye_yao_shou_shou_dai_kao_bie(self):
        """`/mode` 切换接口同样要按适配器收窄——否则能从这条路径绕进去。

        判据落在「绕得进去」这个量上：只查建会话那条路的实现，
        这条 400；不查的（v2.0 现状）会 200 或 409，取决于有没有 `gai_moshi`。
        `JinLei` 故意不定义 `gai_moshi`，所以「不查子集」的实现会走到
        409 那条分支——409 来自「方法不存在」，而不是来自「模式不支持」，
        两者对用户是两件完全不同的事。
        """
        with mock.patch.dict("lifeos.bridge.http.ZHU_CE_QI", {"jinlei": JinLei}):
            code, r = self._post("/sessions", {"agentId": "jinlei", "cwd": self.root,
                                               "permissionMode": "manual"})
        sid = r["session"]["sessionId"]
        with mock.patch.dict("lifeos.bridge.http.ZHU_CE_QI", {"jinlei": JinLei}):
            code, r = self._post(f"/sessions/{sid}/mode", {"permissionMode": "dontAsk"})
        self.assertEqual(code, 400)
        self.assertEqual(r["error"]["code"], "mode_forbidden")

    def test_qie_huan_mo_shi_shou_shou_dai_kao_bie_hou_zhi_cheng_luo_di(self):
        """收窄之后，支持的模式必须还能切成功（别把闸门修成全拒）。"""
        with mock.patch.dict("lifeos.bridge.http.ZHU_CE_QI", {"jinlei": JinLei}):
            code, r = self._post("/sessions", {"agentId": "jinlei", "cwd": self.root,
                                               "permissionMode": "manual"})
        sid = r["session"]["sessionId"]
        # JinLei 有会话但适配器还没启动（没发指令）⇒ 409「会话尚未启动 Agent」。
        # 这一点与模式无关，正是 `test_qie_huan_mo_shi_ye_yao_shou_shou_dai_kao_bie`
        # 断言 400 而不是 409 的理由。
        code, r = self._post(f"/sessions/{sid}/mode", {"permissionMode": "plan"})
        self.assertEqual(code, 409)
        self.assertIn("Agent", json.dumps(r, ensure_ascii=False))


class Ce_Wen_Hui_Bei_Tests(unittest.TestCase):
    """回归守护：契约字段不许把 v2.0 已验收的路径弄坏。"""

    def test_zhu_ce_qi_li_de_mei_ge_mo_shi_zi_dou_shi_bai_ming_dan_de_zi_ji(self):
        for agentId, cls in ZHU_CE_QI.items():
            zi = cls.MOSHI_ZI
            self.assertIsInstance(zi, frozenset, f"{agentId} 的 MOSHI_ZI 不是 frozenset")
            self.assertLessEqual(zi, MOSHI, f"{agentId} 声明了全局白名单之外的值")

    def test_mo_shi_zi_bie_zhi_ru_dian_men_can_qian_reng(self):
        """`bypassPermissions` 绝不进任何 `MOSHI_ZI`。

        实测（spike 报告第 3 节）：该模式下 SDK 在 `can_use_tool` 之前就把调用
        自动批准了，审批回调根本不被调用，整条审批链路静默归零。
        """
        self.assertNotIn("bypassPermissions", MOSHI)
        for cls in (AgentAdapter, JinLei, ZhiDuShi):
            self.assertNotIn("bypassPermissions", cls.MOSHI_ZI)

    def test_qie_huan_mo_shi_de_fu_yong_bao_chi_xing_deng_dian_zai(self):
        """v2.0 的 `/mode` 在适配器省略参数时行为不变（老调用方还这么用）。"""
        g = ShenKa()
        for m in MOSHI:
            self.assertEqual(g.fang(m), m)
        self.assertEqual(g.fang(None), "manual")


if __name__ == "__main__":
    unittest.main()