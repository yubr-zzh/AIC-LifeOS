"""One local Agent result can become an approved, project-scoped memory."""

import asyncio
import json
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from lifeos.agent.runtime import LifeOSAgent
from lifeos.api.server import LifeOSRequestHandler
from lifeos.llm.client import LLMClient
from lifeos.storage.sqlite import StructuredStore


class AgentMemoryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.agent = LifeOSAgent(LLMClient(), storage_dir=root)

        class Handler(LifeOSRequestHandler):
            def log_message(self, _format, *_args):
                pass

        Handler.agent = self.agent
        Handler.structured_store = StructuredStore(root / "entries.db")
        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 2)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, path, body=None):
        url = f"http://127.0.0.1:{self.server.server_address[1]}{path}"
        request = Request(
            url,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers={"content-type": "application/json"},
            method="POST" if body is not None else "GET",
        )
        with urlopen(request) as response:
            return json.load(response)

    def test_result_review_and_scoped_recall(self):
        event = {
            "kind": "agent.result", "sessionId": "s-a", "eventId": "result-1",
            "detail": {"resultText": "fixed the cache invalidation bug"},
        }
        self.request("/api/agent-events", event)
        self.request("/api/agent-events", event)
        evidence = self.request("/agent/evidence?session_id=s-a")["items"]
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["id"], "result-1")

        path = "/agent/evidence/result-1/memory-candidates"
        body = {"claim": "The cache invalidation bug was fixed", "project_id": "project-a"}
        candidate = self.request(path, body)["candidate"]
        self.assertEqual(self.request(path, body)["candidate"]["id"], candidate["id"])
        self.assertEqual(candidate["source_ref"]["record_id"], "result-1")
        self.assertEqual(candidate["scope"]["project_id"], "project-a")
        self.assertEqual(self.agent.memory._read()["project"], [])

        self.request(f"/memory/candidates/{candidate['id']}/commit", {})
        allowed = asyncio.run(self.agent.memory.retrieve(
            "cache invalidation",
            scope={"kind": "project", "project_id": "project-a", "user_id": "local"},
        ))
        other = asyncio.run(self.agent.memory.retrieve(
            "cache invalidation",
            scope={"kind": "project", "project_id": "project-b", "user_id": "local"},
        ))
        self.assertEqual([item["id"] for item in allowed["project"]], [candidate["id"]])
        self.assertEqual(other["project"], [])
        self.assertIsNone(self.agent.agent_evidence.get("result-1", owner_id="other"))

        with self.assertRaises(HTTPError) as missing:
            self.request("/agent/evidence/not-found/memory-candidates", body)
        self.assertEqual(missing.exception.code, 404)

    def test_conversation_distillation_is_scoped_and_never_copies_transcript(self):
        raw_input = "private raw conversation text"
        trace_id = self.agent.trace.start(raw_input)
        body = {
            "content": {"claim": "The user prefers concrete examples."},
            "scope": {"kind": "scenario", "scenario_type": "learning"},
            "category": "user",
        }
        response = self.request(f"/traces/{trace_id}/memory-candidates", body)
        candidate = response["candidate"]

        self.assertEqual(candidate["source"], "direct")
        self.assertEqual(candidate["source_ref"]["record_id"], trace_id)
        self.assertEqual(candidate["scope"]["scenario_type"], "learning")
        self.assertEqual(candidate["content"], {"claim": "The user prefers concrete examples."})
        self.assertNotIn(raw_input, json.dumps(candidate))
        self.assertEqual(self.agent.memory._read()["user"], [])

        with self.assertRaises(HTTPError) as invalid_scope:
            self.request(f"/traces/{trace_id}/memory-candidates", {
                **body,
                "scope": {"kind": "project", "project_id": ""},
                "category": "project",
            })
        self.assertEqual(invalid_scope.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
