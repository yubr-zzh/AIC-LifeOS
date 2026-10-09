"""子进程传输层（v3.0 任务 1）：走 CLI 的适配器共享的基类。

**为什么需要它**：v2.0 只有一个真实适配器（`claude_code.py`），它 import
`claude_agent_sdk` 的 Python dataclass——那是 Anthropic 的进程内协议对象，
其余 harness 一个都没有。cc-connect 对此的解法是全部走子进程 CLI，
而子进程这一层（spawn、stdio 逐行收发、生命周期、pid 回收）在 6 个 harness
之间是**完全相同**的。所以把它抽成一个基类，各家适配器只写"它的 JSON 长什么样"。

**claude_code.py 不继承这里**——它走 Python SDK，没有子进程让它管。

## 承重契约（改之前先逐条读懂）

1. **`kaishi()` 必须在事件循环里调用。** `http._pao` 是全进程唯一调它的地方，
   它已经 `asyncio.run(zhu())` 把整轮编排包起来了。子类**不许**自己
   `asyncio.run`——那会在另一个 loop 上建子进程，之后 `zhong_duan()` /
   `guan_bi()` 经 `duo_cuo` 调度回这条 loop 时就找不到它了。

2. **pid 必须拿得到。** Bridge 崩了以后靠 `http.lu_pid` 回收孤儿进程。
   `claude_code.qu_pid()` 现在读的是 SDK 的私有路径（`kehu._transport._process.pid`），
   读不到就返回 None。子进程是我们自己 spawn 的，`Popen.pid` 直接就有——
   **这条路径比 claude_code 现在更可靠**。

3. **回合边界由子类判，基类不猜。** 「回合结束了」在每家 CLI 上都是一个不同的
   JSON 形状（`result` / `turn/completed` / `step_finish` / `agent_end` …）。
   基类把它抽成 `jie_shou()` 钩子，**判错的后果是 `fasong()` 永远不返回**：
   事件翻译全对、测试全绿、真机上挂死到超时。这是这类适配器最常见的假绿。

## 一次性进程 vs 常驻进程

gemini / kimi / opencode 是**一次性**的：每条指令一个新进程，session 靠
`--resume <id>` 续。cursor 也是一次性的，但它需要**接住 stdin**——
不接的话 Cursor 把所有审批当 EOF 静默自动拒绝（`jie_zhun` 存在的理由）。

pi / codex 是常驻的：一个进程跑到底，靠 stdin 送指令、stdout 收事件。

两种形态共用同一套传输代码，差别只在 `_fa_chu_ming_ling()` 与 `jie_shou()`。
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from lifeos.bridge.adapters.base import AgentAdapter

# stderr 的读取上限。一次性进程的 CLI 把参数错误都写这里，
# 不接的话症状是「挂到超时」而不是「参数错了」——差一个数量级的排查时间。
CUO_CHENG = 8 * 1024


def _qu(a1: Any, a2: str, a3: Any = None) -> Any:
    """取一个字段，dict 与对象都支持。跟 claude_code._qu 同义，两处各留一份。

    **基类自己不用它**（基类只管字节流），留给各家适配器翻译 wire 格式时用。
    放在这里而不是让各家自己写：v2.0 的 `claude_code._qu` 已经踩过
    「按 dict 写的翻译器在真机上一条消息都翻译不出来」（那是 dataclass 实例）。
    """
    if isinstance(a1, dict):
        return a1.get(a2, a3)
    return getattr(a1, a2, a3)


class ZiChengAdapter(AgentAdapter):
    """走子进程 CLI 的适配器基类。一实例 = 一个子进程 = 一个 Agent 会话。

    子类要写的四样东西：

    | 覆写点 | 职责 |
    |---|---|
    | `ZHI_LING`   | argv 前缀，如 `["codex", "app-server", "--listen", "stdio://"]` |
    | `fan_yi`     | 一行 stdout → 若干统一事件（调 `self._fa(kind, payload)`） |
    | `jie_shou`   | 判定回合边界，返回结果 dict 或 None |
    | `_fa_chu_ming_ling` | 把一条指令送进子进程（一次性进程在这里 spawn） |

    传输、生命周期、pid、并发、超时、断连全部由基类管。

    **`gai_moshi` 基类故意不定义**：它是「该 harness 真能切换权限模式」的信号，
    `http._gai_moshi` 用 `hasattr()` 判。要支持的自己定义，别支持的别定义。
    """

    #: argv 前缀。子类必须覆写。空列表 ⇒ 该适配器没写完，`kaishi()` 会明确失败。
    ZHI_LING: list[str] = []

    #: 无头模式标志。多数 CLI 要 `--print` / `-p` 才不弹交互界面。
    WU_ZHI_LING = ""

    #: 无头模式标志的 argv 名。kimi 新版删掉了 `--print`，所以它要用
    #: `CE_WU_TOU` 走探测而不是硬传（见 kimi 适配器）。
    CE_WU_TOU: list[str] = ["--help"]

    #: 一次性进程（gemini/kimi/opencode/cursor）：每条指令一个新进程。
    yi_ci_xing = True

    #: **能不能切换权限模式，且切换后真的生效。**
    #:
    #: `http._gai_moshi` 用 `hasattr(ad, "gai_moshi")` 决定放不放行切换请求。
    #: 所以**基类不能定义 `gai_moshi`**：定义了，`hasattr` 恒为 True，
    #: 三个没有权限回路的 harness 会收到一个它们根本无法兑现的切换请求——
    #: 而 `_gai_moshi` 会把 `hui.permissionMode` 更新成新值**并落盘**，
    #: 用户下次打开会话看到「plan 模式」，实际那个 harness 从来没按 plan 跑过。
    #:
    #: ⇒ **要支持切换的 harness 自己定义 `gai_moshi`；不支持的别定义。**
    #: 「方法不存在」就是可用信号，见本类的 L1 说明。

    def __init__(self, a1: Any = None, a2: Any = None) -> None:
        self.hui = a1      # 事件回调 (kind, payload)
        self.cheng = a2    # 挂起回调 async (kind, payload) -> 任何值
        self.jin: Any = None       # asyncio.subprocess.Process
        self.loop: asyncio.AbstractEventLoop | None = None
        self.moshi = "manual"
        self.gong_ju: dict[str, str] = {}   # toolUseId -> toolName（工具结果块里没有名字）
        self.xiang_id = ""                  # 当前流式消息的 id
        self.kehu_hui = ""                  # Agent 侧会话 id
        self.guan_le = False
        self.zhu_zi = 0
        self.jie_da: dict[str, Any] = {}    # requestId -> 回写目标
        self.cuo_wei = ""                   # stderr 最近内容（错误时带进 result）
        self._ting_du: asyncio.Task | None = None        # 读 stdout 的后台任务
        self._cuo_wei_ting_du: asyncio.Task | None = None  # 读 stderr 的后台任务

        # ---- 回合判定的同步点 ----
        # `fasong()` 挂在一个 Future 上等回合结束；读循环解析到回合边界就 set_result。
        # 用 Future 而不是「边读边 await」：读循环必须能持续跑，
        # 因为回合进行中还有审批请求要从同一条 stdout 上读出来。
        self._jie_shu: dict[int, asyncio.Future] = {}
        #: 回合 Future 的递增序号。见 `fasong()` 里为什么不用指令原文当 key。
        self._xu_hao = 0
        #: 本回合是否已经宣告过结束。进程非零退出时用来区分「崩了」与
        #: 「正常跑完但 CLI 没关连接」。
        self._jie_shu_kao_ben_guo = False

    # ---------- 可用性探测（各 harness 共用的默认实现）----------
    @staticmethod
    def fangquan() -> bool:
        """能否接管权限。子类覆写。默认 False（安全侧默认）。"""
        return False

    @staticmethod
    def wenti2() -> bool:
        """能否接管提问。子类覆写。默认 False。"""
        return False

    async def tanjian(self) -> dict[str, Any]:
        """探测本机是否可用。**绝不能抛异常**——探测失败要能被当成数据返回。

        默认实现：`shutil.which` 找 `ZHI_LING[0]`，找到就跑 `ZHI_LING + ['--version']`
        抓版本号。装了但没登录 / 配置损坏这类情况探测不出来，
        留给 `verify_v3_harness.py` 的真机脚本去撞。
        """
        import re
        import shutil
        import subprocess

        if not self.ZHI_LING:
            return {"available": False, "version": None, "sdkVersion": None,
                    "error": "该适配器没有配置 ZHI_LING"}
        ming = self.ZHI_LING[0]
        lu = shutil.which(ming)
        if lu is None:
            # 也试 Windows 上常见的 .exe / .cmd 后缀（npm 全局装的那些）
            for hou in (".exe", ".cmd", ".bat"):
                if shutil.which(ming + hou):
                    lu = ming + hou
                    break
        if lu is None:
            return {"available": False, "version": None, "sdkVersion": None,
                    "error": f"本机找不到 {ming}"}
        try:
            chu = subprocess.run([lu] + list(self.CE_WU_TOU),
                                 capture_output=True, text=True, timeout=15,
                                 encoding="utf-8", errors="replace")
        except (OSError, subprocess.SubprocessError) as e:
            return {"available": False, "version": lu, "sdkVersion": None,
                    "error": f"{type(e).__name__}: {e}"}
        he = (chu.stdout or "") + (chu.stderr or "")
        m = re.search(r"(\d+\.\d+\.\d+)", he)
        return {"available": True, "version": m.group(1) if m else lu, "sdkVersion": None,
                "error": None}

    # ---------- 生命周期 ----------
    async def kaishi(self, a1: dict) -> None:
        """建立底层连接。常驻进程在这里 spawn；一次性进程留到 `fasong()`。

        a1 含 cwd、permissionMode、resume、env、maxTurns 等。
        """
        # **ZHI_LING 的校验放在最前面，与 yi_ci_xing 无关。**
        # 放在 `_qi_chi_cheng()` 里的话，一次性进程（yi_ci_xing=True）
        # 在 kaishi() 这条路上根本走不到那个检查，要等到第一条指令
        # `fasong()` 才炸——那时用户已经看到会话建起来了。
        if not self.ZHI_LING:
            raise RuntimeError(f"{type(self).__name__} 没有配置 ZHI_LING")
        self.loop = asyncio.get_running_loop()
        self.moshi = a1.get("permissionMode", "manual")
        self.kehu_hui = a1.get("resume") or ""
        if not self.yi_ci_xing:
            await self._qi_chi_cheng(a1)

    async def fasong(self, a1: str) -> None:
        """执行一条指令，等这一轮跑完。

        **返回 None 而不是结果 dict**——6 个子进程 harness 的结果字段各不相同
        （codex 有 turn.status、gemini 有 stats、cursor 无），
        强行凑成一个 dict 只会造出一个谁都不用的假统一字段。
        回合结果由 `jie_shou()` 广播成 `result` 事件（6.3 的既有通道），
        `HuiHua.paichu` 靠那个事件判成功，不靠返回值。
        """
        if self.guan_le:
            raise RuntimeError("会话已关闭")
        await self._fa_chu_ming_ling(a1)
        fu = self.loop.create_future()
        # **key 用递增序号，不用指令原文。** 理由不是「原文会挂死」——
        # 变异验证实测过（tests/_bianyi_chuan_shu.py 的变异 1）：两种写法
        # 都不会让 `fasong()` 挂死，因为 `_jie_shu_kao_ben` 遍历全部待决
        # Future，而 `HuiHua.paichu` 串行执行，前一回合早就在 `finally`
        # 里 pop 干净了。序号是**防御性写法**：让「这个 Future 属于哪一回合」
        # 可追溯，将来若有人给某条 harness 开并发，也不会静默撞掉别人的槽。
        self._xu_hao += 1
        men = self._xu_hao
        # 每个回合重置：否则上一回合的「正常结束」会让本回合的进程退出
        # 被误判成崩溃（`_fan_cheng_kao_ben` 靠它区分两者）。
        self._jie_shu_kao_ben_guo = False
        self._jie_shu[men] = fu
        try:
            await fu
        finally:
            # 用局部 `men` 而不是 `self._xu_hao`：后者可能已被下一次
            # `fasong()` 推进，pop 掉别人的 Future。
            self._jie_shu.pop(men, None)

    async def zhong_duan(self) -> None:
        """中断当前回合。一次性进程直接杀；常驻进程由子类覆写。"""
        await self._zhong_duan()

    async def guan_bi(self) -> None:
        """关闭连接并回收子进程。"""
        self.guan_le = True
        # 挂着的回合 Future 不能留——留着会让 `fasong()` 永远等下去。
        for fu in list(self._jie_shu.values()):
            if not fu.done():
                fu.set_result(None)
        await self._ting_zhi_chi_cheng()

    # ---------- 子进程 ----------
    async def _qi_chi_cheng(self, a1: dict) -> None:
        """spawn 子进程并起读 stdout 的后台任务。"""
        if not self.ZHI_LING:
            raise RuntimeError(f"{type(self).__name__} 没有配置 ZHI_LING")
        argv = list(self.ZHI_LING) + list(self.WU_ZHI_LING.split()) + \
            list(self._zi_ling(a1))
        jin = await asyncio.create_subprocess_exec(
            *argv,
            cwd=a1.get("cwd") or None,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._huan_jing(a1),
            **self._chuang_kong(),
        )
        self.jin = jin
        self._ting_du = asyncio.create_task(self._du_zhan())
        # **stderr 必须同时读**，否则管道写满后子进程会阻塞在写 stderr 上，
        # 表现是「Agent 一直不出字」而不是「报错」——最难看的一种挂死。
        self._cuo_wei_ting_du = asyncio.create_task(self._shou_cuo_wei())

    def _zi_ling(self, a1: dict) -> list[str]:
        """子类在这里追加 argv（cwd、--resume、模型等）。默认空。"""
        return []

    def _huan_jing(self, a1: dict) -> dict[str, str] | None:
        """子进程的环境变量。

        **必须真合并，不能把增量直接交给 `create_subprocess_exec(env=…)`。**
        那个参数是**整体替换**，不是覆盖单键——只给它
        `{"CLAUDE_CONFIG_DIR": …}`，子进程就看不到 `PATH` / `HOME` /
        `USERPROFILE` / `APPDATA`，于是找不到自己的配置与凭据。

        ⚠ **这是一个承重缺陷，2026-10-05 在真机上抓到。**
        症状：codex 适配器一起回合就一路
        `error / codex_error / "Reconnecting... waiting for network"`，
        回合永不收口，`fasong()` 挂到看门狗——**看着像适配器或协议的问题，
        真因是传输层把用户的 CLI 配置环境抹了**。
        为什么 v2.0 没暴露：claude-code 走 Python SDK，**不 spawn 子进程**，
        `_huan_jing` 在那条路径上根本没被调用。codex 是第一个真子进程 harness。

        ⇒ 现在的做法：`os.environ | 增量`。返回 None 表示「完全继承，不覆盖」。
        """
        zeng = dict(a1.get("env") or {})
        if not zeng:
            return None
        import os
        return {**os.environ, **zeng}

    @staticmethod
    def _chuang_kong() -> dict[str, Any]:
        """Windows 上 spawn 时用的 creationflags。

        **新进程组是必须的**：默认情况下 `kill()` 只杀 `cmd /c more` 这一层，
        子进程自己再起的那些（codex 起的沙箱、gemini 起的工具进程）
        会留下来变成孤儿，并在 Bridge 崩溃后继续跑用户���命令。
        `CREATE_NEW_PROCESS_GROUP` 让整棵树能被一起收掉。

        常量在 `subprocess` 里而不是 `asyncio.subprocess`——后者只是把前者
        re-export 了 `PIPE` / `STDOUT` 那几个，creationflags 没有。
        """
        import subprocess as sp
        import sys
        if sys.platform == "win32":
            return {"creationflags": sp.CREATE_NEW_PROCESS_GROUP}
        return {}

    async def _du_zhan(self) -> None:
        """读 stdout 的后台循环。每读到非空行就交给 `fan_yi`。

        **这里不做超时判断**——超时是会话层的事（`HuiHua` 的三层看门狗），
        在这里加超时会把「Agent 正在思考」误判成「Agent 卡死」。
        """
        if self.jin is None or self.jin.stdout is None:
            return
        try:
            while True:
                xing = await self.jin.stdout.readline()
                if not xing:
                    break
                wen = xing.decode("utf-8", errors="replace").strip()
                if not wen:
                    continue
                try:
                    self.fan_yi(wen)
                except Exception as e:  # noqa: BLE001
                    self._fa("error", {"code": "translate_failed",
                                      "message": f"{type(e).__name__}: {e}",
                                      "recoverable": True})
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            self._fa("error", {"code": "stdout_read_failed",
                              "message": f"{type(e).__name__}: {e}", "recoverable": False})
        finally:
            await self._fan_cheng_kao_ben()

    async def _shou_cuo_wei(self) -> None:
        """读 stderr，攒进 `cuo_wei`。不读的话管道会满，进程会卡死。"""
        if self.jin is None or self.jin.stderr is None:
            return
        try:
            while True:
                duan = await self.jin.stderr.read(2048)
                if not duan:
                    break
                self.cuo_wei = (self.cuo_wei + duan.decode("utf-8", errors="replace"))[-CUO_CHENG:]
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            return

    async def _fan_cheng_kao_ben(self) -> None:
        """stdout 读到 EOF = 子进程把管道关了。

        **这里必须 `await jin.wait()` 再看 returncode。** 不 wait 的话
        `Process.returncode` 恒为 None（asyncio 只在 wait 完成后才填它），
        于是这条 error 帧永远发不出去——`fasong()` 挂到审批超时才被
        8.7 的看门狗收走，症状是「Agent 无响应」而不是「进程崩了」。

        `wait_for` 兜底：有些 CLI 关了 stdout 但进程还活着（转后台了），
        那时不该让这个协程把整个读循环吊死。
        """
        jin = self.jin
        if jin is None:
            return
        try:
            await asyncio.wait_for(jin.wait(), 5.0)
        except (asyncio.TimeoutError, ProcessLookupError):
            return
        except Exception:  # noqa: BLE001
            return
        if jin.returncode is None:
            return
        # 正常收尾（退出码 0 且读到了回合结束信号）不是错误。
        if jin.returncode == 0 and self._jie_shu_kao_ben_guo:
            return
        self._fa("error", {"code": "agent_exited",
                          "message": f"Agent 进程已退出（退出码 {jin.returncode}）"
                                     + (f"：{self.cuo_wei}" if self.cuo_wei else ""),
                          "recoverable": False})
        # **必须唤醒挂着的回合。** 只发 error 帧的话，`fasong()` 仍在 await
        # 那个永远不会被 set_result 的 Future——回合挂到 8.7 的看门狗
        # （15 分钟）才被收走，症状是「Agent 无响应」而不是「进程崩了」。
        self._jie_shu_kao_ben(None)

    # ---------- 子类覆写点 ----------
    def fan_yi(self, a1: str) -> None:
        """一行 stdout → 若干统一事件。子类必须实现。"""
        raise NotImplementedError

    def jie_shou(self, a1: dict) -> dict | None:
        """一行事件 → 回合结果 dict，或 None（不是回合边界）。子类必须实现。

        `fan_yi` 里解析到回合边界时，除了调 `self._fa("result", ...)` 还要调
        `self._jie_shu_kao_ben(result)` 让挂起的 `fasong()` 返回。
        """
        raise NotImplementedError

    async def _fa_chu_ming_ling(self, a1: str) -> None:
        """把一条指令送进子进程。一次性进程在这里 spawn。"""
        raise NotImplementedError

    async def _zhong_duan(self) -> None:
        """中断。默认杀进程（一次性 harness 的正确行为）。"""
        await self._zhong_zhi_chi_cheng()

    async def _ting_zhi_chi_cheng(self) -> None:
        """关进程。**顺序：先杀、再关管道、最后 wait。**

        ⚠ 反过来做（先 `wait_closed()`）在 Windows 上**必然挂死**，实测：
        子进程还活着，它的 stdin 还连着，`StreamWriter.wait_closed()`
        会一直等对端把管道写端关掉——而对端在等我们先关。
        死等的表现是「单跑这个用例通过，连着跑就卡住」，
        因为只有前面用例留下的活进程才会触发这个互等。

        每一步都带超时：任何一个子进程不配合都不该让整条关闭路径挂住。
        """
        if self.jin is None:
            return
        for t in (self._ting_du, self._cuo_wei_ting_du):
            if t is not None and not t.done():
                t.cancel()
        self._ting_du = None
        self._cuo_wei_ting_du = None
        jin = self.jin
        self.jin = None
        # 1. 先杀。不杀的话下面每一步都在等一个不打算退出的进程。
        with contextlib.suppress(ProcessLookupError, OSError):
            jin.kill()
        # 2. 再 wait（带超时）。拿到 returncode 后管道才可能真的 EOF。
        with contextlib.suppress(Exception):
            await asyncio.wait_for(jin.wait(), 5.0)
        # 3. 最后关管道。进程已经死了，这里不会互等。
        for pipe in (jin.stdin, jin.stdout, jin.stderr):
            if pipe is None:
                continue
            with contextlib.suppress(Exception):
                await asyncio.wait_for(pipe.wait_closed(), 2.0)

    async def _zhong_zhi_chi_cheng(self) -> None:
        """杀进程但不拆管道（中断≠关闭，后面的回合还要用）。"""
        if self.jin is None:
            return
        with contextlib.suppress(ProcessLookupError):
            self.jin.kill()

    # ---------- 回合边界 ----------
    def _jie_shu_kao_ben(self, a1: dict | None = None) -> None:
        """宣告回合结束，唤醒挂起的 `fasong()`。

        **幂等**：同一回合里 `fan_yi` 可能撞上多个回合边界信号
        （比如 codex 的 `turn/completed` 之后紧跟一个 `error` 帧），
        对同一个 Future set_result 两次会抛 InvalidStateError。
        """
        for fu in list(self._jie_shu.values()):
            if not fu.done():
                self._jie_shu_kao_ben_guo = True
                fu.set_result(a1)

    # ---------- 发事件 ----------
    def _fa(self, a1: str, a2: dict) -> None:
        if self.hui:
            try:
                self.hui(a1, a2)
            except Exception:  # noqa: BLE001
                pass

    # ---------- pid ----------
    def qu_pid(self) -> int | None:
        """取子进程 pid。

        **比 claude_code.qu_pid() 可靠**：那是读 SDK 的私有路径
        （`kehu._transport._process.pid`），读不到就返回 None；
        子进程是我们自己 spawn 的，`Process.pid` 直接就有。
        """
        if self.jin is None:
            return None
        pid = getattr(self.jin, "pid", None)
        return int(pid) if isinstance(pid, int) and pid > 0 else None

    # ---------- 挂起通道 ----------
    async def _cheng(self, a1: str, a2: dict) -> Any:
        """交给 Bridge 的挂起通道。没有挂起能力时一律拒绝（安全侧默认）。"""
        if self.cheng is None:
            return {"denied": True, "message": "没有可用的审批通道，已拒绝"}
        try:
            return await self.cheng(a1, a2)
        except asyncio.CancelledError:
            # 用户中断会走到这里。**必须原样抛出**：吞掉它会让上层以为
            # 这次调用正常返回了，而 Agent 那边已经在取消这条协程了。
            raise