import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lifeos.llm.client import LLMClient, LLMRequestError
from lifeos.llm.profiles import ModelManager, ModelProfileStore


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class ModelProviderMvpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "models.json"

    def test_profiles_redact_keys_and_activate(self):
        store = ModelProfileStore(self.path)
        created = store.create({
            "name": "Test OpenAI",
            "provider": "openai",
            "protocol": "openai",
            "base_url": "https://api.example.test/v1",
            "model": "gpt-test",
            "api_key": "sk-1234567890abcdef",
        })
        public = next(item for item in store.catalog()["profiles"] if item["id"] == created["id"])
        self.assertNotIn("api_key", public)
        self.assertTrue(public["has_api_key"])
        store.activate(created["id"])
        self.assertEqual(store.catalog()["active_profile_id"], created["id"])

    def test_openai_client_maps_completion(self):
        client = LLMClient(
            provider="openai",
            model="gpt-test",
            protocol="openai",
            base_url="https://api.example.test/v1",
            api_key="synthetic-key",
        )
        payload = {"model": "gpt-test", "choices": [{"message": {"content": "ready"}}]}
        with patch("lifeos.llm.client.urlopen", return_value=FakeResponse(payload)):
            result = asyncio.run(client.complete([{"role": "user", "content": "hello"}]))
        self.assertEqual(result["content"], "ready")
        self.assertEqual(result["model"], "gpt-test")

    def test_openai_client_discovers_model_ids_without_completion_request(self):
        response = FakeResponse({"object": "list", "data": [{"id": "Agnes-2.5"}, {"id": "Agnes-2.5-fast"}]})
        client = LLMClient(
            provider="custom", protocol="openai", model="", base_url="https://api.example.test/v1",
            api_key="synthetic-key",
        )
        with patch("lifeos.llm.client.urlopen", return_value=response) as open_url:
            models = client.list_models()
        request = open_url.call_args.args[0]
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.full_url, "https://api.example.test/v1/models")
        self.assertEqual(request.get_header("Authorization"), "Bearer synthetic-key")
        self.assertEqual(models, ["Agnes-2.5", "Agnes-2.5-fast"])

    def test_anthropic_model_discovery_uses_anthropic_headers(self):
        response = FakeResponse({"data": [{"id": "claude-test"}]})
        client = LLMClient(
            provider="anthropic", protocol="anthropic", model="", base_url="https://api.example.test/v1",
            api_key="synthetic-key",
        )
        with patch("lifeos.llm.client.urlopen", return_value=response) as open_url:
            self.assertEqual(client.list_models(), ["claude-test"])
        request = open_url.call_args.args[0]
        self.assertEqual(request.get_header("X-api-key"), "synthetic-key")
        self.assertEqual(request.get_header("Anthropic-version"), "2023-06-01")

    def test_model_discovery_rejects_invalid_url_before_network_access(self):
        client = LLMClient(protocol="openai", base_url="https://example.test:not-a-port/v1")
        with patch("lifeos.llm.client.urlopen") as open_url:
            with self.assertRaisesRegex(LLMRequestError, "base URL is invalid"):
                client.list_models()
        open_url.assert_not_called()

    def test_profile_store_discovers_models_without_persisting_new_profile(self):
        store = ModelProfileStore(self.path)
        before = self.path.read_text(encoding="utf-8")
        with patch("lifeos.llm.profiles.LLMClient.list_models", return_value=["model-a", "model-b"]):
            models = store.discover_models({
                "protocol": "openai", "provider": "custom", "base_url": "https://api.example.test/v1",
                "api_key": "synthetic-key",
            })
        self.assertEqual(models, ["model-a", "model-b"])
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)

    def test_profile_store_reuses_saved_key_for_model_discovery_when_editing(self):
        store = ModelProfileStore(self.path)
        profile = store.create({
            "name": "Test OpenAI", "provider": "custom", "protocol": "openai",
            "base_url": "https://api.example.test/v1", "model": "model-a", "api_key": "synthetic-key",
        })
        observed = {}

        def capture_key(client):
            observed["api_key"] = client.api_key
            return ["model-a", "model-b"]

        with patch("lifeos.llm.profiles.LLMClient.list_models", autospec=True, side_effect=capture_key):
            result = store.discover_models({"profile_id": profile["id"], "base_url": profile["base_url"], "protocol": "openai"})
        self.assertEqual(result, ["model-a", "model-b"])
        self.assertEqual(observed["api_key"], "synthetic-key")

    def test_manager_routes_to_active_profile(self):
        store = ModelProfileStore(self.path)
        store.create({
            "name": "Test OpenAI",
            "provider": "openai",
            "protocol": "openai",
            "base_url": "https://api.example.test/v1",
            "model": "gpt-test",
            "api_key": "synthetic-key",
        })
        active = store.catalog()["active_profile_id"]
        payload = {"model": "gpt-test", "choices": [{"message": {"content": "routed"}}]}
        manager = ModelManager(store)
        with patch("lifeos.llm.client.urlopen", return_value=FakeResponse(payload)):
            result = asyncio.run(manager.complete([{"role": "user", "content": "hello"}]))
        self.assertEqual(result["content"], "routed")
        self.assertEqual(result["model"], "gpt-test")
        self.assertEqual(result["provider"], "openai")
        self.assertEqual(store.catalog()["active_profile_id"], active)


if __name__ == "__main__":
    unittest.main()
