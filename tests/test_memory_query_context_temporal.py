import unittest
from datetime import datetime, timezone

from lifeos.memory.query_context import SessionQueryContext
from lifeos.memory.temporal import resolve_as_of


class QueryContextTemporalTests(unittest.TestCase):
    def test_context_uses_only_same_session_and_scope(self):
        context = SessionQueryContext()
        scope = {"kind": "project", "project_id": "alpha"}
        context.add_and_build("s1", "我在 alpha 处理发布", scope)
        self.assertIn("发布", context.add_and_build("s1", "失败原因是什么", scope))
        self.assertEqual("失败原因是什么", context.add_and_build("s2", "失败原因是什么", scope))
        self.assertEqual("换个项目继续", context.add_and_build("s1", "换个项目继续", {"kind": "project", "project_id": "beta"}))

    def test_context_is_bounded(self):
        context = SessionQueryContext(max_turns=2, max_chars=12)
        context.add_and_build("s", "12345678")
        result = context.add_and_build("s", "abcdefgh")
        self.assertLessEqual(len(result), 12)
        self.assertIn("abcdefgh", result)

    def test_resolves_half_year_and_month_end(self):
        ref = datetime(2026, 10, 18, tzinfo=timezone.utc)
        self.assertEqual(datetime(2026, 6, 30, 23, 59, 59, tzinfo=timezone.utc), resolve_as_of("今年上半年", ref))
        self.assertEqual(datetime(2025, 6, 30, 23, 59, 59, tzinfo=timezone.utc), resolve_as_of("去年上半年", ref))
        self.assertEqual(datetime(2025, 2, 28, 23, 59, 59, tzinfo=timezone.utc), resolve_as_of("2025年2月", ref))
        self.assertIsNone(resolve_as_of("最近怎么样", ref))

    def test_resolves_chinese_quarters_and_english_quarter_notation(self):
        ref = datetime(2026, 10, 18, tzinfo=timezone.utc)
        self.assertEqual(datetime(2026, 3, 31, 23, 59, 59, tzinfo=timezone.utc), resolve_as_of("今年第一季度", ref))
        self.assertEqual(datetime(2025, 9, 30, 23, 59, 59, tzinfo=timezone.utc), resolve_as_of("去年第三季度", ref))
        self.assertEqual(datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc), resolve_as_of("2026 Q4", ref))


if __name__ == "__main__":
    unittest.main()
