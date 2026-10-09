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
from lifeos.memory.providers.tencentdb import TencentDBConfig, TencentDBError, TencentDBMemoryAdapter
from lifeos.memory.retriever import MemoryRetriever
from lifeos.security.permission import PermissionManager
from lifeos.skills.registry import SkillRegistry
from lifeos.storage.sqlite import StructuredStore
from http.server import BaseHTTPRequestHandler, HTTPServer


def run(coro):
    return asyncio.run(coro)


class CoreRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)

    def test_tencentdb_adapter_requires_complete_loopback_identity_config(self):
        with self.assertRaisesRegex(ValueError, "incomplete TencentDB configuration"):
            TencentDBConfig.from_env({"LIFEOS_TDAI_ENDPOINT": "http://127.0.0.1:8420"})
        self.assertIsNone(TencentDBConfig.from_env({}))
        complete = {
            "LIFEOS_TDAI_ENDPOINT": "http://127.0.0.1:8420",
            "LIFEOS_TDAI_SERVICE_ID": "test-instance",
            "LIFEOS_TDAI_TEAM_ID": "test-team",
            "LIFEOS_TDAI_AGENT_ID": "test-agent",
            "LIFEOS_TDAI_USER_ID": "test-user",
        }
        self.assertTrue(TencentDBConfig.from_env(complete).is_loopback)
        complete["LIFEOS_TDAI_ENDPOINT"] = "https://memory.example.com"
        with self.assertRaisesRegex(ValueError, "loopback Gateway"):
            TencentDBConfig.from_env(complete)

    def test_tencentdb_adapter_writes_approved_only_and_fail_closed_filters_scope(self):
        calls = []

        def fake_transport(path, payload):
            calls.append((path, payload))
            if path.endswith("/search"):
                return {
                    "items": [
                        {
                            "id": "global",
                            "content": '{"claim":"global"}',
                            "background": '{"lifeos_memory_id":"global-id","category":"user","scope":{"kind":"global"}}',
                        },
                        {
                            "id": "same-project",
                            "content": '{"claim":"project"}',
                            "background": '{"lifeos_memory_id":"project-id","category":"project","scope":{"kind":"project","project_id":"lifeos"}}',
                        },
                        {
                            "id": "other-project",
                            "content": '{"claim":"secret"}',
                            "background": '{"lifeos_memory_id":"other-id","category":"project","scope":{"kind":"project","project_id":"other"}}',
                        },
                        {"id": "untrusted", "content": '{"claim":"untrusted"}', "background": "{}"},
                    ]
                }
            return {"id": payload.get("id")}

        config = TencentDBConfig(
            endpoint="http://127.0.0.1:8420",
            service_id="test-instance",
            team_id="test-team",
            agent_id="test-agent",
            user_id="test-user",
        )
        adapter = TencentDBMemoryAdapter(config, transport=fake_transport)
        unapproved = {"id": "pending", "content": {"claim": "x"}, "status": "candidate"}
        with self.assertRaisesRegex(ValueError, "user-approved"):
            adapter.write_approved_memory(unapproved)
        self.assertEqual(calls, [])

        first_write = {
            "id": "new-memory",
            "status": "active",
            "content": {"claim": "approved but not remotely bound"},
        }
        with self.assertRaisesRegex(TencentDBError, "cannot create"):
            adapter.write_approved_memory(first_write)
        self.assertEqual(calls, [], "unsupported first writes must fail before sending content")

        approved = {
            "id": "memory-1",
            "status": "active",
            "provider_sync": {"status": "synced", "remote_id": "lifeos-memory-1"},
            "category": "project",
            "content": {"claim": "approved fact"},
            "source": "structured_entry",
            "source_ref": {"kind": "structured_entry", "record_id": "review-1"},
            "scope": {"kind": "project", "project_id": "lifeos"},
        }
        adapter.write_approved_memory(approved)
        self.assertEqual(calls[-1][0], "/v3/atomic/update")
        self.assertEqual(calls[-1][1]["team_id"], "test-team")
        self.assertEqual(calls[-1][1]["session_id"], "lifeos-approved-memory")
        self.assertIn("review-1", calls[-1][1]["background"])

        grouped = adapter.retrieve(
            "approved fact",
            scope={"kind": "project", "project_id": "lifeos"},
            allowed_memory_ids={"global-id", "project-id", "other-id", "untrusted"},
        )
        self.assertEqual(
            {entry["id"] for entry in grouped["project"]},
            {"project-id"},
        )
        self.assertEqual({entry["id"] for entry in grouped["user"]}, {"global-id"})

    def test_tencentdb_adapter_http_wire_matches_v3_contract(self):
        received = []
        hit = {
            "id": "lifeos-memory-1",
            "content": '{"claim":"wire test"}',
            "background": '{"lifeos_memory_id":"memory-1","category":"user","scope":{"kind":"global"}}',
        }

        class GatewayStubHandler(BaseHTTPRequestHandler):
            def log_message(self, _format, *_args):
                pass

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("content-length", "0")))
                headers = {name.lower(): value for name, value in self.headers.items()}
                received.append((self.path, headers, json.loads(raw)))
                data = {"items": [hit]} if self.path.endswith("/search") else {"id": "lifeos-memory-1"}
                payload = json.dumps({"code": 0, "message": "ok", "data": data}).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        server = HTTPServer(("127.0.0.1", 0), GatewayStubHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        config = TencentDBConfig(
            endpoint=f"http://127.0.0.1:{server.server_address[1]}",
            service_id="test-instance",
            team_id="test-team",
            agent_id="test-agent",
            user_id="test-user",
            api_key="test-key",
        )
        adapter = TencentDBMemoryAdapter(config)
        memory = {
            "id": "memory-1",
            "source": "direct",
            "category": "user",
            "status": "active",
            "provider_sync": {"status": "synced", "remote_id": "lifeos-memory-1"},
            "content": {"claim": "wire test"},
            "scope": {"kind": "global"},
        }
        adapter.write_approved_memory(memory)
        recalled = adapter.search_memories("wire test")
        adapter.delete_approved_memory("memory-1")

        self.assertEqual([item[0] for item in received], [
            "/v3/atomic/update", "/v3/atomic/search", "/v3/atomic/delete"
        ])
        self.assertTrue(all(item[1]["x-tdai-service-id"] == "test-instance" for item in received))
        self.assertTrue(all(item[1]["authorization"] == "Bearer test-key" for item in received))
        self.assertEqual(received[0][2]["team_id"], "test-team")
        self.assertEqual(received[0][2]["session_id"], "lifeos-approved-memory")
        self.assertEqual(received[2][2]["ids"], ["lifeos-memory-1"])
        self.assertEqual(recalled, [hit])

    def test_tencentdb_atomic_update_404_is_not_misreported_as_create(self):
        class MissingAtomicHandler(BaseHTTPRequestHandler):
            def log_message(self, _format, *_args):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers.get("content-length", "0")))
                payload = json.dumps({
                    "code": 404,
                    "message": "Atomic note not found",
                    "request_id": "synthetic-request",
                }).encode()
                self.send_response(404)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        server = HTTPServer(("127.0.0.1", 0), MissingAtomicHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        adapter = TencentDBMemoryAdapter(TencentDBConfig(
            endpoint=f"http://127.0.0.1:{server.server_address[1]}",
            service_id="test-instance",
            team_id="test-team",
            agent_id="test-agent",
            user_id="test-user",
        ))
        approved = {
            "id": "new-memory",
            "source": "direct",
            "category": "user",
            "status": "active",
            "provider_sync": {"status": "synced", "remote_id": "lifeos-new-memory"},
            "content": {"claim": "synthetic only"},
            "scope": {"kind": "global"},
        }
        with self.assertRaises(TencentDBError):
            adapter.write_approved_memory(approved)

    def test_chat_runtime_uses_external_l1_with_local_active_id_allowlist(self):
        agent = LifeOSAgent(LLMClient(), storage_dir=self.path)
        candidate = run(
            agent.memory.propose_update(
                "structured_entry",
                {"claim": "not locally relevant"},
                category="user",
                scope={"kind": "global"},
            )
        )
        run(agent.memory.commit_candidate(candidate["id"]))
        observations = {}

        class FakeExternalMemory:
            def retrieve(self, query, scope=None, allowed_memory_ids=None):
                observations.update(query=query, scope=scope, allowed=allowed_memory_ids)
                return {
                    "user": [{"id": candidate["id"], "content": {"claim": "remote hit"}}],
                    "project": [{"id": "stale-id", "content": {"claim": "stale"}}],
                }

        class CaptureExecutor:
            async def execute_chat_turn(self, user_input, memory, trace_id=None,
                                        context=None, plan=None):
                observations["memory"] = memory
                return {"response": "ok", "tool_calls": [], "tool_results": []}

        agent.external_memory = FakeExternalMemory()
        agent.chat.external_memory = agent.external_memory
        agent.chat.executor = CaptureExecutor()
        run(agent.run("question", memory_scope={"kind": "global"}))

        self.assertEqual(observations["allowed"], {candidate["id"]})
        self.assertEqual(observations["scope"]["kind"], "global")
        self.assertIn(candidate["id"], {entry["id"] for entry in observations["memory"]["user"]})
        self.assertNotIn("stale-id", {entry["id"] for values in observations["memory"].values() for entry in values})

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
                    "id": "alice-global",
                    "scope": {"kind": "global", "user_id": "alice"},
                    "content": "study with alice preferences",
                },
                {
                    "id": "learning",
                    "scope": {"kind": "scenario", "scenario_type": "learning"},
                    "content": "study with examples",
                },
                {
                    "id": "writing",
                    "scope": {"kind": "scenario", "scenario_type": "writing"},
                    "content": "study by drafting examples",
                },
                {
                    "id": "project",
                    "scope": {"kind": "project", "project_id": "lifeos", "user_id": "alice"},
                    "content": "study with examples in this project",
                },
                {
                    "id": "other-project",
                    "scope": {"kind": "project", "project_id": "other", "user_id": "alice"},
                    "content": "study with examples in another project",
                },
                {
                    "id": "other-user-same-project",
                    "scope": {"kind": "project", "project_id": "lifeos", "user_id": "bob"},
                    "content": "study with examples for another user",
                },
                {"id": "unassigned", "scope": {"kind": "unassigned"}, "content": "study notes"},
                {"id": "legacy-unscoped", "content": "study from an unscoped legacy entry"},
                {
                    "id": "superseded",
                    "scope": {"kind": "global"},
                    "status": "superseded",
                    "content": "study from an old superseded memory",
                },
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
                    "user_id": "alice",
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
                    "user_id": "alice",
                },
            )
        )

        self.assertEqual({item["id"] for item in default_result["user"]}, {"global"})
        self.assertEqual(
            {item["id"] for item in learning_result["user"]},
            {"global", "alice-global", "learning"},
        )
        self.assertEqual(
            {item["id"] for item in project_result["user"]},
            {"global", "alice-global", "learning", "project"},
        )

    def test_memory_profile_view_is_rebuildable_scoped_and_provenance_backed(self):
        memory = MemoryManager(self.path)
        global_candidate = run(
            memory.propose_update(
                "direct",
                {"claim": "prefers concise answers"},
                source_ref={"kind": "manual", "record_id": "global-note"},
                confidence=0.9,
                confidence_method="user_confirmed",
            )
        )
        learning_candidates = [
            run(
                memory.propose_update(
                    "structured_entry",
                    {"claim": claim},
                    category="user",
                    scope={"kind": "scenario", "scenario_type": "learning", "user_id": "alice"},
                    source_ref={"kind": "structured_entry", "record_id": source_id},
                    occurred_at=occurred_at,
                )
            )
            for claim, source_id, occurred_at in (
                ("learns by building examples", "review-1", "2026-10-01"),
                ("likes small runnable exercises", "review-2", "2026-10-02"),
            )
        ]
        project_candidate = run(
            memory.propose_update(
                "structured_entry",
                {"claim": "LifeOS project uses a memory module"},
                category="project",
                scope={"kind": "project", "project_id": "lifeos", "user_id": "alice"},
                source_ref={"kind": "project_event", "record_id": "lifeos-event-1"},
            )
        )
        bob_candidate = run(
            memory.propose_update(
                "structured_entry",
                {"claim": "learning preference owned by another user"},
                category="user",
                scope={"kind": "scenario", "scenario_type": "learning", "user_id": "bob"},
                source_ref={"kind": "structured_entry", "record_id": "bob-review-1"},
            )
        )
        unassigned_candidate = run(
            memory.propose_update(
                "external",
                {"claim": "unassigned source is not a profile fact"},
                category="reference",
            )
        )

        for candidate in [
            global_candidate,
            *learning_candidates,
            project_candidate,
            bob_candidate,
            unassigned_candidate,
        ]:
            run(memory.commit_candidate(candidate["id"]))
        pending = run(memory.propose_update("direct", {"claim": "not committed yet"}))

        malformed_store = memory._read()
        malformed_store["reference"].append(
            {
                "id": "malformed-scope",
                "scope": {"kind": "unrecognized"},
                "status": "active",
                "content": {"claim": "must fail closed"},
            }
        )
        memory._write(malformed_store)

        before = memory._read()
        profile = memory.profile_view()
        repeated = memory.profile_view()

        self.assertEqual(profile["schema_version"], 1)
        self.assertEqual(profile["version"], repeated["version"])
        self.assertEqual(len(profile["version"]), 64)
        self.assertEqual(len(profile["core_profiles"]), 1)
        self.assertEqual(profile["core_profiles"][0]["memories"][0]["id"], global_candidate["id"])
        global_item = profile["core_profiles"][0]["memories"][0]
        self.assertEqual(global_item["source_ref"]["record_id"], "global-note")
        self.assertEqual(global_item["confidence"], 0.9)
        self.assertEqual(global_item["confidence_method"], "user_confirmed")
        self.assertEqual(len(profile["scenario_profiles"]), 2)
        alice_learning_profile = next(
            group for group in profile["scenario_profiles"] if group["scope"]["user_id"] == "alice"
        )
        self.assertEqual(alice_learning_profile["memory_count"], 2)
        self.assertEqual(
            [item["source_ref"]["record_id"] for item in alice_learning_profile["memories"]],
            ["review-2", "review-1"],
        )
        self.assertEqual(len(profile["project_profiles"]), 1)
        all_profile_ids = {
            item["id"]
            for group in [*profile["core_profiles"], *profile["scenario_profiles"], *profile["project_profiles"]]
            for item in group["memories"]
        }
        self.assertNotIn(unassigned_candidate["id"], all_profile_ids)
        self.assertNotIn(pending["id"], all_profile_ids)
        self.assertNotIn("malformed-scope", all_profile_ids)
        self.assertEqual(memory._read(), before)

        corrected = run(memory.correct_memory(global_candidate["id"], {"claim": "prefers concise, structured answers"}))
        corrected_profile = memory.profile_view()
        self.assertNotEqual(corrected_profile["version"], profile["version"])
        corrected_global_ids = {
            item["id"] for group in corrected_profile["core_profiles"] for item in group["memories"]
        }
        self.assertEqual(corrected_global_ids, {corrected["id"]})

        run(memory.retract_memory(learning_candidates[0]["id"], "user withdrew this memory"))
        retracted_profile = memory.profile_view()
        active_learning_ids = {
            item["id"] for group in retracted_profile["scenario_profiles"] for item in group["memories"]
        }
        self.assertEqual(active_learning_ids, {learning_candidates[1]["id"], bob_candidate["id"]})

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
        class FakeMemoryProvider:
            def __init__(self):
                self.writes = []
                self.deletes = []
                self.fail_next_write = False

            def write_approved_memory(self, item):
                if self.fail_next_write:
                    self.fail_next_write = False
                    raise RuntimeError("simulated provider outage")
                self.writes.append(item["id"])

            def delete_approved_memory(self, memory_id):
                self.deletes.append(memory_id)

        provider = FakeMemoryProvider()
        agent.external_memory = provider
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
        self.assertEqual(provider.writes, [])
        approved = fetch(f"/memory/candidates/{candidate['id']}/commit", "POST")
        self.assertEqual(approved["status"], "committed")
        self.assertEqual(approved["item"]["provider_sync"]["status"], "synced")
        self.assertEqual(provider.writes, [candidate["id"]])
        self.assertEqual(fetch("/memory")["user"][0]["id"], candidate["id"])
        profile = fetch("/memory/profile")
        self.assertEqual(profile["core_profiles"][0]["memories"][0]["id"], candidate["id"])
        corrected = fetch(
            f"/memory/{candidate['id']}/correct",
            "POST",
            {"content": {"preference": "concise"}, "reason": "user correction"},
        )["memory"]
        self.assertEqual(provider.deletes, [candidate["id"]])
        self.assertEqual(provider.writes, [candidate["id"], corrected["id"]])
        self.assertEqual(corrected["version_of"], candidate["id"])
        self.assertEqual(fetch("/memory")["user"][0]["status"], "superseded")
        retracted = fetch(
            f"/memory/{corrected['id']}/retract", "POST", {"reason": "user request"}
        )["memory"]
        self.assertEqual(retracted["status"], "retracted")
        self.assertEqual(provider.deletes, [candidate["id"], corrected["id"]])
        self.assertEqual(fetch("/memory/profile")["core_profiles"], [])
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
        pending = run(agent.memory.propose_update("direct", {"preference": "retryable"}))
        provider.fail_next_write = True
        failed_sync = fetch(f"/memory/candidates/{pending['id']}/commit", "POST")
        self.assertEqual(failed_sync["item"]["provider_sync"]["status"], "pending")
        retried_sync = fetch("/memory/providers/tencentdb/sync-pending", "POST")
        self.assertEqual(
            retried_sync["results"],
            [{"memory_id": pending["id"], "status": "synced"}],
        )
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
        class FakeMemoryProvider:
            def __init__(self):
                self.items = []

            def write_approved_memory(self, item):
                self.items.append(item)

            def delete_approved_memory(self, _memory_id):
                pass

        provider = FakeMemoryProvider()
        agent.external_memory = provider
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
        self.assertEqual(len(provider.items), 1)
        self.assertEqual(provider.items[0]["source_ref"]["record_id"], entry["id"])
        self.assertEqual(provider.items[0]["scope"]["scenario_type"], "learning")

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
