"""Hermes 适配器：接 `hermes chat -q --format stream-json`（v3.0 任务 5）。

**协议事实全部来自本机 v0.21.5 的真实 stdout，不是抄 cc-connect/clawd**——
两份参考仓库都没有它的 CLI 协议实现（方案 §8.2 曾据此把它移出范围，
那条理由**已被真机推翻**，见文件头约束 1）。

## 六条真机约束（看文档看不出来的那种）

1. **CLI 协议形态存在，方案 §8.2 的理由不成立。**
   本机 `hermes chat -q <query> --format stream-json` 可用，是一次性进程 +
   stream-json，与 kimi / opencode 同族。方案 §8.2 写「in-process plugin，
   cc-connect 无实现」——那是查参考仓库得出的结论，不是 CLI 的真实形态。

2. **stderr 上有非 JSON 的纯文本，`--format stream-json` 不抑制它。**
   真机：CLI 自己会打一行 `session_id: 20261005_123701_ebc414`，
   还混有 Python 的 `SyntaxWarning`（`shell.py:13: SyntaxWarning: …`）。
   ⇒ **只解析 stdout**；stderr 由基类攒进 `cuo_wei`，只在错误信息里出现。

3. **`tool_use` 没有 id 字段**（kimi 与 opencode 都有）⇒ 必须自造 id，
   否则 `tool_use` 与 `tool_result` 配不上对，前端工具卡永远收不了口。

4. **`tool_result.output` 是双层 JSON 字符串。**
   外层 `{"output":"…","exit_code":0,"error":null}` 整个塞在 `output` 字段里，
   要 `json.loads` **两次**才拿得到命令输出正文。

5. **`text` 帧分多片**（流式）⇒ 累加成一条完整 `text`，不能每片发一条。
   真机上两片拼起来才是完整答复，每片发一条会让界面出现多条碎消息。
   权威全文在 `result.text`。

6. **工具失败的判据是外层 `is_error`**，不是内层 `error`——
   内层 `error` 可能为 `null` 而外层 `is_error` 为 `true`。

## wire（真机抓的原始行）

    {"type":"system","subtype":"init","session_id":"20261005_123701_ebc414","timestamp":…}
    {"type":"tool_use","name":"terminal","input":{"command":"echo hx"},"timestamp":…}
    {"type":"tool_result","name":"terminal",
     "output":"{\"output\":\"hx\",\"exit_code\":0,\"error\":null}",
     "duration_ms":11715,"is_error":false,"timestamp":…}
    {"type":"text","text":"\\n\\n完成 —","timestamp":…}
    {"type":"text","text":" bash 执行 `echo hx`，输出 `hx`。","timestamp":…}
    {"type":"result","exit_code":0,"text":"完整最终答复","tokens":{…},"duration_ms":31617}
"""

from __future__ import annotations

import json
from typing import Any

from lifeos.bridge.adapters.liu_xing import LiuXingAdapter


