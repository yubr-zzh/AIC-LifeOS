from typing import Any, Dict


class MemoryRetriever:
    def __init__(self, store):
        self.store = store

    async def retrieve(self, query: str) -> Dict[str, Any]:
        query_lower = query.lower()
        result = {"user": [], "project": [], "feedback": []}
        for category in result:
            for item in self.store.get(category, []):
                text = str(item.get("content", ""))
                if not query_lower or query_lower in text.lower():
                    result[category].append(item)
        return result

