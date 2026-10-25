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
from collections import Counter
from math import log
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from lifeos.skills.metrics import jaccard, tokenize
from lifeos.memory.schema import normalize_scope

# Categories searched, in display order.
SEARCH_CATEGORIES = ["user", "project", "feedback", "reference"]

# Minimum score for an entry to be considered relevant. 0.4 balances
# recall (fuzzy hits like "周规划" -> "周计划" score ~0.67) against
# precision (unrelated queries sharing one or two characters score ~0.3).
DEFAULT_THRESHOLD = 0.40
# Explicit as-of queries operate on a smaller, time-qualified candidate set and
# often use conversational paraphrases. Keep a lower lexical floor only there.
HISTORICAL_THRESHOLD = 0.20
GENERIC_QUERY_TOKENS = {
    "用户", "记忆", "项目", "现在", "目前", "之前", "后来", "具体", "这个", "如果",
    "可以", "能不", "什么", "怎么", "哪一", "哪个", "帮我", "请问", "一下", "一下",
    "没有", "不是", "还是", "已经", "自己", "当时", "希望", "告诉", "回答", "记录",
    "能够", "应该", "相关", "需要", "是否", "是否", "对于", "这里", "这条", "一条",
    "不要", "不能", "不想", "而且", "所以", "觉得", "最近", "问的", "的是", "的话",
}


