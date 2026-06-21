from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from src.domain import AgentState


@dataclass
class SubconsciousState:
    """Per-character global state service.

    This service is deliberately separate from citywalk state. It stores the
    character's broad emotional/attention state used by planning, not temporary
    minigame mechanics such as route energy or elapsed walk minutes.
    """

    owner_character_id: str
    _snapshot: AgentState = field(init=False)

    def __post_init__(self) -> None:
        self._snapshot = AgentState(owner_character_id=self.owner_character_id)

    def get_snapshot(self) -> AgentState:
        return self._snapshot

    def replace_snapshot(self, snapshot: AgentState) -> AgentState:
        if snapshot.owner_character_id != self.owner_character_id:
            raise ValueError(
                f"AgentState owner mismatch: {snapshot.owner_character_id} != {self.owner_character_id}"
            )
        self._snapshot = snapshot
        return self._snapshot

    def update(
        self,
        *,
        mood: float | None = None,
        arousal: float | None = None,
        vitality: float | None = None,
        connection_need: float | None = None,
        attention_bias: tuple[str, ...] | None = None,
        metadata: Mapping | None = None,
    ) -> AgentState:
        self._snapshot = self._snapshot.with_updates(
            mood=mood,
            arousal=arousal,
            vitality=vitality,
            connection_need=connection_need,
            attention_bias=attention_bias,
            metadata=metadata,
        )
        return self._snapshot
