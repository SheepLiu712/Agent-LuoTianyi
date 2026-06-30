from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class WorldEvent:
    """Normalized world event consumed by the future runtime."""

    event_id: str
    event_type: str
    title: str
    description: str = ""
    source: str = ""
    start_datetime: datetime | None = None
    end_datetime: datetime | None = None
    is_personal: bool = False
    target_user_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


class WorldEventProvider(Protocol):
    def list_active_events(self, user_id: str | None = None) -> list[WorldEvent]:
        ...

    def get_context_for_runtime(self, user_id: str | None = None) -> str:
        ...
