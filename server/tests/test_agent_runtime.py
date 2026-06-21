import os
import sys

current_dir = os.getcwd()
if current_dir not in sys.path:
    sys.path.append(current_dir)

from src.runtime import agent_runtime
from src.domain import CharacterProfile
from src.runtime.character_registry import CharacterRegistry


class FakeConsciousAgent:
    def __init__(self, config, tts_module, deps, character_profile=None):
        self.config = config
        self.tts_module = tts_module
        self.deps = deps
        self.character_profile = character_profile
        self.character_id = character_profile.character_id if character_profile else "luotianyi"


def test_agent_runtime_owns_default_conscious_agent(monkeypatch):
    monkeypatch.setattr(agent_runtime, "LuoTianyiAgent", FakeConsciousAgent)

    runtime = agent_runtime.init_agent_runtime(
        config={"hello": "world"},
        tts_module="tts",
        redis_client="redis",
        vector_store="vector",
        sql_session_factory=lambda: "session",
        music_manager="music",
    )

    agent = agent_runtime.get_default_agent()
    assert runtime.get_agent("luotianyi") is agent
    assert isinstance(agent, FakeConsciousAgent)
    assert agent.config == {"hello": "world"}
    assert agent.deps.open_sql_session() == "session"
    assert runtime.character_registry.get().character_id == "luotianyi"
    assert agent.character_id == "luotianyi"


def test_agent_runtime_creates_independent_agent_per_registered_character(monkeypatch):
    monkeypatch.setattr(agent_runtime, "LuoTianyiAgent", FakeConsciousAgent)
    registry = CharacterRegistry(
        characters={
            "luotianyi": CharacterProfile(
                character_id="luotianyi",
                display_name="Luo Tianyi",
                memory_namespace="luotianyi",
            ),
            "yanhe": CharacterProfile(
                character_id="yanhe",
                display_name="Yanhe",
                memory_namespace="yanhe",
            ),
        },
        default_character_id="luotianyi",
    )

    runtime = agent_runtime.init_agent_runtime(
        config={"hello": "world"},
        tts_module="tts",
        redis_client="redis",
        vector_store="vector",
        sql_session_factory=lambda: "session",
        music_manager="music",
        character_registry=registry,
    )

    luotianyi = runtime.get_agent("luotianyi")
    yanhe = runtime.get_agent("yanhe")
    assert luotianyi is not yanhe
    assert luotianyi.character_id == "luotianyi"
    assert yanhe.character_id == "yanhe"
    assert set(runtime.conscious_agents) == {"luotianyi", "yanhe"}
