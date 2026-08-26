"""Memory retrieval with fuzzy matching.

The first version did plain substring matching (``query in content``),
which misses semantically-similar but differently-phrased memories. This
version scores each entry against the query using:

- exact substring hit      -> score 1.0 (strongest signal)
- token coverage           -> how much of the query's token set appears
                              in the entry (short-CJK-query friendly)
- jaccard similarity       -> overlap of both token sets

The best of the three signals wins, entries are sorted by descending
score, and every hit carries its ``score`` for traceability. Tokenization
is shared with the skill detector (``lifeos/skills/metrics``), so both
subsystems agree on what counts as "similar".
"""

import re
from typing import Any, Dict, Optional

from lifeos.skills.metrics import jaccard, tokenize

# Categories searched, in display order.
SEARCH_CATEGORIES = ["user", "project", "feedback", "reference"]

# Minimum score for an entry to be considered relevant. 0.4 balances
# recall (fuzzy hits like "周规划" -> "周计划" score ~0.67) against
# precision (unrelated queries sharing one or two characters score ~0.3).
DEFAULT_THRESHOLD = 0.40


class MemoryRetriever:
    def __init__(self, store, threshold: float = DEFAULT_THRESHOLD):
        self.store = store
        self.threshold = threshold

    async def retrieve(self, query: str) -> Dict[str, Any]:
        result = {category: [] for category in SEARCH_CATEGORIES}
        query_lower = (query or "").lower()

        # Empty query returns everything (callers use this to dump memory).
        if not query_lower:
            for category in SEARCH_CATEGORIES:
                result[category] = list(self.store.get(category, []) or [])
            return result

        q_tokens = tokenize(query_lower)
        for category in SEARCH_CATEGORIES:
            scored = []
            for item in self.store.get(category, []) or []:
                text = self._text_of(item).lower()
                if not text:
                    continue
                score = self._similarity(query_lower, text, q_tokens)
                if score >= self.threshold:
                    scored.append((score, item))
            scored.sort(key=lambda pair: pair[0], reverse=True)
            result[category] = [item for _, item in scored]
        return result

    @staticmethod
    def _text_of(item: Dict[str, Any]) -> str:
        content = item.get("content", "")
        if isinstance(content, str):
            return content
        # dict/list content -> compact JSON so tokens are visible to the matcher
        import json

        return json.dumps(content, ensure_ascii=False)

    @classmethod
    def _similarity(cls, query_lower: str, text_lower: str, q_tokens) -> float:
        if query_lower in text_lower:
            return 1.0
        t_tokens = tokenize(text_lower)
        if not q_tokens or not t_tokens:
            return 0.0
        overlap = q_tokens & t_tokens
        bigram_coverage = len(overlap) / len(q_tokens)
        jac = jaccard(q_tokens, t_tokens)
        # Character-level coverage as a third signal: robust to
        # single-character edits ("周规划" vs "周计划" share 周/划).
        # CJK-only: latin words are already matched via tokenize + substring,
        # and per-letter overlap would create false positives.
        q_chars = set(re.findall(r"[\u4e00-\u9fff]", query_lower))
        t_chars = set(re.findall(r"[\u4e00-\u9fff]", text_lower))
        char_coverage = len(q_chars & t_chars) / len(q_chars) if q_chars else 0.0
        return max(bigram_coverage, jac, char_coverage)
