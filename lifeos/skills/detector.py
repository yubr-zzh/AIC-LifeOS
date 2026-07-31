import uuid


class SkillDetector:
    def __init__(self, llm):
        self.llm = llm

    async def detect(self, conversation):
        text = conversation.get("user_input", "")
        if "每次" not in text and "反复" not in text and "自动" not in text:
            return []
        return [
            {
                "id": str(uuid.uuid4()),
                "name": "candidate_from_conversation",
                "description": "Detected repeated workflow from conversation.",
                "risk": "low",
                "source": "global_agent",
            }
        ]

