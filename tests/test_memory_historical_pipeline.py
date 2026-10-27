"""Historical query regressions through context, period parsing and retrieval."""

import unittest
from datetime import datetime, timezone

from lifeos.memory.query_context import SessionQueryContext
from lifeos.memory.retriever import MemoryRetriever
from lifeos.memory.temporal import resolve_as_of
from tools.eval_memory_governance import load_cases


REFERENCE_TIME = datetime(2026, 10, 19, tzinfo=timezone.utc)


class HistoricalPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_chinese_periods_select_the_version_valid_at_period_end(self):
        periods = [
            ("上半年", "2026-06-30T23:59:59+00:00"),
            ("今年上半年", "2026-06-30T23:59:59+00:00"),
            ("去年下半年", "2025-12-31T23:59:59+00:00"),
            ("前年上半年", "2024-06-30T23:59:59+00:00"),
            ("今年第一季度", "2026-03-31T23:59:59+00:00"),
            ("去年第三季度", "2025-09-30T23:59:59+00:00"),
            ("2024年第四季度", "2024-12-31T23:59:59+00:00"),
            ("2026 Q2", "2026-06-30T23:59:59+00:00"),
            ("2025年2月", "2025-02-28T23:59:59+00:00"),
            ("2024年2月", "2024-02-29T23:59:59+00:00"),
        ]
        for period, expected in periods:
            with self.subTest(period=period):
                context = SessionQueryContext()
                scope = {"kind": "global"}
                context.add_and_build("history", "想核对会议纪要的格式偏好。", scope)
                query = context.add_and_build("history", f"{period}那时是什么要求？", scope)
                as_of = resolve_as_of(query, REFERENCE_TIME)
                self.assertIsNotNone(as_of)
                self.assertEqual(as_of.isoformat(), expected)
                end_date = expected[:10]
                next_day = datetime.fromtimestamp(as_of.timestamp() + 1, timezone.utc).date().isoformat()
                store = {"user": [
                    {"id": "old", "content": "会议纪要格式偏好详细叙述。", "scope": scope,
                     "status": "superseded", "valid_from": "2020-01-01", "valid_until": end_date},
                    {"id": "new", "content": "会议纪要格式偏好简洁行动项。", "scope": scope,
                     "valid_from": next_day, "version_of": "old"},
                ]}
                found = await MemoryRetriever(store).retrieve(query, scope=scope, as_of=as_of)
                self.assertEqual([item["id"] for item in found["user"]], ["old"])

    async def test_date_only_expiry_includes_last_microsecond_then_switches_version(self):
        scope = {"kind": "global"}
        store = {"user": [
            {"id": "old", "content": "会议纪要详细叙述", "scope": scope, "status": "superseded",
             "valid_from": "2026-01-01", "valid_until": "2026-06-30"},
            {"id": "new", "content": "会议纪要简洁行动项", "scope": scope,
             "valid_from": "2026-07-01", "version_of": "old"},
        ]}
        for moment, expected_id in [
            ("2026-06-30T23:59:59.999999+00:00", "old"),
            ("2026-07-01T00:00:00+00:00", "new"),
            ("2026-07-01T07:59:59.999999+08:00", "old"),
            ("2026-07-01T08:00:00+08:00", "new"),
        ]:
            with self.subTest(moment=moment):
                found = await MemoryRetriever(store).retrieve("会议纪要", scope=scope, as_of=moment)
                self.assertEqual([item["id"] for item in found["user"]], [expected_id])

    async def test_historical_floor_preserves_scope_retraction_and_source_guards(self):
        scope = {"kind": "project", "project_id": "alpha", "user_id": "user-1"}
        old = {"content": "会议纪要详细叙述", "scope": scope, "status": "superseded",
               "valid_from": "2026-01-01", "valid_until": "2026-06-30"}
        store = {"user": [
            dict(old, id="old"),
            dict(old, id="other-project", scope={**scope, "project_id": "beta"}),
            dict(old, id="other-user", scope={**scope, "user_id": "user-2"}),
            dict(old, id="retracted", status="retracted"),
            dict(old, id="missing-source", source_ids=["absent"]),
            dict(old, id="retracted-source", source_ids=["retracted"]),
            dict(old, id="foreign-source", source_ids=["other-project"]),
            dict(old, id="bad-date", valid_until="invalid"),
            dict(old, id="unbounded", valid_until=None),
            dict(old, id="future", valid_from="2026-07-01", valid_until="2026-12-31"),
        ]}
        as_of = resolve_as_of("今年上半年", REFERENCE_TIME)
        for strategy in ("hybrid", "bm25"):
            with self.subTest(strategy=strategy):
                found = await MemoryRetriever(store, strategy=strategy).retrieve(
                    "会议纪要", scope=scope, as_of=as_of
                )
                self.assertEqual([item["id"] for item in found["user"]], ["old"])

    async def test_gov_002_context_loss_does_not_fabricate_historical_evidence(self):
        case = next(case for case in load_cases() if case["case_id"] == "gov-002")
        scope = {"kind": "global"}
        store = {"user": [{**item, "scope": scope} for item in case["memories"]]}
        topic = case["conversation"][0]["content"]
        question = case["question"]
        for mode in ("same-session", "new-session", "no-session", "evicted", "scope-changed"):
            context = SessionQueryContext()
            context.add_and_build("history", topic, scope)
            if mode == "evicted":
                for _ in range(4):
                    context.add_and_build("history", "嗯", scope)
            if mode == "scope-changed":
                context.add_and_build("history", "嗯", {"kind": "project", "project_id": "beta"})
            session = "new" if mode == "new-session" else None if mode == "no-session" else "history"
            query = context.add_and_build(session, question, scope)
            as_of = resolve_as_of(query, REFERENCE_TIME)
            self.assertEqual(as_of.isoformat(), "2026-06-30T23:59:59+00:00")
            for strategy in ("hybrid", "bm25"):
                with self.subTest(mode=mode, strategy=strategy):
                    found = await MemoryRetriever(store, strategy=strategy).retrieve(query, scope=scope, as_of=as_of)
                    expected = ["m-201"] if mode == "same-session" else []
                    self.assertEqual([item["id"] for item in found["user"]], expected)


if __name__ == "__main__":
    unittest.main()
