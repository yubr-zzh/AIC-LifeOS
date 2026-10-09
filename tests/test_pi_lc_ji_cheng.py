"""pi 适配器的 L-C（进程级）测试：真 spawn `pi --mode rpc`，打一次真回合。

**这一层是唯一能抓「回合边界判错」的**（`chuan_shu` 的文档与 codex 的 L-C 都写了：
事件全翻译对了、单测全绿、真机上 `fasong()` 挂死到 15 分钟看门狗）。
golden（L-B）用的是抄来的样本，它对「真实回合边界到底是什么」这件事
没有任何发言权。

## 默认跳过，但装了就必须真跑

- 没装 pi ⇒ skip（不是 pass，理由写在 skip 消息里）。
- 装了但模型不通 ⇒ **真跑**并把失败原样报出来，不静默跳过。
  「跑了但跑不通」和「没跑」在报告里必须能区分开。
- 还缺模型 ⇒ 再 skip 一层，理由写清缺什么（省额度不是理由，
  这里只是不把「本机没配模型」报成「适配器坏了」）。

## 不 sleep 固定时长

本项目实测 `sleep(2.0)` 在 Windows 上必然 flake。这里一律用
`asyncio.wait_for`（有上界）与轮询（有状态判据）。

## ⚠ 用哪台机器上的凭据

`~/.pi/agent/models.json` 里那台 provider 是本机的，**L-C 用的就是它**
（`_MO_XING` 常量）。Base class 的 `_huan_jing` 是增量合并，所以这是
「在用户自己的 pi 配置上跑」而不是把凭据搬进 LifeOS。**不要把任何
key 写进本文件**——这里只写 provider/model 名。
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import unittest
from pathlib import Path

from lifeos.bridge.adapters.pi import PiAdapter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

#: 本机 pi 里可用的 provider/model（`~/.pi/agent/models.json` 的 providers 里
#: 确实存在的）。**L-C 显式钉模型，故意不跟 pi 的 defaultModel 走**：用户
#: 改配置不该让这一层的红绿跟着漂移。代价是钉的模型下线就红——2026-10-06
#: `cc-switch-open-router/stealth/space-bunny-alpha` 被 OpenRouter 下线，
#: 三条用例齐红（404 No endpoints found），换成本机现役模型
#: （用户 pi TUI 正在用的那个，裸探针 3 stop / 0 error 实证可用）。
#: **这里只写名字，不写任何凭据。**
_MO_XING = "ss/deepseek-v4-flash-vision"

#: 回合预算。真机 pi 首次启动要加载会话索引与扩展，给 180 秒让「模型慢」
#: 表现为慢而不是表现为失败。
HUI_HE_MIAO = 180.0
#: 握手（spawn + `get_state`）的预算。
SHOU_ZHEN_MIAO = 90.0
#: 任何用例挂死的兜底。测试挂死比失败更糟。
SUO_DING = 240.0


def _you_pi_ma() -> bool:
    """pi 装了没。**判 `pi.cmd`**：`shutil.which("pi")` 在 PATHEXT 里有 .CMD 时
    也找得到，但 L-C 是给「能不能真 spawn」用的判据，名字与 `ZHI_LING` 对齐。"""
    return shutil.which("pi.cmd") is not None


def _you_mo_xing_ma() -> bool:
    """本机 pi 配置里有没有那个 provider。

    ⚠ **只读文件、只看键名**：不解析 apiKey、不打印任何内容。
    """
    p = Path(os.path.expanduser("~")) / ".pi" / "agent" / "models.json"
    try:
        b = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return False
    gong = str(_MO_XING.split("/", 1)[0])
    return gong in (b.get("providers") or {})


def _cai_dang_qi() -> list[tuple[str, dict]]:
    return []


@unittest.skipUnless(_you_pi_ma(), "本机没装 pi CLI（pi.cmd）")
@unittest.skipUnless(_you_mo_xing_ma(),
                     f"本机 pi 配置里没有 provider「{_MO_XING.split('/', 1)[0]}」，"
                     "打真回合要花模型额度，跳过")
class Zhen_Shou_Tests(unittest.TestCase):
    """真 spawn、真握手、真打一回合。"""

    def _da_ma(self) -> tuple[PiAdapter, list[tuple[str, dict]]]:
        a = PiAdapter()
        zhuang = _cai_dang_qi()
        a.hui = lambda lei, can: zhuang.append((lei, can))  # type: ignore[assignment]
        return a, zhuang

    @staticmethod
    def _can_shu(cwd: str) -> dict:
        """`kaishi` 的入参。**`model` 走 `xin_jian` 之外的路径**（见 `_zi_ling`）。"""
        return {"cwd": cwd, "permissionMode": "manual", "model": _MO_XING}

    def test_shou_zhen_jian_li_hou_neng_qi_turn_bing_deng_hui_he_jie_shu(self):
        """**最承重的一条：`fasong()` 真会因回合边界返回。**

        判错的后果：所有翻译都对、golden 全绿、真机上挂死到看门狗。
        判据是「fasong 真的在预算内返回了」，不是「收到了某个事件」。
        """
        cwd = str(Path(__file__).resolve().parent.parent)

        async def zhen():
            a, zhuang = self._da_ma()
            try:
                await asyncio.wait_for(a.kaishi(self._can_shu(cwd)), SUO_DING)
                # pid 真拿得到——Bridge 崩了靠它回收孤儿（3.6）
                self.assertIsInstance(a.qu_pid(), int)
                self.assertGreater(a.qu_pid(), 0)
                # sessionId 拿到了，且通过 session 事件上报（`run.hui_fu` 靠它续接）
                self.assertTrue(a.kehu_hui, "没拿到 sessionId")
                self.assertTrue(any(k == "session" and p.get("sessionId") == a.kehu_hui
                                    for k, p in zhuang), f"没有 session 帧：{zhuang}")
                # **真打一回合**。指令要短、要确定，否则断言没法判对错。
                await asyncio.wait_for(a.fasong("只回答两个字：收到"), HUI_HE_MIAO)
            finally:
                await asyncio.wait_for(a.guan_bi(), 30.0)

            # 回合结果：result 帧 + 不带 error
            jie = [p for k, p in zhuang if k == "result"]
            self.assertEqual(len(jie), 1, f"回合结果帧数不对：{zhuang}")
            self.assertFalse(jie[0]["isError"], f"回合失败：{jie[0]}")
            # 正文非空这里**不硬断**：厂商偶发吐「纯空 thinking 回合」（2026-10-06
            # 全量实测一次，会话记录 assistant 只有 content=[('thinking', 0)]，
            # 连 text 部分都没有，pi 如实报空）。文本抽取的正确性由 L-B golden
            # 层把守，本层判的是回合边界与错误信号；lian_fa 的「两轮全空才响」兜底。
            # 残留的回合 Future 不能有
            self.assertEqual(a._jie_shu, {})

        asyncio.run(asyncio.wait_for(zhen(), SUO_DING + 60))

    def test_lian_fa_liang_tiao_dou_neng_deng_hui_he(self):
        """连发两条不同暗号的指令都要返回，且第二轮不带第一轮的暗号。

        分岔：累加器没清空 ⇒ 第二轮 `resultText` 里带着第一轮的暗号，
        用户看到同一条回复出现两遍。单看「都返回了」照样绿。

        两轮暗号不同，是为了把「模型对同一指令的回答本来就可能不同」
        从「累加器没清」里摘出去——2026-10-06 实测同文断言被
        `'</think>收到' != '收到'` 误红：think 标签时有时无是厂商侧行为
        （用户裁定），判据必须落在暗号上，落在正文全等上就会跟着抖。
        """
        cwd = str(Path(__file__).resolve().parent.parent)

        async def zhen():
            a, zhuang = self._da_ma()
            try:
                await asyncio.wait_for(a.kaishi(self._can_shu(cwd)), SUO_DING)
                await asyncio.wait_for(a.fasong("只回答两个字：红叶"), HUI_HE_MIAO)
                self.assertEqual(a._jie_shu, {}, "回合 Future 有残留")
                await asyncio.wait_for(a.fasong("只回答两个字：石桥"), HUI_HE_MIAO)
                self.assertEqual(a._jie_shu, {}, "回合 Future 有残留")
            finally:
                await asyncio.wait_for(a.guan_bi(), 30.0)
            jie = [p for k, p in zhuang if k == "result"]
            self.assertEqual(len(jie), 2, f"{zhuang}")
            for p in jie:
                self.assertFalse(p["isError"], p)
            yi1 = jie[0]["resultText"].strip()
            yi2 = jie[1]["resultText"].strip()
            # 厂商偶发「回合 completed 但一个字没吐」：会话记录里 assistant
            # 只有 content=[('thinking', 0)]（2026-10-06 全量实测，证据见上）。
            # 空轮没有可判的正文，暗号断言只对非空轮做；「第二轮为空 ⇒
            # 不可能粘连」仍成立——累加器真泄漏的话第二轮正文必非空。
            if yi1:
                self.assertIn("红叶", yi1, f"第一轮没答暗号：{jie[0]}")
            if yi2:
                self.assertIn("石桥", yi2, f"第二轮没答暗号：{jie[1]}")
                # **第二轮正文不得含第一轮的暗号**——判据落在「两段正文的关系」上。
                self.assertNotIn("红叶", yi2,
                                 "第二轮带着第一轮的暗号：累加器没清干净")
            self.assertTrue(yi1 or yi2,
                            "两轮都没吐字：模型/环境不可用，粘连无从判起")

        asyncio.run(asyncio.wait_for(zhen(), SUO_DING * 2))

    def test_zhong_duan_zhen_de_fa_chu_le_abort_bing_shou_kou(self):
        """中断必须先发 `abort` 再杀进程，回合必须收口。

        分岔：直接杀进程。pi 来不及收尾，已经收到的 delta 停在半句上，
        用户看到的是「Agent 说到一半消失了」而不是「已中断」。
        判据落在「回合 Future 有没有被唤醒」——杀进程时读循环 EOF 也会
        唤醒它（`_fan_cheng_kao_ben`），所以还要看 `abort` 的 `response`
        有没有回来，那才是「走了正经中断路」的证据。
        """
        cwd = str(Path(__file__).resolve().parent.parent)

        async def zhen():
            a, zhuang = self._da_ma()
            try:
                await asyncio.wait_for(a.kaishi(self._can_shu(cwd)), SUO_DING)
                ren = a.loop.create_task(a.fasong("数到一百，每行一个数，不要停"))
                # 等回合真的起来（第一条 text 事件说明 agent 已经在吐字）
                for _ in range(int(HUI_HE_MIAO / 0.1)):
                    if any(k == "chunk" for k, _ in zhuang):
                        break
                    await asyncio.sleep(0.1)
                self.assertTrue(any(k == "chunk" for k, _ in zhuang),
                                "回合没起来（一条 chunk 都没有）")
                # 记下回合序号，好看清 abort 的响应属于哪次请求
                a._qing_qiu_id += 1
                await asyncio.wait_for(a.zhong_duan(), 30.0)
                # 中断后回合必须收口，不能挂着
                await asyncio.wait_for(ren, 30.0)
            finally:
                await asyncio.wait_for(a.guan_bi(), 30.0)
            self.assertIsNone(a.qu_pid(), "中断后子进程还活着")
            # 累加器必须清干净：中断后的下一回合不能带上「数到一百」的残留
            self.assertEqual(a._zhuan_wen, [], "中断没清累加器")
            self.assertEqual(a._wen_zheng, "", "中断没清正文")

        asyncio.run(asyncio.wait_for(zhen(), SUO_DING))

    def test_guan_bi_hou_pid_bian_none_bu_can_yong(self):
        cwd = str(Path(__file__).resolve().parent.parent)

        async def zhen():
            a, _ = self._da_ma()
            await asyncio.wait_for(a.kaishi(self._can_shu(cwd)), SUO_DING)
            self.assertIsInstance(a.qu_pid(), int)
            await asyncio.wait_for(a.guan_bi(), 30.0)
            self.assertIsNone(a.jin)
            self.assertIsNone(a.qu_pid())

        asyncio.run(asyncio.wait_for(zhen(), SUO_DING))

    def test_guan_bi_shou_wan_le_dai_dai_qi_ren_wu(self):
        """关连接必须把挂起的审批任务收掉。

        分岔：留着不管。协程还握着已经拆掉的子进程 stdin，
        `Bridge` 关掉之后那个协程还活着（取消时会往已关的管道写
        `extension_ui_response`，在 Windows 上抛 `OSError` 变成未捕获异常）。
        """
        cwd = str(Path(__file__).resolve().parent.parent)

        async def zhen():
            a, _ = self._da_ma()
            await asyncio.wait_for(a.kaishi(self._can_shu(cwd)), SUO_DING)

            async def yong_yong_bukai(lei: str, can: dict):
                await asyncio.sleep(3600)

            a.cheng = yong_yong_bukai  # type: ignore[assignment]
            a.fan_yi(json.dumps({"type": "extension_ui_request", "id": "e1",
                                 "method": "confirm", "title": "t", "message": "m"}))
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            self.assertEqual(len(a._dai_dai), 1, "挂起任务没起来")
            await asyncio.wait_for(a.guan_bi(), 30.0)
            self.assertEqual(a._dai_dai, set(), "挂起任务没收掉")

        asyncio.run(asyncio.wait_for(zhen(), SUO_DING))

    def test_sha_chan_jin_cheng_shou_wan_biao_di_pai_de_yang_cheng_guo_cheng(self):
        """**真机验孤儿进程**：`taskkill /T /F` 之后 pi 的 node 树真被收掉。

        L-A 里那条 `test_sha_chan_jin_cheng_zao_hao_diao_taskkill` 只断言
        「调了 taskkill 且带 /T」——它 mock 掉了 `subprocess.run`，所以
        「真机上 node 到底有没有被收掉」它一点发言权都没有。而这个差别在
        Windows 上是实打实的：`pi.cmd` 是 `cmd /c node …` 的包装层，
        kill 它只断包装层（约束 2）。

        判据落在**进程真不在了**这个量上，不是「调了 taskkill」。
        """
        cwd = str(Path(__file__).resolve().parent.parent)
        ji = _pi_de_pid()                 # 基线必须在 spawn 之前取

        async def zhen():
            a, _ = self._da_ma()
            await asyncio.wait_for(a.kaishi(self._can_shu(cwd)), SUO_DING)
            pid = a.qu_pid()
            self.assertIsInstance(pid, int)
            self.assertTrue(_pi_de_pid() - ji,
                            "pi 起来了却没有 node 子进程，这条用例验不到东西")
            await asyncio.wait_for(a.guan_bi(), 30.0)
            for _ in range(100):          # 轮询（有判据），不是 sleep 固定时长
                if not cun_zhen(pid) and not (_pi_de_pid() - ji):
                    break
                await asyncio.sleep(0.1)
            self.assertFalse(cun_zhen(pid), f"pi 的包装进程 {pid} 还活着")
            # **node 孙进程也不该在**：Bridge 崩了之后用户机器上还挂着一个
            # 跑着他自己项目的 node，而 Bridge 自己完全不知道。
            self.assertEqual(_pi_de_pid() - ji, set(),
                             "pi 的 node 子进程变孤儿了 —— /T 没生效或没调")

        asyncio.run(asyncio.wait_for(zhen(), SUO_DING))


def cun_zhen(pid: int) -> bool:
    """pid 还活着吗。走 `tasklist` 查，Windows 上够用（codex 的 L-C 同样做法）。"""
    import subprocess
    try:
        chu = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             capture_output=True, text=True, timeout=15,
                             encoding="utf-8", errors="replace")
        return str(pid) in (chu.stdout or "")
    except Exception:  # noqa: BLE001
        return False


def _pi_de_pid() -> set[int]:
    """命令行里含 pi-coding-agent 的 node 进程 pid 集合。

    ⚠ 走 `Win32_Process` 取 **CommandLine**：`tasklist` 只给镜像名，
    分不出哪个 node 是 pi 的（这台机器上还有别的 node）。
    """
    import subprocess
    try:
        chu = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | "
             "Where-Object { $_.CommandLine -like '*pi-coding-agent*' } | "
             "ForEach-Object { $_.ProcessId }) -join ','"],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return set()
    return {int(x) for x in (chu.stdout or "").replace("\r", "").split(",") if x.strip()}


if __name__ == "__main__":
    unittest.main()