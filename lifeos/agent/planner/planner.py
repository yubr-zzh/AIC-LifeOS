"""委派计划生成（方案 6.5 / 10.1）。

**这个模块不许依赖 LLM 才能跑起来。** `lifeos/llm/client.py` 目前是 mock provider，
对任何非 mock provider 直接 raise NotImplementedError；把委派功能挂在它上面
等于「功能存在但永远跑不通」。

所以分两层：

1. `cehuao()` —— 规则兜底，永远可用。命中关键词或绝对路径就产出**单条**指令的计划。
2. LLM 增强 —— 等 client 支持结构化输出后再加，规则兜底永久保留为降级路径。

两条硬规则（6.5.2）在这里落地：
- **R-V1** summary ≤ 200、instruction ≤ 4000、items 1–20
- **R-V4** dependsOn 不得成环（这里只产单条，天然无环；解析 LLM 结果时才需要校验）
"""

from __future__ import annotations

import re
import time
import uuid
from pathlib import Path

# 触发词。**误触发是真实风险**：「这个文件我明天再看」「帮我运行一下」都会命中，
# 所以有 delegationEnabled 开关（10.1），关掉后 guihua() 直接返回 None。
CICI = [
    "改代码", "写代码", "重构", "运行", "跑一下", "调试", "修 bug", "修复",
    "文件", "仓库", "项目", "测试", "构建", "编译", "提交", "部署",
    "安装依赖", "跑起来", "提交代码", "拉取", "推送", "打包",
]

# 绝对路径：Windows 的盘符、UNC、POSIX 根目录都算。
_LUJING = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\|/(?:home|usr|var|opt|Users)/)")

# 建议的 agent cwd。R-V5 要求它落在信任根内，项目根天然在内。
XIANG = str(Path(__file__).resolve().parent.parent.parent.parent)


def ci_ji(a: str) -> str:
    """毫秒时间戳。全项目的 createdAt 用同一个来源。"""
    return str(int(time.time() * 1000))


def ci_plan(a1: str, a2: list, a3: str) -> dict:
    """组装一份合法的 DelegationPlan。调用方负责保证 items 已过 R-V1/R-V4。"""
    return {
        "planId": f"dp-{uuid.uuid4().hex[:4]}",
        "traceId": a1,
        "ownerId": "local",
        "summary": a2,
        "targetAgent": None,
        "workingDir": a3,
        "status": "draft",
        "items": [],
    }


class Planner:
    def __init__(self, llm):
        self.llm = llm

    async def analyze(self, user_input, memory):
        return {
            "goal": user_input,
            "complexity": self._estimate_complexity(user_input),
            "need_tools": False
        }

    async def create_plan(self, intent):
        return {
            "steps": [
                {
                    "id": 1,
                    "action": "reason",
                    "input": intent["goal"]
                }
            ]
        }

    def _estimate_complexity(self, text):
        if len(text) > 100:
            return 2
        return 1

    # ---- 委派计划 ----

    async def cehuao(self, a1: str, a2: str = "", a3: bool = True) -> dict | None:
        """生成委派计划。命中返回 DelegationPlan，没命中或开关关掉返回 None。

        a1=用户输入  a2=trace_id  a3=开关（delegationEnabled）
        """
        if not a3:
            return None
        a1 = (a1 or "").strip()
        if not a1:
            return None
        if not self._zhong(a1):
            return None

        # R-V1：summary 与 instruction 都有上限，超了直接截断而不是让前端收 400。
        zhai = a1 if len(a1) <= 200 else a1[:197] + "…"
        jiao = a1 if len(a1) <= 4000 else a1[:3997] + "…"
        hui = ci_plan(a2, zhai, XIANG)
        hui["items"] = [
            {
                "itemId": "i-1",
                "order": 1,
                "title": zhai[:40],
                "instruction": jiao,
                "dependsOn": [],
                "editable": True,
                "enabled": True,
                "status": "pending",
            }
        ]
        return hui

    @staticmethod
    def _zhong(a1: str) -> bool:
        if _LUJING.search(a1):
            return True
        return any(c in a1 for c in CICI)
