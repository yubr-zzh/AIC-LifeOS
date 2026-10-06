import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lifeos.agent.runtime import LifeOSAgent
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


def run(coro):
    return asyncio.run(coro)


class ModelProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)

    def test_openai_compatible_request_and_tool_call_mapping(self):
        client = LLMClient(
            provider="deepseek",
            model="deepseek-chat",
            protocol="openai",
            base_url="https://api.example.test/v1",
            api_key="secret-key",
        )
        response = {
            "model": "deepseek-chat",
            "choices": [
                {
                    "message": {
                        "content": "done",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "function": {"name": "write_file", "arguments": "{\"path\":\"a.txt\"}"},
                            }
                        ],
                    }
                }
            ],
            "usage": {"total_tokens": 12},
        }
        with patch("lifeos.llm.client.urlopen", return_value=FakeResponse(response)) as mocked:
            result = run(client.complete([{"role": "user", "content": "hello"}]))

        request = mocked.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.example.test/v1/chat/completions")
        self.assertEqual(request.headers["Authorization"], "Bearer secret-key")
        self.assertEqual(result["content"], "done")
        self.assertEqual(result["tool_calls"][0]["arguments"], {"path": "a.txt"})
        self.assertEqual(result["usage"]["total_tokens"], 12)

    def test_anthropic_system_and_tool_use_mapping(self):
        client = LLMClient(
            provider="anthropic",
            model="claude-test",
            protocol="anthropic",
            base_url="https://api.anthropic.com/v1",
            api_key="anthropic-key",
        )
        response = {
            "model": "claude-test",
            "content": [
                {"type": "text", "text": "hello"},
                {"type": "tool_use", "id": "tool-1", "name": "write_file", "input": {"path": "x"}},
            ],
        }
        with patch("lifeos.llm.client.urlopen", return_value=FakeResponse(response)) as mocked:
            result = run(
                client.complete(
                    [
                        {"role": "system", "content": "system prompt"},
                        {"role": "user", "content": "hello"},
                    ]
                )
            )

        request = mocked.call_args.args[0]
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(request.headers["X-api-key"], "anthropic-key")
        self.assertEqual(body["system"], "system prompt")
        self.assertEqual(result["content"], "hello")
        self.assertEqual(result["tool_calls"][0]["name"], "write_file")

    def test_profiles_redact_keys_and_route_selected_model(self):
        store = ModelProfileStore(self.path / "models.json")
        profile = store.create(
            {
                "name": "Test OpenAI",
                "provider": "openai",
                "protocol": "openai",
                "base_url": "https://api.example.test/v1",
                "model": "gpt-test",
                "api_key": "sk-1234567890abcdef",
            }
        )
        catalog = store.catalog()
        public_profile = next(item for item in catalog["profiles"] if item["id"] == profile["id"])

        self.assertNotIn("api_key", public_profile)
        self.assertTrue(public_profile["has_api_key"])
        self.assertEqual(public_profile["api_key_hint"], "sk-…cdef")
        if os.name == "nt":
            stored = (self.path / "models.json").read_text(encoding="utf-8")
            self.assertNotIn("sk-1234567890abcdef", stored)
            self.assertIn("dpapi:v1:", stored)
            reopened = ModelProfileStore(self.path / "models.json")
            self.assertEqual(reopened.get_profile(profile["id"])["api_key"], "sk-1234567890abcdef")
        cleared = store.update(profile["id"], {"clear_api_key": True})
        self.assertFalse(cleared["has_api_key"])
        store.update(profile["id"], {"api_key": "sk-1234567890abcdef"})

        planner_response = {
            "model": "gpt-test",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "needs_agent": True,
                                "confidence": 0.94,
                                "reason": "需要执行型 Agent",
                                "steps": [{"title": "执行部署", "detail": "运行命令", "time": "现在"}],
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ],
            "usage": {},
        }
        response = {
            "model": "gpt-test",
            "choices": [{"message": {"content": "routed"}}],
            "usage": {},
        }
        agent = LifeOSAgent(ModelManager(store), storage_dir=self.path, model_store=store)
        with patch(
            "lifeos.llm.client.urlopen",
            side_effect=[FakeResponse(planner_response), FakeResponse(response)],
        ) as mocked:
            result = run(agent.run("帮我处理一下这个事情", model_profile_id=profile["id"]))

        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(result["response"], "routed")
        self.assertEqual(result["decision"], "agent")
        self.assertEqual(result["provider"], "openai")
        self.assertEqual(result["model"], "gpt-test")

    @unittest.skipUnless(os.name == "nt", "DPAPI migration is Windows-specific")
    def test_legacy_plaintext_model_key_is_migrated_to_dpapi(self):
        path = self.path / "legacy-models.json"
        secret = "synthetic-legacy-secret"
        path.write_text(json.dumps({
            "active_profile_id": "legacy",
            "profiles": [{
                "id": "legacy",
                "provider": "openai",
                "protocol": "openai",
                "base_url": "https://api.example.test/v1",
                "model": "gpt-test",
                "api_key": secret,
            }],
        }), encoding="utf-8")

        store = ModelProfileStore(path)
        self.assertEqual(store.get_profile("legacy")["api_key"], secret)
        persisted = path.read_text(encoding="utf-8")
        self.assertNotIn(secret, persisted)
        self.assertIn("dpapi:v1:", persisted)


if __name__ == "__main__":
    unittest.main()