class HermesAdapter(LiuXingAdapter):
    """一个实例 = 一个 hermes 会话（每条指令一个新进程）。"""

    agentId = "hermes"
    label = "Hermes Agent"

    #: 会话 id 落在 `claudeSessionId`（前端契约只认这一个键）。
    dui_hui_id = "claudeSessionId"
    #: 一次性进程（每条指令一个新进程）。
    yi_ci_xing = True
    xu_pei_zhuang = False

    #: **声明真能兑现的两档**（2026-10-06 真机核实）：
    #:   manual  → 不加旗标：CLI 按它自己的权限配置跑（危险命令走它自己的审批）；
    #:   dontAsk → `--yolo`（`hermes chat --help` 原文「Bypass all dangerous
    #:             command approval prompts」，旗标在 `-q --format stream-json`
    #:             下真机验证可用）。
    #: ⚠ **`--safe-mode` 不是权限档**——help 原文是「Troubleshooting mode:
    #: disable ALL customizations」（排障开关：关配置/记忆/插件/MCP）。
    #: 早前把它当成 sandbox 权限面的想法作废。模式在会话创建时定死，
    #: 不定义 `gai_moshi`（基类故意不定义，`http._gai_moshi` 用 `hasattr()` 判）。
    MOSHI_ZI = frozenset({"manual", "dontAsk"})

    ZHI_LING = ["hermes"]

    #: **`--version` 而不是基类默认的 `--help`。** 基类抓版本号靠
    #: `(\d+\.\d+\.\d+)` 正则——本机 `hermes --version` 输出
    #: `Hermes Agent v0.21.5+7011.g4393341 (2026.9.24)`，
    #: 正则会正确抓到 `0.21.5`（已验）。而 `--help` 的正文里没有版本号，
    #: 正则不匹配 ⇒ 返回可执行文件路径。
    CE_WU_TOU = ["--version"]

    def __init__(self, a1: Any = None, a2: Any = None) -> None:
        super().__init__(a1, a2)
        #: **同名工具的第几次调用**（约束 3：`tool_use` 没有 id，自造 id 要靠它
        #: 保证不撞）。`tool_result` 只给 `name`，靠它反查是哪一次。
        self._ci: dict[str, int] = {}
        #: 最近的 `tool_use` 帧 id 队列，按 `name` 分桶。`tool_result` 按
        #: name 取最早未配对的那一条（FIFO）——同名的并发调用按发生顺序配。
        self._dai_pei: dict[str, list[str]] = {}
        #: 本回合的 token 统计（`result` 帧带 `tokens`）。
        self._token: dict[str, Any] = {}

    # ---------- 发指令 ----------
    def _zi_ling(self, a1: dict) -> list[str]:
        """argv：`chat --format stream-json [--yolo] [--resume <id>] -q <指令>`。

        `--format stream-json` 恒带：少了它 stdout 是纯文本，一行 JSON 都收不到。

        `self.moshi` 在 `kaishi()` 里存好（`xin_jian` 传的是闸门 1 校验过的
        `effectiveMode`）；按 `MOSHI_ZI` 的映射翻成旗标。未知值按 manual 处理
        （不加旗标）——闸门 1 已保证只会有声明过的值，这是防御性兜底。
        """
        can: list[str] = ["chat", "--format", "stream-json"]
        if self.moshi == "dontAsk":
            can += ["--yolo"]
        if self.kehu_hui:
            can += ["--resume", self.kehu_hui]
        return can + ["-q", self._wen]

    async def _fan_yi_zhun_bei(self) -> None:
        """重置本回合的 id 计数与待配对队列（约束 3 的自造 id 依赖它）。

        ⚠ **`_dai_pei` 必须清**：不清的话上一回合没配对完的 `tool_use`
        会让这一回合的 `tool_result` 配到上一条 id 上，界面上的工具卡
        显示成「上一条工具的结果」。
        """
        self._ci = {}
        self._dai_pei = {}
        self._token = {}

    # ---------- wire 翻译 ----------
    def fan_yi(self, a1: str) -> None:
        """一行 stdout → 若干统一事件。**坏行不许吞掉整轮**（与 codex/pi 同款）。

        ⚠ **这里只解析 stdout**（约束 2）。hermes 在 stderr 上还有一行纯文本
        `session_id: …` 与若干 SyntaxWarning，那些由基类的 `_shou_cuo_wei`
        攒进 `cuo_wei`，**不在这里解析**。
        """
        try:
            zhao = json.loads(a1)
        except (ValueError, TypeError):
            self._fa("error", {"code": "hermes_bad_line",
                               "message": f"hermes 输出了一行非 JSON：{a1[:200]}",
                               "recoverable": True})
            return
        if not isinstance(zhao, dict):
            return
        lei = str(zhao.get("type") or "")
        if lei == "system":
            # session id 在第一行的 `init` 帧就有 ⇒ 可以立刻报。
            self._fa_session(str(zhao.get("session_id") or ""))
        elif lei == "text":
            self._wen_zi(zhao)
        elif lei == "tool_use":
            self._gong_ju_yong(zhao)
        elif lei == "tool_result":
            self._gong_ju_guo(zhao)
        elif lei == "result":
            self._jie_shu_zhao(zhao)

    def _wen_zi(self, a1: dict) -> None:
        """`type:"text"`：**只累加，不发帧**（约束 5）。

        真机上同一段答复被拆成多片（`"\\n\\n完成 —"` + `" bash 执行 …"`）。
        每片发一条 `text` ⇒ 界面出现多条碎消息。
        完整正文在回合结束时由 `_jie_shu_bian_jie` 用 `result.text` 组装。
        """
        self._zhuan_wen.append(str(a1.get("text") or ""))

    def _gong_ju_yong(self, a1: dict) -> None:
        """`type:"tool_use"`：**自造 id**（约束 3：hermes 不给 id）。

        id 形状 `hermes-<序号>`——序号是本回合内**所有**工具调用的递增计数，
        不按 name 分桶，理由见 `_peidui_id`：同名的两次调用在
        `tool_result` 侧只能靠 name 区分，FIFO 取最早未配对的那条。
        """
        ming = str(a1.get("name") or "tool")
        zhao = self._peidui_id(ming)
        self._fa("tool_use", {"messageId": self.xiang_id, "toolUseId": zhao,
                              "toolName": ming,
                              "toolInput": self._dui_xiang(a1, "input", {})})

    def _peidui_id(self, a1: str) -> str:
        """造一个本回合内不重复的 id，并记进待配对队列。"""
        self._ci[a1] = self._ci.get(a1, 0) + 1
        qu_liao = sum(self._ci.values())
        zhao = f"hermes-{qu_liao}"
        self.gong_ju[zhao] = a1
        self._dai_pei.setdefault(a1, []).append(zhao)
        return zhao

    def _gong_ju_guo(self, a1: dict) -> None:
        """`type:"tool_result"`：**`output` 要解两次 JSON**（约束 4）。

        真机：`output` 字段整个是 `{"output":"hx","exit_code":0,"error":null}`
        这个对象的**字符串形式**。只解一次拿到的是那串 JSON，
        再解一次才拿得到 `hx`。

        ⚠ **失败判据是外层 `is_error`**（约束 6），不是内层 `error`。
        """
        ming = str(a1.get("name") or "tool")
        zhao = self._qu_dai_pei(ming)
        if not zhao:
            return  # 没有待配对的 `tool_use` ⇒ 发出去是孤儿，界面工具卡收不了口
        wen = self._gong_ju_wen(a1.get("output"))
        self._fa("tool_result", {"toolUseId": zhao, "toolName": ming,
                                 "text": wen,
                                 "isError": bool(a1.get("is_error"))})

    def _qu_dai_pei(self, a1: str) -> str:
        """取该 name 下最早未配对的一条 `tool_use` id（取走即出队）。"""
        dui = self._dai_pei.get(a1) or []
        return dui.pop(0) if dui else ""

    @classmethod
    def _gong_ju_wen(cls, a1: Any) -> str:
        """`output` 解两次；解不了就把原串当正文（不丢内容、不抛异常）。

        第一次解出来可能仍不是 dict（hermes 偶尔直接给纯文本），
        那种情况原样返回比显示 `{}` 有用。
        """
        yi = cls._json_wen(a1)             # 第 1 次：外层 JSON 串
        if isinstance(yi, dict):
            nei = cls._json_wen(yi.get("output"))   # 第 2 次：内层 output 也是 JSON 串
            if isinstance(nei, str):
                return nei
            if nei is not None and not isinstance(nei, (dict, list)):
                return str(nei)
            return str(yi.get("output") or "")
        if isinstance(yi, str):
            return yi
        return "" if yi is None else str(yi)

    def _jie_shu_zhao(self, a1: dict) -> None:
        """`type:"result"`：回合边界，收口。"""
        self._token = self._dui_xiang(a1, "tokens", {}) or {}
        if int(a1.get("exit_code") or 0) != 0:
            self._cuo_wen = (str(self._dui_xiang(a1, "text", ""))
                             or f"hermes 退出码 {a1.get('exit_code')}")
        self.jie_shou(a1)

    # ---------- 回合边界 ----------
    def _jie_shu_bian_jie(self, a1: dict) -> dict | None:
        """**边界只在 `type=="result"`**。

        权威正文取 **`result.text`** 而不是 text 帧累加器（约束 5）：
        累加器把流式碎片拼起来是对的，但 `result.text` 是 CLI 自己认的
        终稿，两者不一致时以 CLI 为准。累加器只作兜底（`result.text` 为空时）。
        """
        if str(a1.get("type") or "") != "result":
            return None
        wen = str(a1.get("text") or "") or "".join(self._zhuan_wen)
        return {"resultText": wen,
                "isError": bool(self._cuo_wen) or int(a1.get("exit_code") or 0) != 0,
                "subtype": "error" if self._cuo_wen else "completed",
                "durationMs": int(a1.get("duration_ms") or 0),
                "numTurns": 1,
                "totalCostUsd": 0.0}