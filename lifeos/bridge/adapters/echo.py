"""假适配器：不消耗真实 Agent，把状态机、仲裁、超时、断连全部测透（方案 12.3）。

它会故意发一次假权限请求和一次假提问，好让下游的收口函数在没有真实 SDK 的
情况下也能被完整覆盖。

`hui` 是事件回调（kind, payload），kind 取 6.3 的消息 kind；
`cheng` 是挂起回调，签名 `async def(kind, payload) -> 任何值`，Bridge 会注入它。
于是这条回路在阶段 2 就是真的：
发出审批 → 挂起 → 用户在 HTTP 上点按 → 收口 → 恢复执行。

**权限与提问帧不由本适配器广播**——它们由仲裁器在登记挂起项时广播。
适配器再广播一次，前端会收到两张重复的审批卡。
"""

import asyncio

from lifeos.bridge.adapters.base import AgentAdapter


class EchoAdapter(AgentAdapter):
    """收到什么回什么。"""

    agentId = "echo"
    label = "Echo（测试用）"

    def __init__(self, a1=None, a2=None) -> None:
        self.hui = a1  # 事件回调，签名 (kind, payload)
        self.cheng = a2  # 挂起回调，签名 async (kind, payload) -> 任何值
        self.liao: list[str] = []  # 已发送的指令
        self.jie_da: list[str] = []  # 收到的决定，验证 Agent 侧真的恢复了
        self.kaishi_le = False
        self.moshi = "manual"

    @staticmethod
    def fangquan() -> bool:
        return True

    @staticmethod
    def wenti2() -> bool:
        return True

    async def kaishi(self, a1: dict) -> None:
        self.kaishi_le = True

    async def fasong(self, a1: str) -> dict:
        self.liao.append(a1)
        if self.hui:
            self.hui("text", {"text": f"echo: {a1}"})
        if len(self.liao) == 1:
            shen = {"toolName": "Bash", "toolInput": {"command": "echo spike-hi"},
                    "toolUseId": "tool-echo-1", "title": "Claude 想执行一条命令"}
            if self.hui:
                self.hui("tool_use", shen)
            if self.cheng:
                r = await self.cheng("permission", shen)
                self.jie_da.append(str(r))
            if self.hui:
                self.hui("tool_result", {"toolUseId": "tool-echo-1", "toolName": "Bash",
                                         "text": "spike-hi", "isError": False})
        if len(self.liao) == 2:
            wen = {"questions": [{"question": "接下来做什么？", "options": [{"label": "A"}, {"label": "B"}]}],
                   "toolUseId": "tool-echo-2"}
            if self.hui:
                self.hui("text", {"text": "[Agent 提问] 接下来做什么？"})
            if self.cheng:
                r = await self.cheng("question", wen)
                self.jie_da.append(str(r))
        await asyncio.sleep(0)
        jie = {"resultText": f"echo: {a1}", "isError": False, "subtype": "success",
               "durationMs": 0, "numTurns": 1, "totalCostUsd": 0.0}
        # 每条指令都要发 result：3.8 决策回路就是靠它把结果送回 LifeOS 上下文。
        # 少这一步，回路在测试里是通的、在真机上也是「通的」——只是永远送不到。
        if self.hui:
            self.hui("result", jie)
        return jie

    async def gai_moshi(self, a1: str) -> None:
        self.moshi = a1

    async def zhong_duan(self) -> None:
        return None

    async def guan_bi(self) -> None:
        self.kaishi_le = False
