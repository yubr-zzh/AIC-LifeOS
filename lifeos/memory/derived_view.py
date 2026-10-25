"""Deterministic, rebuildable derived-memory views.

This module deliberately does not generate semantic claims. Callers provide
claims and their source MemoryRecord identifiers; this module validates
lineage, scope, and current source eligibility only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .schema import normalize_scope


@dataclass(frozen=True)
class SourceVersion:
    record_id: str
    revision: str


@dataclass(frozen=True)
class DerivedClaim:
    claim_id: str
    text: str
    scope: Mapping[str, Any]
    sources: tuple[SourceVersion, ...]
    semantic_key: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None


@dataclass(frozen=True)
class ClaimState:
    claim: DerivedClaim
    status: str
    invalid_sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class DerivedMemoryView:
    view_id: str
    view_type: str
    scope: Mapping[str, Any]
    generation_id: str
    generated_at: str
    claims: tuple[ClaimState, ...]
    status: str

    @property
    def active_claims(self) -> tuple[DerivedClaim, ...]:
        """Claims whose entire declared support set is currently eligible."""
        return tuple(item.claim for item in self.claims if item.status == "active")


def build_derived_view(
    *,
    view_id: str,
    view_type: str,
    generation_id: str,
    scope: Mapping[str, Any],
    claims: Iterable[DerivedClaim],
    source_records: Iterable[Mapping[str, Any]],
    as_of: datetime | None = None,
) -> DerivedMemoryView:
    """Build the view from claims and current sources without mutating either.

    A claim is active only when every declared source exists at the recorded
    revision, is active, is in the exact same scope, and is within its validity
    interval. Missing lineage fails closed. Rebuilding with changed source
    records deterministically changes eligibility while retaining the claim.
    """
    if not view_id or not view_type or not generation_id:
        raise ValueError("view_id, view_type, and generation_id are required")
    normalized_view_scope = normalize_scope(dict(scope))
    when = _as_utc(as_of or datetime.now(timezone.utc))
    sources_by_id = _index_sources(source_records)
    states: list[ClaimState] = []

    for claim in claims:
        if not claim.claim_id or not claim.text.strip():
            raise ValueError("each claim requires claim_id and non-empty text")
        claim_scope = normalize_scope(dict(claim.scope))
        if claim_scope != normalized_view_scope:
            raise ValueError(f"claim {claim.claim_id} scope does not match view scope")
        if not claim.sources:
            raise ValueError(f"claim {claim.claim_id} requires at least one source")
        _validate_claim_validity(claim, when)

        invalid: list[str] = []
        for source_version in claim.sources:
            record = sources_by_id.get(source_version.record_id)
            reason = _source_invalid_reason(record, source_version, claim_scope, when)
            if reason:
                invalid.append(f"{source_version.record_id}:{reason}")
        status = "active" if not invalid else "stale"
        states.append(ClaimState(claim=claim, status=status, invalid_sources=tuple(invalid)))

    view_status = "active" if all(state.status == "active" for state in states) else "stale"
    return DerivedMemoryView(
        view_id=view_id,
        view_type=view_type,
        scope=normalized_view_scope,
        generation_id=generation_id,
        generated_at=when.isoformat(),
        claims=tuple(states),
        status=view_status,
    )


def _index_sources(records: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for record in records:
        record_id = record.get("id")
        if not isinstance(record_id, str) or not record_id:
            raise ValueError("source MemoryRecord requires a non-empty id")
        if record_id in result:
            raise ValueError(f"duplicate source MemoryRecord id: {record_id}")
        result[record_id] = record
    return result


def _source_invalid_reason(
    record: Mapping[str, Any] | None,
    expected: SourceVersion,
    claim_scope: Mapping[str, Any],
    when: datetime,
) -> str | None:
    if record is None:
        return "missing"
    ref = record.get("source_ref")
    if not isinstance(ref, Mapping) or not isinstance(ref.get("revision"), str) or not ref["revision"].strip():
        return "missing_revision"
    if ref["revision"] != expected.revision:
        return "revision_mismatch"
    if normalize_scope(record.get("scope")) != claim_scope:
        return "scope_mismatch"
    if record.get("status", "active") != "active":
        return str(record.get("status") or "inactive")
    if record.get("superseded_by"):
        return "superseded"
    if not _within_validity(record.get("valid_from"), record.get("valid_until"), when):
        return "expired_or_not_yet_valid"
    return None


def _validate_claim_validity(claim: DerivedClaim, when: datetime) -> None:
    if not _within_validity(claim.valid_from, claim.valid_until, when):
        raise ValueError(f"claim {claim.claim_id} is outside its validity interval")


def _within_validity(start_value: str | None, end_value: str | None, when: datetime) -> bool:
    start = _parse_time(start_value) if start_value else None
    end = _parse_time(end_value) if end_value else None
    return (start is None or start <= when) and (end is None or when < end)


def _parse_time(value: str) -> datetime:
    try:
        return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"invalid ISO-8601 timestamp: {value}") from exc


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
