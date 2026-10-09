import uuid

from lifeos.time_util import xie_shi


class TraceSystem:
    def __init__(self):
        self.records = {}

    def start(self, user_input):
        trace_id = str(uuid.uuid4())
        self.records[trace_id] = {
            "input": user_input,
            "created": xie_shi(),
            "events": [],
        }
        return trace_id

    def event(self, trace_id, name, data=None):
        self.records[trace_id]["events"].append(
            {
                "name": name,
                "created": xie_shi(),
                "data": data or {},
            }
        )

    def get(self, trace_id):
        return self.records.get(trace_id)

