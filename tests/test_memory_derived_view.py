import unittest
from datetime import datetime, timezone

from lifeos.memory.derived_view import (
    DerivedClaim,
    SourceVersion,
    build_derived_view,
)


NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
PROJECT_SCOPE = {
    "kind": "project",
    "project_id": "lifeos",
    "scenario_type": None,
    "user_id": "u-1",
}


def source(**overrides):
    item = {
        "id": "m-1",
        "scope": dict(PROJECT_SCOPE),
        "status": "active",
        "source_ref": {"kind": "conversation", "record_id": "c-1", "revision": "r3"},
        "valid_from": "2026-10-01T00:00:00+00:00",
        "valid_until": None,
    }
    item.update(overrides)
    return item


def claim(*sources):
    return DerivedClaim(
        claim_id="claim-1",
        text="项目默认使用 Python。",
        semantic_key="project.language",
        scope=dict(PROJECT_SCOPE),
        sources=tuple(sources or (SourceVersion("m-1", "r3"),)),
    )


def build(records, claims=None):
    return build_derived_view(
        view_id="view-1",
        view_type="project_summary",
        generation_id="gen-9",
        scope=PROJECT_SCOPE,
        claims=claims or [claim()],
        source_records=records,
        as_of=NOW,
    )


class DerivedViewTests(unittest.TestCase):
    def test_active_source_produces_traceable_active_claim(self):
        view = build([source()])
        self.assertEqual(view.status, "active")
        self.assertEqual(view.active_claims[0].sources, (SourceVersion("m-1", "r3"),))

    def test_retraction_invalidates_claim_without_deleting_lineage(self):
        view = build([source(status="retracted")])
        self.assertEqual(view.claims[0].status, "stale")
        self.assertEqual(view.claims[0].invalid_sources, ("m-1:retracted",))
        self.assertEqual(view.claims[0].claim.sources, (SourceVersion("m-1", "r3"),))
        self.assertEqual(view.active_claims, ())

    def test_expired_source_invalidates_claim(self):
        view = build([source(valid_until="2026-10-19T11:59:59+00:00")])
        self.assertEqual(view.claims[0].status, "stale")
        self.assertEqual(view.claims[0].invalid_sources, ("m-1:expired_or_not_yet_valid",))

    def test_superseded_source_invalidates_claim(self):
        view = build([source(status="superseded", superseded_by="m-2")])
        self.assertEqual(view.claims[0].invalid_sources, ("m-1:superseded",))

    def test_scope_mismatch_fails_closed_at_claim_level(self):
        other_scope = {**PROJECT_SCOPE, "project_id": "other"}
        view = build([source(scope=other_scope)])
        self.assertEqual(view.claims[0].invalid_sources, ("m-1:scope_mismatch",))

    def test_claim_scope_must_match_view_scope(self):
        wrong_scope_claim = DerivedClaim(
            claim_id="claim-other",
            text="Wrong project",
            scope={**PROJECT_SCOPE, "project_id": "other"},
            sources=(SourceVersion("m-1", "r3"),),
        )
        with self.assertRaisesRegex(ValueError, "scope does not match"):
            build([source()], [wrong_scope_claim])

    def test_source_revision_is_mandatory_and_must_match(self):
        missing = build([source(source_ref={"kind": "conversation", "record_id": "c-1"})])
        mismatch = build([source(source_ref={"kind": "conversation", "record_id": "c-1", "revision": "r2"})])
        self.assertEqual(missing.claims[0].invalid_sources, ("m-1:missing_revision",))
        self.assertEqual(mismatch.claims[0].invalid_sources, ("m-1:revision_mismatch",))

    def test_every_declared_source_must_be_valid(self):
        two_source_claim = claim(SourceVersion("m-1", "r3"), SourceVersion("m-2", "r1"))
        view = build(
            [
                source(),
                source(
                    id="m-2",
                    status="retracted",
                    source_ref={"kind": "conversation", "record_id": "c-2", "revision": "r1"},
                ),
            ],
            [two_source_claim],
        )
        self.assertEqual(view.claims[0].invalid_sources, ("m-2:retracted",))

    def test_missing_source_fails_closed(self):
        view = build([])
        self.assertEqual(view.claims[0].invalid_sources, ("m-1:missing",))


if __name__ == "__main__":
    unittest.main()
