"""真实 AgentRuntime 使用禁用向量选择，不替换向量工厂或 AgentMemory。"""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.agent_runtime.agent_runtime import AgentRuntime
from src.infrastructure.persistence.database import vector_store as stores
from src.infrastructure.persistence.database.redis_buffer import RedisBuffer
from src.infrastructure.persistence.database.services.event_store import EventStore
from src.infrastructure.persistence.database.services.memory_store import MemoryStore
from src.infrastructure.persistence.database.sql_database import Base
from tests.integration.runtime.test_component_speaking_startup import runtime_config


@pytest.mark.asyncio
async def test_agent_runtime_disabled_vector_store_constructs_no_vector_resources(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("disabled production vector factory must not construct resources")

    monkeypatch.setattr(stores.chromadb, "PersistentClient", forbidden)
    monkeypatch.setattr(stores, "SiliconFlowEmbeddings", forbidden)
    monkeypatch.setattr(stores, "ThreadPoolExecutor", forbidden)
    monkeypatch.setattr(stores, "vector_store", None)
    config, profile = runtime_config(tmp_path)
    vector_path = tmp_path / "uncreated-vectors"
    config["vector_store"] = {"enabled": False, "vector_store_path": str(vector_path)}
    config["character_registry"] = {
        "characters": {
            "luotianyi": {
                "static_variables_file": profile.static_variables_file,
                "llm_tone_mapping_file": profile.llm_tone_mapping_file,
                "default_target": True,
            }
        }
    }
    engine = create_engine(f"sqlite:///{tmp_path / 'runtime.sqlite'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    database = SimpleNamespace(
        memory_store=MemoryStore({}, sessions, RedisBuffer()),
        event_store=EventStore({}, sessions, RedisBuffer()),
        conversation_service=object(),
        open_sql_session=sessions,
    )
    models = SimpleNamespace(
        register_llm_module=lambda *args, **kwargs: SimpleNamespace(
            prompt_template=SimpleNamespace(get_variables=list)
        ),
        register_vlm_module=lambda *args, **kwargs: object(),
        register_audio_model_module=lambda *args, **kwargs: object(),
    )
    runtime = None
    try:
        runtime = AgentRuntime(config, models, database, media_resolver=SimpleNamespace())
        runtime.ensure_dependencies()
        assert runtime.vector_store.enabled is False
        assert runtime.get_agent() is runtime.get_agent("luotianyi")
        assert not vector_path.exists()
        assert stores.get_vector_store() is runtime.vector_store
    finally:
        if runtime is not None:
            await runtime.shutdown()
        engine.dispose()
    assert stores.vector_store is None
