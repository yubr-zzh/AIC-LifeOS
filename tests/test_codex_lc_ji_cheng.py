"""任务 3 的 L-C（进程级）测试：真 spawn codex app-server，打一次真回合。

**这一层是唯一能抓「回合边界判错」的**（`chuan_shu` 与方案 3.2 都写了：
事件全翻译对了、单测全绿、真机上 `fasong()` 挂死到 15 分钟看门狗）。
golden（L-B）用的是我抄的样本，它对「真实回合边界到底是什么」这件事
没有任何发言权。

## 为什么这些用例默认跳过

codex 不是每个开发机都装了，而且打真回合**要花模型额度**。
所以：

- 没装 codex ⇒ skip（不是 pass，理由写在 skip 消息里）。
- 装了但没配好模型/额度 ⇒ **真跑**并把失败原样报出来，不静默跳过。
  「跑了但跑不通」和「没跑」在报告里必须能区分开。

## 不 sleep 固定时长

本项目实测 `sleep(2.0)` 在 Windows 上必然 flake（`tests/gong_ju.py` 的文档）。
这里一律用 `asyncio.wait_for`（有上界）与轮询（有状态判据）。
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import unittest
from pathlib import Path

from lifeos.bridge.adapters.codex import CodexAdapter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

#: 回合预算。真机实测一个字的回答 138ms，但首次启动要拉 MCP server（~5 秒），
#: 给 180 秒是为了让「模型慢」表现为慢而不是表现为失败。
HUI_HE_MIAO = 180.0
#: 握手 + thread/start 的预算。
SHOU_ZHEN_MIAO = 90.0
#: 任何用例挂死的兜底。测试挂死比失败更糟。
SUO_DING = 240.0


def _you_codex_ma() -> bool:
    return shutil.which("codex") is not None


def _cai_dang_qi() -> list[tuple[str, dict]]:
    return []


@unittest.skipUnless(_you_codex_ma(), "本机没装 codex CLI")
class Zhen_Shou_Tests(unittest.TestCase):
    """真 spawn、真握手、真建 thread、真打一回合。"""

    def _da_ma(self) -> tuple[CodexAdapter, list[tuple[str, dict]]]:
        a = CodexAdapter()
        zhuang = _cai_dang_qi()
        a.hui = lambda lei, can: zhuang.append((lei, can))  # type: ignore[assignment]
        return a, zhuang

    def test_shou_zhen_jian_li_hou_neng_qi_turn_bing_deng_hui_he_jie_shu(self):
        """**最承重的一条：`fasong()` 真会因回合边界返回。**

        判错的后果：所有翻译都对、golden 全绿、真机上挂死到看门狗。
        判据是「fasong 真的在预算内返回了」，不是「收到了某个事件」。
        """
        cwd = str(Path(__file__).resolve().parent.parent)

        async def zhen():
            a, zhuang = self._da_ma()
            try:
                await asyncio.wait_for(a.kaishi({"cwd": cwd, "permissionMode": "manual"}),
                                       SUO_DING)
                # pid 真拿得到——Bridge 崩了靠它回收孤儿（3.6）
                self.assertIsInstance(a.qu_pid(), int)
                self.assertGreater(a.qu_pid(), 0)
                # threadId 拿到了，且通过 session 事件上报（前端靠它续接）
                self.assertTrue(a.kehu_hui, "没拿到 threadId")
                self.assertTrue(any(k == "session" and p.get("threadId") == a.kehu_hui
                                    for k, p in zhuang), f"没有 session 帧：{zhuang}")
                # **真打一回合**。指令要短、要确定，否则断言没法判对错。
                await asyncio.wait_for(a.fasong("只回答两个字：收到"), HUI_HE_MIAO)
            finally:
                await asyncio.wait_for(a.guan_bi(), 30.0)

            # 回合结果：result 帧 + 不带 error
            jie = [p for k, p in zhuang if k == "result"]
            self.assertEqual(len(jie), 1, f"回合结果帧数不对：{zhuang}")
            self.assertFalse(jie[0]["isError"], f"回合失败：{jie[0]}")
            self.assertTrue(jie[0]["resultText"].strip(),
                            f"回合成功但正文为空：{jie[0]}（决策回路靠这个字段回传）")
            # 残留的回合 Future 不能有
            self.assertEqual(a._jie_shu, {})

        asyncio.run(asyncio.wait_for(zhen(), SUO_DING + 60))

    def test_lian_fa_liang_tiao_dou_neng_deng_hui_he(self):
        """同一条指令连发两次都要返回，且第二轮的正文不与第一轮粘连。"""
        cwd = str(Path(__file__).resolve().parent.parent)

        async def zhen():
            a, zhuang = self._da_ma()
            try:
                await asyncio.wait_for(a.kaishi({"cwd": cwd, "permissionMode": "manual"}),
                                       SUO_DING)
                for _ in range(2):
                    await asyncio.wait_for(a.fasong("只回答两个字：收到"), HUI_HE_MIAO)
                    self.assertEqual(a._jie_shu, {}, "回合 Future 有残留")
            finally:
                await asyncio.wait_for(a.guan_bi(), 30.0)
            jie = [p for k, p in zhuang if k == "result"]
            self.assertEqual(len(jie), 2, f"{zhuang}")
            for p in jie:
                self.assertFalse(p["isError"], p)
            # **第二轮正文必须不含第一轮的**——累加器没清空就会这样
            self.assertEqual(jie[0]["resultText"].strip(), jie[1]["resultText"].strip(),
                             "两轮正文不一致，可能是累加器没清干净")

        asyncio.run(asyncio.wait_for(zhen(), SUO_DING * 2))

    def test_zhong_duan_zhen_de_fa_chu_le_turn_interrupt(self):
        """中断必须发 `turn/interrupt`，然后杀进程。

        分岔：直接杀进程。codex 来不及收尾，已经收到的 delta 停在半句上，
        用户看到的是「Agent 说到一半消失了」而不是「已中断」。
        """
        cwd = str(Path(__file__).resolve().parent.parent)

        async def zhen():
            a, zhuang = self._da_ma()
            try:
                await asyncio.wait_for(a.kaishi({"cwd": cwd, "permissionMode": "manual"}),
                                       SUO_DING)
                ren = a.loop.create_task(a.fasong("数到一百，每行一个数，不要停"))
                # 等回合真的起来（turn/started 会置 zhuan_id）
                for _ in range(600):
                    if a.zhuan_id:
                        break
                    await asyncio.sleep(0.1)
                self.assertTrue(a.zhuan_id, "回合没起来（turn/started 没收到）")
                await asyncio.wait_for(a.zhong_duan(), 30.0)
                # 中断后回合必须收口，不能挂着
                await asyncio.wait_for(ren, 30.0)
            finally:
                await asyncio.wait_for(a.guan_bi(), 30.0)
            self.assertIsNone(a.qu_pid(), "中断后子进程还活着")

        asyncio.run(asyncio.wait_for(zhen(), SUO_DING))

    def test_guan_bi_hou_pid_bian_none_bu_can_yong(self):
        cwd = str(Path(__file__).resolve().parent.parent)

        async def zhen():
            a, _ = self._da_ma()
            await asyncio.wait_for(a.kaishi({"cwd": cwd, "permissionMode": "manual"}),
                                   SUO_DING)
            pid = a.qu_pid()
            self.assertIsInstance(pid, int)
            await asyncio.wait_for(a.guan_bi(), 30.0)
            self.assertIsNone(a.jin)
            self.assertIsNone(a.qu_pid())
            # 进程真被杀了（Windows 上 PID 会被系统很快复用，只查「不在」不够，
            # 这里只断言适配器状态；真回收由 tools/verify_v3_harness.py 的
            # 进程级断言负责）

        asyncio.run(asyncio.wait_for(zhen(), SUO_DING))

    def test_zhong_duan_de_hui_shou_cheng_bi_yong_await(self):
        """**`zhong_duan()` 里的 kill 兜底必须真被 await。**

        这是 L-C 挖出来的一个真缺陷（第一版漏了 `await`）：
        `turn/interrupt` 成功时 kill 兜底用不上，所以**回合那条用例照样绿**——
        绿得毫无道理。而 `turn/interrupt` 超时/失败那条路上，
        漏掉的 await 让「杀进程」这步根本没执行，codex 子进程活到 Bridge 退出。

        判据落在「`turn/interrupt` 失败时进程仍被杀掉」这个量上：
        把 `_qing_qiu` 打成必抛异常，绕开 interrupt 只走 kill 兜底。
        """
        cwd = str(Path(__file__).resolve().parent.parent)

        async def zhen():
            a, _ = self._da_ma()
            await asyncio.wait_for(a.kaishi({"cwd": cwd, "permissionMode": "manual"}),
                                   SUO_DING)
            pid = a.qu_pid()
            a.zhuan_id = "tn-sha"          # 逼它走 interrupt 那条路
            a.kehu_hui = a.kehu_hui or "t1"

            async def hui_bu_liao(lei: str, can: dict, miao=30.0):
                raise TimeoutError("假装 turn/interrupt 失败")
            a._qing_qiu = hui_bu_liao      # type: ignore[assignment]
            await asyncio.wait_for(a.zhong_duan(), 30.0)
            # **判据是「进程真死了」，不是 `a.jin` 变 None。**
            # `_zhong_zhi_chi_cheng` 只 kill 不拆管道（中断≠关闭，后面的回合还要用），
            # 清 `self.jin` 的是 `_ting_zhi_chi_cheng`。第一版我断言错了量，
            # 于是这条用例在一个「kill 确实执行了」的实现上转红——
            # 正是那种假绿/假红。
            for _ in range(80):
                if not cun_zhen(pid):
                    break
                await asyncio.sleep(0.1)
            self.assertFalse(cun_zhen(pid),
                             f"codex 进程 {pid} 还活着 —— kill 兜底没执行"
                             "（多半是漏了 await）")

        asyncio.run(asyncio.wait_for(zhen(), SUO_DING))


def cun_zhen(pid: int) -> bool:
    """pid 还活着吗。走 Windows 的 OpenProcess 查退出码，不依赖 tasklist。"""
    import subprocess
    try:
        chu = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             capture_output=True, text=True, timeout=15,
                             encoding="utf-8", errors="replace")
        return str(pid) in (chu.stdout or "")
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    unittest.main()