class MemoryRetriever:
    STRATEGIES = {"legacy", "hybrid", "bm25"}

    def __init__(self, store, threshold: float = DEFAULT_THRESHOLD, strategy: str = "hybrid"):
        if strategy not in self.STRATEGIES:
            raise ValueError(f"unsupported memory retrieval strategy: {strategy}")
        self.store = store
        self.threshold = threshold
        self.strategy = strategy

    async def retrieve(
        self,
        query: str,
        scope: Dict[str, Any] | None = None,
        as_of: datetime | str | None = None,
    ) -> Dict[str, Any]:
        result = {category: [] for category in SEARCH_CATEGORIES}
        query_lower = (query or "").lower()
        requested_scope = normalize_scope(scope) if scope is not None else None
        query_time = self._parse_time(as_of) if as_of is not None else datetime.now(timezone.utc)
        entries_by_id = {
            item.get("id"): item
            for category in SEARCH_CATEGORIES
            for item in (self.store.get(category, []) or [])
            if item.get("id")
        }

        q_tokens = tokenize(query_lower) if query_lower else set()
        for category in SEARCH_CATEGORIES:
            eligible = []
            for item in self.store.get(category, []) or []:
                if not self._scope_matches(item, requested_scope):
                    continue
                if not self._lifecycle_matches(item, query_time, entries_by_id, historical=as_of is not None):
                    continue
                if not query_lower:
                    eligible.append((item, ""))
                    continue
                text = self._text_of(item).lower()
                if not text:
                    continue
                eligible.append((item, text))

            scored = []
            corpus = [text for _, text in eligible]
            bm25_scores = self._bm25_scores(query_lower, corpus) if query_lower and self.strategy == "bm25" else None
            for index, (item, text) in enumerate(eligible):
                if not query_lower:
                    score = 0.0
                elif self.strategy == "bm25":
                    score = bm25_scores[index]
                    if score <= 0:
                        continue
                else:
                    score = (
                        self._similarity(query_lower, text, q_tokens)
                        if self.strategy == "legacy"
                        else self._hybrid_similarity(query_lower, text, q_tokens)
                    )
                    minimum_score = (
                        min(self.threshold, HISTORICAL_THRESHOLD)
                        if as_of is not None
                        else self.threshold
                    )
                    if score < minimum_score:
                        continue
                scored.append((score, item))
            scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("id", ""))))
            result[category] = [item for _, item in scored]
        return result

    @staticmethod
    def _parse_time(value: datetime | str, end_of_day: bool = False) -> datetime:
        date_only = isinstance(value, str) and len(value) == 10 and value[4:5] == "-" and value[7:8] == "-"
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        if date_only and end_of_day:
            parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @classmethod
    def _lifecycle_matches(
        cls,
        item: Dict[str, Any],
        as_of: datetime,
        entries_by_id: Dict[str, Dict[str, Any]],
        historical: bool = False,
        seen: set[str] | None = None,
    ) -> bool:
        status = item.get("status", "active")
        if status != "active" and not (historical and status in {"superseded", "expired"}):
            return False
        try:
            start = cls._parse_time(item["valid_from"]) if item.get("valid_from") else None
            end = cls._parse_time(item["valid_until"], end_of_day=True) if item.get("valid_until") else None
        except (TypeError, ValueError):
            return False
        if status != "active" and end is None:
            return False
        if (start and as_of < start) or (end and as_of > end):
            return False
        source_ids = item.get("source_ids") or []
        if source_ids:
            seen = set(seen or ())
            item_id = item.get("id")
            if item_id in seen:
                return False
            seen.add(item_id)
            for source_id in source_ids:
                source = entries_by_id.get(source_id)
                if source is None:
                    return False
                try:
                    if normalize_scope(source.get("scope")) != normalize_scope(item.get("scope")):
                        return False
                except ValueError:
                    return False
                if not cls._lifecycle_matches(
                    source, as_of, entries_by_id, historical=historical, seen=seen
                ):
                    return False
        return True

    @staticmethod
    def _scope_matches(item: Dict[str, Any], requested_scope: Dict[str, Any] | None) -> bool:
        item_scope = item.get("scope") or {"kind": "unassigned"}
        if not isinstance(item_scope, dict):
            return False
        item_kind = item_scope.get("kind", "unassigned")
        item_user_id = item_scope.get("user_id")
        requested_user_id = requested_scope.get("user_id") if requested_scope else None
        if item_user_id is not None and item_user_id != requested_user_id:
            return False
        if item_kind == "global":
            return True
        if requested_scope is None:
            return False
        if item_kind == "scenario":
            return item_scope.get("scenario_type") == requested_scope.get("scenario_type")
        if item_kind == "project":
            return (
                requested_scope.get("kind") == "project"
                and item_scope.get("project_id") == requested_scope.get("project_id")
            )
        return False

    @staticmethod
    def _text_of(item: Dict[str, Any]) -> str:
        import json

        parts = [item.get("content", item.get("text", ""))]
        for key in ("category", "source_ref", "promotion", "entities", "valid_from", "valid_until"):
            if item.get(key) is not None:
                parts.append(item[key])
        return " ".join(
            value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
            for value in parts
            if value not in (None, "", [], {})
        )

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

    @classmethod
    def _hybrid_similarity(cls, query_lower: str, text_lower: str, q_tokens) -> float:
        """Combine legacy fuzzy similarity with capped informative-token coverage.

        Long conversational queries dilute whole-query coverage. Capping the
        denominator lets a few specific shared terms surface a candidate while
        the result still passes the same threshold and remains subject to hard
        scope/lifecycle filters.
        """
        legacy_score = cls._similarity(query_lower, text_lower, q_tokens)
        if query_lower in text_lower:
            return 1.0
        informative = q_tokens - GENERIC_QUERY_TOKENS
        if not informative:
            return legacy_score
        text_tokens = tokenize(text_lower)
        overlap = informative & text_tokens
        capped_coverage = len(overlap) / min(4, len(informative))
        return max(legacy_score, capped_coverage)

    @staticmethod
    def _bm25_tokens(text: str) -> list[str]:
        """Tokenize Latin words and overlapping CJK bigrams, preserving frequency."""
        text = (text or "").lower()
        tokens = re.findall(r"[a-z0-9]+", text)
        for chunk in re.findall(r"[\u4e00-\u9fff]+", text):
            if len(chunk) == 1:
                tokens.append(chunk)
            else:
                tokens.extend(chunk[index:index + 2] for index in range(len(chunk) - 1))
        return tokens

    @classmethod
    def _bm25_similarity(
        cls,
        query: str,
        document: str,
        corpus: list[str],
        k1: float = 1.5,
        b: float = 0.75,
    ) -> float:
        """Dependency-free BM25 score computed over the already eligible corpus."""
        scores = cls._bm25_scores(query, corpus, k1=k1, b=b)
        try:
            return scores[corpus.index(document)]
        except ValueError:
            return 0.0

    @classmethod
    def _bm25_scores(
        cls,
        query: str,
        corpus: list[str],
        k1: float = 1.5,
        b: float = 0.75,
    ) -> list[float]:
        if not corpus:
            return []
        docs = [Counter(cls._bm25_tokens(text)) for text in corpus]
        query_terms = set(cls._bm25_tokens(query))
        if not query_terms:
            return [0.0] * len(corpus)
        lengths = [sum(freq.values()) for freq in docs]
        average_length = sum(lengths) / len(lengths) or 1.0
        document_frequency = Counter(term for frequency in docs for term in frequency)
        idf = {
            term: log(1 + (len(docs) - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
            for term in query_terms if document_frequency[term]
        }
        scores = []
        for frequencies, length in zip(docs, lengths):
            score = 0.0
            for term, term_idf in idf.items():
                tf = frequencies[term]
                denominator = tf + k1 * (1 - b + b * length / average_length)
                if tf and denominator:
                    score += term_idf * tf * (k1 + 1) / denominator
            scores.append(score)
        return scores
