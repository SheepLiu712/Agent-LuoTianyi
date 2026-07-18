from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import time
from typing import Any, Iterable


@dataclass(frozen=True)
class InjectedMemory:
    memory_id: str
    qwen_item_id: str
    injected_at: float
    text: str


@dataclass(frozen=True)
class MemoryPoolResult:
    status: str
    added_count: int = 0
    deleted_count: int = 0


class CallMemoryPool:
    def __init__(self, *, session, limit: int = 10, id_factory=None) -> None:
        self.session = session
        self.limit = max(1, int(limit))
        self._items: "OrderedDict[str, InjectedMemory]" = OrderedDict()
        self._id_factory = id_factory or (lambda memory_id: f"call-memory-{memory_id}")

    @property
    def memory_ids(self) -> tuple[str, ...]:
        return tuple(self._items.keys())

    async def add_hits(self, hits: Iterable[Any]) -> MemoryPoolResult:
        normalized: list[tuple[str, str]] = []
        seen: set[str] = set()
        for hit in hits:
            memory_id = self._memory_id(hit)
            text = str(getattr(hit, "rendered_text", "") or "").strip()
            if not memory_id or not text or memory_id in seen or memory_id in self._items:
                continue
            seen.add(memory_id)
            normalized.append((memory_id, text))

        if not normalized:
            return MemoryPoolResult(status="no_more_memory")

        deleted_count = 0
        if len(normalized) > self.limit:
            deleted_count = await self._delete_all()

        for memory_id, text in normalized:
            item_id = self._id_factory(memory_id)
            await self.session.append_context_item(role="system", text=text, item_id=item_id)
            self._items[memory_id] = InjectedMemory(
                memory_id=memory_id,
                qwen_item_id=item_id,
                injected_at=time.time(),
                text=text,
            )

        while len(self._items) > self.limit and len(normalized) <= self.limit:
            _, item = self._items.popitem(last=False)
            await self.session.delete_context_item(item.qwen_item_id)
            deleted_count += 1
        return MemoryPoolResult(status="added", added_count=len(normalized), deleted_count=deleted_count)

    async def _delete_all(self) -> int:
        deleted = 0
        for item in list(self._items.values()):
            await self.session.delete_context_item(item.qwen_item_id)
            deleted += 1
        self._items.clear()
        return deleted

    async def clear(self) -> None:
        await self._delete_all()

    @staticmethod
    def _memory_id(hit: Any) -> str:
        record = getattr(hit, "record", None)
        record_id = getattr(record, "id", None) if record is not None else None
        if record_id:
            return str(record_id)
        vector_id = getattr(hit, "vector_id", None)
        return str(vector_id or "")
