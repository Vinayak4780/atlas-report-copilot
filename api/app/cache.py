"""In-process TTL cache for repeated questions. The key includes the client's entitlement set,
so a cached answer can never be served to a client with different access."""
from __future__ import annotations

import hashlib
import re
import threading
import time
from collections import OrderedDict
from typing import Any


def normalise_question(q: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s%.\-]", "", q.lower())).strip()


def cache_key(client_id: str, entitled: list[str], question: str, history: list[str]) -> str:
    raw = "|".join([client_id, ",".join(sorted(entitled)), normalise_question(question),
                    "||".join(normalise_question(h) for h in history[-3:])])
    return hashlib.sha256(raw.encode()).hexdigest()


class TTLCache:
    def __init__(self, ttl_s: int, max_entries: int = 500):
        self.ttl = ttl_s
        self.max = max_entries
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            ts, value = item
            if time.monotonic() - ts > self.ttl:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = (time.monotonic(), value)
            self._data.move_to_end(key)
            while len(self._data) > self.max:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        return len(self._data)
