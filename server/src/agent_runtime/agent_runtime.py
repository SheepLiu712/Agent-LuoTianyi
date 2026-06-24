from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

from src.agent.luotianyi_agent import LuoTianyiAgent
from src.agent_runtime.character_registry import CharacterRegistry, get_default_character_registry
from src.system.database.vector_store import get_vector_store, init_vector_store


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

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        llm_service: Any | None = None,
        capability_manager: Any | None = None,
        database_manager: Any | None = None,
        *,
        character_registry: CharacterRegistry | None = None,
        conscious_agents: dict[str, LuoTianyiAgent] | None = None,
        default_character_id: str = "luotianyi",
    ) -> None:
        registry = character_registry or get_default_character_registry()

        if conscious_agents is not None:
            self.character_registry = registry
            self.conscious_agents = conscious_agents
            self.default_character_id = default_character_id
            return

        if config is None or llm_service is None or capability_manager is None or database_manager is None:
            raise ValueError("AgentRuntime requires config, llm_service, capability_manager, and database_manager")

        agent_config = self._build_agent_config(config, llm_service, capability_manager)
        vector_store = self._initialize_vector_store(agent_config)
        deps = AgentRuntimeDependencies(
            redis_client=database_manager.redis,
            vector_store=vector_store,
            sql_session_factory=database_manager.open_sql_session,
            database=database_manager,
            music_manager=capability_manager.singing.music_manager,
            capabilities=capability_manager,
        )

        tts_module = capability_manager.speech.tts_module
        self.character_registry = registry
        self.conscious_agents = {
            profile.character_id: LuoTianyiAgent(
                agent_config,
                tts_module,
                deps,
                character_profile=profile,
            )
            for profile in registry.characters.values()
        }
        self.default_character_id = registry.get(default_character_id).character_id

        global _agent_runtime
        _agent_runtime = self

    def get_agent(self, character_id: str | None = None) -> LuoTianyiAgent:
        profile = self.character_registry.get(character_id or self.default_character_id)
        try:
            return self.conscious_agents[profile.character_id]
        except KeyError as exc:
            raise KeyError(f"No conscious agent registered for {profile.character_id}") from exc

    @staticmethod
    def _build_agent_config(config: dict[str, Any], llm_service: Any, capability_manager: Any) -> dict[str, Any]:
        subconscious_cfg = config.get("subconscious", {})
        agent_cfg = config.get("agent", {})
        capability_cfg = getattr(capability_manager, "_config", {})
        return {
            "prompt_manager": getattr(llm_service, "config", {}).get("prompt_manager", {}),
            "conversation_manager": subconscious_cfg.get("conversation_manager", {}),
            "memory_manager": subconscious_cfg.get("memory", {}),
            "date_detector": subconscious_cfg.get("date_detector", {}),
            "topic_extractor": subconscious_cfg.get("topic_extractor", {}),
            "vision_module": capability_cfg.get("image_understanding", {}),
            "main_chat": agent_cfg.get("main_chat", {}),
        }

    @staticmethod
    def _initialize_vector_store(agent_config: dict[str, Any]) -> Any:
        vector_cfg = agent_config.get("memory_manager", {}).get("vector_store", {})
        if vector_cfg:
            init_vector_store(vector_cfg)
        return get_vector_store()


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
