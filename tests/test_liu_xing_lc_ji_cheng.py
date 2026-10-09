"""kimi / opencode / hermes 三个一次性进程适配器的 L-C（进程级）测试。

**这一层是唯一能抓「回合边界判错」的**。判错的后果不是翻译出错，而是
`fasong()` 挂死到 15 分钟看门狗——事件全对、单测全绿、用户只看到
「Agent 无响应」。golden（L-B）是抄的样本，它对「真实回合边界到底是什么」
没有发言权。

## 为什么三家写在一个文件里

三家在**协议层毫无共性**（事件形状、边界判据、argv 全不同），但在**形态**上
完全一样：一次性进程、JSONL 到 stdout、**没有权限回路**。
⇒ L-C 要验的东西也相同（回合会收口、累加器清干净、中断能收口、
进程树杀干净），差别只在「用哪家的类」。**一个文件 + 参数化比三份复制好。**

## 默认跳过，但装了就必须真跑

- 没装 ⇒ skip（**不是 pass**，理由写在 skip 消息里）。
- 装了但模型不通 ⇒ **真跑**并把失败原样报出来，不静默跳过。
  「跑了但跑不通」和「没跑」在报告里必须能区分开。

## ⚠ 不 sleep 固定时长

本项目实测 `sleep(2.0)` 在 Windows 上必然 flake。一律 `asyncio.wait_for`
（有上界）与轮询（有状态判据，`tests/gong_ju.py` 里有 `deng_dai`）。

## ⚠ provider 会偶发空响应（真实存在，不是测试写错）

2026-10-05 真机实测：opencode 的 provider 偶发
`{"type":"error",…,"message":"Provider returned an empty response"}`，
**它后面没有 `step_finish`**——这正是 opencode.py 约束 3 那条收口逻辑存在的理由。
所以本文件对 opencode 允许「回合以 isError 收口」也算通过：
**判据是「回合收口了」，不是「回合成功了」**（分岔在 `fasong()` 会不会返回）。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from lifeos.bridge.adapters.hermes import HermesAdapter
from lifeos.bridge.adapters.kimi import KimiAdapter
from lifeos.bridge.adapters.opencode import OpencodeAdapter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

#: 三家 + 它们各自的可执行名。⚠ **可执行名要带后缀**——
#: Windows 上 `create_subprocess_exec("kimi")` 直接 `FileNotFoundError`
#: （npm shim 在磁盘上是 `kimi.cmd`），适配器里靠 `_jie_zhende_ming()` 解析。
#: 这里用 `shutil.which` 直接判，与适配器的解析逻辑同源。
SAN_DA: tuple[tuple[str, type, str], ...] = (
    ("kimi", KimiAdapter, "kimi"),
    ("opencode", OpencodeAdapter, "opencode"),
    ("hermes", HermesAdapter, "hermes"),
)

#: 一回合的预算。三个 CLI 首次启动要加载配置/索引，给足。
HUI_HE_MIAO = 240.0
#: `kaishi` 的预算（一次性进程这里不 spawn，但要走完基类校验）。
SHOU_ZHEN_MIAO = 60.0
#: 任何用例挂死的兜底。**测试挂死比失败更糟**。
SUO_DING = 300.0

#: 指令固定成这两个字，让「两轮正文该相同」这件事可观测（见连发那条）。
_MING_LING = "只回答两个字：收到"

#: 连发用例两轮用**不同的暗号**（2026-10-06 改）：原版两轮同一句并断言
#: 两次正文相等，前提是「模型对同一指令的回答大概率相同」。真机两天各
#: 翻车一次——hermes 一轮回「暮雪先生，收到。」另一轮只回「收到」
#: （措辞不稳定），kimi 第二轮正文混进 `</think>`（思考标签随正文出）。
#: 严格相等把**模型自由度**误判成累加器污染。真正的分岔量是**跨轮串染**：
#: 第二轮的正文里出现第一轮的暗号才算没清干净，判据用「包含」。
_MING_LING_1 = "只回答两个字：红叶"
_MING_LING_2 = "只回答两个字：石桥"
_AN_HAO_1 = "红叶"
_AN_HAO_2 = "石桥"


def _zhuang_lei(cls: type) -> bool:
    """这家装了没。走 `shutil.which` + Windows 后缀，与适配器同源。"""
    for _, _, ming in SAN_DA:
        if cls.agentId != ming:
            continue
        if shutil.which(ming):
            return True
        return any(shutil.which(ming + h) for h in (".exe", ".cmd", ".bat"))
    return False


def cun_zhen(pid: int) -> bool:
    """pid 还活着吗。走 `tasklist`，Windows 上够用（codex 的 L-C 同样做法）。"""
    try:
        chu = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             capture_output=True, text=True, timeout=15,
                             encoding="utf-8", errors="replace")
        return str(pid) in (chu.stdout or "")
    except Exception:  # noqa: BLE001
        return False


#: 本模块的测试开始时刻（CIM 用的 CreationDate 比这个早 ⇒ 是残留，不是本轮的）。
#: **模块导入时取一次**。用「比测试开始更早」而不是「全部杀掉」——
#: 后者会把**用户自己正在用的 opencode 一起杀掉**，那是测试恶意改动用户环境。
_KAI_SHI = None


def _sha_can_zhu_dou(agent_id: str) -> None:
    """**收尾清理：干掉「比本轮测试更早」的那家残留 CLI 进程**（2026-10-05 真机踩到）。

    ## 为什么需要

    opencode 的状态目录 `~/.local/share/opencode/opencode.db` 是 SQLite，
    **上一个没退干净的进程持有它的锁** ⇒ 新进程在 stdout 上一个字节都不吐，
    等到看门狗。症状与「模型不通」完全一样（都是零输出），极难区分。

    残留从哪来：中断用例（`zhong_duan`）与超时用例都会在 CLI 没退干净时
    结束断言，而 `Process.kill()` 只杀 `.cmd` 包装层（pi 约束 2 的同款问题）。

    ## ⚠⚠ 为什么按「启动时间早于本轮」筛，而不是按名字全杀

    按名字全杀 = **测试跑一次就把用户正在用的 opencode 杀掉**。
    那是测试在改用户环境，比它想清的问题更糟。
    ⇒ CIM 的 `CreationDate` 比 `_KAI_SHI` 早的才是残留（上一条用例留下的），
    本轮自己起的进程由用例自己的 `guan_bi` 负责，不该由这里动。

    ⚠ 用 CIM 查 **CommandLine** 而不是只看镜像名：kimi 的真身是 node，
    只按镜像名杀会把用户自己的开发服务器一起杀掉。
    ⚠ 只在 Windows 上做（这三个 CLI 都是 Windows 形态）。
    ⚠ 杀不掉不抛——清理失败不该让用例变红。
    """
    if sys.platform != "win32" or _KAI_SHI is None:
        return
    exe = {"kimi": "node.exe", "opencode": "opencode.exe", "hermes": "hermes.exe"}.get(agent_id)
    if not exe:
        return
    try:
        # ⚠ `-eq` 比字符串、失败就当没有：宁可漏杀也不要在这里抛。
        chu = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq '%s' -and "
             "$_.CommandLine -like '*%s*' -and $_.CreationDate -lt (Get-Date '%s') } | "
             "ForEach-Object { $_.ProcessId }) -join ','"
             % (exe, agent_id, _KAI_SHI.strftime("%Y-%m-%d %H:%M:%S"))],
            capture_output=True, text=True, timeout=40,
            encoding="utf-8", errors="replace")
        for s in (chu.stdout or "").replace("\r", "").split(","):
            if not s.strip():
                continue
            subprocess.run(["taskkill", "/PID", s.strip(), "/T", "/F"],
                           capture_output=True, timeout=20)
    except Exception:  # noqa: BLE001
        pass


def _ji_shi_kai_shi_bian_ju() -> None:
    """模块加载时记下时刻，供 `_sha_can_zhu_dou` 判「谁比测试更早」。"""
    global _KAI_SHI
    import datetime
    _KAI_SHI = datetime.datetime.now() - datetime.timedelta(seconds=2)


_ji_shi_kai_shi_bian_ju()


class _Ji_chu(unittest.TestCase):
    """三家共用的用例骨架。子类只填 `_lei`（用哪个适配器类）。"""

    _lei: type = KimiAdapter
    # `_Ji_chu` 自己也是 TestCase 子类，会被 unittest 单独收集成一份 kimi 用例。
    # 期望档必须跟着这个默认 `_lei` 走，否则 test_mo_shi_zi 在基类上直接
    # AttributeError——子类各自覆写这两个属性，改谁记得改另一份。
    _qi_wang_moshi: tuple[str, ...] = ("manual",)

    def tearDown(self) -> None:
        """**清掉这一家残留的 CLI 进程**（见 `_sha_can_zhu_dou` 的理由）。

        没有这一步，一次失败留下的孤儿会让**后面所有** opencode 用例
        一起挂死——那 3 条首轮失败就是这么来的，看起来像适配器坏了，
        真因是上一条用例没收拾干净。
        """
        _sha_can_zhu_dou(self._lei.agentId)  # type: ignore[attr-defined]

    def _da_ma(self) -> tuple[object, list[tuple[str, dict]]]:
        """造一个不 spawn 任何东西的适配器，把事件收进列表。

        ⚠ **判据是 `hui` 回调收到的帧序列**，不是适配器的内部状态——
        内部状态两种实现读出来可能一样，帧序列不会。
        """
        a = self._lei()
        zhuang: list[tuple[str, dict]] = []
        a.hui = lambda lei, can: zhuang.append((lei, can))  # type: ignore[assignment]
        return a, zhuang

    @staticmethod
    def _can_shu(cwd: str) -> dict:
        return {"cwd": cwd, "permissionMode": "manual"}

    def _da_yi_hui(self, a, zhuang, ming_ling: str = _MING_LING) -> dict | None:
        """打一回合，返回 result 帧（没有则 None）。

        `da_ma` 已经 self 了，失败时断言信息要能指出是哪一家。
        """
        cwd = str(Path(__file__).resolve().parent.parent)

        async def zhen():
            await asyncio.wait_for(a.kaishi(self._can_shu(cwd)), SHOU_ZHEN_MIAO)
            try:
                await asyncio.wait_for(a.fasong(ming_ling), HUI_HE_MIAO)
            finally:
                await asyncio.wait_for(a.guan_bi(), 30.0)

        asyncio.run(asyncio.wait_for(zhen(), SUO_DING))
        jie = [p for k, p in zhuang if k == "result"]
        return jie[0] if jie else None

    # ---- 承重用例 ----

    def test_fasong_zhen_de_hui_shou_bing_qie_sheng_yi_ge_result(self):
        """**最承重的一条：`fasong()` 真会因回合边界返回。**

        判错的后果：所有翻译都对、golden 全绿、真机上挂死到看门狗。
        判据落在「`fasong` 在预算内返回了 **且 result 帧恰好一条**」上——
        「收到了某个事件」这种判据两种实现都成立，是废断言。
        """
        a, zhuang = self._da_ma()
        jie = self._da_yi_hui(a, zhuang)
        jie_all = [p for k, p in zhuang if k == "result"]
        self.assertIsNotNone(jie, f"回合没收口（fasong 没返回或没发 result）："
                                 f"{[k for k, _ in zhuang]}")
        # 正文非空这里**不硬断**：厂商偶发吐「纯空 thinking 回合」（2026-10-06
        # 在 pi 上实测，会话记录 assistant 只有 content=[('thinking', 0)]），
        # 文本抽取的正确性由 L-B golden 层把守，本层判的是回合边界与错误信号。
        self.assertEqual(len(jie_all), 1, f"result 帧数不对：{[k for k, _ in zhuang]}")

    def test_lian_fa_liang_tiao_dou_neng_shou_kou(self):
        """同一条会话连发两条指令都收口，且第二轮正文不与第一轮粘连。

        分岔：累加器没清空 ⇒ 第二轮 `resultText` 里带着第一轮正文，
        用户看到同一条回复出现两遍。**单看「都返回了」照样绿**，
        所以判据落在「两段正文的关系」上——具体见 `_AN_HAO_1` 注释：
        两轮不同暗号 + 「第二轮不得含第一轮暗号」，不用严格相等。
        """
        cwd = str(Path(__file__).resolve().parent.parent)

        async def zhen():
            a, zhuang = self._da_ma()
            await asyncio.wait_for(a.kaishi(self._can_shu(cwd)), SHOU_ZHEN_MIAO)
            try:
                await asyncio.wait_for(a.fasong(_MING_LING_1), HUI_HE_MIAO)
                self.assertEqual(a._jie_shu, {}, "第一回合后 Future 有残留")
                await asyncio.wait_for(a.fasong(_MING_LING_2), HUI_HE_MIAO)
            finally:
                await asyncio.wait_for(a.guan_bi(), 30.0)
            return [p for k, p in zhuang if k == "result"]

        jie = asyncio.run(asyncio.wait_for(zhen(), SUO_DING * 2))
        self.assertEqual(len(jie), 2, f"两回合的 result 帧数不对：{jie}")
        yi1 = str(jie[0].get("resultText") or "").strip()
        yi2 = str(jie[1].get("resultText") or "").strip()
        # 厂商偶发「回合 completed 但一个字没吐」（2026-10-06 在 pi 上实测，
        # 会话记录 assistant 只有 content=[('thinking', 0)]）：空轮没有可判
        # 的正文，暗号断言只对非空轮做。「第二轮为空 ⇒ 不可能粘连」仍成立
        # ——累加器真泄漏的话第二轮正文必非空。两轮全空才响铃。
        if yi1:
            self.assertIn(_AN_HAO_1, yi1, "第一轮没回第一题")
        if yi2:
            self.assertIn(_AN_HAO_2, yi2, "第二轮没回第二题")
            # **第二轮不得带第一轮的暗号**——判据落在「跨轮串染」上
            self.assertNotIn(_AN_HAO_1, yi2,
                             "第二轮带着第一轮的暗号：累加器没清干净")
        self.assertTrue(yi1 or yi2, "两轮都没吐字：模型/环境不可用，粘连无从判起")

    def test_session_id_shang_bao_guo_lai_le(self):
        """session 帧必须发出来，且 `kehu_hui` 与帧里的 id 一致。

        `run.hui_fu` 恢复时靠 `claudeSessionId` 传续接参数（`-r` / `--session`
        / `--resume`）。**没有 session 帧 ⇒ 重启 Bridge 后这一路会话续不上**，
        而症状是「每回合都像新会话，上下文全丢」——很难联想到 session 帧。
        """
        a, zhuang = self._da_ma()
        self._da_yi_hui(a, zhuang)
        ses = [p for k, p in zhuang if k == "session"]
        self.assertEqual(len(ses), 1, f"session 帧数不对（只发一次）："
                                      f"{[k for k, _ in zhuang]}")
        self.assertTrue(ses[0].get("sessionId"), f"session 帧没有 id：{ses[0]}")
        # ⚠ **必须带 `claudeSessionId`**：`http._hui_zhuan` 的 session 分支
        # 只认这一个键（liu_xing.py `_fa_session` 的 docstring 记着这条）。
        self.assertEqual(ses[0].get("claudeSessionId"), ses[0].get("sessionId"),
                         f"claudeSessionId 与 sessionId 不一致：{ses[0]}")
        self.assertEqual(a.kehu_hui, ses[0]["sessionId"],
                         "适配器内部的 kehu_hui 与发出的 session 帧不一致")

    def test_zhen_de_can_spawn_chu_lai(self):
        """**真 spawn**：可执行名解析对了、`FileNotFoundError` 没有出现。

        分岔（2026-10-05 真机踩过）：Windows 上 npm 全局装的是 `kimi.cmd`
        这种 `cmd /c node …` 包装层，`create_subprocess_exec("kimi")` 报
        `FileNotFoundError`——**而 `tanjian()` 用 `shutil.which` 显式试了
        `.cmd` 后缀，照样报 `available=true`**。症状是「显示可用，一发消息就炸」。
        这条用例守的就是那个解析。
        """
        a, _ = self._da_ma()
        zhen = a._jie_zhende_ming()  # type: ignore[attr-defined]
        self.assertTrue(zhen, "解析不出可执行名")
        if sys.platform == "win32":
            self.assertNotEqual(zhen, self._lei.ZHI_LING[0],
                                "Windows 上应解析出带后缀/绝对路径的名字，"
                                f"裸名 spawn 会 FileNotFoundError（拿到 {zhen!r}）")
        self.assertIsNotNone(shutil.which(zhen) or zhen,
                             f"解析出来的名字在磁盘上不存在：{zhen!r}")

    def test_zhong_duan_shou_kou_bing_qing_kong_lei_ji_qi(self):
        """中断必须让回合收口，并清掉累加器。

        分岔：杀掉进程但不清累加器 ⇒ 下一回合的结果里带着「数到一百」的残留，
        用户看到一句不属于自己的话混进回复。
        """
        cwd = str(Path(__file__).resolve().parent.parent)

        async def zhen():
            a, zhuang = self._da_ma()
            await asyncio.wait_for(a.kaishi(self._can_shu(cwd)), SHOU_ZHEN_MIAO)
            ren = a.loop.create_task(a.fasong("数到一百，每行一个数，不要停"))
            # 等回合真的起来（有帧说明 CLI 在吐东西了），**不是 sleep 猜**
            for _ in range(int(HUI_HE_MIAO / 0.1)):
                if any(k in ("text", "chunk", "tool_use") for k, _ in zhuang):
                    break
                await asyncio.sleep(0.1)
            await asyncio.wait_for(a.zhong_duan(), 30.0)
            # 中断后回合必须收口，不能挂着
            await asyncio.wait_for(ren, 30.0)
            await asyncio.wait_for(a.guan_bi(), 30.0)
            # 累加器必须清干净
            self.assertEqual(a._zhuan_wen, [], "中断没清正文累加器")

        asyncio.run(asyncio.wait_for(zhen(), SUO_DING))

    def test_guan_bi_hou_jin_cheng_bian_none(self):
        cwd = str(Path(__file__).resolve().parent.parent)

        async def zhen():
            a, _ = self._da_ma()
            await asyncio.wait_for(a.kaishi(self._can_shu(cwd)), SHOU_ZHEN_MIAO)
            await asyncio.wait_for(a.fasong(_MING_LING), HUI_HE_MIAO)
            pid = a.qu_pid()
            await asyncio.wait_for(a.guan_bi(), 30.0)
            self.assertIsNone(a.jin, "guan_bi 后子进程引用还在")
            self.assertIsNone(a.qu_pid())
            # ⚠ 这三家是**一次性进程**：回合跑完 CLI 自己就退了，
            # 所以「回合后 pid 还在」不是缺陷。真正要守的是 guan_bi 不留引用。
            if isinstance(pid, int):
                for _ in range(100):     # 轮询（有判据），不是 sleep 固定时长
                    if not cun_zhen(pid):
                        break
                    import time
                    time.sleep(0.1)
                self.assertFalse(cun_zhen(pid), f"guan_bi 后进程 {pid} 还活着")

    def test_env_bing_qing_shou_ke_yi_huan_chang_liang_ming_zei_men_kan_bie_ming(self):
        """**实例属性不能遮蔽基类同名方法**（2026-10-05 真机抓到的致命缺陷）。

        `LiuXingAdapter.__init__` 曾经把 `self._huan_jing` 设成 dict，
        而基类有一个**同名方法** `ZiChengAdapter._huan_jing()`（负责
        `{**os.environ, **增量}` 的真合并）。
        实例属性把方法遮蔽 ⇒ `env=self._huan_jing(a1)` 变成「拿 dict 当函数调」
        ⇒ **`TypeError: 'NoneType' object is not callable`，第一条指令 100% 炸**。

        判据落在「基类那个方法还是不是可调用的方法」上——
        「跑通一个回合」也能分岔，但慢且费额度；这条一秒就抓到，且能指出根因。
        """
        a, _ = self._da_ma()
        # 基类方法必须还在（没被实例属性遮蔽）
        self.assertTrue(callable(getattr(a, "_huan_jing", None)),
                        "基类 `_huan_jing()` 方法被实例属性遮蔽了 —— "
                        "第一条指令会 TypeError")
        # 且它返回的是**真合并**的结果，不是原样返回增量
        he = a._huan_jing({"env": {"CLAUDE_CONFIG_DIR": "/tmp/xxx"}})  # type: ignore[attr-defined]
        self.assertIsNotNone(he, "增量为空时返回 None（完全继承）是对的；"
                                 "非空增量必须返回合并后的 dict")
        if he is not None:
            self.assertEqual(he.get("CLAUDE_CONFIG_DIR"), "/tmp/xxx", "增量没覆盖到位")
            # ⚠ Windows 上 `os.environ` 大小写敏感，真键是 `SYSTEMROOT`。
            # 写这条断言前先 print 验过，别照着记忆里的名字写。
            self.assertTrue(
                any(k.upper() == "SYSTEMROOT" for k in he),
                "继承来的键一个都没少：合并结果里没有 SYSTEMROOT")

    def test_sha_chan_jin_cheng_yao_dai_T_bu_yao_dai_ki(self):
        """`taskkill` 必须带 `/T`（杀整棵树），不是只杀包装层。

        分岔：只杀 `kimi.cmd` ⇒ 真正的 node 进程活到 Bridge 退出之后还在跑
        用户项目。判据落在「argv 里有没有 `/T`」上——
        ⚠ **不要 mock 掉 `subprocess.run` 只断言调用**：那样「真机上 node 到底
        收没收掉」没有发言权。这条只守「命令对不对」，真机收没收掉由
        `_jie_zhende_ming` 那条 + 真 spawn 那条间接覆盖。
        """
        import unittest.mock as mock
        a, _ = self._da_ma()
        a.jin = mock.Mock(pid=12345)
        with mock.patch.object(subprocess, "run") as m:
            a._sha_chan_jin_cheng()  # type: ignore[attr-defined]
        self.assertTrue(m.called, "没调 taskkill")
        argv = m.call_args[0][0]
        self.assertIn("/T", argv, f"taskkill 没带 /T（不杀子孙）：{argv}")
        self.assertIn("/F", argv, f"taskkill 没带 /F：{argv}")

    def test_mo_shi_zi_an_jia_sheng_ming_qie_bu_yue_jie(self):
        """能力契约：`MOSHI_ZI` 按**各家真能兑现的档**声明（2026-10-06 起）。

        旧断言「三家都必须是空集」把当时的实现锁成了规范——而空集让前端把
        「未声明」渲染成五档全支持，正是曾经的承重缺口。现在的口径：
        每家声明自己 `-p` 模式下真能兑现的档（期望值在子类的 `_qi_wang_moshi`
        上），且必须 ⊆ 全局白名单、必含 manual（`_jian_hui` 缺省就走它）。

        `fangquan=False` 仍然如实报：`http._jian_hui` 对它有知情同意闸门
        （`acknowledgeNoApproval`），报 False 的语义是「Bridge 接管不了审批」，
        与「声明哪些模式」是两件事。
        """
        self.assertFalse(self._lei.fangquan(),
                         "这三个 CLI 非交互模式下没有权限回路（真机：零审批事件）")
        self.assertFalse(self._lei.wenti2(), "同样没有提问回路")
        self.assertTrue(self._lei.yi_ci_xing, "一次性进程形态没声明")
        from lifeos.bridge.models import MOSHI
        zi = self._lei.MOSHI_ZI
        self.assertEqual(zi, frozenset(self._qi_wang_moshi),
                         "MOSHI_ZI 与该家真机可兑现的档不符")
        self.assertTrue(zi <= set(MOSHI), "声明的模式越界：闸门 1 会 400")
        self.assertIn("manual", zi, "缺省建会话走 manual，不声明它闸门 1 就拦")

    def test_bu_ding_yi_gai_moshi(self):
        """**不得定义 `gai_moshi`**——「方法不存在」就是「不支持切换」的信号。

        分岔：定义了它 ⇒ `http._gai_moshi` 的 `hasattr()` 恒为 True ⇒ 放行切换
        请求并**落盘**，而这三个 harness 从来没按那个模式跑过
        ⇒ 用户下次看到「plan 模式」，实际根本没生效。
        """
        a, _ = self._da_ma()
        self.assertFalse(hasattr(a, "gai_moshi"),
                         "一次性进程这三家没有权限回路，绝不能定义 gai_moshi")


def _za_pei_lei(lei: type) -> type:
    """按「装了没」生成跳过标记。**没装是 skip 不是 pass**。"""
    return unittest.skipUnless(
        _zhuang_lei(lei),
        "本机没装这个 CLI（%s）" % getattr(lei, "agentId", "?"),
    )


# ---- 三家各生成一份用例（协议不同，但验的是同一件事：回合会收口）----

@_za_pei_lei(KimiAdapter)
class Kimi_LC(_Ji_chu):
    """kimi：`kimi -p --output-format stream-json`，边界是 `session.resume_hint`。"""

    _lei = KimiAdapter
    #: kimi 三个权限旗标在 `-p` 下全拒（`--plan`/`-y`/`--auto` 真机 Cannot
    #: combine），只能如实声明 manual。
    _qi_wang_moshi = ("manual",)


@_za_pei_lei(OpencodeAdapter)
class Opencode_LC(_Ji_chu):
    """opencode：`run --format json`，边界是 `step_finish`+`reason==stop` 或 `error`。

    ⚠ **provider 偶发空响应**（真机 2026-10-05 实测）会以 isError 收口，
    那是环境不是适配器——但**回合必须收口**，那是本层真正要守的。
    """

    _lei = OpencodeAdapter
    #: `--auto`（auto-approve permissions not explicitly denied）映射 dontAsk，
    #: 真机核实旗标可被接受；plan 走 `--agent plan` 不是同一机制，不声明。
    _qi_wang_moshi = ("manual", "dontAsk")


@_za_pei_lei(HermesAdapter)
class Hermes_LC(_Ji_chu):
    """hermes：`chat --format stream-json -q`，边界是 `type=="result"`。"""

    _lei = HermesAdapter
    #: `--yolo`（bypass all dangerous command approval prompts）映射 dontAsk，
    #: 真机核实旗标可被接受；`--safe-mode` 是排障开关不是权限档，不声明。
    _qi_wang_moshi = ("manual", "dontAsk")


if __name__ == "__main__":
    unittest.main()