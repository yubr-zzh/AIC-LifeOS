"""任务 1 传输层的承重测试。

判据必须落在「两种实现真的会分岔的那个量」上。所以这里不测
「方法返回了 None」这种两种实现都成立的东西，只测会分岔的：

1. pid 真拿得到（基类 vs `claude_code` 读 SDK 私有路径）
2. `fasong()` 真会因回合边界返回（判错 ⇒ 永久挂起，最常见的假绿）
3. 回合 Future 的 key（我用指令原文当 key 时连发两条就挂死——真踩过的坑）
4. stderr 真被读走（不读 ⇒ 子进程卡在写 stderr 上，症状是「不出字」）
5. `gai_moshi` 的缺席就是信号（`http._gai_moshi` 用 `hasattr` 判）

**不 sleep 固定时长**：本项目实测 `sleep(2.0)` 在 Windows 上必然 flake
（`tests/gong_ju.py` 的文档说明了为什么）。等状态一律用 `asyncio.wait_for`。
"""

from __future__ import annotations

import asyncio
import json
import sys
import unittest

from lifeos.bridge.adapters.chuan_shu import ZiChengAdapter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 假 CLI：真双向。收一行 → 回一行 echo → 回一行 result。
# **不能用 `cmd /c more`**：more 需要 tty，stdin 写进去不产生 stdout，
# 真机实测 `fasong()` 直接挂死到超时（这就是 L-C 要抓的那类形态）。
XUAN_LING = """
import sys, json
for wen in sys.stdin:
    wen = wen.strip()
    if not wen:
        continue
    if wen == 'boom':
        sys.stderr.write('can shu cuo wu: mo shi xuan xiang\\n')
        sys.stderr.flush()
        sys.exit(2)
    print(json.dumps({'kind': 'echo', 'text': wen}), flush=True)
    print(json.dumps({'kind': 'result', 'resultText': 'done:' + wen}), flush=True)
"""

# 任何用例挂死时的兜底。测试挂死 = CI 挂死，比失败更糟。
SUO_DING = 20.0


class JiaShi(ZiChengAdapter):
    """走上面那个假 CLI 的适配器。

    **故意不定义 `gai_moshi`**——它不支持权限模式切换，而
    `http._gai_moshi` 用 `hasattr()` 判，所以「方法不存在」必须是可用信号。
    """

    agentId = "jia"
    label = "假 CLI"
    ZHI_LING = [sys.executable, "-u", "-c", XUAN_LING]
    yi_ci_xing = False

    def fan_yi(self, a1: str) -> None:
        zhao = json.loads(a1)
        if zhao.get("kind") == "echo":
            self._fa("text", {"text": zhao["text"]})
        else:
            self._fa("result", {"resultText": zhao["resultText"], "isError": False})
            self._jie_shu_kao_ben(zhao)

    def jie_shou(self, a1: dict) -> dict | None:
        return a1 if a1.get("kind") == "result" else None

    async def _fa_chu_ming_ling(self, a1: str) -> None:
        self.jin.stdin.write((a1 + "\n").encode())
        await self.jin.stdin.drain()


