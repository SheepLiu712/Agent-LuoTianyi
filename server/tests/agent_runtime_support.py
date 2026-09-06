"""门面契约的离线装配：真实 AgentRuntime，替换旧业务依赖及向量存储。"""
import json
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.agent_runtime import agent_runtime as runtime_module


class Dependency:
    def __init__(self, *args, **kwargs):
        pass

    def ensure_dependencies(self):
        pass


class Mind(Dependency):
    async def search_song_facts_for_topic(self, constraints):
        return ["旧歌曲事实"]


class VectorStore:
    def __init__(self):
        self.close_calls = 0

    def close(self):
        self.close_calls += 1


@pytest.fixture
def runtime_dependencies(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'agent-ledger.sqlite'}")
    sessions = sessionmaker(bind=engine)
    store = VectorStore()
    monkeypatch.setattr(runtime_module, "get_vector_store", lambda: store)
    monkeypatch.setattr(runtime_module, "clear_vector_store", lambda expected: True)
    for name in ("ChatPreprocessor", "SubconsciousMemory", "CharacterReflex"):
        monkeypatch.setattr(runtime_module, name, Dependency)
    monkeypatch.setattr(runtime_module, "CharacterSubconscious", Mind)
    persona = tmp_path / "persona.json"
    persona.write_text(json.dumps({
        "character_name": "测试角色", "character_persona": "测试人格", "speaking_style": "自然",
    }), encoding="utf-8")
    tones = tmp_path / "tones.json"
    tones.write_text("{}", encoding="utf-8")
    profile = {"static_variables_file": str(persona), "llm_tone_mapping_file": str(tones)}
    previous = runtime_module._agent_runtime
    config = {
        "agent": {
            "topic_extractor": {"llm_module": {}},
            "memory": {"memory_writer": {"llm_module": {}}, "user_profile": {"llm_module": {}}},
            "main_chat": {"llm_module": {}}, "date_detector": {"llm_module": {}},
        },
        "character_registry": {"characters": {
            "luotianyi": profile | {"default_target": True}, "miku": dict(profile),
            "disabled": profile | {"enabled": False},
        }},
    }
    yield dict(
        config=config,
        llm_service=SimpleNamespace(register_llm_module=lambda *args: SimpleNamespace(
            prompt_template=SimpleNamespace(get_variables=lambda: []),
        )),
        capability_manager=object(), database_manager=SimpleNamespace(open_sql_session=sessions),
    ), store
    runtime_module.set_agent_runtime(previous)
    engine.dispose()


@pytest_asyncio.fixture
async def runtime(runtime_dependencies):
    kwargs, _ = runtime_dependencies
    instance = runtime_module.AgentRuntime(**kwargs)
    try:
        yield instance
    finally:
        await instance.shutdown()
