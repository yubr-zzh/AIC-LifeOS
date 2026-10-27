"""决策回路在主服务侧的上下文存储（方案 7.7.1）。

**这是 3.8 的落点。** Bridge 每跑完一条委派指令就把结果摘要 POST 过来，
这里把它追加到该会话的上下文里；LifeOS 的大模型下一轮就能看到
「Agent 刚才做了什么、结果是什么」，从而重新判断后续该干什么——
而不是像 v1.0 那样声称「结果回来后可以重新判断」，实际上一条都不入上下文。

两条不能违反的规则：

1. **只追加文本，不产生任何指向 Bridge 的出站调用。** 主服务不能因为收到一个
   `agent.result` 就自己去下发下一条指令——下发必须由用户在界面上点确认。
2. **必须按会话隔离。** 混在一起的话，A 项目的委派结果会出现在 B 项目的上下文里，
   而大模型分不清哪句是用户说的、哪句是 Agent 干的。
"""

from __future__ import annotations

import threading
import time

# 单个会话保留多少条摘要。太多会撑爆上下文；太少会丢掉关键的中间结果。
ZUI_DUO = 40
# 每会话的 Agent 记录**总字符**预算。
#
# **单条不再截断。** 主服务的大模型要读到 Agent 的完整回复，否则长回答的
# 结论部分会被切掉——旧实现在 Bridge 与这里各截 2000 字，两刀都不见了。
# 代价是上下文随历史增长，所以改成按总量兜底：超预算时整条丢掉最旧的，
# 最新一条永远保留。20000 字约等于一次正常对话轮次能承受的增量；
# 历史里长期是长回答时可以调小。
ZONG_CHANG = 20_000


class AgentContextStore:
    """按 sessionId 存 Agent 结果摘要。进程内存态——落盘是阶段 5 的持久化。"""

    def __init__(self, a1: int = ZUI_DUO, a2: int = ZONG_CHANG) -> None:
        self.suo = threading.RLock()
        self.shu: dict[str, list[dict]] = {}
        self.zui_duo = a1
        self.zong_chang = a2

    def tian_jia(self, a1: str, a2: str, a3: dict) -> str:
        """记一条 Agent 侧的事件，返回写进上下文的那句话。

        a1=sessionId a2=事件 kind（agent.result / agent.failed / agent.ended）a3=detail
        """
        wen = self._yao_ju(a2, a3)
        if not wen:
            return ""
        with self.suo:
            lie = self.shu.setdefault(a1 or "default", [])
            lie.append({"kind": a2, "text": wen, "at": time.time()})
            # 条数上限：最近的执行结果才是当下判断的依据
            del lie[: max(0, len(lie) - self.zui_duo)]
            # 总量上限：**整条**丢最旧的，最新那条永远留着。
            # 按字符截一半的话，模型会看到半句结论，比没有更糟。
            while len(lie) > 1 and sum(len(x["text"]) for x in lie) > self.zong_chang:
                lie.pop(0)
        return wen

    def du(self, a1: str | None) -> list[dict]:
        with self.suo:
            return list(self.shu.get(a1 or "default", []))

    def qing(self, a1: str | None) -> None:
        with self.suo:
            self.shu.pop(a1 or "default", None)

    def _yao_ju(self, a1: str, a2: dict) -> str:
        """把事件 detail 拼成一句给大模型看的话。

        **只保留 Agent 干了什么和结果如何**，不搬运工具入参全文——
        那既烧 token 又会把 Agent 自撰的文字（可能含 prompt injection）
        塞进 LifeOS 的上下文。

        **结果正文不再截断**：主模型要读到完整回复。总量由 `tian_jia`
        的 `zong_chang` 预算兜底。
        """
        if a1 == "agent.result":
            zhao = str(a2.get("resultText") or "").strip()
            if a2.get("isError"):
                return f"本地 Agent 执行了一条指令但失败了：{zhao}"
            if not zhao:
                return "本地 Agent 执行了一条指令，没有产出文字结果。"
            return f"本地 Agent 执行了一条指令，结果：{zhao}"
        if a1 == "agent.failed":
            return f"本地 Agent 的委派中断了，原因：{str(a2.get('reason', ''))[:400]}"
        if a1 == "agent.ended":
            return (f"本地 Agent 完成了本次委派，共 {a2.get('batchDone', 0)}/"
                    f"{a2.get('batchTotal', 0)} 条指令。")
        if a1 == "plan.updated":
            return f"委派计划 {a2.get('planId', '')} 状态变为 {a2.get('status', '')}。"
        return ""
