"""Unified LLM client with OpenAI-compatible and Anthropic adapters."""

from __future__ import annotations

import asyncio
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class LLMRequestError(RuntimeError):
    """A model provider returned an invalid or unsuccessful response."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _message_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                elif "text" in block:
                    parts.append(str(block.get("text", "")))
        return "\n".join(part for part in parts if part)
    return str(content)


def _parse_arguments(value):
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {"raw": value}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _error_message(payload, fallback: str) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("code") or fallback)
        if isinstance(error, str):
            return error
        message = payload.get("message")
        if message:
            return str(message)
    return fallback


class LLMClient:
    """Complete(messages, tools) facade for one model profile."""

    def __init__(
        self,
        provider: str = "mock",
        model: str = "default",
        *,
        base_url: str = "",
        api_key: str = "",
        timeout: float = 90,
        protocol: str | None = None,
    ):
        self.provider = provider
        self.model = model
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.timeout = timeout
        self.protocol = protocol or ("mock" if provider == "mock" else "openai")

    @classmethod
    def from_profile(cls, profile: dict) -> "LLMClient":
        return cls(
            provider=profile.get("provider", "custom"),
            model=profile.get("model") or "default",
            base_url=profile.get("base_url", ""),
            api_key=profile.get("api_key", ""),
            timeout=float(profile.get("timeout", 90) or 90),
            protocol=profile.get("protocol", "openai"),
        )

    async def complete(self, messages, tools=None):
        protocol = self.protocol
        if protocol == "mock":
            user_message = self._last_user_message(messages)
            return {
                "content": f"LifeOS mock response: {user_message}",
                "tool_calls": [],
                "usage": {},
                "provider": self.provider,
                "model": self.model,
            }
        if protocol == "openai":
            return await asyncio.to_thread(self._complete_openai, messages, tools)
        if protocol == "anthropic":
            return await asyncio.to_thread(self._complete_anthropic, messages, tools)
        raise NotImplementedError(f"provider protocol not implemented: {protocol}")

    def list_models(self) -> list[str]:
        """Fetch model IDs from an OpenAI-compatible or Anthropic models endpoint."""
        if self.protocol not in {"openai", "anthropic"}:
            raise LLMRequestError(f"model discovery is not supported for protocol: {self.protocol}")
        if not self.base_url:
            raise LLMRequestError("model provider base URL is required")
        try:
            parsed_url = urlparse(self.base_url)
            _validated_port = parsed_url.port  # Force validation before opening a socket.
        except ValueError as exc:
            raise LLMRequestError("base URL is invalid") from exc
        if (parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname
                or parsed_url.username or parsed_url.password):
            raise LLMRequestError("base URL must be an http(s) URL without embedded credentials")

        endpoint = self._endpoint(self.base_url, "/models")
        headers = {}
        if self.protocol == "anthropic":
            headers.update({"anthropic-version": "2023-06-01"})
            if self.api_key:
                headers["x-api-key"] = self.api_key
        elif self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            request = Request(endpoint, headers=headers, method="GET")
        except ValueError as exc:
            raise LLMRequestError("base URL is invalid") from exc
        try:
            with urlopen(request, timeout=min(self.timeout, 20)) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = {}
            message = _error_message(payload, raw or f"HTTP {exc.code}")
            raise LLMRequestError(message, status=exc.code) from exc
        except URLError as exc:
            raise LLMRequestError(f"could not reach model provider: {exc.reason}") from exc
        except TimeoutError as exc:
            raise LLMRequestError("model provider model-list request timed out") from exc

        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise LLMRequestError("model provider returned invalid JSON for model list") from exc
        if not isinstance(payload, dict):
            raise LLMRequestError("model provider returned an unexpected model-list response")
        items = payload.get("data", payload.get("models", []))
        if not isinstance(items, list):
            raise LLMRequestError("model provider model list must be an array")
        models = []
        seen = set()
        for item in items[:500]:
            model_id = item if isinstance(item, str) else (
                item.get("id") or item.get("name") if isinstance(item, dict) else None
            )
            if not isinstance(model_id, str):
                continue
            model_id = model_id.strip()
            if model_id and len(model_id) <= 200 and model_id not in seen:
                seen.add(model_id)
                models.append(model_id)
        if not models:
            raise LLMRequestError("provider returned no model IDs; check the endpoint or use manual entry")
        return models

    def _complete_openai(self, messages, tools=None):
        if not self.base_url:
            raise LLMRequestError("OpenAI-compatible base URL is required")
        endpoint = self._endpoint(self.base_url, "/chat/completions")
        payload = {
            "model": self.model,
            "messages": self._normalize_openai_messages(messages),
        }
        if tools:
            payload["tools"] = tools

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        response = self._post_json(endpoint, payload, headers)

        choices = response.get("choices") or []
        if not choices:
            raise LLMRequestError("model response did not contain choices")
        message = choices[0].get("message") or {}
        tool_calls = []
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            name = function.get("name") or call.get("name") or ""
            tool_calls.append(
                {
                    "id": call.get("id"),
                    "name": name,
                    "action": name,
                    "arguments": _parse_arguments(function.get("arguments")),
                }
            )
        return {
            "content": message.get("content") or "",
            "tool_calls": tool_calls,
            "usage": response.get("usage") or {},
            "provider": self.provider,
            "model": response.get("model") or self.model,
        }

    def _complete_anthropic(self, messages, tools=None):
        if not self.base_url:
            raise LLMRequestError("Anthropic base URL is required")
        endpoint = self._endpoint(self.base_url, "/messages")
        system_parts = []
        converted = []
        for message in messages:
            role = message.get("role")
            content = message.get("content", "")
            if role in {"system", "developer"}:
                text = _message_text(content)
                if text:
                    system_parts.append(text)
                continue
            if role not in {"user", "assistant"}:
                continue
            # 连续同角色的 user 消息合并成一条：对话历史里允许注入独立的
            # 上下文消息（如 Agent 执行记录），部分 provider 要求
            # user/assistant 交替，这里兜底。
            if converted and converted[-1]["role"] == role:
                converted[-1]["content"] = converted[-1]["content"] + "\n\n" + content
                continue
            converted.append({"role": role, "content": content})

        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": converted,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if tools:
            payload["tools"] = self._anthropic_tools(tools)

        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        response = self._post_json(endpoint, payload, headers)

        text_parts = []
        tool_calls = []
        for block in response.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text_parts.append(str(block.get("text", "")))
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    {
                        "id": block.get("id"),
                        "name": block.get("name") or "",
                        "action": block.get("name") or "",
                        "arguments": block.get("input") or {},
                    }
                )
        return {
            "content": "\n".join(part for part in text_parts if part),
            "tool_calls": tool_calls,
            "usage": response.get("usage") or {},
            "provider": self.provider,
            "model": response.get("model") or self.model,
        }

    def _post_json(self, url: str, payload: dict, headers: dict) -> dict:
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            try:
                parsed = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                parsed = {}
            message = _error_message(parsed, raw or f"HTTP {exc.code}")
            raise LLMRequestError(message, status=exc.code) from exc
        except URLError as exc:
            raise LLMRequestError(f"could not reach model provider: {exc.reason}") from exc
        except TimeoutError as exc:
            raise LLMRequestError("model provider request timed out") from exc

        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise LLMRequestError("model provider returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise LLMRequestError("model provider returned an unexpected response")
        return parsed

    @staticmethod
    def _normalize_openai_messages(messages):
        normalized = []
        for message in messages:
            role = message.get("role")
            if role not in {"system", "developer", "user", "assistant", "tool"}:
                continue
            item = {"role": role, "content": message.get("content", "")}
            for key in ("name", "tool_call_id", "tool_calls"):
                if key in message:
                    item[key] = message[key]
            normalized.append(item)
        return normalized

    @staticmethod
    def _anthropic_tools(tools):
        converted = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
                function = tool["function"]
            else:
                function = tool
            name = function.get("name")
            if not name:
                continue
            converted.append(
                {
                    "name": name,
                    "description": function.get("description", ""),
                    "input_schema": function.get("parameters") or {"type": "object", "properties": {}},
                }
            )
        return converted

    @staticmethod
    def _endpoint(base_url: str, suffix: str) -> str:
        base = base_url.rstrip("/")
        return base if base.endswith(suffix) else base + suffix

    @staticmethod
    def _last_user_message(messages):
        for message in reversed(messages):
            if message.get("role") == "user":
                return _message_text(message.get("content", ""))
        return ""
