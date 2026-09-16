import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from lifeos.agent.runtime import LifeOSAgent
from lifeos.agent.executor.executor import Executor
from lifeos.api.server import LifeOSRequestHandler
from lifeos.event.bus import ReliableEventBus
from lifeos.llm.client import LLMClient
from lifeos.memory.manager import MemoryManager
from lifeos.security.permission import PermissionManager
from lifeos.skills.registry import SkillRegistry
from lifeos.storage.sqlite import StructuredStore
from http.server import HTTPServer


def run(coro):
    return asyncio.run(coro)


class CoreRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)

    def test_markdown_round_trip_preserves_runtime_state_and_ids(self):
        memory = MemoryManager(self.path)
        committed = run(memory.propose_update("direct", {"preference": "short"}))
        run(memory.commit_candidate(committed["id"]))
        pending = run(memory.propose_update("direct", {"preference": "long"}))
        before = memory._read()

        memory.import_markdown(memory.export_markdown())
        after = memory._read()

        self.assertEqual(after["user"][0]["id"], committed["id"])
        self.assertEqual(after["candidates"], before["candidates"])
        self.assertEqual(after["backups"], before["backups"])
        self.assertIn(committed["id"], after["vector_index"])
        self.assertIn(pending, after["candidates"])

        edited = memory.export_markdown().replace('"short"', '"concise"')
        memory.import_markdown(edited)
        changed = memory._read()
        self.assertEqual(changed["user"][0]["content"], {"preference": "concise"})
        self.assertEqual(changed["vector_index"][committed["id"]], {"preference": "concise"})
        self.assertEqual(len(changed["backups"]), len(before["backups"]) + 1)
        self.assertIn(pending, changed["candidates"])

        invalid = memory.export_markdown().replace('"concise"', "not-valid-json")
        with self.assertRaises(json.JSONDecodeError):
            memory.import_markdown(invalid)
        self.assertEqual(memory._read(), changed)

    def test_committing_same_candidate_twice_is_idempotent(self):
        memory = MemoryManager(self.path)
        candidate = run(memory.propose_update("direct", {"preference": "short"}))
        first = run(memory.commit_candidate(candidate["id"]))
        second = run(memory.commit_candidate(candidate["id"]))
        self.assertEqual(first, second)
        self.assertEqual(len(memory._read()["user"]), 1)

    def test_interrupted_event_is_available_after_restart(self):
        path = self.path / "events.json"
        bus = ReliableEventBus(path)
        event = run(bus.publish("conversation.completed", {}))
        run(bus.mark_processing(event.id))
        restarted = ReliableEventBus(path)
        available = run(restarted.poll())
        self.assertEqual([e.id for e in available], [event.id])

    def test_feedback_is_not_counted_twice_after_commit(self):
        agent = LifeOSAgent(LLMClient(), storage_dir=self.path)
        run(agent.submit_feedback("helpful", trace_id="t1"))
        run(agent.run_background_once())
        candidate = agent.memory._read()["candidates"][0]
        run(agent.memory.commit_candidate(candidate["id"]))
        run(agent.submit_feedback("not_helpful", trace_id="t2"))
        run(agent.run_background_once())
        analysis = agent.memory._read()["candidates"][-1]["content"]
        self.assertEqual(analysis["rating_counts"], {"helpful": 1, "not_helpful": 1})

    def test_retried_conversation_does_not_duplicate_reflection(self):
        agent = LifeOSAgent(LLMClient(), storage_dir=self.path)
        run(agent.run("hello"))
        event = run(agent.event_bus.poll())[0]
        original = agent.global_agent.skill_detector.detect

        async def fail_once(_conversation):
            agent.global_agent.skill_detector.detect = original
            raise RuntimeError("simulated interruption after reflection")

        agent.global_agent.skill_detector.detect = fail_once
        self.assertEqual(run(agent.run_background_once()), [])
        self.assertEqual(run(agent.run_background_once()), [event.id])
        reflections = [
            candidate for candidate in agent.memory._read()["candidates"]
            if candidate["source"] == "reflection"
        ]
        self.assertEqual(len(reflections), 1)

    def test_candidate_approval_endpoints_persist_to_backend(self):
        agent = LifeOSAgent(LLMClient(), storage_dir=self.path)
        candidate = run(agent.memory.propose_update("direct", {"preference": "short"}))
        skill = {"id": "skill-1", "name": "test_skill", "description": "test", "risk": "low"}
        run(agent.skills.add_pending(skill))

        class Handler(LifeOSRequestHandler):
            def log_message(self, _format, *_args):
                pass

        Handler.agent = agent
        Handler.structured_store = StructuredStore(self.path / "lifeos.db")
        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_address[1]}"

        def fetch(path, method="GET", payload=None):
            data = json.dumps(payload or {}).encode() if method == "POST" else None
            request = Request(base + path, data=data, method=method)
            with urlopen(request) as response:
                return json.load(response)

        self.assertEqual(fetch("/memory")["candidates"][0]["status"], "candidate")
        self.assertEqual(fetch(f"/memory/candidates/{candidate['id']}/commit", "POST")["status"], "committed")
        self.assertEqual(fetch("/memory")["user"][0]["id"], candidate["id"])
        self.assertEqual(fetch("/skills/pending/skill-1/approve", "POST")["status"], "approved")
        self.assertEqual(fetch("/skills")["approved"][0]["id"], "skill-1")
        chat = fetch("/chat", "POST", {"message": "hello"})
        self.assertEqual(fetch("/events")["events"][0]["trace_id"], chat["trace_id"])
        self.assertEqual(fetch(f"/traces/{chat['trace_id']}")["trace_id"], chat["trace_id"])
        self.assertEqual(len(fetch("/background/run-once", "POST")["processed"]), 1)
        self.assertTrue(any(c["source"] == "reflection" for c in fetch("/memory")["candidates"]))
        self.assertEqual(fetch("/permissions"), {"requests": []})

    def test_skill_usage_is_recorded_after_outcome(self):
        registry = SkillRegistry(self.path / "skills.json")
        run(registry.add_pending({
            "id": "skill-1", "name": "planning", "description": "plan work",
            "keywords": ["plan"], "risk": "low",
        }))
        run(registry.approve_by_id("skill-1"))

        class BlockedToolLLM:
            async def complete(self, _messages):
                return {"content": "done", "tool_calls": [{"name": "write_file"}]}

        executor = Executor(BlockedToolLLM(), registry, PermissionManager())
        run(executor.execute_chat_turn("plan", {}))
        usage = run(registry.find("planning"))["usage"]
        self.assertEqual((usage["uses"], usage["successes"], usage["failures"]), (1, 0, 1))

        class FailingLLM:
            async def complete(self, _messages):
                raise RuntimeError("model unavailable")

        executor = Executor(FailingLLM(), registry, PermissionManager())
        with self.assertRaises(RuntimeError):
            run(executor.execute_chat_turn("plan", {}))
        usage = run(registry.find("planning"))["usage"]
        self.assertEqual((usage["uses"], usage["successes"], usage["failures"]), (2, 0, 2))

    def test_chat_reports_blocked_tool_result(self):
        class ToolCallingLLM:
            async def complete(self, _messages):
                return {"content": "requires approval", "tool_calls": [{"name": "write_file"}]}

        agent = LifeOSAgent(ToolCallingLLM(), storage_dir=self.path)
        result = run(agent.run("save this"))
        self.assertEqual(result["tool_results"][0]["status"], "blocked")
        self.assertEqual(result["tool_results"][0]["review"]["decision"], "requires_confirmation")


if __name__ == "__main__":
    unittest.main()
