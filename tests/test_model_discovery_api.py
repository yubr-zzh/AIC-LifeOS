import json
import threading
import unittest
from http.server import HTTPServer
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from lifeos.api.server import LifeOSRequestHandler


class ModelDiscoveryApiTests(unittest.TestCase):
    def test_discover_route_requires_csrf_and_returns_only_model_ids(self):
        class FakeStore:
            received = None

            def discover_models(self, payload):
                self.received = payload
                return ["model-a", "provider/model-b"]

        store = FakeStore()

        class Handler(LifeOSRequestHandler):
            agent = SimpleNamespace(model_store=store)

            def log_message(self, _format, *_args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        payload = {"base_url": "https://provider.example.test/v1", "api_key": "synthetic-secret"}
        request = Request(
            f"http://127.0.0.1:{server.server_address[1]}/models/discover",
            data=json.dumps(payload).encode(),
            headers={"X-LifeOS-CSRF": "synthetic-csrf"},
            method="POST",
        )
        with patch("lifeos.api.server.bridge_admin.yong_ma", return_value=True):
            with urlopen(request) as response:
                body = json.load(response)

        self.assertEqual(body, {"models": ["model-a", "provider/model-b"]})
        self.assertEqual(store.received, payload)
        self.assertNotIn("synthetic-secret", json.dumps(body))

    def test_discover_route_rejects_invalid_csrf(self):
        class Handler(LifeOSRequestHandler):
            def log_message(self, _format, *_args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        request = Request(
            f"http://127.0.0.1:{server.server_address[1]}/models/discover",
            data=b"{}",
            method="POST",
        )
        with patch("lifeos.api.server.bridge_admin.yong_ma", return_value=False):
            with self.assertRaises(HTTPError) as error:
                urlopen(request)
        self.assertEqual(getattr(error.exception, "code", None), 403)


if __name__ == "__main__":
    unittest.main()
