"""任务 4「`/agents` 端点扩展」的承重测试。

任务 2 已经把 `moshi` / `fangquan` / `yi_ci_xing` / `dui_hui_id` 四个能力字段
做完了（见 `test_neng_li_qian_yue.py`）。任务 4 后端剩下的缺口只有一个：
**方案第五节的 `ce_shi`（探测详情）没上报**——前端要靠它回答
「为什么装不上 / 装了为什么连不上」，而现在只能看到一句 `error`。

## 判据落在哪里

判据必须落在「两种实现真的会分岔的那个量」上。本文件的三组分岔：

| 组 | 有 `ce_shi` | 没有 |
|---|---|---|
| 1 | 每个 agent 都带 `ce_shi`，含 `probeMs` 与人话 `shuoming` | 键整个不存在，前端只能显示 `error` |
| 2 | 探测慢/快反映在 `probeMs` 上（真实计时，不是常量） | 恒为 0，界面上的「探测耗时」永远是假的 |
| 3 | `ce_shi.ok` **与 `available` 同向**，且失败时 `shuoming` 说得出**为什么** | 前端要自己猜 `error`，猜错就给出错处置 |

第 3 组最要紧：`available:false` 有两种完全不同的原因——
**没装**（处置是装软件）与**装了但探测命令失败**（处置是看配置/看 PATH）。
这两者混进一句 `error` 里，用户会去装一个已经装了的软件。
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
import unittest
import urllib.request
import uuid
from pathlib import Path
from unittest import mock

from lifeos.bridge import auth
from lifeos.bridge.adapters.base import AgentAdapter
from lifeos.bridge.events import ZongXian
from lifeos.bridge.http import BridgeServer
from lifeos.bridge.planner_guard import ShenKa
from lifeos.bridge.session import HuiHua

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _duan_kou() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Ce_Wen_Bu_Ke_Yong(AgentAdapter):
    """探测「没装」的假适配器：CLI 不在 PATH 上。"""

    agentId = "meiZhuang"
    label = "未安装假适配器"
    MOSHI_ZI = frozenset({"manual", "plan"})

    @staticmethod
    def fangquan() -> bool:
        return False

    async def tanjian(self):
        return {"available": False, "version": None, "sdkVersion": None,
                "error": "本机找不到 meiZhuangXinDeCLI"}

    async def kaishi(self, a1):
        pass

    async def fasong(self, a1):
        pass

    async def zhong_duan(self):
        pass

    async def guan_bi(self):
        pass


class Ce_Wen_Cheng_Gong_Dan_Man(AgentAdapter):
    """探测成功、**且没有权限回路**的假适配器。

    这是「可用但由它自己管权限」那第三态的承重样本（方案第五节 UI 表格第二行）。
    """

    agentId = "ziGuan"
    label = "自带权限假适配器"
    MOSHI_ZI = frozenset({"manual", "plan"})

    @staticmethod
    def fangquan() -> bool:
        return False

    @staticmethod
    def wenti2() -> bool:
        return False

    async def tanjian(self):
        return {"available": True, "version": "1.2.3", "sdkVersion": None, "error": None}

    async def kaishi(self, a1):
        pass

    async def fasong(self, a1):
        pass

    async def zhong_duan(self):
        pass

    async def guan_bi(self):
        pass


class Ce_Wen_Cheng_Gong_Que_Wu_Ban_Hao(AgentAdapter):
    """**可用、但没有版本号**的假适配器（`version: None`）。

    这是「`ce_shi.ok` 必须取自 `available`」那条的承重样本。
    ⚠ **样本必须造出 `available` 与 `version` 不同向**：把 `ok` 算成
    `bool(version)` 的实现，在「装了但抓不到版本号」时会把**可用**的 agent
    报成探测失败——而用户的处置是「装软件」，他已经装了。
    真实注册表（claude-code / codex）两个都可用 ⇒ 同向 ⇒ 那条判据在真机上
    不可观测，只在真机上跑会假绿（实测：变异 2 全量跑时零转红）。
    """

    agentId = "wuBanHao"
    label = "无版本号假适配器"
    MOSHI_ZI = frozenset({"manual"})

    async def tanjian(self):
        return {"available": True, "version": None, "sdkVersion": None, "error": None}

    async def kaishi(self, a1):
        pass

    async def fasong(self, a1):
        pass

    async def zhong_duan(self):
        pass

    async def guan_bi(self):
        pass


class Ce_Wen_Shi_Bai_Que_Wu_Yuan_Yin(AgentAdapter):
    """**探测失败、但没报原因**（`available:false` + `error:None`）的假适配器。

    这是「`ce_shi.shuoming` 的兜底必须按 `available` 分」的承重样本。
    写成 `str(error or "") or "已确认…可用"` 的话，这一组会渲染出
    「已确认 XXX 可用」——而同一行的 `ce_shi.ok` 是 false。
    **同一段代码里两个字段用了两套分岔判据**，正是那段注释要防的事，
    只是从另一个方向漏出来。
    """

    agentId = "wuYuanYin"
    label = "无原因失败假适配器"
    MOSHI_ZI = frozenset({"manual"})

    async def tanjian(self):
        return {"available": False, "version": None, "sdkVersion": None, "error": None}

    async def kaishi(self, a1):
        pass

    async def fasong(self, a1):
        pass

    async def zhong_duan(self):
        pass

    async def guan_bi(self):
        pass


class _Fu_Wu_Lei:
    """起一个真 BridgeServer，`/agents` 走真 HTTP 路径。"""

    def __init__(self):
        self.root = str(Path(__file__).resolve().parent.parent)
        self.z = ZongXian(uuid.uuid4().hex[:8])
        self.h = HuiHua(self.z)
        self.z.zhan = self.h
        self.token = auth.shengcheng()
        self.duan = _duan_kou()
        self.fu = BridgeServer(("127.0.0.1", self.duan), self.z, self.h,
                               ShenKa([self.root]), self.token)
        threading.Thread(target=self.fu.serve_forever, daemon=True).start()

    def ting(self):
        self.fu.shutdown()
        self.fu.server_close()
        self.h.ting_zhi()

    def qu(self, a1: str = "/agents") -> dict:
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.duan}{a1}",
            headers={"x-bridge-token": self.token})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())


class Ce_Shi_Shang_Bao_Tests(unittest.TestCase):
    """`ce_shi` 这个键本身。"""

    def setUp(self):
        self.fu = _Fu_Wu_Lei()

    def tearDown(self):
        self.fu.ting()

    def test_mei_ge_agent_dou_dai_ce_shi(self):
        """**每个** agent（不是「至少一个」）都必须带 `ce_shi`。

        分岔：实现成「只有探测失败的才带」或「只有装了 CLI 的才带」。
        前者让「可用」那行没有耗时、没有说明；后者让用户最需要解释的那一格
        （不可用 + 为什么）恰恰是空的——而那正是唯一需要解释的一格。
        """
        with mock.patch.dict("lifeos.bridge.http.ZHU_CE_QI",
                             {"meiZhuang": Ce_Wen_Bu_Ke_Yong,
                              "ziGuan": Ce_Wen_Cheng_Gong_Dan_Man}):
            d = self.fu.qu()
        for x in d["agents"]:
            self.assertIn("ce_shi", x, f"{x['agentId']} 缺 ce_shi")
            self.assertIsInstance(x["ce_shi"], dict)
            for k in ("ok", "probeMs", "shuoming"):
                self.assertIn(k, x["ce_shi"], f"{x['agentId']} 的 ce_shi 缺 {k}")
            self.assertIsInstance(x["ce_shi"]["ok"], bool)
            self.assertIsInstance(x["ce_shi"]["probeMs"], (int, float))
            self.assertIsInstance(x["ce_shi"]["shuoming"], str)

    def test_ce_shi_de_ok_yu_available_tong_xiang(self):
        """`ce_shi.ok` 与 `available` 必须同向——**不能一个真一个假**。

        分岔：实现成 `ok = bool(version)` 或 `ok = not error`（自己算一份）。
        那样会出现 `available:true` 但 `ce_shi.ok:false`——前端按 ok 渲染成
        红色「探测失败」，按 available 渲染成绿色「可用」，同一行两个结论。
        用户看到自相矛盾的界面，比看到一个明确的错误更难判断。

        ⚠ **样本必须让两者不同向**（`wuBanHao`：可用但没版本号）。
        claude-code 与 codex 都「可用且有版本号」，两个键同向 ⇒ 那条判据在
        真机上根本观测不到（变异 2 实测零转红）。
        """
        with mock.patch.dict("lifeos.bridge.http.ZHU_CE_QI",
                             {"meiZhuang": Ce_Wen_Bu_Ke_Yong,
                              "ziGuan": Ce_Wen_Cheng_Gong_Dan_Man,
                              "wuBanHao": Ce_Wen_Cheng_Gong_Que_Wu_Ban_Hao}):
            d = self.fu.qu()
        for x in d["agents"]:
            self.assertEqual(x["ce_shi"]["ok"], bool(x["available"]),
                             f"{x['agentId']}: ce_shi.ok={x['ce_shi']['ok']} "
                             f"但 available={x['available']}")

    def test_shi_bai_de_ce_shi_shuo_de_chu_wei_shao_me(self):
        """探测失败时 `shuoming` 必须**说得出原因**，不是空串也不是「失败」。

        判据落在「有没有可执行的处置」上：前端会把这句直接显示给用户，
        空串的话用户只剩一个红字「不可用」，什么也做不了。
        """
        with mock.patch.dict("lifeos.bridge.http.ZHU_CE_QI",
                             {"meiZhuang": Ce_Wen_Bu_Ke_Yong}):
            d = self.fu.qu()
        x = {y["agentId"]: y for y in d["agents"]}["meiZhuang"]
        self.assertFalse(x["ce_shi"]["ok"])
        self.assertTrue(x["ce_shi"]["shuoming"].strip(),
                        "失败时必须说得出原因")
        # 说得出原因 = 至少复述了适配器自己报的那个原因，而不是泛泛的「探测失败」
        self.assertIn("meiZhuangXinDeCLI", x["ce_shi"]["shuoming"])

    def test_cheng_gong_de_ce_shi_miao_shu_ting_dian_bu_wei_ling(self):
        """探测成功的 `shuoming` 说它在做什么——「跑 claude --version」比空串有用。

        分岔：实现成「成功就返回空串」。界面上的说明列在成功时全空，
        用户不知道 Bridge 到底拿什么在探测，于是「装了却显示不可用」这类
        问题没有排查入口。
        """
        with mock.patch.dict("lifeos.bridge.http.ZHU_CE_QI",
                             {"ziGuan": Ce_Wen_Cheng_Gong_Dan_Man}):
            d = self.fu.qu()
        x = {y["agentId"]: y for y in d["agents"]}["ziGuan"]
        self.assertTrue(x["ce_shi"]["ok"])
        self.assertTrue(x["ce_shi"]["shuoming"].strip(), "成功时也要说清在探测什么")


class Ce_Shi_Shi_Jian_Tests(unittest.TestCase):
    """`probeMs` 必须是**真实计时**，不是常量 0。

    分岔：把计时删掉、恒返回 0，响应体重完全不变——
    上面那组用例有 `assertIsInstance(..., (int, float))`，而 `0` 也是数字，
    类型断言照样通过 ⇒ 假绿。判据必须落在「慢的那次真的更慢」上。
    """

    def setUp(self):
        self.fu = _Fu_Wu_Lei()

    def tearDown(self):
        self.fu.ting()

    def test_man_de_ce_shi_bi_kuai_de_zheng_de_man(self):
        """慢的那次 `probeMs` 必须**明显**更大。

        用 0.35 秒的假探测对 0 秒的：0.35 秒远大于 HTTP 与线程调度噪声
        （实测整条 `/agents` 往返在毫秒级），而 `probeMs` 是整数毫秒、
        两次取整后 0 与 350 的差距不可能被噪声吃掉。
        """
        class Man(Ce_Wen_Cheng_Gong_Dan_Man):
            agentId = "manDe"

            async def tanjian(self):
                time.sleep(0.35)
                return {"available": True, "version": "1.0.0", "sdkVersion": None,
                        "error": None}

        class Kuai(Ce_Wen_Cheng_Gong_Dan_Man):
            agentId = "kuaiDe"

            async def tanjian(self):
                return {"available": True, "version": "1.0.0", "sdkVersion": None,
                        "error": None}

        with mock.patch.dict("lifeos.bridge.http.ZHU_CE_QI",
                             {"manDe": Man, "kuaiDe": Kuai}):
            d = self.fu.qu()
        by = {x["agentId"]: x for x in d["agents"]}
        self.assertGreaterEqual(
            by["manDe"]["ce_shi"]["probeMs"], 300,
            f"慢探测的 probeMs={by['manDe']['ce_shi']['probeMs']}，计时没生效")
        self.assertLess(
            by["kuaiDe"]["ce_shi"]["probeMs"], 300,
            f"快探测的 probeMs={by['kuaiDe']['ce_shi']['probeMs']}，计时口径不对")

    def test_probe_ms_bing_qie_lan_qie_bu_lian_ji(self):
        """`probeMs` 必须**且只能**是本次探测自己的耗时。

        分岔：实现成「累加所有 agent 的探测耗时」或「复用上一次请求的耗时」。
        前者每个 agent 都报整个 `/agents` 的耗时（两个以上 agent ⇒ 两行都 350ms）、
        前端会显示「两个 agent 各探测了 350 毫秒」——数字对不上真实开销；
        后者「重新探测」按钮点一下不改数字，数字与界面反馈无任何关系。
        """
        class Man(Ce_Wen_Cheng_Gong_Dan_Man):
            agentId = "manDe2"

            async def tanjian(self):
                time.sleep(0.35)
                return {"available": True, "version": "1.0.0", "sdkVersion": None,
                        "error": None}

        with mock.patch.dict("lifeos.bridge.http.ZHU_CE_QI",
                             {"manDe2": Man, "claude-code": Ce_Wen_Cheng_Gong_Dan_Man}):
            d = self.fu.qu()
        by = {x["agentId"]: x for x in d["agents"]}
        self.assertGreaterEqual(by["manDe2"]["ce_shi"]["probeMs"], 300)
        # 另一个（瞬间返回的）不能跟着虚高
        self.assertLessEqual(by["claude-code"]["ce_shi"]["probeMs"], 50,
                             "另一个 agent 的 probeMs 跟着虚高了")


class Hui_Ming_Li_Xing_Tests(unittest.TestCase):
    """`echo` 仍然不对外暴露——任务 4 改了 `/agents`，别把它漏出来。"""

    def setUp(self):
        self.fu = _Fu_Wu_Lei()

    def tearDown(self):
        self.fu.ting()

    def test_echo_bu_dui_wai_bao_lu(self):
        with mock.patch.dict("lifeos.bridge.http.ZHU_CE_QI",
                             {"echo": mock.Mock(agentId="echo", label="Echo"),
                              "ziGuan": Ce_Wen_Cheng_Gong_Dan_Man}):
            d = self.fu.qu()
        self.assertNotIn("echo", {x["agentId"] for x in d["agents"]})

    def test_shi_bai_que_wu_yuan_yin_de_ce_shi_bu_ke_yi_shuo_cheng_gong(self):
        """**`available:false` + `error:None` ⇒ `shuoming` 不能说「已确认可用」。**

        分岔：兜底写成 `str(error or "") or f"已确认 {label} 可用"`。
        这一组 `error` 是空的 ⇒ 落到「已确认可用」那一支，而同一行的
        `ce_shi.ok` 是 `false`。前端 `yuanYin` 读的正是 `shuoming`，
        于是用户看到一个**不可用**的 Agent 被告知「已确认可用」。

        **判据落在「这句话本身说不说可用」上**：断言 `ok == False` 不够
        （两种实现都满足），要断言 `shuoming` 里**不出现「可用」**。
        """
        with mock.patch.dict("lifeos.bridge.http.ZHU_CE_QI",
                             {"wuYuanYin": Ce_Wen_Shi_Bai_Que_Wu_Yuan_Yin}):
            d = self.fu.qu()
        x = {y["agentId"]: y for y in d["agents"]}["wuYuanYin"]
        self.assertFalse(x["available"])
        self.assertFalse(x["ce_shi"]["ok"])
        self.assertNotIn("可用", x["ce_shi"]["shuoming"],
                         f"探测失败的 shuoming 不能说「可用」：{x['ce_shi']['shuoming']!r}")
        self.assertTrue(x["ce_shi"]["shuoming"].strip(), "失败时仍要说得出点什么")

    def test_cha_i_di_ji_le_cheng_gong_que_shi_bie_ke_yong(self):
        """探测抛异常 ⇒ 仍然报 `available:false`，且 `ce_shi.ok` 同向。

        分岔：把 `except` 兜底兜底在只有 `available` 上而没同步 `ce_shi`，
        用户界面上一行写着「可用」旁边挂着「探测失败」。
        """
        class BaoZhua(AgentAdapter):
            agentId = "baoZhua"
            label = "抛异常的假适配器"
            MOSHI_ZI = frozenset({"manual"})

            async def tanjian(self):
                raise RuntimeError("探测时炸了")

            async def kaishi(self, a1):
                pass

            async def fasong(self, a1):
                pass

            async def zhong_duan(self):
                pass

            async def guan_bi(self):
                pass

        with mock.patch.dict("lifeos.bridge.http.ZHU_CE_QI", {"baoZhua": BaoZhua}):
            d = self.fu.qu()
        x = {y["agentId"]: y for y in d["agents"]}["baoZhua"]
        self.assertFalse(x["available"])
        self.assertFalse(x["ce_shi"]["ok"])
        self.assertTrue(x["ce_shi"]["shuoming"].strip())


class Dao_Shang_Han_Bu_Tests(unittest.TestCase):
    """回归守护：真实注册表里的适配器走真 `/agents` 路径时也别炸。

    ⚠ 这一组会真跑 `claude --version` 与 `codex --version`（各起一个子进程）。
    判据是「不抛异常 + 结构完整」，不是「claude 一定装了」。
    """

    def setUp(self):
        self.fu = _Fu_Wu_Lei()

    def tearDown(self):
        self.fu.ting()

    def test_zheng_shi_bao_lu_ke_yong_no_zhe_san_ge_ad_queshi_ke_yong(self):
        # 契约字段：v2.0 的四个 + v3.0 任务 2 的 + 任务 4 的 ce_shi
        yao_qiu_de_zi = ("canUseTool", "canAskQuestion", "fangquan", "wenti2",
                         "moshi", "yi_ci_xing", "dui_hui_id", "ce_shi")
        d = self.fu.qu()
        seen = {x["agentId"]: x for x in d["agents"]}
        for aid in ("claude-code", "codex"):
            if aid not in seen:  # 环境里没装 codex 就会少一个，不该因此失败
                continue
            x = seen[aid]
            for k in yao_qiu_de_zi:
                self.assertIn(k, x, f"{aid} 缺字段 {k}")
            self.assertLessEqual(set(x["moshi"]), {"manual", "acceptEdits", "plan",
                                                   "auto", "dontAsk"})


if __name__ == "__main__":
    unittest.main()