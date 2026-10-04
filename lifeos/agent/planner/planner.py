import asyncio
import importlib
import inspect
import json
import os
import re
from importlib.metadata import entry_points


class Planner:
    """Long-term planning and Agent-necessity routing.

    Routing is intentionally layered:

    1. explicit user override;
    2. deterministic capability/side-effect guardrails;
    3. an optional external router plugin;
    4. the active model for ambiguous language.

    A high-confidence side-effect rule always wins over a model that tries to
    route back to self-planning. This prevents destructive or tool-using work
    from being silently skipped.
    """

    SELF_PLAN = "self_plan"
    AGENT = "agent"

    POLICY_AUTO = "auto"
    POLICY_FORCE_SELF = "force_self_plan"
    POLICY_FORCE_AGENT = "force_agent"
    POLICIES = {POLICY_AUTO, POLICY_FORCE_SELF, POLICY_FORCE_AGENT}

    ROUTE_SOURCE_USER = "user_override"
    ROUTE_SOURCE_RULES = "rules"
    ROUTE_SOURCE_PLUGIN = "external_plugin"
    ROUTE_SOURCE_MODEL = "model"
    ROUTE_SOURCE_FALLBACK = "fallback"

    def __init__(self, llm, plugin=None, plugin_target=None):
        self.llm = llm
        self.plugin = plugin if plugin is not None else self._load_router_plugin(plugin_target)

    async def analyze(self, user_input, memory, routing_policy=POLICY_AUTO):
        policy = self._normalize_policy(routing_policy)
        rules = self._rule_assessment(user_input)

        if policy == self.POLICY_FORCE_AGENT:
            assessment = self._assessment(
                self.AGENT,
                1.0,
                "用户已强制选择 Agent 模式。",
                self._agent_steps(user_input),
                self.ROUTE_SOURCE_USER,
                provider="lifeos-policy",
                model="force-agent",
                signals=["user:force_agent"],
                requires_side_effects=True,
            )
        elif policy == self.POLICY_FORCE_SELF:
            assessment = self._assessment(
                self.SELF_PLAN,
                1.0,
                "用户已强制选择自规划模式。",
                self._default_steps(user_input),
                self.ROUTE_SOURCE_USER,
                provider="lifeos-policy",
                model="force-self-plan",
                signals=["user:force_self_plan"],
                requires_side_effects=False,
            )
        elif rules.get("explicit"):
            assessment = rules
        elif rules.get("decision") and rules.get("confidence", 0) >= 0.86:
            assessment = rules
        else:
            plugin_assessment = await self._plugin_assessment(user_input, memory, policy)
            model_assessment = await self._model_assessment(user_input, memory)
            assessment = self._merge_assessments(rules, plugin_assessment, model_assessment, user_input)

        return {
            "goal": user_input,
            "complexity": self._estimate_complexity(user_input, assessment),
            "need_tools": assessment["decision"] == self.AGENT,
            "agent_enabled": assessment["decision"] == self.AGENT,
            "decision": assessment["decision"],
            "reason": assessment["reason"],
            "confidence": assessment["confidence"],
            "steps": assessment["steps"],
            "provider": assessment.get("provider"),
            "model": assessment.get("model"),
            "routing_policy": policy,
            "route_source": assessment.get("source", self.ROUTE_SOURCE_FALLBACK),
            "route_signals": assessment.get("signals", []),
            "requires_side_effects": bool(assessment.get("requires_side_effects")),
        }

    async def create_plan(self, intent):
        steps = []
        for index, step in enumerate(intent.get("steps", []), start=1):
            steps.append(
                {
                    "id": index,
                    "action": "self_plan" if intent.get("decision") == self.SELF_PLAN else "reason",
                    "title": step.get("title") or step.get("detail") or f"步骤 {index}",
                    "detail": step.get("detail", ""),
                    "time": step.get("time", ""),
                    "input": intent.get("goal", ""),
                }
            )
        if not steps:
            steps = [
                {
                    "id": 1,
                    "action": "reason",
                    "title": "澄清目标与完成标准",
                    "detail": "先写下结果是什么，以及什么情况算完成。",
                    "time": "今天",
                    "input": intent.get("goal", ""),
                }
            ]
        return {"steps": steps}

    def _normalize_policy(self, value):
        return value if value in self.POLICIES else self.POLICY_AUTO

    async def _plugin_assessment(self, user_input, memory, policy):
        if self.plugin is None:
            return None
        payload = {
            "user_input": user_input,
            "memory": memory,
            "routing_policy": policy,
        }
        try:
            method = getattr(self.plugin, "classify", self.plugin if callable(self.plugin) else None)
            if method is None:
                return None
            result = method(payload)
            if inspect.isawaitable(result):
                result = await result
            parsed = self._parse_assessment(result)
            if not parsed:
                return None
            return self._assessment(
                parsed["decision"],
                max(parsed["confidence"], 0.8),
                parsed["reason"],
                parsed["steps"] or self._default_steps(user_input),
                self.ROUTE_SOURCE_PLUGIN,
                provider="external-plugin",
                model=getattr(self.plugin, "__class__", type(self.plugin)).__name__,
                signals=parsed.get("signals", []) + ["plugin:external"],
                requires_side_effects=parsed.get("requires_side_effects", parsed["decision"] == self.AGENT),
            )
        except Exception:
            return None

    async def _model_assessment(self, user_input, memory):
        try:
            completion = await self.llm.complete(self._assessment_messages(user_input, memory))
            parsed = self._parse_assessment(completion.get("content", ""))
            if not parsed:
                return None
            return self._assessment(
                parsed["decision"],
                parsed["confidence"],
                parsed["reason"],
                parsed["steps"] or self._default_steps(user_input),
                self.ROUTE_SOURCE_MODEL,
                provider=completion.get("provider"),
                model=completion.get("model"),
                signals=parsed.get("signals", []) + ["model:structured"],
                requires_side_effects=parsed.get(
                    "requires_side_effects", parsed["decision"] == self.AGENT
                ),
            )
        except Exception:
            return None

    def _merge_assessments(self, rules, plugin, model, user_input):
        # A specialized external router is useful only when the built-in
        # guardrails remain neutral; ambiguous requests still need model input.
        if plugin and plugin.get("confidence", 0) >= 0.8:
            plugin["signals"] = self._unique(
                list(rules.get("signals", [])) + list(plugin.get("signals", []))
            )
            return plugin

        if rules.get("decision") == self.AGENT:
            if model:
                rules["reason"] = (
                    f"{rules['reason']} 模型判定：{model.get('reason', '')}"
                ).strip()
                rules["provider"] = model.get("provider")
                rules["model"] = model.get("model")
            return rules

        if model:
            if (
                model.get("decision") == self.SELF_PLAN
                and model.get("requires_side_effects")
            ):
                model["decision"] = self.AGENT
                model["reason"] = "检测到外部副作用，按安全规则切换为 Agent。"
            if rules.get("decision") == self.SELF_PLAN and model.get("decision") == self.AGENT:
                if not model.get("requires_side_effects") and model.get("confidence", 0) < 0.9:
                    return rules
            model["signals"] = self._unique(
                list(rules.get("signals", [])) + list(model.get("signals", []))
            )
            return model

        if rules.get("decision"):
            return rules

        return self._assessment(
            self.SELF_PLAN,
            0.55,
            "当前信息不足以证明需要执行型 Agent，先反馈自规划步骤。",
            self._default_steps(user_input),
            self.ROUTE_SOURCE_FALLBACK,
            provider="lifeos-rule",
            model="conservative-fallback",
            signals=["fallback:insufficient-signal"],
            requires_side_effects=False,
        )

    def _assessment(
        self,
        decision,
        confidence,
        reason,
        steps,
        source,
        *,
        provider=None,
        model=None,
        signals=None,
        requires_side_effects=False,
    ):
        return {
            "decision": decision,
            "confidence": max(0.0, min(1.0, float(confidence))),
            "reason": str(reason),
            "steps": steps,
            "source": source,
            "provider": provider,
            "model": model,
            "signals": self._unique(signals or []),
            "requires_side_effects": bool(requires_side_effects),
        }

    def _rule_assessment(self, text):
        normalized = (text or "").lower()
        explicit_agent = bool(
            re.search(r"(使用|调用|交给|让|启用|开启)\s*agent|用\s*agent|agent\s*(执行|处理)", normalized)
        )
        explicit_self = bool(
            re.search(
                r"(不需要|不用|别用|无需)\s*agent|我自己|自行规划|只要建议|给我步骤|帮我拆解",
                normalized,
            )
        )
        if explicit_agent:
            return self._assessment(
                self.AGENT,
                0.99,
                "用户已明确要求使用 Agent。",
                self._agent_steps(text),
                self.ROUTE_SOURCE_USER,
                provider="lifeos-rule",
                model="explicit-agent-routing",
                signals=["user:explicit_agent"],
                requires_side_effects=True,
            )
        if explicit_self:
            return self._assessment(
                self.SELF_PLAN,
                0.99,
                "用户已明确选择自规划。",
                self._default_steps(text),
                self.ROUTE_SOURCE_USER,
                provider="lifeos-rule",
                model="explicit-self-plan-routing",
                signals=["user:explicit_self_plan"],
                requires_side_effects=False,
            )

        direct_command = self._matches(
            normalized,
            r"(npm|pnpm|yarn|pip|git|docker|kubectl|curl|wget|bash|powershell|cmd)\s+[\w./:-]+",
        )
        side_effects = self._matches(
            normalized,
            r"(运行|执行|安装|部署|下载|上传|修改|编辑|创建|新建|删除|移动|重命名|发送|提交|发布|调用|读取|查看|检查|扫描|抓取|爬取|启动|停止|重启|同步|写入|保存|测试|构建|修复|调试|写|生成|整理|打开|复制|粘贴|压缩|解压|重装|更新|升级|回滚|push|pull|commit|merge|install|deploy|run|execute|modify|edit|create|delete|update|save|write|generate|send|download|upload|test|build)",
        )
        tool_targets = self._matches(
            normalized,
            r"(代码|项目|仓库|文件|目录|文件夹|终端|命令行|shell|数据库|服务器|浏览器|网页|网站|接口|api|邮件|日历|系统|进程|端口|依赖|脚本|程序|repo|repository|file|folder|code|database|server|browser|test|build|npm|pnpm|yarn|pip|git|docker|kubectl)",
        )
        self_signals = self._matches(
            text or "",
            r"(总结|概述|解释|说明|建议|头脑风暴|构思|润色|翻译|规划|计划|拆解|复盘|分析|比较|推荐|清单|日记|心得|读书笔记|写作|阅读|梳理|安排|怎么写|怎么安排|给我思路)",
        )
        ambiguous_content_actions = self._matches(normalized, r"(写|生成|整理)")
        operational_effects = [item for item in side_effects if item not in ambiguous_content_actions]

        signals = []
        signals.extend(f"side_effect:{item}" for item in side_effects)
        signals.extend(f"tool_target:{item}" for item in tool_targets)
        signals.extend(f"self_intent:{item}" for item in self_signals)

        if direct_command:
            return self._assessment(
                self.AGENT,
                0.99,
                "检测到明确的终端或工具命令，需要 Agent 执行。",
                self._agent_steps(text),
                self.ROUTE_SOURCE_RULES,
                provider="lifeos-rule",
                model="direct-command-guardrail",
                signals=signals + ["rule:direct_command"],
                requires_side_effects=True,
            )

        if side_effects and tool_targets:
            return self._assessment(
                self.AGENT,
                0.95,
                "检测到工具对象和可能产生副作用的操作，需要 Agent。",
                self._agent_steps(text),
                self.ROUTE_SOURCE_RULES,
                provider="lifeos-rule",
                model="side-effect-guardrail",
                signals=signals + ["rule:side_effect_with_target"],
                requires_side_effects=True,
            )

        if operational_effects and not self_signals:
            return self._assessment(
                self.AGENT,
                0.84,
                "请求包含执行动作，优先保留 Agent 能力。",
                self._agent_steps(text),
                self.ROUTE_SOURCE_RULES,
                provider="lifeos-rule",
                model="action-signal-guardrail",
                signals=signals + ["rule:action_signal"],
                requires_side_effects=True,
            )

        if self_signals and not operational_effects:
            return self._assessment(
                self.SELF_PLAN,
                0.9,
                "请求属于理解、规划或表达任务，不需要工具副作用。",
                self._default_steps(text),
                self.ROUTE_SOURCE_RULES,
                provider="lifeos-rule",
                model="content-intent-guardrail",
                signals=signals + ["rule:content_intent"],
                requires_side_effects=False,
            )

        return self._assessment(
            self.SELF_PLAN,
            0.52,
            "规则未发现明确副作用，交由模型继续判断。",
            self._default_steps(text),
            self.ROUTE_SOURCE_FALLBACK,
            provider="lifeos-rule",
            model="neutral-signal",
            signals=signals + ["rule:neutral"],
            requires_side_effects=False,
        )

    def _assessment_messages(self, user_input, memory):
        memory_text = ""
        if memory:
            memory_text = "\n相关 Memory（仅用于理解偏好，不得扩大任务范围）：\n" + json.dumps(
                memory, ensure_ascii=False, default=str
            )[:4000]
        system = (
            "你是 LifeOS 的长期规划路由器。你必须判断用户请求是否需要执行型 Agent。"
            "\n需要 Agent：读取或修改文件、运行命令、测试、构建、部署、抓取网页、"
            "发送消息、写入数据库、调用外部工具，或任何会产生副作用的操作。"
            "\n不需要 Agent：总结、解释、建议、头脑风暴、规划、拆解、复盘、写作、"
            "比较、个人决策、清单等只产生文本结果的任务。"
            "\n遇到含糊请求时，不要猜测已授权工具；只根据明确上下文判断。"
            "\n只返回 JSON，不要 Markdown："
            '{"decision":"self_plan|agent","confidence":0.0,"reason":"中文理由",'
            '"requires_side_effects":false,"signals":["可核对信号"],'
            '"steps":[{"title":"步骤标题","detail":"完成提示","time":"今天"}]}'
            "\nsteps 给出 3 到 5 步。"
        )
        return [
            {"role": "system", "content": system + memory_text},
            {"role": "user", "content": user_input},
        ]

    def _parse_assessment(self, payload):
        if isinstance(payload, dict) and "choices" in payload:
            payload = payload["choices"]
        if isinstance(payload, dict) and "content" in payload:
            payload = payload["content"]
        if not isinstance(payload, str):
            data = payload if isinstance(payload, dict) else None
        else:
            data = None
            candidate = payload.strip()
            fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.S)
            if fenced:
                candidate = fenced.group(1)
            elif "{" in candidate and "}" in candidate:
                candidate = candidate[candidate.find("{") : candidate.rfind("}") + 1]
            try:
                data = json.loads(candidate)
            except (TypeError, ValueError, json.JSONDecodeError):
                lowered = candidate.lower()
                if "self_plan" in lowered or "无需 agent" in lowered or "不需要 agent" in lowered:
                    return {
                        "decision": self.SELF_PLAN,
                        "reason": "当前任务更适合由用户自行推进。",
                        "confidence": 0.78,
                        "steps": [],
                        "signals": ["text:self_plan"],
                        "requires_side_effects": False,
                    }
                if "agent" in lowered:
                    return {
                        "decision": self.AGENT,
                        "reason": "模型建议使用 Agent。",
                        "confidence": 0.78,
                        "steps": [],
                        "signals": ["text:agent"],
                        "requires_side_effects": True,
                    }
                return None
        if not isinstance(data, dict):
            return None

        needs_agent = data.get("needs_agent")
        decision_value = str(data.get("decision", "")).lower()
        if isinstance(needs_agent, bool):
            decision = self.AGENT if needs_agent else self.SELF_PLAN
        elif decision_value in {self.AGENT, "use_agent"}:
            decision = self.AGENT
        elif decision_value in {self.SELF_PLAN, "self-plan"}:
            decision = self.SELF_PLAN
        else:
            return None

        confidence = data.get("confidence", 0.75)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.75
        if confidence > 1:
            confidence = confidence / 100
        confidence = max(0.0, min(1.0, confidence))

        raw_steps = data.get("steps")
        steps = []
        if isinstance(raw_steps, list):
            for item in raw_steps[:5]:
                if isinstance(item, str):
                    steps.append({"title": item, "detail": "", "time": ""})
                elif isinstance(item, dict):
                    title = str(item.get("title") or item.get("step") or "").strip()
                    if title:
                        steps.append(
                            {
                                "title": title,
                                "detail": str(item.get("detail") or item.get("note") or "").strip(),
                                "time": str(item.get("time") or "").strip(),
                            }
                        )
        signals = data.get("signals", [])
        if not isinstance(signals, list):
            signals = []
        return {
            "decision": decision,
            "reason": str(data.get("reason") or "由长期规划根据任务复杂度判断。").strip(),
            "confidence": confidence,
            "steps": steps,
            "signals": [str(item) for item in signals[:8]],
            "requires_side_effects": bool(data.get("requires_side_effects", decision == self.AGENT)),
        }

    def _load_router_plugin(self, target=None):
        target = target or os.environ.get("LIFEOS_AGENT_ROUTER_PLUGIN")
        if target:
            try:
                module_name, separator, attribute = target.partition(":")
                if not separator:
                    module_name, _, attribute = target.rpartition(".")
                module = importlib.import_module(module_name)
                return getattr(module, attribute)
            except Exception:
                return None
        try:
            discovered = entry_points()
            selected = (
                discovered.select(group="lifeos.agent_routers")
                if hasattr(discovered, "select")
                else discovered.get("lifeos.agent_routers", [])
            )
            for entry in selected:
                try:
                    return entry.load()
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def _default_steps(self, text):
        if re.search(r"旅行|路线|预算", text or ""):
            return [
                {"title": "确认出行范围", "detail": "写明日期、同行人和必须完成的预订。", "time": "今天"},
                {"title": "确定预算边界", "detail": "区分固定支出和弹性支出。", "time": "明天"},
                {"title": "比较路线取舍", "detail": "按时间、体验和成本比较两个方案。", "time": "本周"},
                {"title": "写回日历提醒", "detail": "把确定事项放入日历并保留待确认项。", "time": "周末"},
            ]
        if re.search(r"写作|文章|文案|笔记", text or ""):
            return [
                {"title": "明确读者与用途", "detail": "写清最终给谁看、要解决什么问题。", "time": "今天"},
                {"title": "列出核心观点", "detail": "先完成结构，不急着润色句子。", "time": "今天"},
                {"title": "完成第一版", "detail": "按结构写完，再处理事实与表达。", "time": "明天"},
                {"title": "修订并收束", "detail": "根据反馈做一次集中修改。", "time": "本周"},
            ]
        return [
            {"title": "复述目标与完成标准", "detail": "用一句话写清结果和完成条件。", "time": "今天"},
            {"title": "列出已知与未知", "detail": "把信息和仍需确认的事项分开。", "time": "今天"},
            {"title": "拆成四个可执行步骤", "detail": "每步都应能在一次专注时间内推进。", "time": "明天"},
            {"title": "安排第一步", "detail": "为下一步写入明确日期和时段。", "time": "本周"},
        ]

    def _agent_steps(self, text):
        return [
            {"title": "读取任务与相关资源", "detail": "只使用当前工作区和已授权 Memory。", "time": "1–2 分钟"},
            {"title": "生成执行计划", "detail": "列出将改动的文件、命令和权限。", "time": "约 2 分钟"},
            {"title": "等待用户确认", "detail": "确认前不修改外部环境。", "time": "待确认"},
            {"title": "执行并记录 trace", "detail": "完成后生成可回溯的执行记录。", "time": "按任务"},
        ]

    def _estimate_complexity(self, text, assessment):
        if assessment.get("decision") == self.AGENT:
            return 3
        if len(text or "") > 100:
            return 2
        return 1

    @staticmethod
    def _matches(text, pattern):
        return Planner._unique(re.findall(pattern, text or "", flags=re.I))

    @staticmethod
    def _unique(items):
        seen = set()
        output = []
        for item in items:
            value = str(item)
            if value and value not in seen:
                seen.add(value)
                output.append(value)
        return output
