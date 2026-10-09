"""OpenCode 适配器：接 `opencode run --format json`（v3.0 任务 5）。

**协议事实全部来自本机 1.18.34 的真实 stdout，不是抄 cc-connect 源码**——
抄源码会踩三个坑（见文件头末尾）。

## 六条真机约束（看文档看不出来的那种）

1. **`--dangerously-skip-permissions` 在本机版本已不存在。**
   cc-connect 的 `agent/opencode/session.go:181` 还在传它——照抄直接参数报错。
   本机 `opencode run --help` 里只有 `--auto`（语义是「自动批准未被显式拒绝
   的权限」），**本适配器不传它**：Bridge 不替用户决定权限策略。

2. **回合边界是 `type=="step_finish"` 且 `part.reason=="stop"`。**
   `reason` 还可能是 `"tool-calls"`——那是一个 step 结束时，**一个回合里
   会出现多次**（每调一次工具就多一个 step）。拿 `step_finish` 当边界
   ⇒ 第一次工具调用后就把回合收走，后面的正文全丢。

3. **`type=="error"` 之后回合不会收口。** 真机 provider 偶发
   `{"type":"error",…,"error":{"name":"UnknownError","data":{"message":"…empty response…"}}}`，
   **它后面没有 `step_finish`**。等 `step_finish` 就挂死到 15 分钟看门狗。
   ⇒ 收到 `error` 必须立刻收口。同一条指令重试即正常。

4. **`tool_use` 与 `tool_result` 合并在同一个 `part.state` 里**，不是两条事件。
   `state.status` 可为 `running` / `completed` / `error`。

5. **session id 在每一行的 `sessionID` 字段**，第一行 `step_start` 就有
   ⇒ 可以在第一回合就报 session（比 kimi 早，它只能等回合末尾）。

6. **spawn 后必须立刻关 stdin**（`_qi_chi_cheng` 覆写）。`opencode run`
   会探测 stdin：非 TTY 的管道开着不关，它等 piped 输入的 EOF 等到看门狗，
   stdout 零输出——症状与「模型不通 / SQLite 锁」一模一样。2026-10-06
   分岔实验实锤（stdin 开着 45s 零行 vs 关闭后 12s 出全套事件），
   三条 L-C 红即此根因。

## wire（真机抓的原始行，截断）

    {"type":"step_start","timestamp":…,"sessionID":"ses_xxx",
     "part":{"id":"prt_…","messageID":"msg_…","type":"step-start"}}
    {"type":"tool_use","sessionID":"ses_xxx",
     "part":{"type":"tool","tool":"bash","callID":"7b1cfa04-…",
             "state":{"status":"completed","input":{"command":"echo ox"},
                      "output":"ox\n","metadata":{"exit":0}}}}
    {"type":"step_finish","sessionID":"ses_xxx","part":{"reason":"tool-calls",…}}
    {"type":"text","sessionID":"ses_xxx","part":{"type":"text","text":"收到"}}
    {"type":"step_finish","sessionID":"ses_xxx","part":{"reason":"stop",…}}
"""

from __future__ import annotations

import json
from typing import Any

from lifeos.bridge.adapters.liu_xing import LiuXingAdapter


