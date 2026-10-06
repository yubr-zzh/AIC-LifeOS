"""Small in-process synchronization helpers for file-backed stores."""

import asyncio
from functools import wraps


def synchronized(method):
    """Serialize one store operation across request threads.

    The wrapped class must initialize ``self._lock`` as a ``threading.RLock``.
    The lock covers the full read/modify/write transaction, not just the final
    atomic file replacement.
    """
    if asyncio.iscoroutinefunction(method):
        @wraps(method)
        async def async_wrapper(self, *args, **kwargs):
            with self._lock:
                return await method(self, *args, **kwargs)

        return async_wrapper

    @wraps(method)
    def sync_wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return sync_wrapper
