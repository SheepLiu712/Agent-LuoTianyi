"""Deterministic per-call LRU pool for already recalled memories."""

import hashlib
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass

from src.domain import MemoryHit

from ._lifecycle import _Lifecycle


@dataclass(frozen=True, slots=True)
class CallMemory:
    memory_id: str
    content: str

    def __post_init__(self) -> None:
        if not self.memory_id or not self.content:
            raise ValueError("memory_id and content are required")


class CallMemoryPool:
    def __init__(self, capacity: int = 10) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._state = _Lifecycle()
        self._capacity = capacity
        self._items: OrderedDict[str, CallMemory] = OrderedDict()

    def remember(self, memory: CallMemory) -> None:
        self._state.check()
        self._items.pop(memory.memory_id, None)
        self._items[memory.memory_id] = memory
        while len(self._items) > self._capacity:
            self._items.popitem(last=False)

    def snapshot(self) -> tuple[CallMemory, ...]:
        self._state.check()
        return tuple(self._items.values())

    def remember_hits(self, hits: Iterable[MemoryHit]) -> None:
        """将授权命中加入本交互的记忆池，保留稳定身份与近似最近使用顺序。"""
        self._state.check()
        for hit in hits:
            text = hit.rendered_text.strip()
            if text:
                identity = hit.memory_record_id or hit.vector_id or hashlib.sha256(text.encode("utf-8")).hexdigest()
                self.remember(CallMemory(identity, text))

    def clear(self) -> None:
        self._state.check()
        self._items.clear()

    def _close(self) -> None:
        self._items.clear()
