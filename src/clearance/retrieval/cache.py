"""A cache whose keys always include the reader's principal set and the ACL epoch.

There is no way to build a key without principals, so two users with different permissions can never share an
entry (a classic leak: user A's cached answer served to user B who asked the same question). The ACL epoch is
bumped by every permission change, content change and deletion, so entries computed under old permissions stop
matching the moment the change commits, in every process that reads the epoch.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from collections.abc import Sequence


def principals_hash(principals: Sequence[str]) -> str:
    return hashlib.sha256("\n".join(sorted(set(principals))).encode("utf-8")).hexdigest()[:16]


class PermissionScopedCache[T]:
    def __init__(self, *, max_entries: int = 2000, ttl_seconds: float = 600.0, enabled: bool = True) -> None:
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self.enabled = enabled
        self._data: OrderedDict[str, tuple[float, T]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key(namespace: str, principals: Sequence[str], acl_epoch: int, *parts: object) -> str:
        if not principals:
            raise ValueError("a cache key needs the reader's principal set")
        material = json.dumps(
            [namespace, sorted(set(principals)), acl_epoch, [str(part) for part in parts]], ensure_ascii=False
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def get(self, namespace: str, principals: Sequence[str], acl_epoch: int, *parts: object) -> T | None:
        if not self.enabled:
            return None
        key = self.key(namespace, principals, acl_epoch, *parts)
        with self._lock:
            entry = self._data.get(key)
            if entry is None or time.monotonic() - entry[0] > self.ttl_seconds:
                self._data.pop(key, None)
                self.misses += 1
                return None
            self._data.move_to_end(key)
            self.hits += 1
            return entry[1]

    def put(self, namespace: str, principals: Sequence[str], acl_epoch: int, *parts: object, value: T) -> None:
        if not self.enabled:
            return
        key = self.key(namespace, principals, acl_epoch, *parts)
        with self._lock:
            self._data[key] = (time.monotonic(), value)
            self._data.move_to_end(key)
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        return len(self._data)
