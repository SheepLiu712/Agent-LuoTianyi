from __future__ import annotations

from typing import Any, Dict, Mapping, TYPE_CHECKING

if TYPE_CHECKING:
    from src.agent.luotianyi_agent import LuoTianyiAgent
    from src.agent_runtime.character_registry import CharacterRegistry
    from src.agent_runtime.character_runtime import CharacterRuntime


class AgentRegistry:
    """Registry for conscious character models."""

    def __init__(
        self,
        config: Dict[str, Any],
        character_registry: CharacterRegistry,
        character_runtimes: Dict[str, CharacterRuntime],
    ) -> None:
        self.config = config
        self.character_registry = character_registry
        self._agents = {
            character_id: runtime.conscious
            for character_id, runtime in character_runtimes.items()
        }

    def get(self, character_id: str | None = None) -> LuoTianyiAgent:
        profile = self.character_registry.get(character_id)
        try:
            return self._agents[profile.character_id]
        except KeyError as exc:
            raise KeyError(f"No conscious agent registered for {profile.character_id}") from exc

    def all(self) -> Mapping[str, LuoTianyiAgent]:
        return self._agents
