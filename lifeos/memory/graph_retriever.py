"""Small provenance-aware graph retrieval prototype.

This is an offline relation-path experiment, not a graph database or a
production entity extractor. Facts must be supplied with explicit entities,
scope and source lineage.
"""

from collections import defaultdict, deque
from datetime import datetime

from lifeos.memory.retriever import MemoryRetriever
from lifeos.memory.schema import normalize_scope


def retrieve_graph_facts(
    query: str,
    facts: list[dict],
    source_records: list[dict],
    *,
    scope: dict,
    as_of: datetime | str | None = None,
    top_k: int = 5,
    max_hops: int = 2,
) -> list[dict]:
    """Return source-backed edges on short paths between query-mentioned entities."""
    if top_k < 1 or max_hops < 1:
        return []
    normalized_query = " ".join((query or "").casefold().split())
    requested_scope = normalize_scope(scope)
    by_id = {record.get("id"): record for record in source_records if record.get("id")}
    all_by_id = {**by_id, **{fact.get("id"): fact for fact in facts if fact.get("id")}}
    query_time = MemoryRetriever._parse_time(as_of) if as_of is not None else datetime.now().astimezone()
    eligible = []
    for fact in facts:
        if not isinstance(fact.get("subject"), str) or not isinstance(fact.get("object"), str):
            continue
        if not fact.get("source_ids"):
            continue
        if not MemoryRetriever._scope_matches(fact, requested_scope):
            continue
        if not MemoryRetriever._lifecycle_matches(
            fact, query_time, all_by_id, historical=as_of is not None
        ):
            continue
        eligible.append(fact)

    entities = {
        entity
        for fact in eligible
        for entity in (fact["subject"], fact["object"])
        if entity.casefold() in normalized_query
    }
    if len(entities) < 2:
        return []

    adjacency = defaultdict(list)
    for fact in eligible:
        adjacency[fact["subject"]].append((fact["object"], fact))
        adjacency[fact["object"]].append((fact["subject"], fact))

    selected = {}
    for start in sorted(entities):
        queue = deque([(start, 0, [])])
        visited = {start: 0}
        while queue:
            node, depth, path = queue.popleft()
            if depth >= max_hops:
                continue
            for neighbor, edge in adjacency[node]:
                next_path = path + [edge]
                if neighbor in entities and neighbor != start:
                    for path_edge in next_path:
                        selected[path_edge["id"]] = path_edge
                if visited.get(neighbor, max_hops + 1) > depth + 1:
                    visited[neighbor] = depth + 1
                    queue.append((neighbor, depth + 1, next_path))

    return sorted(selected.values(), key=lambda fact: (len(fact.get("source_ids", [])), fact["id"]))[:top_k]
