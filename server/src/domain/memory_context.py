from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.domain.memory_record import MemoryRecord, MemoryType


@dataclass(frozen=True)
class MemoryHit:
    """A recalled memory with canonical record data when available."""

    rendered_text: str
    score: float
    query: str
    source: str = "vector"
    record: Optional[MemoryRecord] = None
    vector_id: str | None = None

    @property
    def memory_type(self) -> MemoryType | None:
        return self.record.memory_type if self.record else None

    @property
    def memory_record_id(self) -> str | None:
        return self.record.id if self.record else None


@dataclass(frozen=True)
class MemoryContext:
    """Typed memory recall result for planning.

    Legacy prompts can still consume `render_for_prompt()`, while future
    planners can inspect memory type, ownership, score, and graph links.
    """

    hits: tuple[MemoryHit, ...] = field(default_factory=tuple)

    def render_for_prompt(self) -> list[str]:
        return [hit.rendered_text for hit in self.hits if hit.rendered_text]

    def by_type(self, memory_type: MemoryType) -> tuple[MemoryHit, ...]:
        return tuple(hit for hit in self.hits if hit.memory_type == memory_type)
