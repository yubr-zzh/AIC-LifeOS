class ReflectionEngine:
    def __init__(self, llm):
        self.llm = llm

    async def reflect(self, conversation):
        user_input = conversation.get("user_input", "")
        response = conversation.get("result", {}).get("response", "")
        return {
            "summary": f"User asked: {user_input}",
            "response": response,
            "memory_type": "conversation_reflection",
        }

