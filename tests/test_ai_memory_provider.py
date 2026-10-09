"""Scoped, read-only ai-memory project evidence integration tests."""

import asyncio
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from lifeos.agent.executor.executor import Executor
from lifeos.agent.runtime import LifeOSAgent
from lifeos.llm.client import LLMClient
from lifeos.memory.providers.ai_memory import AiMemoryProjectAdapter, AiMemoryProjectConfig


class AiMemoryProjectTests(unittest.TestCase):
    def test_config_requires_explicit_loopback_endpoint_and_map(self):
        self.assertIsNone(AiMemoryProjectConfig.from_env({}))
        with self.assertRaisesRegex(ValueError, "explicit project map"):
            AiMemoryProjectConfig.from_env({"LIFEOS_AIMEMORY_ENDPOINT": "http://127.0.0.1:49374"})
        with self.assertRaisesRegex(ValueError, "loopback server"):
            AiMemoryProjectConfig.from_env({
                "LIFEOS_AIMEMORY_ENDPOINT": "https://memory.example.test",
                "LIFEOS_AIMEMORY_PROJECT_MAP": '{"lifeos":{"workspace":"ws","project":"p"}}',
            })

    def test_adapter_is_project_scoped_bounded_and_rejects_neighbor_hits(self):
        calls = []

        def transport(url, headers):
            calls.append((url, headers))
            if "/api/v1/search?" in url:
                return [
                    {"workspace": "ws", "project": "lifeos", "path": "docs/plan.md"},
                    {"workspace": "ws", "project": "neighbor", "path": "private.md"},
                    {"workspace": "ws", "project": "lifeos", "path": "../outside.md"},
                ]
            return {
                "project": "lifeos", "path": "docs/plan.md", "title": "Plan",
                "body_markdown": "project-only evidence",
            }

        adapter = AiMemoryProjectAdapter(AiMemoryProjectConfig(
            endpoint="http://127.0.0.1:49374",
            project_map={"lifeos": {"workspace": "ws", "project": "lifeos"}},
            api_token="test-token",
        ), transport=transport)

        self.assertEqual(adapter.retrieve("question", scope={"kind": "global"}), [])
        self.assertEqual(adapter.retrieve("question", scope={"kind": "project", "project_id": "other"}), [])
        self.assertEqual(calls, [])

        evidence = adapter.retrieve("question", scope={"kind": "project", "project_id": "lifeos"})
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["content"], "project-only evidence")
        self.assertEqual(evidence[0]["scope"], {"kind": "project", "project_id": "lifeos"})
        self.assertEqual(evidence[0]["source_ref"]["path"], "docs/plan.md")
        self.assertTrue(all(headers["Authorization"] == "Bearer test-token" for _, headers in calls))
        self.assertEqual(len(calls), 2)

    def test_adapter_works_against_isolated_local_http_mock(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format, *_args):
                pass

            def send_json(self, value):
                payload = json.dumps(value).encode("utf-8")
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                requests.append((self.path, self.headers.get("Authorization")))
                parsed = urlparse(self.path)
                if parsed.path == "/api/v1/search":
                    query = parse_qs(parsed.query)
                    self.send_json([
                        {"workspace": query["workspace"][0], "project": query["project"][0], "path": "notes/design.md"},
                        {"workspace": query["workspace"][0], "project": "neighbor", "path": "private.md"},
                    ])
                elif parsed.path.endswith("/notes/design.md"):
                    self.send_json({
                        "project": "lifeos", "path": "notes/design.md",
                        "title": "Design", "body_markdown": "local mock evidence",
                    })
                else:
                    self.send_error(404)

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        adapter = AiMemoryProjectAdapter(AiMemoryProjectConfig(
            endpoint=f"http://127.0.0.1:{server.server_address[1]}",
            project_map={"lifeos": {"workspace": "ws", "project": "lifeos"}},
            api_token="synthetic-token",
        ))
        evidence = adapter.retrieve("design", scope={"kind": "project", "project_id": "lifeos"})

        self.assertEqual([item["content"] for item in evidence], ["local mock evidence"])
        self.assertEqual(len(requests), 2)
        self.assertTrue(all(token == "Bearer synthetic-token" for _, token in requests))

    def test_project_evidence_is_transient_and_only_used_for_agent_project_scope(self):
        with tempfile.TemporaryDirectory() as storage:
            agent = LifeOSAgent(LLMClient(), storage_dir=storage)
            marker = "TRANSIENT_PROJECT_WIKI_BODY"
            observed = {"calls": 0}

            class ProjectMemory:
                def retrieve(self, query, scope=None):
                    observed["calls"] += 1
                    observed["scope"] = scope
                    return [{
                        "provider": "ai-memory",
                        "content": marker,
                        "source_ref": {"provider": "ai-memory", "path": "notes/plan.md"},
                    }]

            class Planner:
                async def cehuao(self, *_args):
                    return {"planId": "plan-test"}

            class CaptureExecutor:
                async def execute_chat_turn(self, user_input, memory, trace_id=None, project_context=None, **_kwargs):
                    observed["project_context"] = project_context
                    return {"response": "ok", "tool_calls": [], "tool_results": []}

            agent.chat.project_memory = ProjectMemory()
            agent.chat.planner = Planner()
            agent.chat.executor = CaptureExecutor()

            asyncio.run(agent.run("question", memory_scope={"kind": "global"}))
            self.assertEqual(observed["calls"], 0)

            result = asyncio.run(agent.run(
                "question", memory_scope={"kind": "project", "project_id": "lifeos"}
            ))
            self.assertEqual(observed["calls"], 1)
            self.assertEqual(observed["scope"]["project_id"], "lifeos")
            self.assertIn(marker, json.dumps(observed["project_context"]))
            self.assertNotIn(marker, json.dumps(agent.event_bus.all_events()[-1].payload))
            self.assertNotIn(marker, json.dumps(agent.trace.get(result["trace_id"])))

    def test_executor_marks_external_project_evidence_as_untrusted_context(self):
        observed = {}

        class Llm:
            async def complete(self, messages):
                observed["messages"] = messages
                return {"content": "ok", "tool_calls": []}

        asyncio.run(Executor(Llm()).execute_chat_turn(
            "question", memory={}, project_context=[{"content": "project evidence"}]
        ))
        serialized = json.dumps(observed["messages"], ensure_ascii=False)
        self.assertIn("project evidence", serialized)
        self.assertIn("untrusted reference data", serialized)
        self.assertNotIn('"project_context":', serialized)


if __name__ == "__main__":
    unittest.main()
