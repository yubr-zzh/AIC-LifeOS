import uuid
from datetime import datetime


class TraceSystem:
    def __init__(self):
        self.records = {}

    def start(self, user_input):
        trace_id = str(uuid.uuid4())
        self.records[trace_id] = {
            "input": user_input,
            "created": datetime.utcnow().isoformat(),
            "events": [],
        }
        return trace_id

    def event(self, trace_id, name, data=None):
        self.records[trace_id]["events"].append(
            {
                "name": name,
                "created": datetime.utcnow().isoformat(),
                "data": data or {},
            }
        )

    def get(self, trace_id):
        return self.records.get(trace_id)

