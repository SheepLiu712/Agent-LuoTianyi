from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Mapping


def clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


@dataclass(frozen=True)
class AgentState:
    """Global character state, independent from minigame/session state.

    Citywalk has its own temporary state for one outing. This snapshot is the
    character-level state that future subconscious maintenance and conscious
    planning can use across channels.
    """

    owner_character_id: str
    mood: float = 0.55
    arousal: float = 0.45
    vitality: float = 0.70
    connection_need: float = 0.35
    attention_bias: tuple[str, ...] = ()
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def with_updates(
        self,
        *,
        mood: float | None = None,
        arousal: float | None = None,
        vitality: float | None = None,
        connection_need: float | None = None,
        attention_bias: tuple[str, ...] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "AgentState":
        return replace(
            self,
            mood=clamp_unit(self.mood if mood is None else mood),
            arousal=clamp_unit(self.arousal if arousal is None else arousal),
            vitality=clamp_unit(self.vitality if vitality is None else vitality),
            connection_need=clamp_unit(self.connection_need if connection_need is None else connection_need),
            attention_bias=self.attention_bias if attention_bias is None else tuple(attention_bias),
            metadata=self.metadata if metadata is None else dict(metadata),
            updated_at=datetime.now(),
        )
