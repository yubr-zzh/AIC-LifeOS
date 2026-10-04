import asyncio
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from lifeos.agent.runtime import LifeOSAgent
from lifeos.llm.client import LLMClient
from lifeos.storage.sqlite import StructuredStore


def create_agent():
    return LifeOSAgent(LLMClient())


class LifeOSRequestHandler(BaseHTTPRequestHandler):
    agent = create_agent()
    structured_store = StructuredStore()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/events":
            self._send_json({"events": [vars(event) for event in self.agent.event_bus.all_events()]})
            return
        if parsed.path == "/memory":
            self._send_json(self.agent.memory._read())
            return
        if parsed.path == "/memory/profile":
            self._send_json(self.agent.memory.profile_view())
            return
        if parsed.path == "/skills":
            self._send_json(self.agent.skills._read())
            return
        if parsed.path == "/permissions":
            self._send_json({"requests": []})
            return
        if parsed.path.startswith("/traces/"):
            trace = self.agent.trace.get(unquote(parsed.path.rsplit("/", 1)[-1]))
            if trace is None:
                self.send_error(404, "trace not found")
            else:
                self._send_json({"trace_id": unquote(parsed.path.rsplit("/", 1)[-1]), **trace})
            return
        if parsed.path == "/entries":
            self._handle_list_entries(parse_qs(parsed.query))
            return
        if parsed.path.startswith("/entries/"):
            self._handle_get_entry(unquote(parsed.path.rsplit("/", 1)[-1]))
            return
        if parsed.path == "/memory/markdown":
            self._handle_export_markdown()
            return
        self.send_error(404, "not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        parts = parsed.path.strip("/").split("/")
        if len(parts) == 4 and parts[:2] == ["memory", "candidates"] and parts[3] in {"commit", "reject"}:
            self._handle_memory_candidate(unquote(parts[2]), parts[3])
            return
        if parsed.path == "/memory/providers/tencentdb/sync-pending":
            self._handle_tencentdb_sync_pending()
            return
        if len(parts) == 3 and parts[0] == "memory" and parts[2] in {"correct", "retract"}:
            self._handle_memory_mutation(unquote(parts[1]), parts[2])
            return
        if len(parts) == 3 and parts[0] == "entries" and parts[2] == "memory-candidates":
            self._handle_structured_entry_memory_candidate(unquote(parts[1]))
            return
        if len(parts) == 4 and parts[:2] == ["skills", "pending"] and parts[3] in {"approve", "reject"}:
            self._handle_skill_candidate(unquote(parts[2]), parts[3])
            return
        if self.path == "/chat":
            self._handle_chat()
            return
        if self.path == "/background/run-once":
            self._handle_background_once()
            return
        if self.path == "/entries":
            self._handle_create_entry()
            return
        if self.path == "/feedback":
            self._handle_feedback()
            return
        if self.path == "/memory/markdown":
            self._handle_import_markdown()
            return
        self.send_error(404, "not found")

    def do_PUT(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/entries/"):
            self._handle_update_entry(unquote(parsed.path.rsplit("/", 1)[-1]))
            return
        self.send_error(404, "not found")

    def _handle_chat(self):
        body = self._read_json()
        try:
            result = asyncio.run(
                self.agent.run(
                    body.get("message", ""),
                    memory_scope=body.get("memory_scope"),
                )
            )
        except ValueError as exc:
            self._send_json(
                {"error": {"code": "invalid_request", "message": str(exc)}},
                status=400,
            )
            return
        self._send_json(result)

    def _handle_background_once(self):
        result = asyncio.run(self.agent.run_background_once())
        self._send_json({"processed": result})

    def _handle_list_entries(self, query):
        kind = query.get("kind", [None])[0]
        entry_date = query.get("date", [None])[0]
        try:
            entries = self.structured_store.list_entries(kind=kind, entry_date=entry_date)
        except (TypeError, ValueError) as exc:
            self._send_json({"error": {"code": "invalid_request", "message": str(exc)}}, status=400)
            return
        self._send_json({"entries": entries})

    def _handle_get_entry(self, entry_id):
        entry = self.structured_store.get(entry_id)
        if entry is None:
            self.send_error(404, "entry not found")
            return
        self._send_json({"entry": entry})

    def _handle_create_entry(self):
        self._save_entry()

    def _handle_update_entry(self, entry_id):
        if self.structured_store.get(entry_id) is None:
            self.send_error(404, "entry not found")
            return
        self._save_entry(entry_id)

    def _save_entry(self, entry_id=None):
        try:
            entry = self.structured_store.upsert(self._read_json(), entry_id=entry_id)
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            self._send_json({"error": {"code": "invalid_request", "message": str(exc)}}, status=400)
            return
        self._send_json({"entry": entry}, status=201 if entry_id is None else 200)

    def _handle_feedback(self):
        body = self._read_json()
        rating = body.get("rating")
        trace_id = body.get("trace_id")
        note = body.get("note", "")
        valid = {"plan_too_heavy", "just_right", "helpful", "not_helpful"}
        if rating not in valid:
            self._send_json(
                {"error": {"code": "invalid_request", "message": f"rating must be one of {sorted(valid)}"}},
                status=400,
            )
            return
        asyncio.run(self.agent.submit_feedback(rating=rating, trace_id=trace_id, note=note))
        self._send_json({"ok": True})

    def _handle_export_markdown(self):
        md = self.agent.memory.export_markdown()
        self._send_json({"markdown": md, "source": "backend"})

    def _handle_import_markdown(self):
        body = self._read_json()
        text = body.get("markdown", "")
        if not isinstance(text, str) or not text.strip():
            self._send_json(
                {"error": {"code": "invalid_request", "message": "markdown body is required"}},
                status=400,
            )
            return
        try:
            store = self.agent.memory.import_markdown(text)
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json({"error": {"code": "invalid_request", "message": str(exc)}}, status=400)
            return
        counts = {
            key: len(value)
            for key, value in store.items()
            if isinstance(value, list)
        }
        self._send_json({"ok": True, "categories": counts})

    def _handle_memory_candidate(self, candidate_id, action):
        try:
            if action == "commit":
                item = asyncio.run(self.agent.memory.commit_candidate(candidate_id))
                item = self._sync_approved_memory(item)
            else:
                item = asyncio.run(self.agent.memory.reject_candidate(candidate_id))
        except KeyError as exc:
            self._send_json({"error": {"code": "not_found", "message": str(exc)}}, status=404)
            return
        except ValueError as exc:
            self._send_json({"error": {"code": "conflict", "message": str(exc)}}, status=409)
            return
        self._send_json({"status": "committed" if action == "commit" else "rejected", "item": item})

    def _sync_approved_memory(self, item):
        """Sync only after the existing LifeOS approval/commit gate."""
        provider = getattr(self.agent, "external_memory", None)
        if provider is None:
            return item
        try:
            provider.write_approved_memory(item)
            return self.agent.memory.set_provider_sync(
                item["id"], "synced", remote_id=f"lifeos-{item['id']}"
            )
        except Exception as exc:
            # The local approval is durable; deterministic remote IDs make a
            # repeated commit request a safe retry without resending raw source.
            return self.agent.memory.set_provider_sync(
                item["id"], "pending", error=type(exc).__name__
            )

    def _handle_tencentdb_sync_pending(self):
        provider = getattr(self.agent, "external_memory", None)
        if provider is None:
            self._send_json({"error": {"code": "provider_disabled"}}, status=409)
            return
        outcomes = []
        for item in self.agent.memory.memory_records():
            sync = item.get("provider_sync") or {}
            if sync.get("status") != "pending":
                continue
            try:
                if item.get("status", "active") == "active":
                    provider.write_approved_memory(item)
                    updated = self.agent.memory.set_provider_sync(
                        item["id"], "synced", remote_id=f"lifeos-{item['id']}"
                    )
                else:
                    provider.delete_approved_memory(item["id"])
                    updated = self.agent.memory.set_provider_sync(item["id"], "deleted")
                outcomes.append({"memory_id": item["id"], "status": updated["provider_sync"]["status"]})
            except Exception as exc:
                updated = self.agent.memory.set_provider_sync(
                    item["id"], "pending", error=type(exc).__name__
                )
                outcomes.append({"memory_id": item["id"], "status": "pending", "error": type(exc).__name__})
        self._send_json({"results": outcomes})

    def _handle_memory_mutation(self, memory_id, action):
        body = self._read_json()
        previous = None
        try:
            previous = self.agent.memory._find_memory(self.agent.memory._read(), memory_id)
        except KeyError:
            pass
        try:
            if action == "correct":
                item = asyncio.run(
                    self.agent.memory.correct_memory(
                        memory_id, body.get("content"), reason=body.get("reason")
                    )
                )
            else:
                item = asyncio.run(
                    self.agent.memory.retract_memory(memory_id, reason=body.get("reason"))
                )
        except KeyError as exc:
            self._send_json({"error": {"code": "not_found", "message": str(exc)}}, status=404)
            return
        except ValueError as exc:
            self._send_json({"error": {"code": "conflict", "message": str(exc)}}, status=409)
            return
        provider = getattr(self.agent, "external_memory", None)
        previous_sync = (previous or {}).get("provider_sync", {}).get("status")
        if provider is not None and previous and previous_sync in {"synced", "pending"}:
            remote_deleted = False
            try:
                provider.delete_approved_memory(memory_id)
                self.agent.memory.set_provider_sync(memory_id, "deleted")
                remote_deleted = True
                if action == "correct":
                    provider.write_approved_memory(item)
                    item = self.agent.memory.set_provider_sync(
                        item["id"], "synced", remote_id=f"lifeos-{item['id']}"
                    )
                else:
                    item = self.agent.memory.set_provider_sync(memory_id, "deleted")
            except Exception as exc:
                # Local lifecycle state remains authoritative for the read
                # filter, so stale remote results are discarded on recall.
                target_id = item["id"] if action == "correct" else memory_id
                item = self.agent.memory.set_provider_sync(
                    target_id, "pending", error=type(exc).__name__
                )
                if action == "correct" and not remote_deleted:
                    self.agent.memory.set_provider_sync(
                        memory_id, "pending", error=type(exc).__name__
                    )
        self._send_json({"status": item.get("status"), "memory": item})

    def _handle_structured_entry_memory_candidate(self, entry_id):
        entry = self.structured_store.get(entry_id)
        if entry is None:
            self._send_json(
                {"error": {"code": "not_found", "message": "structured entry not found"}},
                status=404,
            )
            return
        if entry["kind"] not in {"daily_plan", "daily_review", "phase_plan", "phase_review"}:
            self._send_json(
                {"error": {"code": "invalid_request", "message": "entry kind is not enabled for memory capture"}},
                status=400,
            )
            return
        body = self._read_json()
        content = body.get("content")
        category = body.get("category")
        scope = body.get("scope")
        if not isinstance(content, dict) or not content:
            self._send_json(
                {"error": {"code": "invalid_request", "message": "non-empty distilled content is required"}},
                status=400,
            )
            return
        if not category or not isinstance(scope, dict):
            self._send_json(
                {"error": {"code": "invalid_request", "message": "category and scope are required"}},
                status=400,
            )
            return
        try:
            candidate = asyncio.run(
                self.agent.memory.propose_update(
                    source="structured_entry",
                    content=content,
                    source_ref={
                        "kind": "structured_entry",
                        "record_id": entry["id"],
                        "record_kind": entry["kind"],
                        "revision": entry["updated_at"],
                    },
                    scope=scope,
                    category=category,
                    confidence=body.get("confidence"),
                    confidence_method=body.get("confidence_method"),
                    occurred_at=entry["entry_date"],
                )
            )
        except ValueError as exc:
            self._send_json(
                {"error": {"code": "invalid_request", "message": str(exc)}},
                status=400,
            )
            return
        response_status = 201 if candidate.get("status") == "candidate" else 200
        self._send_json(
            {"status": candidate.get("status"), "candidate": candidate},
            status=response_status,
        )

    def _handle_skill_candidate(self, skill_id, action):
        try:
            if action == "approve":
                item = asyncio.run(self.agent.skills.approve_by_id(skill_id))
            else:
                item = asyncio.run(self.agent.skills.reject_by_id(skill_id))
        except KeyError as exc:
            self._send_json({"error": {"code": "not_found", "message": str(exc)}}, status=404)
            return
        self._send_json({"status": "approved" if action == "approve" else "rejected", "skill": item})

    def _read_json(self):
        length = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        return json.loads(raw)

    def _send_json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def run(host="127.0.0.1", port=8765):
    server = HTTPServer((host, port), LifeOSRequestHandler)
    print(f"LifeOS API listening on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
