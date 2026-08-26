"""Skill candidate detection for the LifeOS Global Agent.

Upgraded from keyword heuristics to a metric-based detector that scores
candidate skills across four dimensions:

- frequency:  how often similar tasks recur in the event history
- similarity: token overlap with known workflow templates
- complexity: tool-call and response depth of the current task
- success:    historical tool outcomes + user ratings on related traces

A candidate is emitted only when the composite score clears a
threshold AND the task has recurred often enough to justify a skill.
"""

import uuid

from lifeos.skills.metrics import jaccard, keyword_similarity, normalize, tokenize

# Weighting of the four metric dimensions (sums to 1.0).
WEIGHTS = {
    "frequency": 0.30,
    "similarity": 0.35,
    "complexity": 0.15,
    "success": 0.20,
}

DETECT_THRESHOLD = 0.30
# A task must have appeared at least once in history (plus the current
# conversation) before we propose a skill for it.
MIN_FREQUENCY = 1

# Similarity threshold for counting a historical task as "the same task".
HISTORY_SIMILARITY = 0.20

# Built-in workflow templates. Each carries keyword sets used for
# similarity scoring and for naming the generated skill.
WORKFLOW_TEMPLATES = [
    {
        "name": "paper_reading",
        "description": "阅读论文 / 整理文献笔记",
        "keywords": ["论文", "文献", "paper", "阅读", "arxiv", "pdf", "综述", "笔记"],
    },
    {
        "name": "project_planning",
        "description": "项目规划 / 任务拆解 / 排期",
        "keywords": ["项目", "规划", "计划", "任务", "排期", "plan", "project", "里程碑", "拆解"],
    },
    {
        "name": "weekly_summary",
        "description": "周总结 / 复盘 / 回顾",
        "keywords": ["周", "总结", "复盘", "回顾", "weekly", "summary", "review", "反思"],
    },
    {
        "name": "document_writing",
        "description": "写作 / 文档 / 报告",
        "keywords": ["写", "文档", "报告", "简历", "ppt", "docx", "文章", "写作"],
    },
    {
        "name": "code_review",
        "description": "代码审查 / 调试 / 重构",
        "keywords": ["代码", "审查", "重构", "bug", "调试", "review", "refactor", "code"],
    },
]


class SkillDetector:
    """Metric-based skill candidate detector.

    ``detect(conversation)`` computes a composite score using event
    history (frequency), workflow templates (similarity), tool-call
    depth (complexity) and feedback outcomes (success), then returns
    candidate skills that clear the threshold with their metrics.
    """

    def __init__(self, llm, event_bus=None, memory=None):
        self.llm = llm
        self.event_bus = event_bus
        self.memory = memory

    async def detect(self, conversation):
        user_input = conversation.get("user_input", "")
        if not user_input:
            return []

        tokens = tokenize(user_input)

        # similarity: best match against workflow templates
        best_template, best_sim = self._match_template(user_input)

        # frequency: how often similar tasks recur in history
        freq = await self._count_similar_frequency(tokens)

        # complexity: tool-call depth of this task
        complexity = self._complexity(conversation)

        # success: historical tool outcomes + user ratings
        success = await self._success_feedback(conversation)

        score = (
            WEIGHTS["frequency"] * normalize(min(freq, 5) / 5.0)
            + WEIGHTS["similarity"] * best_sim
            + WEIGHTS["complexity"] * complexity
            + WEIGHTS["success"] * success
        )

        if best_template is None or freq < MIN_FREQUENCY:
            return []
        if score < DETECT_THRESHOLD:
            return []

        return [
            {
                "id": str(uuid.uuid4()),
                "name": best_template["name"],
                "description": best_template["description"],
                "keywords": best_template["keywords"],
                "risk": "low",
                "source": "global_agent",
                "metrics": {
                    "frequency": freq,
                    "similarity": round(best_sim, 3),
                    "complexity": round(complexity, 3),
                    "success_rate": round(success, 3),
                    "score": round(score, 3),
                },
            }
        ]

    def _match_template(self, user_input):
        best = None
        best_sim = 0.0
        for template in WORKFLOW_TEMPLATES:
            sim = keyword_similarity(user_input, template["keywords"])
            if sim > best_sim:
                best_sim = sim
                best = template
        return best, best_sim

    async def _count_similar_frequency(self, tokens) -> int:
        if self.event_bus is None:
            return 0
        count = 0
        for event in self.event_bus.all_events():
            if event.type != "conversation.completed":
                continue
            past_input = event.payload.get("user_input", "")
            if past_input and jaccard(tokens, tokenize(past_input)) >= HISTORY_SIMILARITY:
                count += 1
        return count

    def _complexity(self, conversation) -> float:
        result = conversation.get("result", {})
        tool_calls = result.get("tool_calls", []) or []
        n_tools = len(tool_calls)
        response = result.get("response", "") or ""
        # 0-4 tools -> 0..1, plus a small response-depth signal.
        return normalize(min(n_tools, 4) / 4.0 + min(len(response), 800) / 8000.0)

    async def _success_feedback(self, conversation) -> float:
        # 1. tool outcome of the current conversation
        tool_results = conversation.get("result", {}).get("tool_results", []) or []
        blocked = sum(1 for t in tool_results if t.get("status") == "blocked")
        ok_tools = len(tool_results) - blocked
        success = (ok_tools / len(tool_results)) if tool_results else 0.8

        # 2. user ratings on related traces (committed + candidates)
        if self.memory is not None:
            try:
                store = self.memory._read()
            except Exception:
                store = {}
            rated = []
            for entry in store.get("feedback", []):
                content = entry.get("content", {})
                if content.get("rating"):
                    rated.append(content)
            for candidate in store.get("candidates", []):
                if candidate.get("source") == "user_feedback":
                    content = candidate.get("content", {})
                    if content.get("rating"):
                        rated.append(content)
            if rated:
                good = sum(
                    1 for r in rated if r.get("rating") in ("helpful", "just_right")
                )
                rated_score = good / len(rated)
                success = 0.5 * success + 0.5 * rated_score
        return normalize(success)
