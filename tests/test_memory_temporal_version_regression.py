"""Offline regression from Chinese period resolution to version selection."""

from datetime import datetime, timedelta, timezone
import unittest

from lifeos.memory.retriever import MemoryRetriever
from lifeos.memory.temporal import resolve_as_of


REFERENCE = datetime(2026, 10, 19, tzinfo=timezone.utc)
PERIODS = (
    ("上半年", "2026-06-30"),
    ("今年下半年", "2026-12-31"),
    ("去年上半年", "2025-06-30"),
    ("去年下半年", "2025-12-31"),
    ("前年上半年", "2024-06-30"),
    ("前年下半年", "2024-12-31"),
    ("今年第一季度", "2026-03-31"),
    ("今年第二季度", "2026-06-30"),
    ("去年第三季度", "2025-09-30"),
    ("2024年第四季度", "2024-12-31"),
    ("2026 Q1", "2026-03-31"),
    ("2026 q2", "2026-06-30"),
    ("2025 Q3", "2025-09-30"),
    ("2025 Q4", "2025-12-31"),
    ("2024年2月", "2024-02-29"),
    ("2025年2月", "2025-02-28"),
    ("2026年2月", "2026-02-28"),
    ("2025年12月", "2025-12-31"),
)


class ChinesePeriodVersionRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_period_end_selects_old_version_and_next_second_selects_new(self):
        for phrase, end_date in PERIODS:
            # Expected instants are explicit fixtures, independent of the resolver.
            expected = datetime.fromisoformat(end_date + "T23:59:59+00:00")
            next_start = expected + timedelta(seconds=1)
            scope = {"kind": "project", "project_id": "alpha"}
            query = f"{phrase}的会议纪要格式是什么？"
            resolved = resolve_as_of(query, REFERENCE)
            with self.subTest(phrase=phrase, stage="resolution"):
                self.assertEqual(resolved, expected)
            store = {"user": [
                {"id": "old", "content": "会议纪要格式采用详细叙述。",
                 "scope": scope, "status": "superseded", "superseded_by": "new",
                 "valid_from": "2024-01-01", "valid_until": end_date},
                {"id": "new", "content": "会议纪要格式采用简洁行动项。",
                 "scope": scope, "version_of": "old",
                 "valid_from": next_start.isoformat()},
                # An exact lexical match must never bypass scope or retraction.
                {"id": "other-project", "content": query,
                 "scope": {"kind": "project", "project_id": "beta"}},
                {"id": "retracted", "content": query, "scope": scope,
                 "status": "retracted", "valid_until": end_date},
            ]}
            for strategy in ("hybrid", "bm25"):
                retriever = MemoryRetriever(store, strategy=strategy)
                for instant, wanted in ((resolved, "old"), (next_start, "new")):
                    with self.subTest(phrase=phrase, strategy=strategy, as_of=instant):
                        found = await retriever.retrieve(query, scope=scope, as_of=instant)
                        self.assertEqual([item["id"] for item in found["user"]], [wanted])

    async def test_explicit_timestamp_validity_is_inclusive_without_date_expansion(self):
        store = {"user": [
            {"id": "old", "content": "会议纪要格式采用详细叙述。",
             "scope": {"kind": "global"}, "status": "expired",
             "valid_until": "2026-06-30T12:00:00+00:00"},
        ]}
        for strategy in ("hybrid", "bm25"):
            retriever = MemoryRetriever(store, strategy=strategy)
            for instant, wanted in (
                ("2026-06-30T20:00:00+08:00", ["old"]),
                ("2026-06-30T12:00:00.000001+00:00", []),
                ("2026-06-30T23:59:59+00:00", []),
            ):
                with self.subTest(strategy=strategy, as_of=instant):
                    found = await retriever.retrieve("会议纪要格式", as_of=instant)
                    self.assertEqual([item["id"] for item in found["user"]], wanted)

    def test_invalid_month_and_non_temporal_queries_are_not_resolved(self):
        for query in ("2026年0月", "2026年13月", "最近的会议纪要", "会议纪要格式"):
            with self.subTest(query=query):
                self.assertIsNone(resolve_as_of(query, REFERENCE))


if __name__ == "__main__":
    unittest.main()
