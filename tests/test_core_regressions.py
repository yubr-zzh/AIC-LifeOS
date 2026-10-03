import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from lifeos.agent.runtime import LifeOSAgent
from lifeos.agent.executor.executor import Executor
from lifeos.api.server import LifeOSRequestHandler
from lifeos.event.bus import ReliableEventBus
from lifeos.llm.client import LLMClient
from lifeos.memory.manager import MemoryManager
from lifeos.memory.retriever import MemoryRetriever
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
        committed = run(
            memory.propose_update(
                "direct",
                {"preference": "short"},
                source_ref={"kind": "manual", "record_id": "pref-1"},
            )
        )
        run(memory.commit_candidate(committed["id"]))
        pending = run(memory.propose_update("direct", {"preference": "long"}))
        before = memory._read()

        memory.import_markdown(memory.export_markdown())
        after = memory._read()

        self.assertEqual(after["user"][0]["id"], committed["id"])
        self.assertEqual(after["user"][0]["source_ref"]["record_id"], "pref-1")
        self.assertEqual(after["user"][0]["scope"]["kind"], "global")
        self.assertEqual(after["candidates"], before["candidates"])
        self.assertEqual(after["backups"], before["backups"])
        self.assertIn(committed["id"], after["vector_index"])
        self.assertIn(pending, after["candidates"])

        invalid = memory.export_markdown().replace('"short"', "not-valid-json")
        with self.assertRaises(json.JSONDecodeError):
            memory.import_markdown(invalid)
        self.assertEqual(memory._read(), before)
        edited = memory.export_markdown().replace('"short"', '"concise"')
        with self.assertRaisesRegex(ValueError, "explicit correction or retraction operations"):
            memory.import_markdown(edited)
        self.assertEqual(memory._read(), before)
        document = memory.export_markdown()
        start = document.index("## user (1)")
        end = document.index("## project (0)", start)
        removed = document[:start] + "## user (0)\n\n_（空）_\n\n" + document[end:]
        with self.assertRaisesRegex(ValueError, "explicit retract operation"):
            memory.import_markdown(removed)
        self.assertEqual(memory._read(), before)

    def test_explicit_memory_correction_supersedes_old_version_and_is_idempotent(self):
        memory = MemoryManager(self.path)
        candidate = run(
            memory.propose_update(
                "direct",
                {"preference": "short"},
                source_ref={"kind": "manual", "record_id": "pref-1"},
            )
        )
        original = run(memory.commit_candidate(candidate["id"]))

        corrected = run(memory.correct_memory(original["id"], {"preference": "concise"}, "user correction"))
        repeated = run(memory.correct_memory(original["id"], {"preference": "concise"}, "user correction"))
        store = memory._read()
        old = memory._find_memory(store, original["id"])

        self.assertEqual(corrected, repeated)
        self.assertEqual(old["status"], "superseded")
        self.assertEqual(old["superseded_by"], corrected["id"])
        self.assertEqual(corrected["version_of"], original["id"])
        self.assertEqual(corrected["evidence_source_ref"]["record_id"], "pref-1")
        self.assertNotIn(original["id"], store["vector_index"])
        recalled = run(memory.retrieve("concise"))
        self.assertEqual([item["id"] for item in recalled["user"]], [corrected["id"]])
        self.assertEqual(run(memory.retrieve("short"))["user"], [])
        with self.assertRaisesRegex(ValueError, "cannot be corrected from status: superseded"):
            run(memory.correct_memory(original["id"], {"preference": "brief"}))
        with self.assertRaisesRegex(ValueError, "cannot be retracted from status: superseded"):
            run(memory.retract_memory(original["id"]))
        self.assertEqual(memory._find_memory(memory._read(), original["id"])["superseded_by"], corrected["id"])

    def test_explicit_memory_retraction_is_idempotent_and_not_recallable(self):
        memory = MemoryManager(self.path)
        candidate = run(memory.propose_update("direct", {"preference": "quiet"}))
        accepted = run(memory.commit_candidate(candidate["id"]))

        retracted = run(memory.retract_memory(accepted["id"], "user asked to forget"))
        repeated = run(memory.retract_memory(accepted["id"], "user asked to forget"))
        store = memory._read()

        self.assertEqual(retracted, repeated)
        self.assertEqual(retracted["status"], "retracted")
        self.assertIn(accepted["id"], {item["id"] for item in store["user"]})
        self.assertNotIn(accepted["id"], store["vector_index"])
        self.assertEqual(run(memory.retrieve("quiet"))["user"], [])
        with self.assertRaisesRegex(ValueError, "cannot be corrected from status: retracted"):
            run(memory.correct_memory(accepted["id"], {"preference": "calm"}))

    def test_committing_same_candidate_twice_is_idempotent(self):
        memory = MemoryManager(self.path)
        candidate = run(memory.propose_update("direct", {"preference": "short"}))
        first = run(memory.commit_candidate(candidate["id"]))
        second = run(memory.commit_candidate(candidate["id"]))
        self.assertEqual(first, second)
        self.assertEqual(len(memory._read()["user"]), 1)

    def test_rejected_candidate_cannot_be_committed_and_rejection_is_idempotent(self):
        memory = MemoryManager(self.path)
        candidate = run(memory.propose_update("direct", {"preference": "short"}))

        first_rejection = run(memory.reject_candidate(candidate["id"]))
        second_rejection = run(memory.reject_candidate(candidate["id"]))
        self.assertEqual(first_rejection["status"], "rejected")
        self.assertEqual(second_rejection["status"], "rejected")
        with self.assertRaisesRegex(ValueError, "cannot be committed from status: rejected"):
            run(memory.commit_candidate(candidate["id"]))
        self.assertEqual(memory._read()["user"], [])

    def test_committed_candidate_cannot_be_rejected(self):
        memory = MemoryManager(self.path)
        candidate = run(memory.propose_update("direct", {"preference": "short"}))
        run(memory.commit_candidate(candidate["id"]))

        with self.assertRaisesRegex(ValueError, "cannot be rejected from status: committed"):
            run(memory.reject_candidate(candidate["id"]))
        self.assertEqual(len(memory._read()["user"]), 1)

    def test_memory_candidate_and_committed_entry_preserve_source_and_scope(self):
        memory = MemoryManager(self.path)
        source_ref = {
            "kind": "structured_entry",
            "record_id": "daily-review-1",
            "record_kind": "daily_review",
        }
        scope = {
            "kind": "scenario",
            "scenario_type": "learning",
            "project_id": None,
            "user_id": "local-user",
        }

        candidate = run(
            memory.propose_update(
                "structured_entry",
                {"claim": "prefer small runnable examples"},
                source_ref=source_ref,
                scope=scope,
                category="user",
                confidence=0.8,
                confidence_method="user_confirmed",
                occurred_at="2026-10-01T00:00:00+08:00",
            )
        )
        committed = run(memory.commit_candidate(candidate["id"]))

        self.assertEqual(candidate["source_ref"], source_ref)
        self.assertEqual(candidate["scope"], scope)
        self.assertEqual(candidate["confidence"], 0.8)
        self.assertEqual(committed["source_ref"], source_ref)
        self.assertEqual(committed["scope"], scope)
        self.assertEqual(committed["confidence_method"], "user_confirmed")
        self.assertEqual(committed["occurred_at"], "2026-10-01T00:00:00+08:00")
        self.assertEqual(run(memory.retrieve("small runnable examples"))["user"], [])
        learning_hits = run(
            memory.retrieve(
                "small runnable examples",
                scope={"kind": "scenario", "scenario_type": "learning", "user_id": "local-user"},
            )
        )["user"]
        self.assertEqual([entry["id"] for entry in learning_hits], [candidate["id"]])

    def test_unknown_memory_source_is_rejected_instead_of_becoming_project_memory(self):
        memory = MemoryManager(self.path)

        with self.assertRaisesRegex(ValueError, "unknown memory source"):
            run(memory.propose_update("new_unregistered_source", {"claim": "x"}))
        with self.assertRaisesRegex(ValueError, "unknown memory source"):
            run(memory.propose_update("new_unregistered_source", {"claim": "x"}, category="user"))

        self.assertEqual(memory._read()["candidates"], [])

    def test_project_scoped_memory_requires_a_project_id(self):
        memory = MemoryManager(self.path)

        with self.assertRaisesRegex(ValueError, "project scope requires project_id"):
            run(
                memory.propose_update(
                    "direct",
                    {"claim": "project fact"},
                    scope={"kind": "project", "scenario_type": "project", "project_id": None},
                )
            )

        self.assertEqual(memory._read()["candidates"], [])

    def test_memory_confidence_requires_a_method_and_stays_in_unit_interval(self):
        memory = MemoryManager(self.path)

        with self.assertRaisesRegex(ValueError, "confidence requires confidence_method"):
            run(memory.propose_update("direct", {"claim": "x"}, confidence=0.7))
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            run(
                memory.propose_update(
                    "direct",
                    {"claim": "x"},
                    confidence=1.2,
                    confidence_method="model_estimate",
                )
            )

        self.assertEqual(memory._read()["candidates"], [])

    def test_memory_retrieval_defaults_to_global_and_respects_scenario_scope(self):
        store = {
            "user": [
                {"id": "global", "scope": {"kind": "global"}, "content": "study preference"},
                {
                    "id": "learning",
                    "scope": {"kind": "scenario", "scenario_type": "learning"},
                    "content": "study with examples",
                },
                {
                    "id": "project",
                    "scope": {"kind": "project", "project_id": "lifeos"},
                    "content": "study with examples in this project",
                },
                {
                    "id": "other-project",
                    "scope": {"kind": "project", "project_id": "other"},
                    "content": "study with examples in another project",
                },
                {"id": "unassigned", "scope": {"kind": "unassigned"}, "content": "study notes"},
            ]
        }
        retriever = MemoryRetriever(store)

        default_result = run(retriever.retrieve("study"))
        learning_result = run(
            retriever.retrieve(
                "study",
                scope={
                    "kind": "scenario",
                    "scenario_type": "learning",
                    "project_id": None,
                },
            )
        )
        project_result = run(
            retriever.retrieve(
                "study",
                scope={
                    "kind": "project",
                    "scenario_type": "learning",
                    "project_id": "lifeos",
                },
            )
        )

        self.assertEqual([item["id"] for item in default_result["user"]], ["global"])
        self.assertEqual(
            {item["id"] for item in learning_result["user"]},
            {"global", "learning"},
        )
        self.assertEqual(
            {item["id"] for item in project_result["user"]},
            {"global", "learning", "project"},
        )

    def test_legacy_memory_store_is_upgraded_once_with_backup(self):
        legacy_store = {
            "user": [{"id": "old-user", "source": "direct", "content": {"preference": "short"}}],
            "project": [],
            "feedback": [],
            "reference": [],
            "candidates": [],
            "backups": [],
            "vector_index": {},
            "cache": {},
        }
        storage_path = self.path / "memory.json"
        storage_path.write_text(json.dumps(legacy_store), encoding="utf-8")

        memory = MemoryManager(self.path)
        migrated = memory._read()
        first_backup_count = len(migrated["backups"])
        MemoryManager(self.path)
        reopened = memory._read()

        self.assertEqual(migrated["schema_version"], 3)
        self.assertEqual(migrated["user"][0]["scope"]["kind"], "global")
        self.assertEqual(migrated["user"][0]["source_ref"], None)
        self.assertEqual(migrated["user"][0]["content"], {"preference": "short"})
        self.assertEqual(migrated["user"][0]["status"], "active")
        self.assertEqual(first_backup_count, 1)
        self.assertEqual(reopened["schema_version"], 3)
        self.assertEqual(len(reopened["backups"]), first_backup_count)

    def test_schema_v2_memory_store_migrates_lifecycle_status_once(self):
        v2_store = {
            "schema_version": 2,
            "user": [{"id": "v2-user", "source": "direct", "content": {"preference": "quiet"}}],
            "project": [],
            "feedback": [],
            "reference": [],
            "candidates": [],
            "backups": [],
            "vector_index": {},
            "cache": {},
        }
        (self.path / "memory.json").write_text(json.dumps(v2_store), encoding="utf-8")

        memory = MemoryManager(self.path)
        first = memory._read()
        backup_count = len(first["backups"])
        MemoryManager(self.path)
        reopened = memory._read()

        self.assertEqual(first["schema_version"], 3)
        self.assertEqual(first["user"][0]["status"], "active")
        self.assertEqual(first["backups"][0]["store"]["schema_version"], 2)
        self.assertEqual(len(reopened["backups"]), backup_count)

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
        corrected = fetch(
            f"/memory/{candidate['id']}/correct",
            "POST",
            {"content": {"preference": "concise"}, "reason": "user correction"},
        )["memory"]
        self.assertEqual(corrected["version_of"], candidate["id"])
        self.assertEqual(fetch("/memory")["user"][0]["status"], "superseded")
        retracted = fetch(
            f"/memory/{corrected['id']}/retract", "POST", {"reason": "user request"}
        )["memory"]
        self.assertEqual(retracted["status"], "retracted")
        with self.assertRaises(HTTPError) as superseded_error:
            fetch(f"/memory/{candidate['id']}/retract", "POST")
        self.assertEqual(superseded_error.exception.code, 409)
        with self.assertRaises(HTTPError) as retracted_error:
            fetch(
                f"/memory/{corrected['id']}/correct",
                "POST",
                {"content": {"preference": "calm"}},
            )
        self.assertEqual(retracted_error.exception.code, 409)
        persisted = fetch("/memory")
        self.assertEqual(persisted["user"][0]["status"], "superseded")
        self.assertEqual(persisted["user"][1]["status"], "retracted")
        self.assertEqual(fetch("/skills/pending/skill-1/approve", "POST")["status"], "approved")
        self.assertEqual(fetch("/skills")["approved"][0]["id"], "skill-1")
        chat = fetch(
            "/chat",
            "POST",
            {
                "message": "hello",
                "memory_scope": {"kind": "global"},
            },
        )
        self.assertEqual(fetch("/events")["events"][0]["trace_id"], chat["trace_id"])
        self.assertEqual(fetch("/events")["events"][0]["payload"]["memory_scope"]["kind"], "global")
        self.assertEqual(fetch(f"/traces/{chat['trace_id']}")["trace_id"], chat["trace_id"])
        self.assertEqual(len(fetch("/background/run-once", "POST")["processed"]), 1)
        self.assertTrue(any(c["source"] == "reflection" for c in fetch("/memory")["candidates"]))
        self.assertEqual(fetch("/permissions"), {"requests": []})

    def test_structured_entry_can_create_idempotent_memory_candidate_with_source_link(self):
        agent = LifeOSAgent(LLMClient(), storage_dir=self.path)
        structured_store = StructuredStore(self.path / "lifeos.db")

        class Handler(LifeOSRequestHandler):
            def log_message(self, _format, *_args):
                pass

        Handler.agent = agent
        Handler.structured_store = structured_store
        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_address[1]}"

        def post(path, payload):
            request = Request(
                base + path,
                data=json.dumps(payload).encode(),
                method="POST",
            )
            with urlopen(request) as response:
                return json.load(response)

        entry = structured_store.upsert(
            {
                "kind": "daily_review",
                "entry_date": "2026-10-01",
                "title": "学习复盘",
                "content": "今天先尝试了一个小例子，理解起来更顺。",
            }
        )
        request_body = {
            "content": {"claim": "学习时先做小例子有助于理解"},
            "category": "user",
            "scope": {
                "kind": "scenario",
                "scenario_type": "learning",
                "project_id": None,
            },
        }

        first = post(f"/entries/{entry['id']}/memory-candidates", request_body)
        replay = post(f"/entries/{entry['id']}/memory-candidates", request_body)
        self.assertEqual(first["candidate"]["id"], replay["candidate"]["id"])
        self.assertEqual(first["candidate"]["source_ref"]["record_id"], entry["id"])
        self.assertEqual(first["candidate"]["source_ref"]["record_kind"], "daily_review")
        self.assertNotIn("今天先尝试", json.dumps(first["candidate"]["content"], ensure_ascii=False))

        committed = post(
            f"/memory/candidates/{first['candidate']['id']}/commit",
            {},
        )
        self.assertEqual(committed["item"]["source_ref"]["record_id"], entry["id"])
        replay_after_commit = post(
            f"/entries/{entry['id']}/memory-candidates",
            request_body,
        )
        self.assertEqual(replay_after_commit["status"], "committed")
        self.assertEqual(len(agent.memory._read()["candidates"]), 1)

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

    def test_chat_uses_explicit_memory_scope_and_records_it_with_conversation(self):
        agent = LifeOSAgent(LLMClient(), storage_dir=self.path)
        candidate = run(
            agent.memory.propose_update(
                source="structured_entry",
                content={"claim": "learning scoped fact"},
                category="user",
                scope={"kind": "scenario", "scenario_type": "learning"},
                source_ref={"kind": "structured_entry", "record_id": "review-1"},
            )
        )
        run(agent.memory.commit_candidate(candidate["id"]))

        scope = {"kind": "scenario", "scenario_type": "learning"}
        run(agent.run("learning scoped fact", memory_scope=scope))
        conversation = agent.event_bus.all_events()[-1]

        self.assertEqual(conversation.payload["memory_scope"]["scenario_type"], "learning")
        self.assertEqual(
            [entry["id"] for entry in conversation.payload["memory"]["user"]],
            [candidate["id"]],
        )

    def test_chat_api_rejects_invalid_memory_scope(self):
        agent = LifeOSAgent(LLMClient(), storage_dir=self.path)
        structured_store = StructuredStore(self.path / "lifeos.db")

        class Handler(LifeOSRequestHandler):
            def log_message(self, _format, *_args):
                pass

        Handler.agent = agent
        Handler.structured_store = structured_store
        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        request = Request(
            f"http://127.0.0.1:{server.server_address[1]}/chat",
            data=json.dumps(
                {
                    "message": "work on project",
                    "memory_scope": {"kind": "project", "project_id": None},
                }
            ).encode(),
            method="POST",
        )

        with self.assertRaises(HTTPError) as error:
            urlopen(request)
        self.assertEqual(error.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
