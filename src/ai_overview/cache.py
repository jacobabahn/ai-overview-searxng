"""Per-worker memory of completed first answers; never written to disk."""

import time
from collections import OrderedDict
from threading import Lock
from typing import Optional


class AnswerCache:
    """Bounded LRU with expiry; `get`/`put` is the seam for a shared store."""

    def __init__(self, entries: int, ttl_seconds: int) -> None:
        self.entries = entries
        self.ttl = ttl_seconds
        self._items: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._lock = Lock()

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            if item[0] <= time.monotonic():
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return item[1]

    def put(self, key: str, answer: str) -> None:
        with self._lock:
            self._items[key] = (time.monotonic() + self.ttl, answer)
            self._items.move_to_end(key)
            while len(self._items) > self.entries:
                self._items.popitem(last=False)
