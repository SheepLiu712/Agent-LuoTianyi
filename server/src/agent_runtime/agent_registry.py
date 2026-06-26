from __future__ import annotations

from typing import Any, Mapping

from src.agent.luotianyi_agent import LuoTianyiAgent
from src.agent_runtime.character_registry import CharacterRegistry


class AgentRegistry:
    """Registry for conscious character models."""

    def __init__(
        self,
        config: Mapping[str, Any],
        character_registry: CharacterRegistry,
        conscious_agents: Mapping[str, LuoTianyiAgent],
    ) -> None:
        self.config = dict(config)
        self.character_registry = character_registry
        self._agents = dict(conscious_agents)

    def get(self, character_id: str | None = None) -> LuoTianyiAgent:
        profile = self.character_registry.get(character_id)
        try:
            return self._agents[profile.character_id]
        except KeyError as exc:
            raise KeyError(f"No conscious agent registered for {profile.character_id}") from exc

    def all(self) -> Mapping[str, LuoTianyiAgent]:
        return self._agents
