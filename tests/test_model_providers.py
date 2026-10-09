import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lifeos.llm.client import LLMClient
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