class OpencodeAdapter(LiuXingAdapter):
    """一个实例 = 一个 opencode 会话（每条指令一个新进程）。"""

    agentId = "opencode"
    label = "OpenCode"

    #: 会话 id 落在 `claudeSessionId`（前端契约只认这一个键）。
    dui_hui_id = "claudeSessionId"
    #: 一次性进程（每条指令一个新进程）。
    yi_ci_xing = True
    xu_pei_zhuang = False

    #: **声明真能兑现的两档**（2026-10-06 真机核实）：
    #:   manual  → 不加旗标：CLI 按它自己的权限配置跑，Bridge 不额外放权；
    #:   dontAsk → `--auto`（`opencode run --help` 原文「auto-approve permissions
    #:             that are not explicitly denied (dangerous!)」，与
    #:             「只在规则明确禁止时停下」逐字对应；旗标在 `run` 模式下
    #:             真机验证可被接受）。
    #: `plan` 要走 `--agent plan`，与 permissionMode 不是同一机制（见约束 1 的
    #: 讨论），不声明；`acceptEdits` / `auto` 没有对应旗标，硬映射就是 UI 承诺
    #: 兑现不了的能力。模式在会话创建时定死、不定义 `gai_moshi`
    #: （基类故意不定义，`http._gai_moshi` 用 `hasattr()` 判）。
    MOSHI_ZI = frozenset({"manual", "dontAsk"})

    ZHI_LING = ["opencode"]

    #: **`--version` 而不是基类默认的 `--help`。** 基类抓版本号靠
    #: `(\d+\.\d+\.\d+)` 正则，而 `opencode --help` 的正文里有
    #: `--print-logs`、`--log-level` 等，**实测正则会匹配到 `--print-logs`
    #: 里的 `127.0.0`**，界面上显示一个完全不相干的版本号。
    CE_WU_TOU = ["--version"]

    def __init__(self, a1: Any = None, a2: Any = None) -> None:
        super().__init__(a1, a2)
        #: 本回合的 token 统计（`step_finish` 带 `tokens`，`cost` 在 step 上）。
        self._token: dict[str, Any] = {}
        #: 本回合 error 收口过没有。**防的是「清理之后的第二条 error」**：
        #: `jie_shou` 的 `_fan_le` 闸在 `_qing_kong()` 里复位（那是给下一回合
        #: 用的），防不了同一回合里 opencode 重试连吐的第二条 error 再走一遍
        #: 收口 ⇒ 同一回合发两个 result 帧。按 spawn 重置（`_fan_yi_zhun_bei`），
        #: 「同一条指令重试即正常」靠的就是这个重置。
        self._cuo_shou_kou_le = False

    # ---------- 发指令 ----------
    def _zi_ling(self, a1: dict) -> list[str]:
        """argv：`run --format json [--auto] [-s <id>] <指令>`。

        ⚠ **不加 `--dangerously-skip-permissions`**（约束 1，本版本已无此参数）。
        `--format json` 恒带：少了它 stdout 上是格式化文本，一行 JSON 都收不到。

        `self.moshi` 在 `kaishi()` 里存好（`xin_jian` 传的是闸门 1 校验过的
        `effectiveMode`）；按 `MOSHI_ZI` 的映射翻成旗标。未知值按 manual 处理
        （不加旗标）——闸门 1 已保证只会有声明过的值，这是防御性兜底。
        """
        can: list[str] = ["run", "--format", "json"]
        if self.moshi == "dontAsk":
            can += ["--auto"]
        if self.kehu_hui:
            can += ["--session", self.kehu_hui]
        return can + [self._wen]

    async def _fan_yi_zhun_bei(self) -> None:
        """重置本回合的状态。指令原文由基类存进 `self._wen`。

        一次性进程一回合一个新进程，这里就是「新回合」的起点——上一回合
        不管是正常收口（`jie_shou` 已清）、被中断（`liu_xing._zhong_duan`
        已清）还是中途崩掉（**没人清**），都不许把状态带过来。`_qing_kong`
        不碰 `_fa_le_session` / `kehu_hui`（续接靠它们），放心调。
        """
        self._token = {}
        self._cuo_shou_kou_le = False
        self._qing_kong()

    async def _qi_chi_cheng(self, a1: dict) -> None:
        """spawn 后**立刻关掉 stdin**（约束 6，2026-10-06 分岔实验实锤）。

        基类给所有子进程 `stdin=PIPE`，而一次性进程从不写它——对 kimi/hermes
        无所谓（它们不读 stdin），但 **`opencode run` 会探测 stdin**：非 TTY
        的管道开着不关，它以为还有 piped 输入要读，**等 EOF 等到看门狗**，
        stdout 一个字节都不吐——症状与「模型不通 / SQLite 锁」一模一样
        （追了两天没定位的三条 L-C 红就是它）。分岔实验（同暗号
        同 argv 同 cwd）：stdin 开着 45s 零行且进程活着；spawn 后关闭
        12s 出全套 step_start/text/step_finish，14s 跑完一回合。
        ⇒ 关 stdin = 给 EOF，opencode 立即按 argv 里的指令跑。

        **只 close 不 `await wait_closed()`**：Windows Proactor 上那步会等
        对端把读端关掉，进程没退就挂（`chuan_shu._ting_zhi_chi_cheng`
        的注释记着同款互等）。
        """
        await super()._qi_chi_cheng(a1)
        jin_stdin = self.jin.stdin if self.jin is not None else None
        if jin_stdin is not None:
            jin_stdin.close()

    # ---------- wire 翻译 ----------
    def fan_yi(self, a1: str) -> None:
        """一行 stdout → 若干统一事件。**坏行不许吞掉整轮**（与 codex/pi 同款）。"""
        try:
            zhao = json.loads(a1)
        except (ValueError, TypeError):
            self._fa("error", {"code": "opencode_bad_line",
                               "message": f"opencode 输出了一行非 JSON：{a1[:200]}",
                               "recoverable": True})
            return
        if not isinstance(zhao, dict):
            return
        lei = str(zhao.get("type") or "")
        # session id 每行都有 ⇒ 第一行就能报（约束 5）。
        self._fa_session(str(zhao.get("sessionID") or ""))
        if lei == "text":
            self._wen_zi(zhao)
        elif lei == "tool_use":
            self._gong_ju(zhao)
        elif lei == "step_finish":
            self._bu_zhou(zhao)
        elif lei == "error":
            self._cuo_ji(zhao)

    def _wen_zi(self, a1: dict) -> None:
        """`type:"text"`：正文在 `part.text`。"""
        wen = str(self._dui_xiang(a1.get("part"), "text", ""))
        if not wen:
            return
        self._zhuan_wen.append(wen)
        self._fa("text", {"messageId": self.xiang_id, "text": wen})

    def _gong_ju(self, a1: dict) -> None:
        """`type:"tool_use"`：**工具结果也在这条事件的 `part.state` 里**（约束 4）。

        ⚠ `state.status == "running"` 时只有 input 没有 output，
        **那时只发 `tool_use` 不发 `tool_result`**——发了就是一条空的工具结果，
        界面上工具卡永远收不了口。
        """
        part = self._dui_xiang(a1, "part", {})
        zhao = str(part.get("callID") or part.get("id") or "")
        ming = str(part.get("tool") or "tool")
        if not zhao:
            return
        self.gong_ju[zhao] = ming
        self._fa("tool_use", {"messageId": self.xiang_id, "toolUseId": zhao,
                              "toolName": ming,
                              "toolInput": self._dui_xiang(part.get("state"), "input", {})})
        state = self._dui_xiang(part, "state", {})
        zhuang = str(state.get("status") or "")
        if zhuang == "running":
            return
        self._fa("tool_result", {"toolUseId": zhao, "toolName": ming,
                                 "text": str(state.get("output") or ""),
                                 "isError": zhuang == "error"})

    def _bu_zhou(self, a1: dict) -> None:
        """`type:"step_finish"`：**只有 `part.reason=="stop"` 才是回合边界**（约束 2）。

        `reason == "tool-calls"` 每调一次工具就出现一次，拿它当边界
        ⇒ 第一次工具调用后就把回合收走，后面的正文全丢。
        """
        part = self._dui_xiang(a1, "part", {})
        self._token = self._dui_xiang(part, "tokens", {}) or {}
        if str(part.get("reason") or "") != "stop":
            return
        self.jie_shou(a1)

    def _cuo_ji(self, a1: dict) -> None:
        """`type:"error"`：**必须主动收口**（约束 3）。

        真机实测：provider 偶发 `UnknownError / empty response`，
        **它后面没有 `step_finish`** ⇒ 等边界就挂死到 15 分钟看门狗。
        症状是「Agent 无响应」而不是「报错了」。

        ⚠ **一回合只触发一次**（`_cuo_shou_kou_le` 闸，实测收口）：
        opencode 内部重试会在同一回合连吐多条 error，第一条已经收口发帧，
        后续的再走一遍就是给同一回合发第二个 `result` 帧（空正文）+
        重复的 error 帧。`jie_shou` 的 `_fan_le` 帮不上——它在 `_qing_kong()`
        里复位，防的是同一事件的重入，不是清理之后的第二条线。
        """
        if self._cuo_shou_kou_le:
            return
        self._cuo_shou_kou_le = True
        err = self._dui_xiang(a1, "error", {})
        data = self._dui_xiang(err, "data", {})
        # 没有错误信息时兜底成「已经说过的话 + 一句说得出原因的说明」——
        # 空字符串会让界面显示一个空的错误框，比这句更糟。
        msg = str(data.get("message") or err.get("message")
                  or ("".join(self._zhuan_wen) or "opencode 报错了但没给原因"))
        self._cuo_wen = msg
        # **先发 error 帧再收口**：反过来的话上层的 result 帧先于 error 到达，
        # 界面上「跑完了」出现在「出错了」之前。
        self._fa("error", {"code": "opencode_error", "message": msg,
                           "recoverable": True})
        self.jie_shou(a1)

    # ---------- 回合边界 ----------
    def _jie_shu_bian_jie(self, a1: dict) -> dict | None:
        """**两条边界**（这是三个适配器里唯一有两条的）：

        1. `step_finish` 且 `part.reason == "stop"` —— 正常收口。
        2. `type == "error"` —— 异常收口（约束 3：后面没有 `step_finish`）。

        ⚠ **`error` 的判据是「这一行是 error」本身**，不是「有没有错误信息」——
        没有信息时也必须收口（`msg` 兜底成一句说得出原因的话）。
        """
        lei = str(a1.get("type") or "")
        if lei == "error":
            return {"resultText": "".join(self._zhuan_wen),
                    "isError": True, "subtype": "error",
                    "errorMessage": self._cuo_wen or "opencode 报错了但没给原因"}
        if lei != "step_finish":
            return None
        part = self._dui_xiang(a1, "part", {})
        if str(part.get("reason") or "") != "stop":
            return None
        return {"resultText": "".join(self._zhuan_wen),
                "isError": bool(self._cuo_wen),
                "subtype": "error" if self._cuo_wen else "completed",
                "totalCostUsd": float(part.get("cost") or 0.0)}