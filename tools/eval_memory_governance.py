"""Deterministic retrieval baseline for the synthetic governance mini-set.

This evaluates candidate retrieval and governance filters only. It does not
generate answers or claim LongMemEval-compatible answer accuracy.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lifeos.memory.retriever import DEFAULT_THRESHOLD, HISTORICAL_THRESHOLD, MemoryRetriever
from lifeos.memory.temporal import resolve_as_of


CASES_PATH = ROOT / "datasets" / "lifeos-governance-v1" / "cases.jsonl"
DEFAULT_OUTPUT = ROOT / "artifacts" / "memory-governance-baseline.json"


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _scope_allowed(memory_scope: dict[str, Any], request_scope: dict[str, Any]) -> bool:
    """Hard scope boundary: project may see itself and approved global scope."""
    memory_user = memory_scope.get("user_id")
    request_user = request_scope.get("user_id")
    if memory_user is not None and memory_user != request_user:
        return False
    kind = memory_scope.get("type", memory_scope.get("kind", "unassigned"))
    requested = request_scope.get("type", request_scope.get("kind"))
    if kind == "global":
        return True
    if kind == "project":
        return (
            requested == "project"
            and memory_scope.get("project_id") == request_scope.get("project_id")
        )
    return False


def _currently_valid(memory: dict[str, Any], as_of: datetime, by_id: dict[str, dict[str, Any]]) -> bool:
    return MemoryRetriever._lifecycle_matches(memory, as_of, by_id)


def _rank(
    query: str,
    memories: list[dict[str, Any]],
    scorer: str = "legacy",
    threshold: float = DEFAULT_THRESHOLD,
) -> list[tuple[float, dict[str, Any]]]:
    scored = []
    query_lower = query.lower()
    corpus = [MemoryRetriever._text_of(memory).lower() for memory in memories]
    tokens = None
    bm25_scores = MemoryRetriever._bm25_scores(query_lower, corpus) if scorer == "bm25" else None
    for index, (memory, text) in enumerate(zip(memories, corpus)):
        if not text:
            continue
        if tokens is None:
            from lifeos.skills.metrics import tokenize

            tokens = tokenize(query_lower)
        if scorer == "bm25":
            score = bm25_scores[index]
            eligible = score > 0
        else:
            score = (
                MemoryRetriever._hybrid_similarity(query_lower, text, tokens)
                if scorer == "hybrid"
                else MemoryRetriever._similarity(query_lower, text, tokens)
            )
            eligible = score >= threshold
        if eligible:
            scored.append((score, memory))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
    return scored


def evaluate(cases: list[dict[str, Any]], k: int = 5, scorer: str = "legacy") -> dict[str, Any]:
    rows = []
    total_evidence = 0
    recalled_evidence = 0
    guarded_recalled_evidence = 0
    all_evidence_hits = 0
    guarded_all_evidence_hits = 0
    historical_recalled_evidence = 0
    historical_total_evidence = 0
    historical_all_evidence_hits = 0
    temporal_cases = 0
    evidence_cases = 0
    forbidden_hits = 0
    scope_violations = 0
    for case in cases:
        query = " ".join(
            [turn["content"] for turn in case.get("conversation", []) if turn["role"] == "user"]
            + [case["question"]]
        )
        in_scope = [
            memory
            for memory in case["memories"]
            if _scope_allowed(memory.get("scope", {}), case["request_scope"])
        ]
        scope_violations += sum(
            1
            for memory in case["memories"]
            if not _scope_allowed(memory.get("scope", {}), case["request_scope"])
            and memory["id"] in case["expected_evidence_ids"]
        )
        raw_top = _rank(query, in_scope, scorer)[:k]
        raw_ids = [memory["id"] for _, memory in raw_top]
        as_of = resolve_as_of(query, _parse_time(case["as_of"])) or _parse_time(case["as_of"])
        assert as_of is not None
        by_id = {memory["id"]: memory for memory in case["memories"]}
        query_as_of = resolve_as_of(query, _parse_time(case["as_of"]))
        historical_ids = []
        if query_as_of is not None:
            historical_valid = [
                memory for memory in in_scope
                if MemoryRetriever._lifecycle_matches(memory, query_as_of, by_id, historical=True)
            ]
            # Keep prior turns in the ranking query: they often name the topic
            # while the final ask contributes the historical date and contrast.
            historical_ids = [
                memory["id"]
                for _, memory in _rank(
                    query, historical_valid, scorer, threshold=HISTORICAL_THRESHOLD
                )[:k]
            ]
        valid = [memory for memory in in_scope if _currently_valid(memory, as_of, by_id)]
        guarded_top = _rank(query, valid, scorer)[:k]
        guarded_ids = [memory["id"] for _, memory in guarded_top]
        evidence = set(case["expected_evidence_ids"])
        forbidden = set(case["must_not_use_ids"])
        raw_recalled = evidence & set(raw_ids)
        guarded_recalled = evidence & set(guarded_ids)
        historical_recalled = evidence & set(historical_ids)
        if query_as_of is not None and evidence:
            temporal_cases += 1
            historical_total_evidence += len(evidence)
            historical_recalled_evidence += len(historical_recalled)
            historical_all_evidence_hits += int(evidence <= set(historical_ids))
        total_evidence += len(evidence)
        recalled_evidence += len(raw_recalled)
        guarded_recalled_evidence += len(guarded_recalled)
        if evidence:
            evidence_cases += 1
            all_evidence_hits += int(evidence <= set(raw_ids))
            guarded_all_evidence_hits += int(evidence <= set(guarded_ids))
        forbidden_hits += len(forbidden & set(guarded_ids))
        rows.append(
            {
                "case_id": case["case_id"],
                "category": case["category"],
                "expected_action": case["expected_action"],
                "expected_evidence_ids": sorted(evidence),
                "raw_top_k": raw_ids,
                "guarded_current_top_k": guarded_ids,
                "historical_as_of_top_k": historical_ids,
                "raw_evidence_recall": len(raw_recalled) / len(evidence) if evidence else None,
                "guarded_evidence_recall": len(guarded_recalled) / len(evidence) if evidence else None,
                "forbidden_ids_in_guarded_top_k": sorted(forbidden & set(guarded_ids)),
            }
        )
    return {
        "dataset": "lifeos-governance-mini-set",
        "k": k,
        "method": f"LifeOS {scorer} lexical retrieval (threshold={DEFAULT_THRESHOLD}; scope filtered; current-validity filter reported separately)",
        "limitations": [
            "No answer generation or semantic judge is run.",
            "Historical, retracted, and expired evidence may be needed to explain history or lifecycle; the current-validity view deliberately excludes it.",
            "This synthetic mini-set is not a substitute for LongMemEval.",
        ],
        "metrics": {
            "raw_evidence_recall_at_k": recalled_evidence / total_evidence if total_evidence else 0.0,
            "raw_all_evidence_recall_rate": all_evidence_hits / evidence_cases if evidence_cases else 0.0,
            "current_valid_evidence_recall_at_k": guarded_recalled_evidence / total_evidence if total_evidence else 0.0,
            "current_valid_all_evidence_recall_rate": guarded_all_evidence_hits / evidence_cases if evidence_cases else 0.0,
            "forbidden_current_candidate_hits": forbidden_hits,
            "cross_scope_expected_evidence_violations": scope_violations,
            "historical_as_of_evidence_recall_at_k": historical_recalled_evidence / historical_total_evidence if historical_total_evidence else 0.0,
            "historical_as_of_all_evidence_recall_rate": historical_all_evidence_hits / temporal_cases if temporal_cases else 0.0,
            "explicit_temporal_cases": temporal_cases,
            "cases_with_evidence": evidence_cases,
            "total_expected_evidence_items": total_evidence,
        },
        "cases": rows,
    }


def load_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=CASES_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("-k", type=int, default=5)
    parser.add_argument("--scorer", choices=("legacy", "hybrid", "bm25"), default="legacy")
    args = parser.parse_args()
    if args.k < 1:
        parser.error("-k must be >= 1")
    result = evaluate(load_cases(args.dataset), k=args.k, scorer=args.scorer)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))
    print(f"Detailed report: {args.output.relative_to(ROOT) if args.output.is_relative_to(ROOT) else args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
