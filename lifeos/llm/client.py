class LLMClient:
    """Unified LLM interface with a mock provider by default."""

    def __init__(self, provider="mock", model="default"):
        self.provider = provider
        self.model = model

    async def complete(self, messages, tools=None):
        if self.provider != "mock":
            raise NotImplementedError(f"provider not implemented: {self.provider}")

        user_message = self._last_user_message(messages)
        return {
            "content": f"LifeOS mock response: {user_message}",
            "tool_calls": [],
            "usage": {},
            "provider": self.provider,
            "model": self.model,
        }

    def _last_user_message(self, messages):
        for message in reversed(messages):
            if message.get("role") == "user":
                return message.get("content", "")
        return ""

