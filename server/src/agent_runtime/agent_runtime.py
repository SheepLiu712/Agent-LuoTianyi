from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

from src.agent.luotianyi_agent import LuoTianyiAgent
from src.agent_runtime.character_registry import CharacterRegistry, get_default_character_registry


@dataclass
class AgentRuntimeDependencies:
    redis_client: Any
    vector_store: Any
    sql_session_factory: Callable[[], Session]
    music_manager: Any
    database: Any | None = None
    capabilities: Any | None = None

    def open_sql_session(self) -> Session:
        return self.sql_session_factory()


class AgentRuntime:
    """Owns conscious agents and character lookup for the server runtime."""

    def __init__(self,config):
    character_registry: CharacterRegistry
    conscious_agents: dict[str, LuoTianyiAgent]
    default_character_id: str = "luotianyi"


    def get_agent(self, character_id: str | None = None) -> LuoTianyiAgent:
        profile = self.character_registry.get(character_id or self.default_character_id)
        try:
            return self.conscious_agents[profile.character_id]
        except KeyError as exc:
            raise KeyError(f"No conscious agent registered for {profile.character_id}") from exc


_agent_runtime: AgentRuntime | None = None


def init_agent_runtime(
    config: dict[str, Any],
    tts_module: Any,
    redis_client: Any,
    vector_store: Any,
    sql_session_factory: Callable[[], Session],
    music_manager: Any,
    database: Any | None = None,
    capabilities: Any | None = None,
    character_registry: CharacterRegistry | None = None,
) -> AgentRuntime:
    global _agent_runtime

    registry = character_registry or get_default_character_registry()
    deps = AgentRuntimeDependencies(
        redis_client=redis_client,
        vector_store=vector_store,
        sql_session_factory=sql_session_factory,
        database=database,
        music_manager=music_manager,
        capabilities=capabilities,
    )
    conscious_agents = {
        profile.character_id: LuoTianyiAgent(
            config,
            tts_module,
            deps,
            character_profile=profile,
        )
        for profile in registry.characters.values()
    }
    default_profile = registry.get()
    _agent_runtime = AgentRuntime(
        character_registry=registry,
        conscious_agents=conscious_agents,
        default_character_id=default_profile.character_id,
    )
    return _agent_runtime


def get_agent_runtime() -> AgentRuntime:
    if _agent_runtime is None:
        raise ValueError("AgentRuntime has not been initialized.")
    return _agent_runtime


def get_default_agent() -> LuoTianyiAgent:
    return get_agent_runtime().get_agent()