class ChuanShuTests(unittest.TestCase):
    def _kaishi(self, a: JiaShi) -> JiaShi:
        hui: list[tuple[str, dict]] = []
        a.hui = lambda k, p: hui.append((k, p))
        a.shuju = hui  # type: ignore[attr-defined]
        return a

    # ---- L1 结构 ----
    def test_gai_moshi_que_xi_ji_wei_xin_hao(self):
        """**方法不存在**就是「这个 harness 不能切权限模式」的信号。

        `http._gai_moshi` 是这么判的：`hasattr(ad, "gai_moshi")` 为假就 409。
        基类如果定义了它，这个断言恒为真——三个没有权限回路的 harness
        会收到一个无法兑现的切换请求，而 `_gai_moshi` 会把新模式**落盘**，
        用户下次看到「plan 模式」，实际那个 harness 从来没按 plan 跑过。
        """
        self.assertFalse(hasattr(JiaShi(), "gai_moshi"),
                         "基类定义了 gai_moshi ⇒ hasattr 恒为 True ⇒ "
                         "http 会放行无法兑现的切换请求")

    def test_shi_you_gai_moshi_de_ke_yi_chu_lie(self):
        """反过来也钉住：真能切的必须自己有，否则 http 会误 409。"""

        class KeYi(ZiChengAdapter):
            async def gai_moshi(self, a1: str) -> None:
                self.moshi = a1

        self.assertTrue(hasattr(KeYi(), "gai_moshi"))

    def test_qi_zhi_ling_kong_de_yao_ming_que_fan_dui(self):
        async def zhen():
            with self.assertRaises(RuntimeError) as e:
                await ZiChengAdapter().kaishi({"cwd": "."})
            self.assertIn("ZHI_LING", str(e.exception))

        asyncio.run(zhen())

    # ---- pid ----
    def test_pid_neng_qu_dao(self):
        """pid 必须真拿得到——Bridge 崩了靠 `http.lu_pid` 回收孤儿进程。

        这是基类比 `claude_code.qu_pid()` 强的地方：后者读 SDK 的私有路径
        （`kehu._transport._process.pid`），读不到就返回 None。
        """

        async def zhen():
            a = self._kaishi(JiaShi())
            await a.kaishi({"cwd": "."})
            try:
                pid = a.qu_pid()
                self.assertIsInstance(pid, int)
                self.assertGreater(pid, 0)
            finally:
                await a.guan_bi()

        asyncio.run(zhen())

    def test_guan_bi_hou_pid_bian_none(self):
        async def zhen():
            a = self._kaishi(JiaShi())
            await a.kaishi({"cwd": "."})
            await a.guan_bi()
            self.assertIsNone(a.jin)
            self.assertIsNone(a.qu_pid())

        asyncio.run(zhen())

    # ---- 回合边界（最承重）----
    def test_fasong_hui_wei_jie_shou_de_sheng_fan_yi(self):
        """**回合边界判对，`fasong()` 才会返回。**

        判错的症状：事件全翻译对了、单测全绿、真机上挂死到超时。
        这里用真子进程 + `wait_for` 兜底，判据就是「fasong 真的返回了」。
        """

        async def zhen():
            a = self._kaishi(JiaShi())
            await a.kaishi({"cwd": "."})
            try:
                await asyncio.wait_for(a.fasong("ni hao"), SUO_DING)
            finally:
                await a.guan_bi()
            self.assertIn(("text", {"text": "ni hao"}), a.shuju)
            self.assertTrue(
                any(k == "result" and p.get("resultText") == "done:ni hao"
                    for k, p in a.shuju),
                f"没收到回合结束事件：{a.shuju}")

        asyncio.run(zhen())

    def test_lian_fa_tong_yi_tiao_zhi_ling_bu_hang_guai(self):
        """同一条指令连发三次都要返回，且不留悬空的回合 Future。

        这条用例守的是「连发多条都干净」（回合 Future 字典回到空）。
        **它不守「key 用原文会挂死」**——变异验证实测那不会发生：
        `_jie_shu_kao_ben` 遍历全部待决 Future，而 `HuiHua.paichu` 是串行的，
        前一回合的 Future 早就在 `finally` 里 pop 干净了。
        写测试时我以为会挂死，是误判；这里保留断言，但按实测结论写清楚。
        """

        async def zhen():
            a = self._kaishi(JiaShi())
            await a.kaishi({"cwd": "."})
            try:
                for _ in range(3):
                    await asyncio.wait_for(a.fasong("zai pao yi bian"), SUO_DING)
                    self.assertEqual(a._jie_shu, {},
                                     f"回合 Future 有残留：{list(a._jie_shu)}")
            finally:
                await a.guan_bi()

        asyncio.run(zhen())

    def test_fasong_zai_guan_bi_zhi_hou_yao_ming_que_fan_dui(self):
        async def zhen():
            a = self._kaishi(JiaShi())
            a.guan_le = True
            with self.assertRaises(RuntimeError) as e:
                await a.fasong("ni hao")
            self.assertIn("会话已关闭", str(e.exception))

        asyncio.run(zhen())

    def test_guan_bi_hui_qing_gua_zhe_de_fasong(self):
        """关连接时挂着的 `fasong()` 要被唤醒——否则永远占着一个 task。"""

        async def zhen():
            a = self._kaishi(JiaShi())
            await a.kaishi({"cwd": "."})
            ren = asyncio.create_task(a.fasong("hui yong bu hui lai"))
            # 让 fasong 真的挂上去（它先 await _fa_chu_ming_ling 才登记 Future）
            await asyncio.sleep(0.3)
            await a.guan_bi()
            await asyncio.wait_for(ren, SUO_DING)

        asyncio.run(zhen())

    def test_jie_shu_kao_ben_shou_lian_chuan_wu_hai(self):
        """回合边界撞两次不能抛 InvalidStateError。

        codex 的 `turn/completed` 后面常跟一个 `error` 帧，对同一个 Future
        set_result 两次就是 InvalidStateError，会把整轮编排炸掉。
        """

        async def zhen():
            a = self._kaishi(JiaShi())
            fu: asyncio.Future = asyncio.get_event_loop().create_future()
            a._jie_shu[1] = fu
            a._jie_shu_kao_ben({"a": 1})
            a._jie_shu_kao_ben({"a": 2})      # 不抛
            self.assertTrue(fu.done())

        asyncio.run(zhen())

    # ---- stderr ----
    def test_cuo_wei_bing_bie_kan_zhua_bu_liu_diao(self):
        """**stderr 必须被读走**，否则管道写满后子进程卡在写 stderr 上。

        症状不是报错，是「Agent 一直不出字」——最难查的一种挂死。
        """

        async def zhen():
            a = self._kaishi(JiaShi())
            await a.kaishi({"cwd": "."})
            try:
                # boom 让假 CLI 写 stderr 后退出；fasong 因进程退出被唤醒。
                await asyncio.wait_for(a.fasong("boom"), SUO_DING)
                for _ in range(200):
                    if a.cuo_wei:
                        break
                    await asyncio.sleep(0.05)
                self.assertIn("can shu cuo wu", a.cuo_wei)
            finally:
                await a.guan_bi()

        asyncio.run(zhen())

    # ---- tanjian ----
    def test_tanjian_neng_zhao_dao_bing_qi_ke_yi_liu_cheng_shu_ju(self):
        async def zhen():
            xian = await JiaShi().tanjian()
            self.assertIs(xian["available"], True)
            self.assertIsNone(xian["error"])
            self.assertTrue(xian["version"])

        asyncio.run(zhen())

    def test_tanjian_mei_zhuang_bu_neng_zhe_ma_zhong(self):
        """**绝不能抛异常**——探测失败本身就是要报告给用户的数据。"""

        class MeiZhuang(ZiChengAdapter):
            ZHI_LING = ["zhen-bu-cun-zai-de-ming-ling-xyz"]

        async def zhen():
            xian = await MeiZhuang().tanjian()
            self.assertIs(xian["available"], False)
            self.assertIn("找不到", xian["error"])

        asyncio.run(zhen())

    def test_tanjian_mei_pei_zhi_ming_ling_bu_neng_zhe_ma_zhong(self):
        async def zhen():
            xian = await ZiChengAdapter().tanjian()
            self.assertIs(xian["available"], False)
            self.assertTrue(xian["error"])

        asyncio.run(zhen())

    # ---- 环境变量 ----
    def test_huan_jing_zeng_liang_bu_mo_di_bie_de(self):
        """**增量而非整份替换**：只给 CLAUDE_CONFIG_DIR 不该把 SYSTEMROOT/PATH 抹掉。

        ⚠ **这条断言 2026-10-05 改过方向。** 原断言是
        `assertEqual(_huan_jing({...}), {"CLAUDE_CONFIG_DIR": ...})`
        —— 也就是「只保留增量」——**那正是缺陷本身**：
        `create_subprocess_exec(env=…)` 是**整体替换**，不是覆盖单键，
        传进去的残缺字典会让子进程看不到 `PATH`/`HOME`/`USERPROFILE`/`APPDATA`。

        真机症状：codex 一起回合就一路 `Reconnecting... waiting for network`，
        回合永不收口。v2.0 没暴露是因为 claude-code 走 Python SDK，不 spawn
        子进程，`_huan_jing` 在那条路径上根本没被调用。

        ⇒ 判据改成**「继承来的键一个都没少，且增量确实覆盖到位」**——
        落在「两种实现读出来不一样」的量上（原判据两种实现都成立）。
        """
        a = JiaShi()
        import os as _os
        xian = a._huan_jing({"env": {"CLAUDE_CONFIG_DIR": "/tmp/x"}})
        self.assertIsNotNone(xian)
        # 继承来的环境一个都不能少。**键名要按 os.environ 里实际的大小写写**——
        # Windows 环境变量名不敏感，但 `os.environ` 这个 dict 是大小写敏感的，
        # 查一个不存在的 `SystemRoot` 恒为 None，断言会假红（第一版就踩了）。
        for k in ("PATH", "SYSTEMROOT", "APPDATA", "USERPROFILE", "TEMP"):
            if k in _os.environ:
                self.assertIn(k, xian, "丢了 %s ⇒ 子进程找不到自己的配置与凭据" % k)
        self.assertEqual(xian["CLAUDE_CONFIG_DIR"], "/tmp/x")
        # 空增量仍然是「完全继承」——传 {} 在某些实现里等于清空环境
        self.assertIsNone(a._huan_jing({}))
        self.assertIsNone(a._huan_jing({"env": {}}))

    def test_chuang_kong_men_you_zhi_ding_zi_chuang_process_group(self):
        """Windows 上必须新进程组。

        默认情况下 `kill()` 只杀 `cmd /c more` 这一层，CLI 自己再起的那些
        （codex 的沙箱、gemini 的工具进程）会变孤儿，Bridge 崩溃后继续跑用户命令。
        """
        import sys as _s
        men = ZiChengAdapter._chuang_kong()
        if _s.platform == "win32":
            import subprocess as sp
            self.assertEqual(men.get("creationflags"), sp.CREATE_NEW_PROCESS_GROUP)
        else:
            self.assertEqual(men, {})

    def test_guan_bi_de_shijian_yao_zai_http_de_yu_e_bian_nei(self):
        """**`guan_bi` 必须在 `http._guan_yong` 的 5 秒预算内返回。**

        变异验证第 8 条挖出来的覆盖缺口：`guan_bi` 里 kill / wait / 关管道
        三步都带超时（5+5+2 秒），加起来超过 5 秒。而 http 侧是
        `duo_cuo(a1, ad.guan_bi, 5.0)` + `except: pass`——**超了不会报错，
        只会静默地让子进程留在后台**。所以这条断言是唯一能守住那个预算的东西。
        """
        async def zhen():
            a = self._kaishi(JiaShi())
            await a.kaishi({"cwd": "."})
            await asyncio.wait_for(a.guan_bi(), 5.0)

        asyncio.run(zhen())


if __name__ == "__main__":
    unittest.main()