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
        result = asyncio.run(self.agent.run(body.get("message", "")))
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
            else:
                item = asyncio.run(self.agent.memory.reject_candidate(candidate_id))
        except KeyError as exc:
            self._send_json({"error": {"code": "not_found", "message": str(exc)}}, status=404)
            return
        except ValueError as exc:
            self._send_json({"error": {"code": "conflict", "message": str(exc)}}, status=409)
            return
        self._send_json({"status": "committed" if action == "commit" else "rejected", "item": item})

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
