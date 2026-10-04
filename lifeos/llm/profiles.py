"""Persistent model profiles and per-request model routing for LifeOS."""

from __future__ import annotations

import contextvars
import copy
import re
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from lifeos.llm.client import LLMClient
from lifeos.storage.atomic import write_json


MODEL_PROVIDER_PRESETS = [
    {
        "id": "mock",
        "label": "LifeOS Mock",
        "protocol": "mock",
        "base_url": "",
        "models": ["lifeos-mock"],
        "api_key_required": False,
        "description": "本地演示模型，不需要网络或 API Key。",
    },
    {
        "id": "openai",
        "label": "OpenAI",
        "protocol": "openai",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-5", "gpt-5-mini", "gpt-4.1", "gpt-4o", "o3"],
        "api_key_required": True,
        "description": "OpenAI 官方 Chat Completions API。",
    },
    {
        "id": "anthropic",
        "label": "Anthropic Claude",
        "protocol": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "models": ["claude-sonnet-4-5", "claude-opus-4-1", "claude-3-5-haiku-latest"],
        "api_key_required": True,
        "description": "Anthropic Messages API，支持 Claude 系列。",
    },
    {
        "id": "gemini",
        "label": "Google Gemini",
        "protocol": "openai",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "models": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"],
        "api_key_required": True,
        "description": "通过 Gemini 的 OpenAI 兼容接口调用。",
    },
    {
        "id": "deepseek",
        "label": "DeepSeek",
        "protocol": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "api_key_required": True,
        "description": "DeepSeek 官方 OpenAI 兼容接口。",
    },
    {
        "id": "qwen",
        "label": "通义千问 Qwen",
        "protocol": "openai",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen3-max", "qwen-plus", "qwen3-coder-plus"],
        "api_key_required": True,
        "description": "阿里云百炼 DashScope OpenAI 兼容接口。",
    },
    {
        "id": "moonshot",
        "label": "月之暗面 Kimi",
        "protocol": "openai",
        "base_url": "https://api.moonshot.cn/v1",
        "models": ["kimi-k2-0905-preview", "moonshot-v1-128k"],
        "api_key_required": True,
        "description": "Moonshot / Kimi 官方 OpenAI 兼容接口。",
    },
    {
        "id": "zhipu",
        "label": "智谱 GLM",
        "protocol": "openai",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["glm-4.5", "glm-4-plus", "glm-4-flash"],
        "api_key_required": True,
        "description": "智谱 BigModel OpenAI 兼容接口。",
    },
    {
        "id": "minimax",
        "label": "MiniMax",
        "protocol": "openai",
        "base_url": "https://api.minimax.chat/v1",
        "models": ["MiniMax-M2", "MiniMax-Text-01"],
        "api_key_required": True,
        "description": "MiniMax OpenAI 兼容接口。",
    },
    {
        "id": "xai",
        "label": "xAI Grok",
        "protocol": "openai",
        "base_url": "https://api.x.ai/v1",
        "models": ["grok-4", "grok-3", "grok-3-mini"],
        "api_key_required": True,
        "description": "xAI Grok OpenAI 兼容接口。",
    },
    {
        "id": "openrouter",
        "label": "OpenRouter",
        "protocol": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "models": [
            "openai/gpt-4.1",
            "anthropic/claude-sonnet-4",
            "google/gemini-2.5-pro",
            "deepseek/deepseek-chat",
        ],
        "api_key_required": True,
        "description": "用一个 Key 访问多家模型，适合快速切换。",
    },
    {
        "id": "ollama",
        "label": "Ollama / 本地模型",
        "protocol": "openai",
        "base_url": "http://127.0.0.1:11434/v1",
        "models": ["qwen3:8b", "llama3.2", "deepseek-r1:8b"],
        "api_key_required": False,
        "description": "连接本机 Ollama、vLLM 或其他 OpenAI 兼容服务。",
    },
    {
        "id": "custom",
        "label": "自定义 OpenAI 兼容服务",
        "protocol": "openai",
        "base_url": "",
        "models": [],
        "api_key_required": False,
        "description": "手动填写 Base URL 与模型 ID。",
    },
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _preset(provider: str) -> dict:
    for item in MODEL_PROVIDER_PRESETS:
        if item["id"] == provider:
            return item
    return MODEL_PROVIDER_PRESETS[-1]


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "model"


def _api_key_hint(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "••••"
    return f"{value[:3]}…{value[-4:]}"


class ModelProfileStore:
    """JSON-backed model profiles stored under the local LifeOS state folder."""

    def __init__(self, path: str | Path = ".lifeos/models.json"):
        self.path = Path(path)
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write(self._default_state())

    @staticmethod
    def _default_state():
        now = _now()
        return {
            "active_profile_id": "mock",
            "profiles": [
                {
                    "id": "mock",
                    "name": "LifeOS 本地演示",
                    "provider": "mock",
                    "protocol": "mock",
                    "base_url": "",
                    "model": "lifeos-mock",
                    "models": ["lifeos-mock"],
                    "api_key": "",
                    "enabled": True,
                    "builtin": True,
                    "created_at": now,
                    "updated_at": now,
                }
            ],
        }

    def _read(self) -> dict:
        import json

        with self._lock:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                data = self._default_state()
                self._write(data)
            if not isinstance(data, dict) or not isinstance(data.get("profiles"), list):
                raise ValueError("model profile store is malformed")
            return data

    def _write(self, data: dict) -> None:
        with self._lock:
            write_json(self.path, data)
            try:
                self.path.chmod(0o600)
            except OSError:
                pass

    def list_profiles(self) -> list[dict]:
        with self._lock:
            return copy.deepcopy(self._read().get("profiles", []))

    def get_profile(self, profile_id: str) -> dict:
        for profile in self.list_profiles():
            if profile.get("id") == profile_id:
                return profile
        raise KeyError(f"model profile not found: {profile_id}")

    def get_active_profile_id(self) -> str:
        with self._lock:
            data = self._read()
            active = data.get("active_profile_id")
            if any(profile.get("id") == active for profile in data.get("profiles", [])):
                return active
            fallback = data.get("profiles", [{}])[0].get("id", "mock")
            data["active_profile_id"] = fallback
            self._write(data)
            return fallback

    def activate(self, profile_id: str) -> dict:
        with self._lock:
            data = self._read()
            profile = next((item for item in data["profiles"] if item.get("id") == profile_id), None)
            if profile is None:
                raise KeyError(f"model profile not found: {profile_id}")
            data["active_profile_id"] = profile_id
            self._write(data)
            return self.public_profile(profile)

    def create(self, payload: dict) -> dict:
        with self._lock:
            data = self._read()
            profile = self._profile_from_payload(payload)
            profile_id = profile["id"]
            if any(item.get("id") == profile_id for item in data["profiles"]):
                profile_id = f"{profile_id}-{uuid.uuid4().hex[:6]}"
                profile["id"] = profile_id
            now = _now()
            profile["created_at"] = now
            profile["updated_at"] = now
            data["profiles"].append(profile)
            if data.get("active_profile_id") in {None, "mock"} and profile["protocol"] != "mock":
                data["active_profile_id"] = profile_id
            self._write(data)
            return self.public_profile(profile)

    def update(self, profile_id: str, payload: dict) -> dict:
        with self._lock:
            data = self._read()
            existing = next((item for item in data["profiles"] if item.get("id") == profile_id), None)
            if existing is None:
                raise KeyError(f"model profile not found: {profile_id}")
            merged = copy.deepcopy(existing)
            merged.update(payload)
            if payload.get("api_key"):
                merged["api_key"] = str(payload["api_key"]).strip()
            elif payload.get("clear_api_key"):
                merged["api_key"] = ""
            updated = self._normalize_profile(merged, existing=existing)
            updated["id"] = profile_id
            updated["created_at"] = existing.get("created_at") or _now()
            updated["updated_at"] = _now()
            index = data["profiles"].index(existing)
            data["profiles"][index] = updated
            self._write(data)
            return self.public_profile(updated)

    def delete(self, profile_id: str) -> dict:
        with self._lock:
            data = self._read()
            profile = next((item for item in data["profiles"] if item.get("id") == profile_id), None)
            if profile is None:
                raise KeyError(f"model profile not found: {profile_id}")
            if profile.get("builtin"):
                raise ValueError("builtin model profiles cannot be deleted")
            data["profiles"] = [item for item in data["profiles"] if item.get("id") != profile_id]
            if data.get("active_profile_id") == profile_id:
                data["active_profile_id"] = data["profiles"][0]["id"] if data["profiles"] else "mock"
            self._write(data)
            return self.public_profile(profile)

    def catalog(self) -> dict:
        return {
            "active_profile_id": self.get_active_profile_id(),
            "profiles": [self.public_profile(item) for item in self.list_profiles()],
            "presets": copy.deepcopy(MODEL_PROVIDER_PRESETS),
        }

    def public_profile(self, profile: dict) -> dict:
        preset = _preset(profile.get("provider", "custom"))
        api_key = profile.get("api_key", "")
        return {
            "id": profile.get("id"),
            "name": profile.get("name") or preset["label"],
            "provider": profile.get("provider", "custom"),
            "provider_label": preset["label"],
            "protocol": profile.get("protocol", preset["protocol"]),
            "base_url": profile.get("base_url", ""),
            "model": profile.get("model", ""),
            "models": list(profile.get("models") or []),
            "enabled": bool(profile.get("enabled", True)),
            "builtin": bool(profile.get("builtin")),
            "has_api_key": bool(api_key),
            "api_key_hint": _api_key_hint(api_key),
            "created_at": profile.get("created_at"),
            "updated_at": profile.get("updated_at"),
        }

    def test(self, profile_or_id: dict | str) -> dict:
        import asyncio

        if isinstance(profile_or_id, str):
            profile = self.get_profile(profile_or_id)
        else:
            existing = None
            profile_id = profile_or_id.get("id")
            if profile_id:
                try:
                    existing = self.get_profile(profile_id)
                except KeyError:
                    existing = None
            profile = self._normalize_profile(profile_or_id, existing=existing)
        client = LLMClient.from_profile(profile)
        started = time.perf_counter()
        result = asyncio.run(
            client.complete(
                [
                    {"role": "system", "content": "You are a connection test. Reply briefly."},
                    {"role": "user", "content": "Reply with only: OK"},
                ]
            )
        )
        preview = str(result.get("content", "")).strip()[:160]
        return {
            "ok": True,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "provider": result.get("provider"),
            "model": result.get("model"),
            "preview": preview,
        }

    def _profile_from_payload(self, payload: dict) -> dict:
        profile = self._normalize_profile(payload)
        profile_id = str(payload.get("id") or "").strip()
        if not profile_id:
            profile_id = f"{_slug(profile.get('provider', 'custom'))}-{uuid.uuid4().hex[:6]}"
        profile["id"] = _slug(profile_id)
        return profile

    def _normalize_profile(self, payload: dict, existing: dict | None = None) -> dict:
        provider = str(payload.get("provider") or (existing or {}).get("provider") or "custom").strip()
        preset = _preset(provider)
        protocol = str(payload.get("protocol") or (existing or {}).get("protocol") or preset["protocol"]).strip()
        if protocol not in {"mock", "openai", "anthropic"}:
            raise ValueError("protocol must be mock, openai, or anthropic")
        model = str(payload.get("model") or (existing or {}).get("model") or (preset["models"][0] if preset["models"] else "")).strip()
        base_url = str(payload.get("base_url") or (existing or {}).get("base_url") or preset["base_url"]).strip().rstrip("/")
        if payload.get("clear_api_key"):
            api_key = ""
        elif payload.get("api_key"):
            api_key = str(payload["api_key"]).strip()
        elif "api_key" in payload and existing is None:
            api_key = ""
        else:
            api_key = str((existing or {}).get("api_key") or "").strip()
        if protocol != "mock":
            if not base_url.startswith(("http://", "https://")):
                raise ValueError("base_url must start with http:// or https://")
            if not model:
                raise ValueError("model is required")
        if protocol == "mock":
            base_url = ""
            model = model or "lifeos-mock"
            api_key = ""
        models = payload.get("models") if isinstance(payload.get("models"), list) else []
        models = [str(item) for item in models if str(item).strip()]
        if model and model not in models:
            models.insert(0, model)
        return {
            "id": payload.get("id") or (existing or {}).get("id"),
            "name": str(payload.get("name") or (existing or {}).get("name") or preset["label"]).strip(),
            "provider": provider,
            "protocol": protocol,
            "base_url": base_url,
            "model": model,
            "models": models,
            "api_key": api_key,
            "enabled": bool(payload.get("enabled", (existing or {}).get("enabled", True))),
            "builtin": bool((existing or {}).get("builtin", False)),
        }


_profile_override = contextvars.ContextVar("lifeos_model_profile", default=None)


class ModelManager:
    """Route LLM calls through the active profile, with per-request override."""

    def __init__(self, store: ModelProfileStore, fallback=None):
        self.store = store
        self.fallback = fallback
        self.provider = "router"
        self.model = "active-profile"

    async def complete(self, messages, tools=None):
        profile_id = _profile_override.get() or self.store.get_active_profile_id()
        profile = self.store.get_profile(profile_id)
        if profile.get("protocol") == "mock" and self.fallback is not None:
            result = await self.fallback.complete(messages, tools)
            result["provider"] = profile.get("provider", "mock")
            result["model"] = profile.get("model", "lifeos-mock")
            return result
        return await LLMClient.from_profile(profile).complete(messages, tools)

    @contextmanager
    def bind(self, profile_id: str | None):
        token = _profile_override.set(profile_id)
        try:
            yield
        finally:
            _profile_override.reset(token)
