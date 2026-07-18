from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RealtimeToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]

    def as_payload(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True)
class RealtimeEvent:
    type: str
    raw: dict[str, Any] = field(default_factory=dict)
    event_id: str | None = None
    response_id: str | None = None
    item_id: str | None = None
    call_id: str | None = None
    delta: str = ""
    transcript: str = ""
    name: str | None = None
    arguments: str = ""
    usage: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
