"""pi 适配器：接 `pi --mode rpc`（v3.0 任务 6，方案 4.2）。

pi 有两种模式：`--mode json`（一次性进程）和 `--mode rpc`（持久进程）。
**本适配器选 `rpc`**，与 `HuiHua` 的「一适配器实例 = 一持久子进程 = 一会话」
对齐，也才拿得到 `extension_ui_request` 那条审批/提问回路
（`--mode json` 完全不支持它，cc-connect 的 `RespondPermission` 里
`if !s.rpc { return nil }` 就是这个意思）。

## 协议事实（来自本机 pi 1.0.2 的 docs/ 与 dist/ 源码，不是抄文档）

pi 的 RPC **不是 JSON-RPC 2.0**：它有四条记录族，靠 `type` 区分。

| 方向 | `type` | 用途 |
|---|---|---|
| stdin | 无 `type`… 命令 | `{"id":"p-1","type":"prompt","message":"…"}` |
| stdout | `response` | 命令结果，`{"id":…,"success":…,"data":…}` |
| stdout | 各类会话事件 | `message_update` / `agent_settled` / … |
| 双向 | `extension_ui_request` / `extension_ui_response` | 扩展对话框 |

**所以 codex 那套 `_qing_qiu` / `_hui_yi` 的 JSON-RPC 结构能搬，但不是原样搬**：
`jsonrpc:"2.0"` 与 `"result"`/`"error"` 字段一律没有，成功判据是
`success` 布尔，失败是 `success:false` + 顶层 `error` **字符串**。

## 五条真机踩出来的约束（看文档看不出来的那种）

1. **Windows 上可执行名是 `pi.cmd`，不是 `pi`。**
   npm 全局装出来的是 shell shim（无扩展名那个是 sh 脚本），Python 的
   `create_subprocess_exec("pi")` 直接 `FileNotFoundError`。
   `tanjian()` 走 `shutil.which("pi.cmd")` 能找到，探测照样报 available。
   ⇒ **所以 `ZHI_LING[0]` 写裸名 `pi`，真名在 `_qi_chi_cheng` 里运行时解析**
   （`_jie_zhende_ming`），别把 `pi.cmd` 写死进 `ZHI_LING`（换平台全挂）。

2. **杀 `pi.cmd` 会留下 `node` 孤儿。**
   `pi.cmd` 是 `cmd /c node …cli.js` 的包装层，`Process.kill()` 只杀掉它，
   真正的 agent 进程活到 Bridge 退出之后还在跑（实测：杀完 tasklist 里
   node.exe 仍在）。⇒ **必须 `taskkill /T /F` 杀整棵树**，见 `_sha_chan_jin_cheng`。
   基类 `_ting_zhi_chi_cheng` / `_zhong_zhi_chi_cheng` 用的都是 `jin.kill()`，
   所以本适配器覆写这两个方法，**基类一行不动**（它有 6 家共用）。

3. **回合边界是 `agent_settled`，不是 `agent_end`。**
   `docs/json.md` 写得很死：`agent_end` 闭的是**一次底层 agent run**，
   之后还可能有自动重试 / 溢出恢复 / 压缩恢复 / steer / follow-up；
   「Pi 不会再自动继续」的事件是 `agent_settled`。真机实测顺序：
   `… → turn_end → agent_end → agent_settled`。
   拿 `agent_end` 判边界 ⇒ 一次 429 重试就把回合收走，结果是空的。

4. **`agent_end.willRetry=true` 时更不能收回合。**
   pi 在同一次 run 内自己重试（429 / 529），此时会发一个 `agent_end`
   然后重新 `agent_start`。cc-connect 的 `handleEvent` 也专门 `break` 在这里。
   ⇒ `jie_shou` 对 `agent_end` 一律返回 None，判据写在 `agent_settled` 上。

5. **正文有两个来源，权威的是 `message_end`。**
   `message_update.assistantMessageEvent.text_delta` 是打字机增量；
   `message_end{message:{role:"assistant",content:[{type:"text",text}]}}`
   才是完整文本（docs 原文：「This is the authoritative final message」）。
   两者都发会像 codex 那样在界面上出现两条一样的消息
   ⇒ delta 只发 `chunk`，`message_end` 才发 `text`。

## 审批回路的真实边界（别把它吹大）

`extension_ui_request` 的对话框方法（`select` / `confirm` / `input` / `editor`）
是真阻塞：pi 把 Promise 挂在 `pendingExtensionRequests` 上，等我们回
`extension_ui_response`。`dist/modes/rpc/rpc-mode.js` 里那四个
`createExtensionUIContext.*` 与 `parsed.type === "extension_ui_response"`
两段代码就是这条回路的完整实现，**不是文档承诺**。

但要说清它管的是谁：**这是扩展的 UI API，不是内置工具的审批闸门。**
内置 `bash` / `edit` / `write` 工具**不发** `extension_ui_request`（真机打过：
一次 `bash` 回合全程 0 条 extension_ui_request）。所以本机这个形态下它
**不是**内置工具的审批闸门，`fangquan()` 如实报 **False**
（回路代码仍在，只是不对外承诺接管内置工具）。
本机装了 permission-gate 一类扩展时，它才是扩展侧真的闸门。
`notify` / `setStatus` / `setWidget` / `setTitle` / `set_editor_text`
是 fire-and-forget，**不能回响应**，本适配器直接忽略。
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
from typing import Any

from lifeos.bridge.adapters.chuan_shu import ZiChengAdapter

#: 握手（get_state 拿 sessionId）的预算。首次启动要加载扩展与模型目录。
SHOU_ZHEN_MIAO = 60.0
#: 单条命令的默认预算（`prompt` 只是「已接受」，秒回；`compact` 类才慢）。
QING_QIU_MIAO = 30.0


class PiAdapter(ZiChengAdapter):
    """一个实例 = 一个 `pi --mode rpc` 子进程 = 一个 pi 会话。"""

    agentId = "pi"
    label = "pi Coding Agent"

    #: pi 的权限面是**工具 allowlist**（`--tools` / `--exclude-tools`），
    #: 没有 claude-code 那种五档模式，也切不出 plan。
    #: 只声明真能兑现的「手动」一档——空集会被 `http._dui_lie` 当成
    #: 「未声明」而上报全局白名单，前端于是渲染出 auto / dontAsk 等
    #: 选下去必然 400 的选项（两种死法都要避开）。
    #: 顺带：因此**不定义 `gai_moshi`**（基类故意不定义，见 `chuan_shu`）。
    MOSHI_ZI = frozenset({"manual"})

    #: 会话 id 落在 `claudeSessionId`：**这就是 `kaishi()` 真的写出去的那个键**
    #: （下面 `self._fa("session", {…"claudeSessionId":…})`），也是
    #: `http._hui_zhuan` 的 session 分支唯一读的键。**不写 `sessionId`**——
    #: `AgentSession.sessionId` 已被 LifeOS 自己的会话 id 占着，写它等于覆盖。
    dui_hui_id = "claudeSessionId"
    #: rpc 是常驻进程：一条指令一个 run，进程活到底。
    yi_ci_xing = False
    xu_pei_zhuang = False

    #: `--mode rpc` 必须显式写。**第 0 位写裸名 `pi`，不写 `pi.cmd`**
    #: （约束 1 的续）：那是 Windows 上的一处硬编码，换到 macOS / Linux 全挂。
    #: 真名在 `_qi_chi_cheng` 里由 `_jie_zhende_ming` 运行时解析。
    ZHI_LING = ["pi", "--mode", "rpc"]

    #: **`--version` 而不是基类默认的 `--help`**。
    #: 基类抓版本号靠 `(\d+\.\d+\.\d+)` 正则，`pi.cmd --help` 的正文里
    #: 没有版本号 ⇒ 正则不匹配 ⇒ `tanjian()` 把**可执行文件路径**当版本号返回
    #: （实测抓到 `C:\Users\Liuxj\AppData\Roaming\npm\pi.cmd`），
    #: `/agents` 上界面上显示成一串路径。真机 `pi.cmd --version` 输出 `1.0.2`。
    CE_WU_TOU = ["--version"]

    #: 需要回响应对话框的 `extension_ui_request.method`。其余五个
    #: （notify / setStatus / setWidget / setTitle / set_editor_text）
    #: 是 fire-and-forget，回了也是空操作。
    DUI_HUA = ("confirm", "select", "input", "editor")

    def __init__(self, a1: Any = None, a2: Any = None) -> None:
        super().__init__(a1, a2)
        #: 命令 id 的递增序号。**不用指令原文当 id**：pi 的 `response` 原样回显 id，
        #: 两个请求撞 id 就张冠李戴。
        self._qing_qiu_id = 0
        #: id -> Future，等 pi 的 `response`。
        self._qing_qiu_deng: dict[str, asyncio.Future] = {}
        #: 本回合正文（text_delta 累加）+ 思考（thinking_delta 累加）。
        self._zhuan_wen: list[str] = []
        self._si_wei_wen: list[str] = []
        #: 最近一条 assistant `message_end` 的权威正文（docs/json.md：
        #: 「This is the authoritative final message」）。**只在 delta 累加器
        #: 为空时兜底**——provider 不吐增量时（真机上出现过 message_update
        #: 里一条 text_delta 都没有、message_end 直接带全文），
        #: 只读 delta 会让 resultText 是空的，而 3.8 决策回路靠这个字段
        #: 把结果送回 LifeOS 对话上下文 ⇒ 用户看到「跑完了但什么都没说」。
        self._wen_zheng = ""
        #: 本回合见到的 assistant `stopReason:"error"` 的 errorMessage。
        #: **攒到回合边界才发**：pi 可能马上自动重试（约束 4），
        #: 立刻发出去等于告诉用户「失败了」而它自己已经恢复好了。
        self._cuo_wen = ""
        #: 回合起点（monotonic），算 durationMs 用。**pi 不给耗时**。
        self._zhuan_kaishi = 0.0
        #: 等待用户决定的挂起任务。**必须能在关连接时收掉**：
        #: 留着会让 `guan_bi` 之后还有协程握着已经拆掉的子进程 stdin。
        self._dai_dai: set[asyncio.Task] = set()

    # ---------- 能力 ----------
    @staticmethod
    def fangquan() -> bool:
        """**False**——`extension_ui_request` 不是内置工具的审批闸门。

        见文件头「审批回路的真实边界」：内置 `bash` / `edit` / `write`
        **不发** `extension_ui_request`（真机打过：一次 bash 回合全程 0 条）。
        报 True 时 `AgentsSection.tsx:330` 那句「权限由它自己的界面管」
        不会渲染 ⇒ 用户以为审批受管，实际内置工具一次都不问。
        报 False 恰好让那句话出现，是如实描述。

        ⚠ **代码没删**：`DUI_HUA` + `fan_yi` 里的扩展确认框回路仍然在跑
        （本机装了 permission-gate 一类扩展时它是真的）。`fangquan()`
        只是不再对外承诺「内置工具的审批由我们接管」。
        """
        return False

    @staticmethod
    def wenti2() -> bool:
        """True——`select` / `input` / `editor` 三种对话框同一条回路。"""
        return True

    # ---------- 生命周期 ----------
    # ---------- 可执行名解析（Windows 上是承重的，约束 1）----------
    @classmethod
    def _jie_zhende_ming(cls) -> str:
        """把 `ZHI_LING[0]` 解析成 `create_subprocess_exec` 真能 spawn 的名字。

        **Windows 上 `create_subprocess_exec("pi")` 直接 `FileNotFoundError`**，
        因为它不做 PATHEXT 展开，而 npm 全局装出来的 pi 在磁盘上是
        `…\\npm\\pi.CMD`（`cmd /c node …cli.js` 的包装层），裸名只活在
        npm 的 shim 解析里。⇒ 症状是**假绿**：`tanjian()` 显式试过
        `.exe/.cmd/.bat` 后缀，`/agents` 照样报 `available=true`，
        真发第一条指令时炸。

        与 `LiuXingAdapter._jie_zhende_ming` 逻辑相同但**独立写一份**：
        pi 走 `ZiChengAdapter` 那条路，用不上 `liu_xing`，而往 `chuan_shu`
        加钩子会牵动 codex / pi 两个已验收适配器（不能共用的独立写，
        避免改动影响扩散）。**两份逻辑会漂，改一处记得改另一处。**

        顺序：`shutil.which` 拿绝对路径优先（PATHEXT 有多个候选时它可能返回
        带空格的完整路径，直接用比拼后缀稳）→ 依次试 `.exe`/`.cmd`/`.bat`
        → 找不到就交回裸名，让 spawn 抛它自己那个更直白的 `FileNotFoundError`。
        """
        ming = cls.ZHI_LING[0]
        lu = shutil.which(ming)
        if lu:
            return lu
        for hou in (".exe", ".cmd", ".bat"):
            lu2 = shutil.which(ming + hou)
            if lu2:
                return lu2
        return ming

    async def _qi_chi_cheng(self, a1: dict) -> None:
        """spawn 子进程——**覆写基类只为把 `ZHI_LING[0]` 换成解析后的真名**。

        基类（`chuan_shu.py:245-268`）把 `self.ZHI_LING` 原样交给
        `create_subprocess_exec`，Windows 上那对 npm shim 会 `FileNotFoundError`。

        ⚠ **解析结果不存成任何与基类方法同名的实例属性**（实例属性遮蔽
        同名方法 ⇒ 第一条指令 100% 炸）。直接写 `self.ZHI_LING`
        即可——基类下一行就是 `list(self.ZHI_LING)`，自动拿到解析后的名字；
        不用复原，每次 spawn 赋的都是同一个值。
        ⚠ 只在 `kaishi()` 里走一次（`yi_ci_xing = False`，常驻进程）。
        """
        yuan = list(self.ZHI_LING)
        yuan[0] = self._jie_zhende_ming()
        self.ZHI_LING = yuan
        await super()._qi_chi_cheng(a1)

    def _huan_jing(self, a1: dict) -> dict[str, str] | None:
        """子进程环境：**真合并之后摘掉继承来的 `ANTHROPIC_*`**（env 继承的坑）。

        pi 会读 `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_BASE_URL` 当自己的 provider
        凭据。宿主是 Claude Code 时，父进程 env 里带着
        `ANTHROPIC_AUTH_TOKEN=PROXY_MANAGED`，基类的真合并把它原样带给 pi
        ⇒ pi 拿它当 bearer 打自己的 API ⇒ `401 Invalid bearer token`
        （L-D 的 2 条红）与 L-C 的概率性红。

        **摘除范围是继承来的键**；`a1["env"]` 里显式给的 `ANTHROPIC_*` 仍然
        生效——Bridge 想给就给得进去，摘的只是「不小心带进来」的那部分。
        没有任何要摘的键时返回 `None`（完全继承），与基类口径一致。
        只动 pi 自己：codex 不读 `ANTHROPIC_*`，基类那个真合并一行不动
        （动 `chuan_shu` 牵动已验收适配器）。键名比较用
        `upper()`——Windows 的 env 块大小写不敏感，`os.environ` 的键却保留原样。
        """
        zeng = dict(a1.get("env") or {})
        if not zeng:
            if not any(k.upper().startswith("ANTHROPIC_") for k in os.environ):
                return None
            return {k: v for k, v in os.environ.items()
                    if not k.upper().startswith("ANTHROPIC_")}
        xian = {k.upper() for k in zeng}   # 显式给的键说了算，不摘
        he = {**os.environ, **zeng}
        return {k: v for k, v in he.items()
                if not (k.upper().startswith("ANTHROPIC_") and k.upper() not in xian)}

    def _zi_ling(self, a1: dict) -> list[str]:
        """argv 追加。`resume` → `--session-id`，可选 `model` → `--model`。

        **不带 `--model` 时用 pi 自己的默认**：Bridge 侧 `xin_jian()` 只传
        cwd / permissionMode / resume / env，用户在 pi TUI 里选过的模型
        存在它自己的 settings.json 里，硬传反而会覆盖掉。
        `model` 做成可选参数只为让 L-C 能指定一个本机可用的 provider。
        """
        can: list[str] = []
        if self.kehu_hui:
            can += ["--session-id", self.kehu_hui]
        mo = str(a1.get("model") or "").strip()
        if mo:
            can += ["--model", mo]
        return can

    async def kaishi(self, a1: dict) -> None:
        """建立连接：spawn → `get_state` 拿 sessionId → 上报 session 帧。

        ⚠ **`get_state` 探针是必需的，不是可选的**：`pi --mode rpc` **不在
        stdout 上推 session 头**（`docs/json.md`：「RPC mode does not emit this
        record」），唯一能拿到 sessionId 的办法就是问。
        拿不到 ⇒ `--session-id` 传不进去 ⇒ 重启后会话接不上
        （`run.hui_fu` 靠的正是这个字段）。
        """
        await super().kaishi(a1)
        self.kehu_hui = ""
        zhao = await self._qing_qiu("get_state", None, SHOU_ZHEN_MIAO)
        sid = str((zhao or {}).get("sessionId") or "")
        if sid:
            self.kehu_hui = sid
        # `claudeSessionId` 也带上：v2.0 的前端续接字段是它，
        # `http._hui_zhuan` 只认这个键（AgentSession 也只有这个字段）。
        self._fa("session", {"sessionId": self.kehu_hui,
                             "claudeSessionId": self.kehu_hui})

    async def zhong_duan(self) -> None:
        """中断当前回合：**先发 `abort` 再杀进程**。

        直接杀的话 pi 来不及收尾，已经收到的 delta 停在半句上——
        用户看到的是「Agent 说到一半消失了」而不是「已中断」。
        `abort` 的响应是「会话已空闲」，它不等 agent_settled，
        所以杀进程仍然是必需的兜底（约束 2：光靠它会留下 node 孤儿）。
        """
        if self.jin is None:
            return
        try:
            await asyncio.wait_for(self._qing_qiu("abort", None), 5.0)
        except Exception:  # noqa: BLE001
            pass  # 杀进程兜底
        await self._zhong_zhi_chi_cheng()
        self._qing_kong()

    async def guan_bi(self) -> None:
        """关连接。**先收挂起任务再拆进程**（否则协程还握着已拆掉的 stdin）。"""
        for t in list(self._dai_dai):
            t.cancel()
        self._dai_dai.clear()
        await super().guan_bi()

    # ---------- 发指令 ----------
    async def _fa_chu_ming_ling(self, a1: str) -> None:
        """发一条指令 = 一个 `prompt` 命令。回合由 `jie_shou` 判（约束 3、4）。

        **响应不等**：`prompt` 的 `response` 只说「已接受」
        （`data.disposition` = started / queued / handled），等到它
        **证明不了任何事**，而且 pi 的处理是异步的（`handleCommand` 是
        async）。回合结果靠 `agent_settled` 那一帧。
        """
        await self._qing_qiu("prompt", {"message": a1}, QING_QIU_MIAO)
        self._zhuan_kaishi = time.monotonic()

    def jie_shou(self, a1: dict) -> dict | None:
        """**回合边界判定。这是这类适配器最承重的一行。**

        判错的后果（`chuan_shu` 文档里写过）：事件全翻译对了、单测全绿、
        真机上 `fasong()` 挂死到 15 分钟看门狗才被收走。

        **边界只有 `agent_settled`**（约束 3、4）：

        - `agent_end` 一律返回 None——它是「一次底层 run 结束」，
          后面还可能有自动重试 / 溢出恢复 / 压缩恢复；
          `willRetry=true` 更不能收（cc-connect 的 `handleEvent` 同样在这里 break）。
        - `turn_end` 更早，一个 run 里能有多次（工具调用前后各一次）。
        """
        if a1.get("type") != "agent_settled":
            return None
        # ⚠ **优先 `_wen_zheng`（最后一条非空 assistant message 的权威正文），
        # delta 累加器只作兜底。** 一个 run 里有多条 assistant 消息
        # （工具调用前后各一条），delta 累加器会把「让我先看看」这种
        # 中间话术与最终答案拼在一起；最后一条 message_end 才是答复。
        wen = self._wen_zheng or "".join(self._zhuan_wen)
        cuo = self._cuo_wen
        # ⚠ 判定落在「本回合有没有 errorMessage」这个量上，而不是
        # 「最后一条 assistant 消息的 stopReason」——后者会被后一次成功的
        # 消息覆盖掉，用户看到的是「跑完了但结论是失败」。
        xiao = {"resultText": wen, "isError": bool(cuo),
                "subtype": "error" if cuo else "completed",
                "durationMs": int((time.monotonic() - self._zhuan_kaishi) * 1000)
                if self._zhuan_kaishi else 0,
                "numTurns": 1, "totalCostUsd": 0.0,
                "sessionId": self.kehu_hui}
        if cuo:
            xiao["errorMessage"] = cuo
        self._qing_kong()
        return xiao

    def _qing_kong(self) -> None:
        """回合边界之后清累加器，否则下一回合的结果是两条回复拼一起。"""
        self._zhuan_wen = []
        self._si_wei_wen = []
        self._wen_zheng = ""
        self._cuo_wen = ""
        self._zhuan_kaishi = 0.0

    # ---------- 事件翻译 ----------
    def fan_yi(self, a1: str) -> None:
        """一行 stdout → 若干统一事件。**坏行不许吞掉整轮。**"""
        try:
            zhao = json.loads(a1)
        except json.JSONDecodeError:
            self._fa("error", {"code": "pi_bad_line",
                               "message": f"pi 输出了一行非 JSON：{a1[:200]}",
                               "recoverable": True})
            return
        if not isinstance(zhao, dict):
            return
        lei = str(zhao.get("type") or "")
        if lei == "response":
            self._da_dian(zhao)                     # 命令结果
        elif lei == "extension_ui_request":
            self._chui_qi(zhao)                    # 扩展对话框（阻塞，要回响应）
        elif lei:
            self._fan_gao_gao(zhao)

    def _fan_gao_gao(self, a1: dict) -> None:
        """会话事件 → 统一事件。判据来自 `docs/json.md` + 真机输出。"""
        lei = str(a1.get("type") or "")

        if lei == "agent_settled":
            jie = self.jie_shou(a1)
            if jie is not None:
                if jie.get("isError"):
                    self._fa("error", {"code": "pi_run_failed",
                                       "message": jie.get("errorMessage") or "回合失败",
                                       "recoverable": False})
                self._fa("result", jie)
                self._jie_shu_kao_ben(jie)
            return
        if lei == "message_update":
            self._kuai_liu(a1.get("assistantMessageEvent") or {})
            return
        if lei == "message_end":
            self._wenzi_jie(a1.get("message") or {})
            return

        # ---- 内容类：工具 ----
        if lei == "tool_execution_end":
            zhao = str(a1.get("toolCallId") or "")
            self._fa("tool_result", {"toolUseId": zhao,
                                     "toolName": str(a1.get("toolName")
                                                     or self.gong_ju.get(zhao) or "tool"),
                                     "text": self._gong_ju_mian(a1.get("result")),
                                     "isError": bool(a1.get("isError"))})
            return

        # ---- 状态类：只发 error，其余一律忽略 ----
        if lei == "auto_retry_end" and not a1.get("success"):
            # pi 的自动重试彻底失败。**必须在 agent_settled 之前发**——
            # 那之后的 errorMessage 已经不再被收走，界面就只剩一个空回合。
            self._cuo_wen = str(a1.get("finalError") or self._cuo_wen
                                or "pi 自动重试仍失败")
            return
        if lei == "compaction_end":
            cuo = str(a1.get("errorMessage") or "")
            if cuo:
                self._fa("error", {"code": "pi_compaction_failed",
                                   "message": cuo, "recoverable": True})
            return
        if lei == "extension_error":
            self._fa("error", {"code": "pi_extension_error",
                               "message": str(a1.get("error") or "pi 扩展抛了异常"),
                               "recoverable": True})
            return

        # 其余全部忽略：`agent_start` / `turn_start` / `turn_end` /
        # `message_start` / `text_start|delta|end` 之外的流式子事件 /
        # `tool_execution_start|update` / `bash_execution_update` /
        # `queue_update` / `entry_appended` / `session_info_changed` /
        # `thinking_level_changed` / `compaction_start` /
        # `auto_retry_start` / `summarization_retry_*` / `session`（json 模式才有）。
        # 它们不进统一模型，硬翻译只会造出谁都不用的假字段。
        # ⚠ **`turn_end` 故意落在这里**：它比 `agent_settled` 早（约束 3）。

    def _kuai_liu(self, a1: dict) -> None:
        """`message_update` 的 `assistantMessageEvent`：只发 `chunk`（打字机效果）。

        **正文与思考必须分开**（判据落在 `messageKind` 上），
        混成同一个 kind 的话界面上思考会被当成回复正文显示出去。
        `toolcall_end` 也从这里出去（它是模型侧决定「要调这个工具」的那一刻）。
        """
        lei = str(a1.get("type") or "")
        if lei == "toolcall_end":
            tc = a1.get("toolCall") or {}
            # ⚠ **不发 `tool_execution_start` 的 tool_use**：pi 为同一次工具
            # 调用发两条（`toolcall_end` 是模型侧决定，`tool_execution_start`
            # 是执行侧开始），两条都发界面就出现两张一样的工具卡。
            # cc-connect 也只取 `toolcall_end`（session.go `emitToolFromMessage`）。
            zhao = str(tc.get("id") or "")
            self.gong_ju[zhao] = str(tc.get("name") or "tool")
            self._fa("tool_use", {"messageId": self.xiang_id, "toolUseId": zhao,
                                  "toolName": str(tc.get("name") or "tool"),
                                  "toolInput": tc.get("arguments") or {}})
            return
        delta = str(a1.get("delta") or "")
        if not delta:
            return
        if lei == "text_delta":
            self._zhuan_wen.append(delta)
            self._fa("chunk", {"messageId": self.xiang_id, "delta": delta,
                               "messageKind": "text"})
        elif lei == "thinking_delta":
            self._si_wei_wen.append(delta)
            self._fa("chunk", {"messageId": self.xiang_id, "delta": delta,
                               "messageKind": "thinking"})

    def _wenzi_jie(self, a1: dict) -> None:
        """`message_end`：本条消息的权威终态。

        - `role == "assistant"`：正文落成一条 `text`（约束 5），
          失败时把 `errorMessage` 攒起来（约束 4）。
        - `role == "toolResult"`：**故意不发 `text`**，它已经在
          `tool_execution_end` 里作为 `tool_result` 发过了（那是带
          `toolUseId` 的那一份，能配对）。这里再发一遍界面会多一条气泡。
        - `role` 是 `user` / `system`：用户输入与系统提示，**不回显**
          （否则界面把用户刚说的话再显示一遍）。
        """
        role = str(a1.get("role") or "")
        if role == "assistant":
            if str(a1.get("stopReason") or "") == "error":
                msg = str(a1.get("errorMessage") or "")
                if msg:
                    self._cuo_wen = msg
            wen = self._nei_rong_wen(a1.get("content"))
            if wen:
                self._wen_zheng = wen
                self._fa("text", {"messageId": self.xiang_id, "text": wen})
            # ⚠ **空 content 不动 `_wen_zheng`**：这一条是「工具调用轮」的
            # assistant message（真机上 `content: []` + `stopReason:"toolUse"`）。
            # 清掉它不会更准——这一轮真正的答复在后面那条消息里（会覆盖回来），
            # 而工具调用后回合直接结束（中止/报错）时，清掉就等于把已经说过的话丢了。
            return
        if role == "toolResult":
            return
        # user / system / 未知 role：忽略。

    # ---------- 审批与提问（挂起通道）----------
    def _chui_qi(self, a1: dict) -> None:
        """`extension_ui_request`。

        **fire-and-forget 的五种必须直接忽略**（约束 0 那张表）：
        `notify` / `setStatus` / `setWidget` / `setTitle` / `set_editor_text`
        在 pi 那边**没有挂起的 Promise**（`dist/modes/rpc/rpc-mode.js` 里
        它们不往 `pendingExtensionRequests` 里塞东西），回响应是无操作。

        对话框四种则**必须回**：pi 那边 Promise 挂着，回调没来就一直等，
        扩展（permission-gate 那类）就一直卡住 → 回合挂到超时。
        """
        fang = str(a1.get("method") or "")
        if fang not in self.DUI_HUA:
            return
        ext_id = str(a1.get("id") or "")
        if not ext_id:
            return
        if fang == "confirm":
            self._qi_ren_wu(
                "permission",
                {"toolUseId": f"pi-ext-{ext_id}", "toolName": "extension_confirm",
                 "toolInput": {"title": str(a1.get("title") or ""),
                               "message": str(a1.get("message") or ""),
                               "method": fang},
                 "title": str(a1.get("title") or "pi 扩展想跟你确认一件事")},
                self._jue_ding, ext_id)
            return
        if fang == "select":
            xuan = self._xuan_xiang(a1.get("options"))
            self._qi_ren_wu(
                "question",
                {"toolUseId": f"pi-ext-{ext_id}",
                 "questions": [{"id": ext_id, "question": str(a1.get("title") or "选一个"),
                                "header": "Select", "options": xuan}],
                 "title": str(a1.get("title") or "pi 扩展让你选一个")},
                lambda zhao: self._xuan_jie_xi(zhao, xuan), ext_id)
            return
        # input / editor：都是自由文本，同一条回路。
        # ⚠ **不要再包一层 lambda**：`self._wen_ben_jie_xi` 返回的已经是
        # 整个响应 dict（`{"value":…}` 或 `{"cancelled":true}`），
        # 包一层会变成 `{"value": {"value": …}}` —— pi 的解析器
        # `"value" in r ? r.value : undefined` 拿到的是个对象，
        # 扩展会拿它去当字符串用。
        self._qi_ren_wu(
            "question",
            {"toolUseId": f"pi-ext-{ext_id}",
             "questions": [{"id": ext_id, "question": str(a1.get("title") or "请输入"),
                            "header": "input", "options": []}],
             "title": str(a1.get("title") or "pi 扩展要一段文字")},
            self._wen_ben_jie_xi, ext_id)

    def _qi_ren_wu(self, a1: str, a2: dict, a3: Any, a4: str) -> asyncio.Task | None:
        """起一个挂起任务：交给 Bridge 等用户决定，再把结果回写给 pi。

        **必须起任务而不是直接 await**：调用点在读循环里（`fan_yi`），
        那里不能 await —— await 的话审批还没收口，读循环就停了，
        而 pi 的响应要从同一条 stdin 写回去，永远等不到。
        四个对话框方法**都必须回**（见 `_chui_qi`），所以这里没有「安静
        退化成取消」那条路：没有 loop 时回 `{"cancelled": True}`，
        pi 那边拿到的 `undefined` / `false` 与「用户按了取消」同义。
        """
        loop = self.loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                self._hui_dao_ui(a4, {"cancelled": True})
                return None

        async def zhuo() -> None:
            try:
                zhao = await self._cheng(a1, a2)
            except asyncio.CancelledError:
                # 关连接时要给 pi 一个明确答复，否则它的 Promise 一直挂着。
                self._hui_dao_ui(a4, {"cancelled": True})
                raise
            except Exception:  # noqa: BLE001
                self._hui_dao_ui(a4, {"cancelled": True})
                return
            self._hui_dao_ui(a4, a3(zhao))

        fu = loop.create_task(zhuo())
        self._dai_dai.add(fu)
        fu.add_done_callback(self._dai_dai.discard)
        return fu

    # ---------- 命令收发（pi 的四条记录族，不是 JSON-RPC）----------
    async def _qing_qiu(self, a1: str, a2: dict | None,
                        a3: float = QING_QIU_MIAO) -> Any:
        """发一条命令并等它的 `response`。**id 单调递增、不复用。**"""
        self._qing_qiu_id += 1
        bian = f"lifeos-{self._qing_qiu_id}"
        fu = (self.loop or asyncio.get_event_loop()).create_future()
        self._qing_qiu_deng[bian] = fu
        cmd: dict[str, Any] = {"id": bian, "type": a1}
        if a2:
            cmd.update(a2)
        try:
            await self._xie_xia(cmd)
            zhao = await asyncio.wait_for(fu, a3)
        finally:
            self._qing_qiu_deng.pop(bian, None)
        if isinstance(zhao, dict) and not zhao.get("success", False):
            raise RuntimeError(f"pi {a1} 失败：{zhao.get('error') or zhao}")
        return (zhao or {}).get("data")

    async def _xie_xia(self, a1: dict) -> None:
        """写一行 JSON 到 stdin。**必须带换行且 drain**——pi 按行成帧
        （`docs/rpc.md` 的 Framing 段：strict JSONL，LF 分隔），
        少换行 pi 那边就一直等，症状是「握手全部超时」。"""
        if self.jin is None or self.jin.stdin is None:
            raise RuntimeError("pi 子进程没起来")
        self.jin.stdin.write((json.dumps(a1, ensure_ascii=False) + "\n").encode("utf-8"))
        await self.jin.stdin.drain()

    def _da_dian(self, a1: dict) -> None:
        """`response` → 唤醒对应 Future。

        **按 `id` 配对，不靠顺序**：pi 的命令处理是异步的
        （`docs/rpc.md`：「Command handling is asynchronous, so clients should
        correlate by ID rather than response order」）。
        """
        bian = a1.get("id")
        if not isinstance(bian, str):
            return
        fu = self._qing_qiu_deng.get(bian)
        if fu is not None and not fu.done():
            fu.set_result(a1)

    def _hui_dao_ui(self, a1: str, a2: dict) -> None:
        """回 `extension_ui_response`。**同步写**：调用点在读循环或挂起任务里，
        两个地方都不该为一次写盘 await。"""
        if self.jin is None or self.jin.stdin is None:
            return
        xiang: dict[str, Any] = {"type": "extension_ui_response", "id": a1}
        xiang.update(a2)
        try:
            self.jin.stdin.write((json.dumps(xiang, ensure_ascii=False) + "\n")
                                 .encode("utf-8"))
        except Exception:  # noqa: BLE001
            pass

    # ---------- 进程回收（Windows 特有）----------
    async def _ting_zhi_chi_cheng(self) -> None:
        """关进程。覆写基类：**必须杀整棵树**（约束 2）。

        基类用的是 `jin.kill()`，只杀得掉 `pi.cmd` 这个 cmd 包装层，
        真正的 `node …/cli.js` 会活到 Bridge 退出之后还在跑用户项目。
        先杀树再让基类拆管道。
        """
        self._sha_chan_jin_cheng()
        await super()._ting_zhi_chi_cheng()

    async def _zhong_zhi_chi_cheng(self) -> None:
        """杀进程不拆管道（中断≠关闭）。同样要杀整棵树（约束 2）。"""
        self._sha_chan_jin_cheng()

    def _sha_chan_jin_cheng(self) -> None:
        """`taskkill /T /F` 杀进程树（仅 Windows）。

        为什么不是 `jin.kill()`：`pi.cmd` 是 `cmd /c node …` 的包装层，
        kill 它只断掉包装层。实测 kill 之后 `tasklist` 里 node.exe 仍在，
        也就是 agent 进程成了孤儿。`/T` 杀子孙、`/F` 强杀。
        `run.py` 杀 Bridge 孤儿时也走同一条路（`shang_si`）。
        """
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
            # 杀不动也要继续往下走：管道拆不掉的话 `guan_bi` 会挂到超时，
            # 而那比留一个孤儿严重。基类后面还有 `jin.kill()` 兜底。
            pass

    # ---------- 答案翻译 ----------
    @staticmethod
    def _shi_allow(a1: Any) -> bool:
        """Bridge 回来的决定怎么算「允许」。

        `arbiter.shou` 对 allow 回 `PermissionResultAllow`，对 deny 回
        `PermissionResultDeny`。**不能用 `if zhao:` 判**——`Deny` 也是真对象。
        判错的方向必须是 deny：安全侧默认。
        """
        if a1 is None:
            return False
        xing = getattr(a1, "behavior", None)
        if xing is not None:
            return str(xing).lower() in ("allow", "accept")
        if isinstance(a1, dict):
            return bool(a1.get("allowed"))
        return False

    def _jue_ding(self, a1: Any) -> dict[str, Any]:
        """allow/deny → `{"confirmed": bool}`。

        **必须是 `confirmed`，不能是 `cancelled`**：pi 的 confirm 解析器
        （`dist/modes/rpc/rpc-mode.js` 的 `createExtensionUIContext.confirm`）
        是 `"cancelled" in r ? false : "confirmed" in r ? r.confirmed : false`——
        两个键都合法，但只有 `confirmed:false` 才表达「用户明确拒绝了」。
        `cancelled` 在扩展那边与「超时」「没答复」同义，permission-gate
        这类扩展会把它当成「用户没表态」而放行。
        """
        return {"confirmed": self._shi_allow(a1)}

    @classmethod
    def _xuan_jie_xi(cls, a1: Any, a2: list[str]) -> dict[str, str]:
        """`select` 的答案：**原样回第一个候选 label**。

        pi 要的是一个 option 字符串（`docs/rpc-extension-ui.md`：
        「`value` (the selected option string)」）。Bridge 侧
        `arbiter._du_wen` 把结构化答案拼成自然语言
        （`PermissionResultDeny(message="用户对问题的回答：\\n- …")`），
        所以只能**按候选闭集匹配回 label**：候选集是我们自己发给 pi 的，已知。
        匹配不上就交 `cancelled`——pi 会拿到 `undefined`，那是对的方向
        （比回一个它不认识的选项好：扩展会拿它去索引自己的数组，越界）。
        """
        wen = str(getattr(a1, "message", "") or "")
        if not cls._shi_allow(a1):
            return {"cancelled": True}
        for biao in a2 or []:
            if biao and biao in wen:
                return {"value": biao}
        return {"cancelled": True}

    @staticmethod
    def _wen_ben_jie_xi(a1: Any) -> dict[str, Any]:
        """`input` / `editor` 的答案：把自然语言答案剥成纯文本。

        allow 时 `arbiter` 回的 message 形如
        `用户对问题的回答：\\n- 用户输入的内容`，而 pi 要的是一个裸字符串
        （扩展会把它直接当文件内容 / 命令参数用）。⇒ 剥掉前缀那几行。
        剥不出来就交 `cancelled`（pi 侧拿到 `undefined`）。
        """
        if not PiAdapter._shi_allow(a1):
            return {"cancelled": True}
        wen = str(getattr(a1, "message", "") or "").strip()
        if not wen:
            return {"cancelled": True}
        for xian in ("用户对问题的回答：", "用户对问题的回答:"):
            if wen.startswith(xian):
                wen = wen[len(xian):].strip()
                break
        # 答案走 arbiter 时是 `- <值>` 的列表形状，值本身可能是多行。
        # ⚠ 用 `startswith("- ")` 判会漏掉只有破折号的情形（`用户拒绝回答` 时
        # 拼出来的是 `…\n- `，剥完前缀只剩一个 `-`），于是回出去的是字面量
        # `"-"` —— 扩展会拿它当用户填的内容用，比 cancelled 坏得多。
        if wen.startswith("-"):
            wen = wen[1:].strip()
        return {"value": wen or None} if wen else {"cancelled": True}

    # ---------- 形状工具 ----------
    @staticmethod
    def _nei_rong_wen(a1: Any) -> str:
        """`content` 数组 → 文本（只取 `type=="text"` 块）。

        **不能只取 `[0]`**：一条 assistant 消息里可以有多个 text 块
        （工具调用前后各一段，就是两条 message 但也可能是同一 message 里的两块），
        只取第一块等于把后半截回复丢掉。
        """
        if isinstance(a1, str):
            return a1
        if not isinstance(a1, list):
            return ""
        return "".join(str(b.get("text") or "")
                       for b in a1
                       if isinstance(b, dict) and b.get("type") == "text")

    @staticmethod
    def _gong_ju_mian(a1: Any) -> str:
        """工具结果 → 文本。优先 `content[].text`，否则退回整份 JSON。

        `structuredContent` 里是结构化产物（stdout / 退出码），展示价值低，
        所以不进正文；但 `content` 为空时**不能什么都不给**——
        界面上一条空的工具结果没法排查。
        """
        if isinstance(a1, dict):
            wen = PiAdapter._nei_rong_wen(a1.get("content"))
            if wen:
                return wen
            try:
                return json.dumps(a1, ensure_ascii=False)[:500]
            except (TypeError, ValueError):
                return ""
        return str(a1 or "")

    @staticmethod
    def _xuan_xiang(a1: Any) -> list[str]:
        """`extension_ui_request.options` → label 列表。

        pi 发两种形状（cc-connect 的 `forwardSelect` 记了这条）：
        `["Red","Green"]` 与 `[{label,description}]`。两种都要收，
        只认字符串会让带描述的选项被静默丢掉。
        """
        if not isinstance(a1, list):
            return []
        out: list[str] = []
        for xuan in a1:
            if isinstance(xuan, str):
                if xuan:
                    out.append(xuan)
            elif isinstance(xuan, dict):
                for k in ("label", "text", "name", "value"):
                    biao = str(xuan.get(k) or "")
                    if biao:
                        out.append(biao)
                        break
        return out