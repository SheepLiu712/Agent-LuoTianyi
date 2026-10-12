"""Deterministic per-call LRU pool for already recalled memories."""

from collections import OrderedDict
from dataclasses import dataclass


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
        self._capacity = capacity
        self._items: OrderedDict[str, CallMemory] = OrderedDict()

    def remember(self, memory: CallMemory) -> None:
        self._items.pop(memory.memory_id, None)
        self._items[memory.memory_id] = memory
        while len(self._items) > self._capacity:
            self._items.popitem(last=False)

    def snapshot(self) -> tuple[CallMemory, ...]:
        return tuple(self._items.values())

    def clear(self) -> None:
        self._items.clear()
