
class LLMClient:
    """
    Unified LLM interface.
    v0.2 first supports adapter architecture.
    """

    def __init__(self, provider="mock", model="default"):
        self.provider = provider
        self.model = model

    async def complete(self, messages):
        return {
            "content": "LLM response placeholder",
            "usage": {}
        }
