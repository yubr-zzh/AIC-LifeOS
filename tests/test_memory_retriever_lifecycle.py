import unittest

from lifeos.memory.retriever import MemoryRetriever


class MemoryRetrieverLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_bm25_ranks_chinese_candidates_after_scope_and_lifecycle_filters(self):
        store = {
            "user": [
                {"id": "weak", "content": "周末计划，准备读书", "scope": {"kind": "global"}},
                {"id": "strong", "content": "周末去杭州旅行，计划西湖和灵隐寺行程", "scope": {"kind": "global"}},
                {"id": "wrong-scope", "content": "杭州旅行，西湖路线", "scope": {"kind": "project", "project_id": "other"}},
                {"id": "retracted", "content": "杭州旅行，西湖路线", "scope": {"kind": "global"}, "status": "retracted"},
            ]
        }
        found = await MemoryRetriever(store, strategy="bm25").retrieve(
            "我周末去杭州旅行，西湖有什么行程安排", scope={"kind": "project", "project_id": "alpha"}
        )
        self.assertEqual([item["id"] for item in found["user"]], ["strong", "weak"])

    async def test_bm25_can_retrieve_historical_version_after_as_of_filter(self):
        store = {
            "user": [
                {"id": "old", "content": "杭州办公室每周一开会", "scope": {"kind": "global"}, "status": "superseded", "valid_from": "2026-01-01T00:00:00+00:00", "valid_until": "2026-06-30T23:59:59+00:00"},
                {"id": "new", "content": "上海办公室每周三开会", "scope": {"kind": "global"}, "valid_from": "2026-07-01T00:00:00+00:00"},
            ]
        }
        found = await MemoryRetriever(store, strategy="bm25").retrieve(
            "杭州办公室每周开会", as_of="2026-05-01T00:00:00+00:00"
        )
        self.assertEqual([item["id"] for item in found["user"]], ["old"])

    async def test_hybrid_uses_as_of_floor_for_paraphrased_historical_memory(self):
        store = {
            "user": [
                {"id": "old", "content": "用户偏好详细叙述式会议纪要。", "scope": {"kind": "global"}, "status": "superseded", "valid_from": "2026-01-01", "valid_until": "2026-06-30", "superseded_by": "new"},
                {"id": "new", "content": "用户偏好先给结论、再列行动项的简洁格式。", "scope": {"kind": "global"}, "valid_from": "2026-07-01", "version_of": "old"},
                {"id": "unrelated", "content": "周末喜欢烤箱做披萨。", "scope": {"kind": "global"}, "status": "superseded", "valid_from": "2026-01-01", "valid_until": "2026-06-30"},
            ]
        }
        query = (
            "我在回看今年年初的项目周会记录，想把当时的纪要习惯和现在对照一下。 "
            "具体说上半年那段时间，我是不是还希望把讨论过程写得比较完整，而不是现在这种先看结论和行动项的简洁格式？"
        )
        found = await MemoryRetriever(store, strategy="hybrid").retrieve(
            query, scope={"kind": "global"}, as_of="2026-06-30T23:59:59+00:00"
        )
        self.assertIn("old", [item["id"] for item in found["user"]])
        self.assertNotIn("new", [item["id"] for item in found["user"]])
        self.assertNotIn("unrelated", [item["id"] for item in found["user"]])

    async def test_retriever_rejects_unknown_strategy(self):
        with self.assertRaises(ValueError):
            MemoryRetriever({}, strategy="semantic")

    async def test_hybrid_remains_the_default_strategy(self):
        self.assertEqual(MemoryRetriever({}).strategy, "hybrid")

    async def test_current_retrieval_excludes_expired_and_future_memories(self):
        store = {
            "user": [
                {"id": "current", "content": "weekly office schedule Tuesday", "scope": {"kind": "global"}},
                {"id": "expired", "content": "weekly office schedule Wednesday", "scope": {"kind": "global"}, "valid_until": "2026-10-01T00:00:00+00:00"},
                {"id": "future", "content": "weekly office schedule Friday", "scope": {"kind": "global"}, "valid_from": "2026-11-01T00:00:00+00:00"},
            ]
        }
        found = await MemoryRetriever(store).retrieve(
            "weekly office schedule", as_of="2026-10-18T00:00:00+00:00"
        )
        self.assertEqual({item["id"] for item in found["user"]}, {"current"})

    async def test_historical_as_of_can_select_superseded_version(self):
        store = {
            "user": [
                {"id": "old", "content": "preferred meeting format detailed narrative", "scope": {"kind": "global"}, "status": "superseded", "valid_from": "2026-01-01T00:00:00+00:00", "valid_until": "2026-06-30T23:59:59+00:00"},
                {"id": "new", "content": "preferred meeting format concise action list", "scope": {"kind": "global"}, "valid_from": "2026-07-01T00:00:00+00:00"},
            ]
        }
        retriever = MemoryRetriever(store)
        old = await retriever.retrieve("preferred meeting format", as_of="2026-05-01T00:00:00+00:00")
        now = await retriever.retrieve("preferred meeting format", as_of="2026-10-18T00:00:00+00:00")
        self.assertEqual({item["id"] for item in old["user"]}, {"old"})
        self.assertEqual({item["id"] for item in now["user"]}, {"new"})

    async def test_derived_memory_is_hidden_when_a_source_is_invalid(self):
        store = {
            "user": [
                {"id": "source", "content": "prefers evening work", "scope": {"kind": "global"}, "status": "retracted"},
                {"id": "derived", "content": "profile evening work preference", "scope": {"kind": "global"}, "source_ids": ["source"]},
            ]
        }
        found = await MemoryRetriever(store).retrieve("evening work preference")
        self.assertEqual(found["user"], [])

    async def test_derived_memory_is_hidden_when_source_scope_differs(self):
        store = {
            "user": [
                {"id": "source", "content": "prefers evening work", "scope": {"kind": "project", "project_id": "alpha"}},
                {"id": "derived", "content": "profile evening work preference", "scope": {"kind": "global"}, "source_ids": ["source"]},
            ]
        }
        found = await MemoryRetriever(store).retrieve("evening work preference")
        self.assertEqual(found["user"], [])

    async def test_invalid_lifecycle_timestamp_fails_closed(self):
        store = {
            "user": [
                {"id": "bad-date", "content": "project schedule weekly meeting", "scope": {"kind": "global"}, "valid_until": "not-a-date"}
            ]
        }
        found = await MemoryRetriever(store).retrieve("project schedule weekly meeting")
        self.assertEqual(found["user"], [])

    async def test_hybrid_score_recovers_relevant_record_from_conversational_query(self):
        store = {
            "user": [
                {
                    "id": "meeting-style",
                    "content": "用户偏好先给结论、再列行动项的简洁会议纪要。",
                    "scope": {"kind": "global"},
                }
            ]
        }
        query = "对，之后如果我让你整理会议纪要，请先把结论放前面，再清楚列出谁要做什么，不用把讨论过程写成很长的流水账。"
        found = await MemoryRetriever(store).retrieve(query, scope={"kind": "global"})
        self.assertEqual([item["id"] for item in found["user"]], ["meeting-style"])


if __name__ == "__main__":
    unittest.main()
