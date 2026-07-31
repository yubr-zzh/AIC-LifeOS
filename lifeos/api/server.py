import asyncio
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from lifeos.agent.runtime import LifeOSAgent
from lifeos.llm.client import LLMClient


def create_agent():
    return LifeOSAgent(LLMClient())


class LifeOSRequestHandler(BaseHTTPRequestHandler):
    agent = create_agent()

    def do_POST(self):
        if self.path == "/chat":
            self._handle_chat()
            return
        if self.path == "/background/run-once":
            self._handle_background_once()
            return
        self.send_error(404, "not found")

    def _handle_chat(self):
        body = self._read_json()
        result = asyncio.run(self.agent.run(body.get("message", "")))
        self._send_json(result)

    def _handle_background_once(self):
        result = asyncio.run(self.agent.run_background_once())
        self._send_json({"processed": result})

    def _read_json(self):
        length = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        return json.loads(raw)

    def _send_json(self, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
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

