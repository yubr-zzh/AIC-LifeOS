"""Kimi 适配器：接 `kimi -p --output-format stream-json`（v3.0 任务 5）。

**协议事实全部来自本机 2.1.1 的真实 stdout，不是抄 cc-connect 源码**——
抄源码会踩三个坑（见文件头末尾）。

## 五条真机约束（看文档看不出来的那种）

1. **`--plan` 不能与 `-p` 组合。** 真机：`error: Cannot combine --prompt with --plan.`
   ⇒ 这个 CLI 上根本没有「只读」模式，不能声明 plan。

2. **新版删掉了 `--print`。** 只能 `-p <prompt>`。cc-connect 的
   `agent/kimi/session.go:91` 还在 `args = append(args, "--print")` ——
   照抄会直接 `unknown option`。

3. **回合边界是 `role=="meta"` 且 `type=="session.resume_hint"`。**
   同一份 JSON 里还有一个 `{"role":"meta","type":"system.version"}`，
   它在**开头**。拿 `role=="meta"` 当边界 ⇒ 每回合刚开始就收口，
   结果是空的，`fasong()` 秒回而界面上什么都没有。

4. **session id 只能从 `resume_hint` 那行拿，且只在回合末尾出现。**
   `run.hui_fu` 恢复时靠 `claudeSessionId` 传 `-r`；第一回合的 `session`
   帧必然晚于回合结束——这没问题，下一条指令一定在回合结束之后才发。

5. **不加 `-r` 时它会自己续上同 cwd 的上一条会话。** 真机实测：
   换一条新指令不加 `-r`，它仍然记得上一轮。所以「新建会话」在 CLI 侧
   没有干净的开关；Bridge 侧不提供「强制新建」入口（v3.0 范围内不做）。

## wire（真机抓的原始行）

    {"role":"meta","type":"system.version","version":"2.1.1"}
    {"role":"assistant","tool_calls":[{"type":"function","id":"3bcb859b-…",
      "function":{"name":"Bash","arguments":"{\"command\":\"echo kimi-tool\"}"}}]}
    {"role":"tool","tool_call_id":"3bcb859b-…","content":"kimi-tool\n"}
    {"role":"assistant","content":"完成。"}
    {"role":"meta","type":"session.resume_hint","session_id":"session_xxx",
      "command":"kimi -r session_xxx"}

`role:"assistant"` 的 `content`（字符串）与 `tool_calls`（数组）**二选一，
不会同时有**。⚠ `tool_calls[].function.arguments` 是 **JSON 字符串**，
不解的话 `toolInput` 会是一个字符串而不是 dict。
"""

from __future__ import annotations

import json
from typing import Any

from lifeos.bridge.adapters.liu_xing import LiuXingAdapter


