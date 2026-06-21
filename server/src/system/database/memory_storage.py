import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple


class WatchError(Exception):
    """Compatibility error type for Redis-like optimistic locking APIs."""


@dataclass
class _Entry:
    value: str
    expire_at: Optional[float]


class MemoryStorage:
    """In-memory Redis replacement with per-user isolation and locks.

    Key format keeps compatibility with existing code, e.g.:
    - user_context:{user_id}
    - user_knowledge:{user_id}
    """

    def __init__(self):
        self._store: Dict[str, _Entry] = {}
        self._locks: Dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()
        self._global_lock = threading.RLock()

    def setex(self, key: str, seconds: int, value: str) -> None:
        lock = self._resolve_lock(key)
        with lock:
            expire_at = time.time() + max(0, int(seconds)) if seconds is not None else None
            self._store[key] = _Entry(value=str(value), expire_at=expire_at)

    def get(self, key: str) -> Optional[str]:
        lock = self._resolve_lock(key)
        with lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if entry.expire_at is not None and entry.expire_at <= time.time():
                self._store.pop(key, None)
                return None
            return entry.value

    def delete(self, key: str) -> int:
        lock = self._resolve_lock(key)
        with lock:
            return 1 if self._store.pop(key, None) is not None else 0

    def clear_user(self, user_id: str) -> None:
        with self._user_lock(user_id):
            suffix = f":{user_id}"
            keys = [k for k in self._store.keys() if k.endswith(suffix)]
            for k in keys:
                self._store.pop(k, None)

    def clear_all(self) -> None:
        with self._global_lock:
            self._store.clear()

    def pipeline(self):
        return _MemoryPipeline(self)

    @contextmanager
    def user_guard(self, user_id: str):
        """Expose a per-user lock context for test and advanced atomic updates."""
        with self._user_lock(user_id):
            yield

    def _resolve_lock(self, key: str) -> threading.RLock:
        user_id = self._extract_user_id(key)
        if user_id is None:
            return self._global_lock
        return self._get_user_lock(user_id)

    def _extract_user_id(self, key: str) -> Optional[str]:
        if ":" not in key:
            return None
        _, user_id = key.rsplit(":", 1)
        return user_id or None

    def _get_user_lock(self, user_id: str) -> threading.RLock:
        with self._locks_guard:
            lock = self._locks.get(user_id)
            if lock is None:
                lock = threading.RLock()
                self._locks[user_id] = lock
            return lock

    @contextmanager
    def _user_lock(self, user_id: str):
        lock = self._get_user_lock(user_id)
        with lock:
            yield


class _MemoryPipeline:
    """Very small Redis pipeline compatibility layer."""

    def __init__(self, storage: MemoryStorage):
        self._storage = storage
        self._locked_users: List[Tuple[str, threading.RLock]] = []
        self._commands: List[Tuple[str, int, str]] = []
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.unwatch()

    def watch(self, *keys: str) -> None:
        if self._closed:
            raise RuntimeError("Pipeline is closed")
        user_ids = sorted({
            uid
            for uid in (self._storage._extract_user_id(k) for k in keys)
            if uid is not None
        })
        for uid in user_ids:
            lock = self._storage._get_user_lock(uid)
            lock.acquire()
            self._locked_users.append((uid, lock))

    def unwatch(self) -> None:
        while self._locked_users:
            _, lock = self._locked_users.pop()
            lock.release()

    def multi(self) -> None:
        # No-op for compatibility.
        return

    def get(self, key: str) -> Optional[str]:
        return self._storage.get(key)

    def setex(self, key: str, seconds: int, value: str):
        self._commands.append((key, seconds, value))

    def execute(self) -> List[Any]:
        results = []
        try:
            for key, seconds, value in self._commands:
                self._storage.setex(key, seconds, value)
                results.append(True)
            return results
        finally:
            self._commands.clear()
            self.unwatch()
