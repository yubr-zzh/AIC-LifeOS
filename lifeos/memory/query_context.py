"""Small, session-local context window for memory retrieval queries."""

from collections import deque


class SessionQueryContext:
    def __init__(self, max_turns: int = 5, max_chars: int = 1500):
        self.max_turns = max_turns
        self.max_chars = max_chars
        self._sessions = {}

    def add_and_build(self, session_id, text, scope=None):
        if not session_id:
            return text
        key = (session_id, self._scope_key(scope))
        # Remove prior scope entries for this session to avoid retaining data
        # that could be reused after the caller changes authorization scope.
        for old_key in list(self._sessions):
            if old_key[0] == session_id and old_key != key:
                del self._sessions[old_key]
        turns = self._sessions.setdefault(key, deque(maxlen=self.max_turns))
        turns.append(text)
        selected = []
        size = 0
        for turn in reversed(turns):
            separator = 1 if selected else 0
            if size + separator + len(turn) > self.max_chars:
                remaining = self.max_chars - size - separator
                if remaining > 0:
                    selected.append(turn[-remaining:])
                break
            selected.append(turn)
            size += separator + len(turn)
        return " ".join(reversed(selected))

    @staticmethod
    def _scope_key(scope):
        if not scope:
            return ()
        return tuple(scope.get(key) for key in ("kind", "scenario_type", "project_id", "user_id"))
