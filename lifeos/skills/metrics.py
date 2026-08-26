"""Shared metric helpers for skill detection and evaluation.

Kept dependency-free so both the detector and the registry can import
them without circular imports.
"""

import re


def tokenize(text: str) -> set[str]:
    """Coarse tokenization for CJK + latin text.

    CJK text is split into 2-grams to capture meaningful chunks;
    latin words are lowercased and split on non-alphanumerics.
    """
    if not text:
        return set()
    text_l = str(text).lower()
    tokens = set()
    tokens.update(re.findall(r"[a-z0-9]+", text_l))
    cjk = re.findall(r"[\u4e00-\u9fff]+", text_l)
    for chunk in cjk:
        for i in range(len(chunk) - 1):
            tokens.add(chunk[i : i + 2])
        if len(chunk) == 1:
            tokens.add(chunk)
    return tokens


def jaccard(a: set, b: set) -> float:
    """Jaccard similarity between two token sets."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def normalize(value: float) -> float:
    """Clamp a score into [0.0, 1.0]."""
    return max(0.0, min(1.0, value))


def keyword_similarity(query_text, keywords) -> float:
    """Similarity between a query and a keyword list.

    Mixes two signals so short CJK queries still score meaningfully:
    - direct keyword hits: how many list keywords appear verbatim
      (normalized so 3+ hits saturate at 1.0)
    - token coverage: how much of the query's token set is covered by
      the keyword token set

    Returns the stronger of the two signals.
    """
    if not query_text or not keywords:
        return 0.0
    text_l = str(query_text).lower()
    q_tokens = tokenize(query_text)
    kw_tokens = set()
    direct_hits = 0
    for kw in keywords:
        kw_l = str(kw).lower()
        kw_tokens |= tokenize(kw_l)
        if kw_l in text_l:
            direct_hits += 1
    hit_rate = min(direct_hits, 3) / 3.0
    cover = len(q_tokens & kw_tokens) / len(q_tokens) if q_tokens else 0.0
    return max(hit_rate, cover)
