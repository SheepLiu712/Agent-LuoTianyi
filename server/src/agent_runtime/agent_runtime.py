from __future__ import annotations

from typing import Any, Dict

from src.agent.luotianyi_agent import LuoTianyiAgent
from src.agent_runtime.agent_registry import AgentRegistry
from src.agent_runtime.character_registry import CharacterRegistry, get_default_character_registry
from src.agent_runtime.runtime_hub import AgentRuntimeHub
from src.agent_runtime.subconscious import Subconscious
from src.subconscious.character_mind import CharacterSubconscious
from src.system.database.vector_store import get_vector_store, init_vector_store
from src.utils.logger import get_logger


class AgentRuntime:
    """Owns conscious agents, character lookup, and shared subconscious services."""

    def __init__(
        self,
        config: Dict[str, Any],
        llm_service: Any,
        capability_manager: Any,
        database_manager: Any,
    ) -> None:
        self.logger = get_logger(__name__)
        self.config = config
        self.character_registry = CharacterRegistry(config.get("character_registry", {}), llm_service, capability_manager, database_manager)
        self.default_character_id = self.character_registry.get().character_id

        agent_config = self._build_agent_config(self.config, llm_service, capability_manager)
        vector_store = self._initialize_vector_store(agent_config)
        conscious_agents, character_minds = self._build_character_runtimes(
            agent_config=agent_config,
            capability_manager=capability_manager,
            database_manager=database_manager,
            vector_store=vector_store,
        )
        self.agent_registry = AgentRegistry(
            self.config.get("agent_registry", {}),
            self.character_registry,
            conscious_agents,
        )
        self.conscious_agents = dict(self.agent_registry.all())
        self.subconscious = Subconscious(
            self.config.get("subconscious", {}),
            self.agent_registry,
            character_minds,
        )

        global _agent_runtime
        _agent_runtime = self

    def get_agent(self, character_id: str | None = None) -> LuoTianyiAgent:
        return self.agent_registry.get(character_id or self.default_character_id)

    def get_state(self, character_id: str | None = None):
        return self.subconscious.get_state(character_id or self.default_character_id)

    def _build_character_runtimes(
        self,
        *,
        agent_config: dict[str, Any],
        capability_manager: Any,
        database_manager: Any,
        vector_store: Any,
    ) -> tuple[dict[str, LuoTianyiAgent], dict[str, CharacterSubconscious]]:
        agents: dict[str, LuoTianyiAgent] = {}
        minds: dict[str, CharacterSubconscious] = {}
        for profile in self.character_registry.characters.values():
            if not profile.enabled:
                continue
            tts_module = self._get_tts_module(capability_manager, profile.character_id)
            music_manager = self._get_music_manager(capability_manager, profile.character_id)
            hub = AgentRuntimeHub(
                {},
                redis_client=database_manager.redis,
                vector_store=vector_store,
                sql_session_factory=database_manager.open_sql_session,
                database=database_manager,
                music_manager=music_manager,
                capabilities=capability_manager,
            )
            mind = CharacterSubconscious(agent_config, hub, profile)
            minds[profile.character_id] = mind
            agents[profile.character_id] = LuoTianyiAgent(
                agent_config,
                tts_module,
                hub,
                character_profile=profile,
                subconscious=mind,
            )
        return agents, minds

    @staticmethod
    def _build_agent_config(config: Dict[str, Any], llm_service: Any, capability_manager: Any) -> dict[str, Any]:
        subconscious_cfg = dict(config.get("subconscious", {}))
        agent_cfg = dict(config.get("agent", {}))
        capability_cfg = getattr(capability_manager, "config", {})
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
    def _initialize_vector_store(agent_config: Dict[str, Any]) -> Any:
        vector_cfg = agent_config.get("memory_manager", {}).get("vector_store", {})
        if vector_cfg:
            init_vector_store(vector_cfg)
        return get_vector_store()

    def _get_tts_module(self, capability_manager: Any, character_id: str) -> Any:
        modules = getattr(getattr(capability_manager, "speech", None), "tts_module", {})
        if character_id in modules:
            return modules[character_id]
        if self.default_character_id in modules:
            return modules[self.default_character_id]
        if modules:
            return next(iter(modules.values()))
        raise ValueError(f"No TTS module available for character_id={character_id}")

    def _get_music_manager(self, capability_manager: Any, character_id: str) -> Any:
        singing = getattr(capability_manager, "singing", None)
        managers = getattr(singing, "singing_manager", {}) if singing is not None else {}
        if character_id in managers:
            return managers[character_id]
        default_character_id = getattr(singing, "default_character_id", None)
        if default_character_id in managers:
            return managers[default_character_id]
        if managers:
            return next(iter(managers.values()))
        raise ValueError(f"No singing manager available for character_id={character_id}")


_agent_runtime: AgentRuntime | None = None


def get_agent_runtime() -> AgentRuntime:
    if _agent_runtime is None:
        raise ValueError("AgentRuntime has not been initialized.")
    return _agent_runtime


def get_default_agent() -> LuoTianyiAgent:
    return get_agent_runtime().get_agent()