class KimiAdapter(LiuXingAdapter):
    """一个实例 = 一个 kimi 会话（每条指令一个新进程）。"""

    agentId = "kimi"
    label = "Kimi Code"

    #: 会话 id 落在 `claudeSessionId`（kimi 没有独立的字段名）。
    dui_hui_id = "claudeSessionId"
    #: 一次性进程（每条指令一个新进程）。
    yi_ci_xing = True
    xu_pei_zhuang = False

    #: **只声明 `manual` 一档**（2026-10-06 真机逐个核实）。kimi 的三个权限
    #: 旗标在无头模式（`-p`）下一个都带不了，全部当场报错：
    #:   `--plan` → `error: Cannot combine --prompt with --plan.`
    #:   `-y`     → `error: Cannot combine --prompt with --yolo.`
    #:   `--auto` → `error: Cannot combine --prompt with --auto.`
    #: ⇒ `-p` 模式没有可切换的权限面，permissionMode 恒为 manual
    #: （CLI 按它自己的配置跑，Bridge 不额外放权）。
    #: ⚠ `-y`（Ask When Needed）/ `--auto`（Never Ask）是**交互模式**的档，
    #: 早前文件头注释「两档」的说法只对 TTY 成立——声明它们就是 UI 承诺
    #: 兑现不了的能力（别停在中间态）。
    #: 也不定义 `gai_moshi`（基类故意不定义，`http._gai_moshi` 用 `hasattr()` 判）。
    MOSHI_ZI = frozenset({"manual"})

    ZHI_LING = ["kimi"]

    #: **`--version` 而不是基类默认的 `--help`。** 基类那个默认值是为
    #: 「只判装没装」的探测准备的，它抓版本号靠 `(\d+\.\d+\.\d+)` 正则——
    #: `--help` 的输出里没有版本号，正则不匹配 ⇒ `tanjian()` 把**可执行文件
    #: 路径**当版本号返回（实测踩过：抓到 `C:\...\kimi.CMD`）。
    #: 而 `kimi --help` 的正文里还有 `[--agent <name>]` 之类，
    #: 万一匹配到别的东西会显示一个完全无关的号。
    CE_WU_TOU = ["--version"]

    # ---------- 发指令 ----------
    def _zi_ling(self, a1: dict) -> list[str]:
        """argv：`[--output-format stream-json] [-r <id>] -p <指令>`。

        `-r` 只在有续接 id 时加。**`--output-format` 恒带**——
        少了它 CLI 走 text 输出，stdout 上没有 JSON，`fan_yi` 一行都收不到。

        **指令原文 `self._wen` 由基类的 `_fa_chu_ming_ling` 存好**
        （它收到的 `_zi_ling(a1)` 里只有 cwd/env，没有指令）。
        """
        can: list[str] = ["--output-format", "stream-json"]
        if self.kehu_hui:
            can += ["-r", self.kehu_hui]
        return can + ["-p", self._wen]

    # ---------- wire 翻译 ----------
    def fan_yi(self, a1: str) -> None:
        """一行 stdout → 若干统一事件。**坏行不许吞掉整轮**（与 codex/pi 同款）。"""
        try:
            zhao = json.loads(a1)
        except (ValueError, TypeError):
            self._fa("error", {"code": "kimi_bad_line",
                               "message": f"kimi 输出了一行非 JSON：{a1[:200]}",
                               "recoverable": True})
            return
        if not isinstance(zhao, dict):
            return
        role = str(zhao.get("role") or "")
        if role == "assistant":
            self._zhu_li_zi(zhao)
        elif role == "tool":
            self._gong_ju_guo(zhao)
        elif role == "meta":
            self._yuan_xin_xi(zhao)

    def _zhu_li_zi(self, a1: dict) -> None:
        """`role:"assistant"`：`content` 与 `tool_calls` 二选一（真机 wire）。"""
        tiao = a1.get("tool_calls")
        if isinstance(tiao, list) and tiao:
            for tc in tiao:
                self._fa_gong_ju_yong(tc)
            return
        wen = str(a1.get("content") or "")
        if not wen:
            return  # 空 content 不动累加器：下一条才是真正的答复
        self._zhuan_wen.append(wen)
        self._fa("text", {"messageId": self.xiang_id, "text": wen})

    def _fa_gong_ju_yong(self, a1: Any) -> None:
        """`tool_calls[]` → `tool_use`。⚠ **`arguments` 是 JSON 字符串**，要解一次。"""
        if not isinstance(a1, dict):
            return
        fn = a1.get("function")
        if not isinstance(fn, dict):
            return
        ming = str(fn.get("name") or "tool")
        # `_json_wen` 解不了时原样返回字符串——那时 toolInput 是字符串，
        # 但**比丢掉工具调用强**：界面上仍能看到「它要跑这条命令」。
        shu = self._json_wen(fn.get("arguments"))
        zhao = str(a1.get("id") or "")
        if not zhao:
            return  # 没有 id ⇒ 后面配不上，等于没有这条工具调用
        self.gong_ju[zhao] = ming
        self._fa("tool_use", {"messageId": self.xiang_id, "toolUseId": zhao,
                              "toolName": ming,
                              "toolInput": shu if isinstance(shu, dict) else {"raw": shu}})

    def _gong_ju_guo(self, a1: dict) -> None:
        """`role:"tool"` → `tool_result`。靠 `tool_call_id` 配对。"""
        zhao = str(a1.get("tool_call_id") or "")
        if not zhao:
            return
        self._fa("tool_result", {"toolUseId": zhao,
                                 "toolName": self.gong_ju.get(zhao, "tool"),
                                 "text": str(a1.get("content") or ""),
                                 "isError": False})

    def _yuan_xin_xi(self, a1: dict) -> None:
        """`role:"meta"`：只有 `session.resume_hint` 是回合边界（约束 3）。

        ⚠ **收口走 `jie_shou()`**：它内部发 `result` 帧 + 唤醒 `fasong()`
        + 清累加器。基类读循环不会自动调它（`chuan_shu.py` 里没有任何地方
        调 `jie_shou`）——漏掉这一步 `fasong()` 挂死到 15 分钟看门狗。
        """
        if str(a1.get("type") or "") != "session.resume_hint":
            return  # `system.version` 在开头，不是边界
        # **先报 session 再收口**：`_fa_session` 会写 `self.kehu_hui`，
        # 而 `jie_shou` 组装结果时要读它。顺序反了第一回合的结果里
        # sessionId 会是空的。
        self._fa_session(str(a1.get("session_id") or ""))
        self.jie_shou(a1)

    # ---------- 回合边界 ----------
    def _jie_shu_bian_jie(self, a1: dict) -> dict | None:
        """**边界只在 `session.resume_hint` 那一行**（约束 3）。

        判错的后果（`chuan_shu` 文件头承重契约 3）：事件全翻译对了、
        单测全绿，真机上 `fasong()` 挂死到看门狗。
        反过来判太宽也一样：拿 `role=="meta"` 当边界会在第一行就收口，
        结果是空的。
        """
        if str(a1.get("role") or "") != "meta":
            return None
        if str(a1.get("type") or "") != "session.resume_hint":
            return None
        return {"resultText": "".join(self._zhuan_wen),
                "isError": bool(self._cuo_wen),
                "subtype": "error" if self._cuo_wen else "completed",
                "sessionId": str(a1.get("session_id") or self.kehu_hui)}
