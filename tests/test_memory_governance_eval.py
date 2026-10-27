import unittest

from tools.eval_memory_governance import CASES_PATH, _scope_allowed, evaluate, load_cases


class GovernanceEvalTests(unittest.TestCase):
    def test_project_scope_excludes_other_projects_and_unassigned(self):
        requested = {"type": "project", "project_id": "alpha"}
        self.assertTrue(_scope_allowed({"type": "project", "project_id": "alpha"}, requested))
        self.assertTrue(_scope_allowed({"type": "global"}, requested))
        self.assertFalse(_scope_allowed({"type": "project", "project_id": "beta"}, requested))
        self.assertFalse(_scope_allowed({"type": "unassigned"}, requested))
        self.assertFalse(
            _scope_allowed({"type": "global", "user_id": "other-user"}, {**requested, "user_id": "user-1"})
        )

    def test_validity_guard_does_not_return_superseded_current_value(self):
        case = {
            "case_id": "test-version",
            "category": "version",
            "as_of": "2026-10-18T10:00:00+08:00",
            "request_scope": {"type": "global"},
            "question": "What is my current editor?",
            "memories": [
                {"id": "old", "text": "Current editor is Vim.", "scope": {"type": "global"}, "status": "superseded"},
                {"id": "new", "text": "Current editor is VS Code.", "scope": {"type": "global"}, "status": "active"},
            ],
            "expected_action": "answer",
            "expected_answer": "VS Code",
            "expected_evidence_ids": ["new"],
            "must_not_use_ids": ["old"],
        }
        result = evaluate([case], k=2)
        self.assertIn("new", result["cases"][0]["guarded_current_top_k"])
        self.assertNotIn("old", result["cases"][0]["guarded_current_top_k"])
        self.assertEqual(result["metrics"]["forbidden_current_candidate_hits"], 0)

    def test_historical_as_of_filter_admits_old_version_and_excludes_current(self):
        case = next(case for case in load_cases(CASES_PATH) if case["case_id"] == "gov-002")
        result = evaluate([case], scorer="hybrid")
        from lifeos.memory.temporal import resolve_as_of
        from tools.eval_memory_governance import _parse_time
        from lifeos.memory.retriever import MemoryRetriever

        as_of = resolve_as_of(case["question"], _parse_time(case["as_of"]))
        by_id = {memory["id"]: memory for memory in case["memories"]}
        self.assertTrue(MemoryRetriever._lifecycle_matches(by_id["m-201"], as_of, by_id, historical=True))
        self.assertFalse(MemoryRetriever._lifecycle_matches(by_id["m-208"], as_of, by_id, historical=True))

    def test_bm25_keeps_scope_and_lifecycle_governance_guards(self):
        result = evaluate(load_cases(CASES_PATH), scorer="bm25")
        self.assertEqual(result["metrics"]["forbidden_current_candidate_hits"], 0)
        self.assertEqual(result["metrics"]["cross_scope_expected_evidence_violations"], 0)
        self.assertEqual(result["metrics"]["raw_evidence_recall_at_k"], 1.0)
        self.assertEqual(result["metrics"]["current_valid_evidence_recall_at_k"], 0.8461538461538461)

    def test_historical_retrieval_keeps_prior_user_turn_as_topic_context(self):
        case = next(case for case in load_cases(CASES_PATH) if case["case_id"] == "gov-002")
        result = evaluate([case], scorer="hybrid")
        self.assertEqual(result["cases"][0]["historical_as_of_top_k"], ["m-201"])
        self.assertEqual(result["metrics"]["historical_as_of_evidence_recall_at_k"], 1.0)

    def test_historical_recall_metric_uses_temporal_evidence_denominator(self):
        result = evaluate(load_cases(CASES_PATH), scorer="bm25")
        self.assertEqual(result["metrics"]["historical_as_of_evidence_recall_at_k"], 1.0)


if __name__ == "__main__":
    unittest.main()
