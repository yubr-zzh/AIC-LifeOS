"""一次性进程适配器的共享层（v3.0 任务 5）。

**它解决什么**：`kimi` / `opencode` / `hermes` 三家在协议层毫无共性
（事件形状、回合边界、参数全不同），但在**形态**上完全一样：

- 一次性进程：每条指令一个新进程，跑完自己退出；
- stdout 上是 newline-delimited JSON（JSONL），一行一个事件；
- **没有权限回路、也没有提问回路**——权限由 CLI 自己管，Bridge 接管不了；
- 回合边界由某一行 JSON 判定，判错的后果是 `fasong()` 挂死。

**text 归集、结果 dict 组装、`.CMD` 杀整棵树**这三件事三家逐字相同，
放三份就是三份会各自漂移的代码。**抽到这里，三个适配器各写自己的 wire 翻译。**

**为什么不往 `chuan_shu.py` 里加**：那个基类 `codex` 与 `pi` 都在用，
动它影响面最大——而本轮纪律是「不能共用的独立写新文件，避免改动影响扩散」。
新增一个中间层对已有四个适配器**零改动**。

## 与 `chuan_shu.py` 的分工

`ZiChengAdapter` 管「怎么起一个子进程、怎么读它的 stdout、怎么回收它」，
那部分三家完全相同，已经有了。**本文件管「一条 JSONL 事件流怎么变成统一事件、
回合在哪里收」**——三家相同的那一半。

| 职责 | 在哪 |
|---|---|
| spawn / 读循环 / stderr / pid / 生命周期 | `ZiChengAdapter`（`chuan_shu.py`） |
| text 归集、结果组装、杀整棵树 | **本文件** |
| argv 拼接、wire 翻译、回合边界判定 | 三个子类各自 |

## 承重契约（改之前先逐条读懂）

1. **嵌套 JSON 解析绝不能抛异常。** 基类读循环（`chuan_shu.py:330-333`）
   捕获 `fan_yi` 的异常后只发一帧 `translate_failed`，**不调 `_jie_shu_kao_ben`**
   ⇒ 回合永不收口，`fasong()` 挂到 15 分钟看门狗。症状是「Agent 无响应」
   而不是「翻译出错」。本文件所有 JSON 取值都给兜底。

2. **结果正文优先取权威来源，累加器只作兜底。** 与 `pi.py` 的 `_wen_zheng`
   同一口径：一个回合里有多条 assistant 消息时，delta 累加器会把
   「让我先看看」这种中间话术与最终答复拼在一起。

3. **子类调用 `jie_shou()` 一次即完成收口。** 本类内部已含
   「发 `result` 帧 → 唤醒 `fasong()` → 清累加器」三步，子类不要自己拼
   `result` 帧，也不要另外调 `_jie_shu_kao_ben`。漏调即挂死——
   这是这类适配器最常见的假绿（事件全对、`fasong()` 永不返回）。

4. **`.CMD` 包装层必须杀整棵树。** 见 `_ting_zhi_chi_cheng`。

## pid 上报（2026-10-06 补上的承重缺口）

**一次性进程的 pid 现在会登记进 `runtime.json` 了。** 旧缺口：`http.xin_jian`
在 `kaishi()` **之后**采一次 `qu_pid()`，而本类 `yi_ci_xing=True` ⇒ 基类
`kaishi` 不 spawn ⇒ 那一刻 `self.jin is None` ⇒ 恒 `None` ⇒
Bridge 被强杀时正在跑回合的子进程变孤儿（带用户全部权限改文件）。

修法就是当初文件头预案的那条：**`http.xin_jian` 注入一个 pid 上报回调
（`self.pid_hui`，与 `cheng` 同一个注入方式），`_qi_chi_cheng` 成功之后调
`_bao_pid()`**。一次性进程每回合 spawn 一个新进程，所以**每回合都要报**；
旧条目由 `http.lu_pid` 按会话替换。没改成在 `xin_jian` 里轮询 `qu_pid()`——
那是把一处采样改成 N 处采样，仍会漏。

claude-code / codex 不走这条：前者走 Python SDK（pid 在 SDK 里有），
后者常驻、`kaishi` 就 spawn，`xin_jian` 的既有采样对它们本来就工作。
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from typing import Any

from lifeos.bridge.adapters.chuan_shu import ZiChengAdapter


class LiuXingAdapter(ZiChengAdapter):
    """一次性进程 + JSONL 流 + 无权限回路的适配器基类。

    子类要写的三样东西：

    | 覆写点 | 职责 |
    |---|---|
    | `ZHI_LING`   | argv 前缀，如 `["kimi"]` |
    | `_zi_ling`   | 本条指令的 argv 追加（含续接参数与指令本身） |
    | `fan_yi` / `_jie_shu_bian_jie` | wire 翻译与回合边界判定 |

    **`jie_shou()` 由本类实现**（模板方法）：子类覆写 `_jie_shu_bian_jie()`
    判边界、自己组装结果字段，本类负责收尾（补默认字段 + 重置累加器）。
    **注意结果帧与 Future 唤醒在子类的 `fan_yi` 里做**（见承重契约 3）。
    """

    def __init__(self, a1: Any = None, a2: Any = None) -> None:
        super().__init__(a1, a2)
        #: 本回合正文累加器。各家按自己的 wire 往里塞。
        self._zhuan_wen: list[str] = []
        #: 本回合思考类内容累加器（与正文分开装，界面才能区分）。
        self._si_wei_wen: list[str] = []
        #: 回合起点（monotonic），算 durationMs 用。**kimi 不报耗时，靠它。**
        self._zhuan_kaishi = 0.0
        #: 本回合的错误信息。**回合边界才发它**，不要一收到 error 就广播。
        self._cuo_wen = ""
        #: session id 是否已经上报过。**只发一次**：同一会话后续回合
        #: 拿到的还是同一个 id，反复发只是让落盘多写几遍。
        self._fa_le_session = False
        #: 本回合是否已经收过口。**同一回合只收一次**——`jie_shou` 清完累加器
        #: 再被调一次会发出一个 `resultText=""` 的空结果帧（实测踩过）。
        self._fan_le = False
        #: `kaishi()` 记下的一回合 spawn 参数。`_fa_chu_ming_ling` 是另一个
        #: 方法，拿不到 `kaishi` 的入参，只能靠这两个字段中转。
        self._cwd = ""
        #: ⚠ **不能叫 `_huan_jing`**——基类有一个**同名方法**
        #: `ZiChengAdapter._huan_jing()`（`chuan_shu.py:272`，负责
        #: `{**os.environ, **增量}` 的真合并）。
        #: 实例属性会把方法遮蔽掉 ⇒ 基类 `env=self._huan_jing(a1)` 变成
        #: 「拿一个 dict 当函数调」⇒ `TypeError: 'NoneType' object is not callable`
        #: ⇒ **三个适配器的第一条指令 100% 炸**。
        #: （2026-10-05 真机抓到：spawn 一起来就 TypeError，不是协议问题。）
        self._huan_jing_zhuan: dict[str, str] | None = None
        #: 本回合的指令原文。`_fa_chu_ming_ling` 存进来，子类的 `_zi_ling`
        #: 拼 argv 时读它（基类的 `_zi_ling` 收到的 `a1` 只有 cwd/env）。
        self._wen = ""
        #: `ZHI_LING[0]` 解析后的真实可执行名（带 `.cmd`/`.exe` 或绝对路径）。
        #: `None` 表示还没解析。**每次 spawn 前重解析**，别缓存成实例状态——
        #: 用户装/卸载 CLI 后同一个 Bridge 进程要能立刻反映（见 `_qi_chi_cheng`）。
        self._zhen_ming: str | None = None
        #: pid 上报回调，由 `http.xin_jian` 注入（与 `cheng` 同一个注入方式）：
        #: `lambda pid: lu_pid(pid, sessionId)`。**每回合 spawn 成功后调一次**
        #: （见 `_bao_pid`）——一次性进程每条指令一个新进程，只靠 `xin_jian`
        #: 在 `kaishi()` 后采那一次，对这里恒为 `None`。`None` = 没人要
        #: （裸适配器 / 单测直接构造），上报跳过。
        self.pid_hui = None

    # ---------- 能力（三个子类口径相同，一律无权限回路）----------
    @staticmethod
    def fangquan() -> bool:
        """False——非交互模式下这三个 CLI 直接执行命令，零审批事件。

        真机实测（2026-10-05）：kimi 与 opencode 在 `-p` / `run` 模式下
        跑 `rm -f zzz_t.txt` 全程没发过任何审批请求，命令直接执行。
        ⇒ Bridge 接管不了它的权限，`/agents` 报 False 让 UI 说清这件事，
        而不是让用户在 LifeOS 里点了「批准」而对方根本没问。
        """
        return False

    @staticmethod
    def wenti2() -> bool:
        """False——同 `fangquan()`：没有提问回路。"""
        return False

    # ---------- 生命周期 ----------
    async def kaishi(self, a1: dict) -> None:
        """建立连接。**一次性进程这里不 spawn**，只记下本回合要用的参数。

        覆写它是为了把 `cwd` 与 `env` 中转给 `_fa_chu_ming_ling`——
        基类 `kaishi` 收到它们就丢。基类那句 `self.kehu_hui = a1.get("resume")`
        仍照常执行（续接靠它），本方法只在它之前存两个字段。
        """
        self._cwd = a1.get("cwd") or ""
        self._huan_jing_zhuan = a1.get("env")
        await super().kaishi(a1)

    async def _fa_chu_ming_ling(self, a1: str) -> None:
        """把一条指令送进 CLI：**这一回合新起一个进程，跑完自己退出。**

        ⚠ **直接复用基类的 `_qi_chi_cheng`**——它已经是 `async`、吃同一份
        dict，内部含 cwd / env / creationflags / 读 stdout / 读 stderr。
        自己重写一遍 spawn 只会多一处 `env=` 整体替换的坑。

        调用顺序是承重的：`fasong()` 先调本方法、再挂回合 Future，
        所以进程起来时读循环已在跑，收到的行立刻进 `fan_yi`。

        **子类覆写 `_fan_yi_zhun_bei`**（把指令原文存到 `self._wen`）而不是
        覆写本方法——本方法统一负责「存指令 → spawn → 开计时 → 放行收口闸」，
        这四步的顺序错了就会出现「回合收口了但正文是空的」。
        """
        self._wen = a1
        await self._fan_yi_zhun_bei()
        await self._qi_chi_cheng({"cwd": self._cwd or None, "env": self._huan_jing_zhuan})
        self._zhuan_kaishi = time.monotonic()
        self._fan_le = False

    async def _fan_yi_zhun_bei(self) -> None:
        """子类覆写：起进程前的准备（重置本回合的累加器与计数）。"""
        return

    # ---------- 可执行名解析（Windows 上是承重的）----------
    @classmethod
    def _jie_zhende_ming(cls) -> str:
        """把 `ZHI_LING[0]` 解析成 `create_subprocess_exec` 真能 spawn 的名字。

        ## 为什么承重（2026-10-05 真机抓到的缺陷）

        **Windows 上 `create_subprocess_exec("kimi")` 直接 `FileNotFoundError`，
        而 Bash 里 `command -v kimi` 却找得到。** 差别在于前者不做 PATHEXT 展开：
        npm 全局装的 CLI 在磁盘上是 `kimi.cmd`（一个 `cmd /c node …cli.js`
        的包装层），`kimi` 这个裸名只存在于 npm 的 shim 解析里。

        ⇒ **症状是假绿**：`tanjian()` 用 `shutil.which` 且显式试了 `.exe/.cmd/.bat`
        后缀，所以 `/agents` 报 `available=true`；真发第一条指令时却炸
        `FileNotFoundError`，界面上表现为「Agent 显示可用，一发消息就失败」。

        分家清楚：`hermes` 装在 `miniconda3/Scripts/hermes.exe`（真 exe），
        `codex` 是 `codex.exe`——**它们裸名就能 spawn**。只有 npm shim 那两个
        （kimi / opencode）踩坑。

        ## 为什么不写死 `kimi.cmd`

        写死在本机能跑，换到 macOS / Linux 就全挂（那边是 `kimi` 无后缀）。
        ⇒ 运行时解析，两种平台都对。

        ## 复用而不是重写

        基类 `tanjian()`（`chuan_shu.py:159-163`）**已经有同一套后缀试探逻辑**，
        但那是给「探测」用的，没有回填到 spawn 的 argv 上——两处各写一遍会漂。
        本方法用同样顺序（`.exe` → `.cmd` → `.bat`），
        **并额外接受 `shutil.which` 返回的绝对路径**（Windows 上 PATHEXT
        有多个候选时 `which` 可能返回带空格的完整路径，直接用比拼后缀稳）。
        """
        import shutil

        ming = cls.ZHI_LING[0]
        lu = shutil.which(ming)
        if lu:
            return lu
        for hou in (".exe", ".cmd", ".bat"):
            lu2 = shutil.which(ming + hou)
            if lu2:
                return lu2
        # 找不到就交回裸名，让 spawn 抛它自己那个更直白的
        # `FileNotFoundError`（错误信息里带的就是用户写的那个名字）。
        return ming

    async def _qi_chi_cheng(self, a1: dict) -> None:
        """spawn 子进程——**覆写基类只为把 `ZHI_LING[0]` 换成解析后的真名**。

        基类（`chuan_shu.py:245-268`）把 `self.ZHI_LING` 原样交给
        `create_subprocess_exec`，Windows 上那对 npm shim 会 `FileNotFoundError`。

        ⚠ **为什么覆写整个方法而不加一个钩子**：加钩子要改 `chuan_shu.py`，
        而那个基类 `codex` 与 `pi` 都在用（本轮纪律：不能共用的独立写新文件，
        避免改动影响扩散）。这里覆写只动 argv 第 0 位，其余全走基类逻辑，
        **对已有四个适配器零改动**。
        """
        self._zhen_ming = self._jie_zhende_ming()
        yuan = list(self.ZHI_LING)
        yuan[0] = self._zhen_ming
        # **实例属性遮蔽类属性**：基类 `_qi_chi_cheng` 会 `list(self.ZHI_LING)`
        # 拼在 argv 最前，所以这一步之后基类自动拿到解析后的名字。
        # 不用 try/finally 复原——每次 spawn 都重新赋同一个值，
        # 而 `tanjian()` 读实例上的绝对路径照样工作（`shutil.which` 接受绝对路径）。
        # ponytail: 借实例属性传参有点绕，但比在 chuan_shu 加钩子
        # （影响 codex/pi 两个已验收适配器）便宜。改基类时回来清掉。
        self.ZHI_LING = yuan
        await super()._qi_chi_cheng(a1)
        # spawn 成功了才报 pid：失败（FileNotFoundError 之类）时 super() 抛异常，
        # 这行根本走不到，不会把一个不存在的 pid 登记进 runtime.json。
        self._bao_pid()

    def _bao_pid(self) -> None:
        """把刚 spawn 的子进程 pid 报给 Bridge（落进 `runtime.json` 的 pids）。

        **每回合都要报**：一次性进程每条指令 spawn 一个新进程，旧进程此刻
        已经退出，Bridge 侧（`http.lu_pid`）会按会话替换旧条目。只有这样，
        Bridge 被强杀时 runtime.json 里留着的才是**正在跑回合的那一个** pid，
        下次启动的 `sao_bing` 才杀得掉它。

        上报失败绝不影响回合：pid 登记是 best effort，回调抛异常不能把一次
        正常的 spawn 搞挂。
        """
        hui = self.pid_hui
        if hui is None or self.jin is None:
            return
        try:
            hui(int(self.jin.pid))
        except Exception:  # noqa: BLE001
            pass

    # ---------- 回合边界（模板方法）----------
    def fan_yi(self, a1: str) -> None:
        """子类覆写：一行 stdout → 若干统一事件。

        ⚠ **子类必须自己在收口处调 `jie_shou()`**（本类已实现「发 result +
        唤醒 Future」）。基类读循环**不会**自动调它——`chuan_shu.py` 里
        没有任何地方调 `jie_shou`，那是子类的活。漏调 ⇒ `fasong()` 挂死
        到 15 分钟看门狗。
        """
        raise NotImplementedError

    def jie_shou(self, a1: dict) -> dict | None:
        """一行事件 → 回合结果 dict，或 None（不是回合边界）。

        **本类是收口的唯一入口**：判边界、补默认字段、发 `result` 帧、
        清累加器、唤醒挂起的 `fasong()`。子类的 `fan_yi` 解析到边界时
        调它一次即可，不要自己拼 `result` 帧——三家各拼一遍就会漂。

        边界判定本身交给子类的 `_jie_shu_bian_jie`。

        ⚠ **`_qing_kong` 之后是空的**：本方法先清累加器再返回，
        所以对同一个事件再调一次会得到 `resultText=""` 的空结果
        （实测踩过）。`_fan_le` 是幂等闸——同一回合只收一次口。
        """
        if self._fan_le:
            return None
        bian = self._jie_shu_bian_jie(a1)
        if bian is None:
            return None
        self._fan_le = True
        self._bu_que_men_can(bian)
        # **先发帧再唤醒**：反过来的话 `fasong()` 可能先返回，
        # 上层（`HuiHua.paichu`）已经推进到下一条指令，而上一条的结果帧
        # 才刚要发出去 ⇒ 界面上结果帧落在下一回合里。
        self._fa("result", bian)
        self._jie_shu_kao_ben(bian)
        self._qing_kong()
        return bian

    def _jie_shu_bian_jie(self, a1: dict) -> dict | None:
        """子类覆写：这一行是不是回合边界？是则返回结果 dict，否则 None。"""
        raise NotImplementedError

    def _bu_que_men_can(self, a1: dict) -> None:
        """补齐结果 dict 的可选字段。子类可在自己的判定里覆盖它们。"""
        a1.setdefault("resultText", "".join(self._zhuan_wen))
        a1.setdefault("isError", bool(self._cuo_wen))
        a1.setdefault("subtype", "error" if self._cuo_wen else "completed")
        a1.setdefault("durationMs",
                      int((time.monotonic() - self._zhuan_kaishi) * 1000)
                      if self._zhuan_kaishi else 0)
        a1.setdefault("numTurns", 1)
        a1.setdefault("totalCostUsd", 0.0)
        a1.setdefault("sessionId", self.kehu_hui)
        if self._cuo_wen:
            a1.setdefault("errorMessage", self._cuo_wen)

    def _qing_kong(self) -> None:
        """回合边界之后清累加器，否则下一回合的结果是两条回复拼一起。"""
        self._zhuan_wen = []
        self._si_wei_wen = []
        self._cuo_wen = ""
        self._zhuan_kaishi = 0.0
        self._fan_le = False

    # ---------- session 帧 ----------
    def _fa_session(self, a1: str) -> None:
        """发一次 `session` 帧，让 Bridge 落盘会话 id。

        ⚠ **必须带 `claudeSessionId`**：`http._hui_zhuan` 的 `session` 分支
        （`http.py:1121-1125`）只认这一个键，`AgentSession` 也只有它，
        而 `run.hui_fu` 恢复时靠它把续接 id 传回 `_zi_ling`。
        """
        if not a1 or self._fa_le_session:
            return
        self._fa_le_session = True
        self.kehu_hui = a1
        self._fa("session", {"sessionId": a1, "claudeSessionId": a1})

    # ---------- 中断与关闭 ----------
    async def _zhong_duan(self) -> None:
        """中断。一次性进程没有「礼貌地打招呼」这回事，直接杀整棵树。

        杀完**必须清累加器**（2026-10-06 opencode L-C 实测抓到的泄漏）：
        被杀的回合不走 `jie_shou` ⇒ 不清 `_qing_kong`，而 opencode 的
        `text` 事件是整段正文、回合中途就进了 `_zhuan_wen`——kill 赢了
        收口竞争时残留留在累加器里，下一回合（重试）的结果会带着
        上一条被中断的正文。kimi/hermes 到回合末才填累加器，同样
        的路径只是碰巧没炸，闸在这里三家一起收口。
        """
        await self._zhong_zhi_chi_cheng()
        self._qing_kong()

    async def _ting_zhi_chi_cheng(self) -> None:
        """关进程。覆写基类：**必须杀整棵树**（文件头第 4 条）。

        基类用的是 `jin.kill()`。`kimi` / `opencode` 在 Windows 上是
        `kimi.CMD` / `opencode.CMD`——npm 的 `cmd /c node …` 包装层，
        `kill()` 只断掉包装层，真正的 node 进程活到 Bridge 退出之后还在跑
        用户项目。`taskkill /T /F` 杀子孙 + 强杀。
        """
        self._sha_chan_jin_cheng()
        await super()._ting_zhi_chi_cheng()

    async def _zhong_zhi_chi_cheng(self) -> None:
        """杀进程不拆管道（中断≠关闭，后续回合还要用）。同样要杀整棵树。"""
        self._sha_chan_jin_cheng()

    def _sha_chan_jin_cheng(self) -> None:
        """`taskkill /T /F` 杀进程树（仅 Windows）。

        杀不动也要继续往下走：管道拆不掉的话 `guan_bi` 会挂到超时，
        而那比留一个孤儿严重。基类后面还有 `jin.kill()` 兜底。
        """
        if sys.platform != "win32":
            return
        jin = self.jin
        if jin is None:
            return
        pid = getattr(jin, "pid", None)
        if not isinstance(pid, int) or pid <= 0:
            return
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:  # noqa: BLE001
            pass

    # ---------- 嵌套 JSON 取值（绝不抛异常）----------
    @staticmethod
    def _dui_xiang(a1: Any, a2: str, a3: Any) -> Any:
        """取字段并保证类型正确，否则给默认值。**不能抛**（文件头第 1 条）。"""
        if not isinstance(a1, dict):
            return a3
        v = a1.get(a2, a3)
        return v if isinstance(v, type(a3)) else a3

    @staticmethod
    def _json_wen(a1: Any) -> Any:
        """把「JSON 字符串」解成对象；解不了就原样返回。

        三个 CLI 都把嵌套结构塞成字符串（kimi 的 `arguments`、
        hermes 的 `output`）。**解不了必须返回原串而不是抛**——
        丢掉内容比显示一段原始 JSON 差得多。
        """
        if not isinstance(a1, str):
            return a1
        try:
            return json.loads(a1)
        except (ValueError, TypeError):
            return a1