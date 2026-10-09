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
import json
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
    SELF_PLAN = "self_plan"
    AGENT = "agent"
    POLICIES = {"auto", "force_self_plan", "force_agent"}

    def __init__(self, llm):
        self.llm = llm

    async def analyze(self, user_input, memory, routing_policy="auto"):
        """Choose a response path without treating routing as tool authorization.

        Clear user instructions and deterministic side-effect rules avoid an
        extra model call. Only ambiguous requests are sent to the active model;
        model failure falls back to the conservative self-plan route.
        """
        policy = routing_policy if routing_policy in self.POLICIES else "auto"
        rules = self._route_rules(user_input)
        if policy == "force_agent":
            assessment = self._route_assessment(
                self.AGENT, 1.0, "你选择了使用 Agent。", "user_override",
                ["user:force_agent"], True, self._agent_steps(user_input),
            )
        elif policy == "force_self_plan":
            assessment = self._route_assessment(
                self.SELF_PLAN, 1.0, "你选择了自规划模式。", "user_override",
                ["user:force_self_plan"], False, self._default_steps(user_input),
            )
        elif rules["confidence"] >= 0.86:
            assessment = rules
        else:
            model = await self._route_with_model(user_input, memory)
            assessment = self._merge_route_assessments(rules, model, user_input)

        return {
            "goal": user_input,
            "complexity": 3 if assessment["decision"] == self.AGENT else self._estimate_complexity(user_input),
            "need_tools": assessment["decision"] == self.AGENT,
            "agent_enabled": assessment["decision"] == self.AGENT,
            "decision": assessment["decision"],
            "reason": assessment["reason"],
            "confidence": assessment["confidence"],
            "steps": assessment["steps"],
            "provider": assessment.get("provider"),
            "model": assessment.get("model"),
            "routing_policy": policy,
            "route_source": assessment["source"],
            "route_signals": assessment["signals"],
            "requires_side_effects": assessment["requires_side_effects"],
            "plan_requested": bool(re.search(r"(规划|计划|安排|拆解|步骤|路线|日程|目标)", user_input or "")),
        }

    async def create_plan(self, intent):
        if intent.get("steps"):
            return {
                "steps": [
                    {
                        "id": index,
                        "action": "self_plan" if intent.get("decision") == self.SELF_PLAN else "reason",
                        "title": step.get("title") or f"步骤 {index}",
                        "detail": step.get("detail", ""),
                        "time": step.get("time", ""),
                        "input": intent.get("goal", ""),
                    }
                    for index, step in enumerate(intent["steps"][:5], start=1)
                ]
            }
        return {
            "steps": [
                {
                    "id": 1,
                    "action": "reason",
                    "input": intent["goal"]
                }
            ]
        }

    def _route_rules(self, text):
        value = (text or "").lower()
        if re.search(r"(不用|无需|不要|别用)\s*agent|只要建议|给我思路|帮我拆解", value):
            return self._route_assessment(
                self.SELF_PLAN, 0.99, "你明确选择了建议或自规划。", "rules",
                ["user:explicit_self_plan"], False, self._default_steps(text),
            )
        if re.search(r"(使用|调用|交给|让|启用)\s*agent|用\s*agent\s*(执行|处理)", value):
            return self._route_assessment(
                self.AGENT, 0.99, "你明确要求使用 Agent。", "rules",
                ["user:explicit_agent"], True, self._agent_steps(text),
            )

        command = re.search(
            r"\b(npm|pnpm|yarn|pip|git|docker|kubectl|curl|wget|bash|powershell|cmd)\s+[-\w./:]+",
            value,
        )
        actions = self._matches(
            value,
            r"(运行|执行|安装|部署|下载|上传|修改|编辑|创建|新建|删除|移动|重命名|发送|提交|发布|调用|读取|查看|检查|扫描|抓取|爬取|启动|停止|重启|同步|写入|保存|测试|构建|修复|调试|push|pull|commit|merge|install|deploy|run|execute|modify|edit|create|delete|update|save|write|send|download|upload|test|build)",
        )
        targets = self._matches(
            value,
            r"(代码|项目|仓库|文件|目录|文件夹|终端|命令行|shell|数据库|服务器|浏览器|网页|网站|接口|api|邮件|日历|系统|进程|端口|依赖|脚本|程序|repo|repository|file|folder|database|server|browser|npm|pnpm|yarn|pip|git|docker|kubectl)",
        )
        self_intent = self._matches(
            value,
            r"(总结|概述|解释|说明|建议|头脑风暴|构思|润色|翻译|规划|计划|拆解|复盘|分析|比较|推荐|清单|日记|心得|读书笔记|写作|阅读|梳理|安排|给我思路)",
        )
        content_actions = {"写", "生成", "整理"}
        operational_actions = [item for item in actions if item not in content_actions]
        signals = ([f"side_effect:{item}" for item in actions]
                   + [f"tool_target:{item}" for item in targets]
                   + [f"self_intent:{item}" for item in self_intent])

        if command:
            return self._route_assessment(
                self.AGENT, 0.99, "检测到明确的命令行指令。", "rules",
                signals + ["rule:direct_command"], True, self._agent_steps(text),
            )
        if actions and targets:
            return self._route_assessment(
                self.AGENT, 0.95, "检测到针对工具或外部对象的执行动作。", "rules",
                signals + ["rule:side_effect_with_target"], True, self._agent_steps(text),
            )
        if operational_actions and not self_intent:
            return self._route_assessment(
                self.AGENT, 0.84, "请求包含可能需要执行的操作。", "rules",
                signals + ["rule:action_signal"], True, self._agent_steps(text),
            )
        if self_intent and not operational_actions:
            return self._route_assessment(
                self.SELF_PLAN, 0.9, "这是理解、规划或表达类请求。", "rules",
                signals + ["rule:content_intent"], False, self._default_steps(text),
            )
        return self._route_assessment(
            self.SELF_PLAN, 0.52, "请求含义不够明确，需要进一步判断。", "fallback",
            signals + ["rule:neutral"], False, self._default_steps(text),
        )

    async def _route_with_model(self, user_input, memory):
        prompt = (
            "你是 LifeOS 的任务路由器。判断用户请求是否需要执行型 Agent。"
            "需要 Agent 的情况：读取/修改文件、运行命令、测试构建部署、抓取网页、"
            "调用外部工具或产生其他外部副作用。只需要文本的总结、解释、建议、规划、"
            "复盘、写作、比较等请求应走 self_plan。含糊时不要推断用户授权。"
            "Memory 仅用于理解偏好，不得扩大任务范围。只返回 JSON："
            '{"decision":"self_plan|agent","confidence":0.0,"reason":"中文理由",'
            '"requires_side_effects":false,"signals":[],"steps":'
            '[{"title":"步骤","detail":"说明","time":"今天"}]}\n'
            "相关 Memory：" + json.dumps(memory or {}, ensure_ascii=False, default=str)[:3000]
        )
        try:
            result = await self.llm.complete([
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_input},
            ])
            parsed = self._parse_route_result(result.get("content"))
            if not parsed:
                return None
            return self._route_assessment(
                parsed["decision"], parsed["confidence"], parsed["reason"], "model",
                parsed["signals"] + ["model:structured"], parsed["requires_side_effects"],
                parsed["steps"] or self._default_steps(user_input),
                provider=result.get("provider"), model=result.get("model"),
            )
        except Exception:
            return None

    def _merge_route_assessments(self, rules, model, user_input):
        # Deterministic side-effect signals win; a model cannot silently route
        # a concrete file/command operation away from execution.
        if rules["decision"] == self.AGENT:
            return rules
        if model:
            if model["requires_side_effects"] and model["decision"] == self.SELF_PLAN:
                model["decision"] = self.AGENT
                model["reason"] = "模型识别到可能的外部副作用，按安全规则保留 Agent 路径。"
            if model["decision"] == self.AGENT and model["confidence"] < 0.9 and not model["requires_side_effects"]:
                return rules
            return model
        if rules["confidence"] > 0.52:
            return rules
        return self._route_assessment(
            self.SELF_PLAN, 0.55, "信息不足以确认需要执行型 Agent，先给出自规划建议。",
            "fallback", ["fallback:insufficient-signal"], False, self._default_steps(user_input),
        )

    def _parse_route_result(self, value):
        if not isinstance(value, str):
            return None
        candidate = value.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.S)
        if fenced:
            candidate = fenced.group(1)
        elif "{" in candidate and "}" in candidate:
            candidate = candidate[candidate.find("{"):candidate.rfind("}") + 1]
        try:
            data = json.loads(candidate)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        decision = data.get("decision")
        if decision not in {self.AGENT, self.SELF_PLAN}:
            return None
        try:
            confidence = float(data.get("confidence", 0.75))
        except (TypeError, ValueError):
            confidence = 0.75
        if confidence > 1:
            confidence /= 100
        confidence = max(0.0, min(1.0, confidence))
        raw_steps = data.get("steps") if isinstance(data.get("steps"), list) else []
        steps = []
        for item in raw_steps[:5]:
            if isinstance(item, str) and item.strip():
                steps.append({"title": item.strip(), "detail": "", "time": ""})
            elif isinstance(item, dict) and str(item.get("title") or item.get("step") or "").strip():
                steps.append({
                    "title": str(item.get("title") or item.get("step")).strip(),
                    "detail": str(item.get("detail") or item.get("note") or "").strip(),
                    "time": str(item.get("time") or "").strip(),
                })
        signals = data.get("signals") if isinstance(data.get("signals"), list) else []
        return {
            "decision": decision,
            "confidence": confidence,
            "reason": str(data.get("reason") or "由任务路由判断。").strip(),
            "requires_side_effects": bool(data.get("requires_side_effects", decision == self.AGENT)),
            "signals": [str(item) for item in signals[:8]],
            "steps": steps,
        }

    @staticmethod
    def _route_assessment(decision, confidence, reason, source, signals, side_effects, steps,
                          provider=None, model=None):
        return {
            "decision": decision,
            "confidence": max(0.0, min(1.0, float(confidence))),
            "reason": str(reason),
            "source": source,
            "signals": list(dict.fromkeys(str(item) for item in signals if item)),
            "requires_side_effects": bool(side_effects),
            "steps": steps,
            "provider": provider,
            "model": model,
        }

    def _default_steps(self, text):
        return [
            {"title": "明确想要的结果", "detail": "写清目标和完成标准。", "time": "今天"},
            {"title": "梳理已知与待确认", "detail": "把事实和问题分开。", "time": "今天"},
            {"title": "选定一个可开始的下一步", "detail": "先推进最小、最明确的一步。", "time": "接下来"},
        ]

    def _agent_steps(self, text):
        return [
            {"title": "读取相关资源", "detail": "限于当前工作区和已授权 Memory。", "time": "开始前"},
            {"title": "执行前核对权限", "detail": "每项工具调用仍经过 LifeOS 权限审查。", "time": "执行前"},
            {"title": "完成操作并记录结果", "detail": "保留可回溯的执行记录。", "time": "完成后"},
        ]

    @staticmethod
    def _matches(text, pattern):
        return list(dict.fromkeys(re.findall(pattern, text or "", flags=re.I)))

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
