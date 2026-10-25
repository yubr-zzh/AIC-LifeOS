import unittest

from lifeos.memory.graph_retriever import retrieve_graph_facts


class GraphRetrieverTests(unittest.TestCase):
    def setUp(self):
        self.sources = [
            {"id": "s1", "scope": {"kind": "global"}, "status": "active"},
            {"id": "s2", "scope": {"kind": "global"}, "status": "active"},
            {"id": "sx", "scope": {"kind": "project", "project_id": "other"}, "status": "active"},
            {"id": "sold", "scope": {"kind": "global"}, "status": "retracted"},
        ]
        self.facts = [
            {"id": "f1", "subject": "LifeOS", "predicate": "stores_in", "object": "TencentDB", "source_ids": ["s1"], "scope": {"kind": "global"}, "status": "active"},
            {"id": "f2", "subject": "TencentDB", "predicate": "stores", "object": "global cognition", "source_ids": ["s2"], "scope": {"kind": "global"}, "status": "active"},
            {"id": "fx", "subject": "LifeOS", "predicate": "uses", "object": "secret store", "source_ids": ["sx"], "scope": {"kind": "project", "project_id": "other"}, "status": "active"},
            {"id": "fold", "subject": "LifeOS", "predicate": "stores_in", "object": "LegacyDB", "source_ids": ["sold"], "scope": {"kind": "global"}, "status": "active"},
        ]

    def test_multihop_path_returns_source_backed_edges(self):
        result = retrieve_graph_facts(
            "Where does LifeOS store global cognition?", self.facts, self.sources,
            scope={"kind": "global"}, top_k=5, max_hops=2,
        )
        self.assertEqual({"f1", "f2"}, {fact["id"] for fact in result})
        self.assertTrue(all(fact["source_ids"] for fact in result))

    def test_scope_and_retracted_sources_are_filtered_before_path_search(self):
        result = retrieve_graph_facts(
            "Where does LifeOS store secret store?", self.facts, self.sources,
            scope={"kind": "global"}, top_k=5, max_hops=2,
        )
        self.assertEqual([], result)
        result = retrieve_graph_facts(
            "Where does LifeOS store LegacyDB?", self.facts, self.sources,
            scope={"kind": "global"}, top_k=5, max_hops=1,
        )
        self.assertEqual([], result)

    def test_graph_retrieval_fails_closed_without_two_query_anchors(self):
        result = retrieve_graph_facts(
            "What stores things?", self.facts, self.sources,
            scope={"kind": "global"},
        )
        self.assertEqual([], result)


if __name__ == "__main__":
    unittest.main()
