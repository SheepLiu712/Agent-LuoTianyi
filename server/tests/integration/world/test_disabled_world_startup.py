"""真实 WorldRuntime/Clock/Task 的关闭与依赖降级；不改任务执行算法。"""

from types import SimpleNamespace

import pytest

from src.world import world_runtime as world_module
from src.world.world_runtime import WorldRuntime

TASK_CLASSES = {
    "citywalk": "CitywalkTask",
    "auto_song_learner": "LearnSingSongsTask",
    "qq_music_credential_refresh": "QQMusicCredentialRefreshTask",
    "song_knowledge": "VCPediaNewSongTask",
    "bili_dynamic_fetcher": "BiliEventUpdateTask",
    "dynamic_interaction": "DynamicInteractionTask",
    "diary": "DiaryTask",
    "expired_event_cleanup": "ExpiredEventCleanupTask",
}


def all_disabled():
    return {key: {"enabled": False} for key in TASK_CLASSES}


@pytest.mark.asyncio
async def test_all_disabled_world_is_valid_and_creates_no_tasks_or_timer_actions(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("a disabled world task was constructed")

    for name in TASK_CLASSES.values():
        monkeypatch.setattr(world_module, name, forbidden)
    holidays = []

    async def ensure_holidays():
        holidays.append("initialized")

    world = WorldRuntime(all_disabled())
    system = SimpleNamespace(
        database_manager=SimpleNamespace(event_store=SimpleNamespace(ensure_holidays=ensure_holidays))
    )
    world.wire_dependencies(server_runtime=system)
    assert world.tasks == []
    assert world.world_clock.last_results == {}
    world.start_background_services()
    try:
        import asyncio

        await asyncio.sleep(0)
        assert holidays == ["initialized"]
        assert world.world_clock._tasks == {}
        assert world.world_clock._daily_actions == {}
        assert world.world_clock._interval_actions == {}
    finally:
        await world.stop_background_services()
    assert not world.world_clock.is_running


@pytest.mark.asyncio
async def test_vector_disabled_citywalk_keeps_registration_but_skips_before_side_effects(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.infrastructure.persistence.database.redis_buffer import RedisBuffer
    from src.infrastructure.persistence.database.services.event_store import EventStore
    from src.infrastructure.persistence.database.sql_database import Base, Event
    from src.infrastructure.persistence.database.vector_store import VectorStoreFactory
    from src.world.citywalk.runtime_scheduler import CitywalkRuntimeService

    engine = create_engine(f"sqlite:///{tmp_path / 'world.sqlite'}")
    Base.metadata.create_all(engine)
    events = EventStore({}, sessionmaker(bind=engine), RedisBuffer())
    vectors = VectorStoreFactory.create_vector_store("chroma", {"enabled": False})
    config = all_disabled()
    config["citywalk"] = {
        "enabled": True,
        "daily_run_probability": 1.0,
        "clock_config": {
            "type": "interval",
            "params": {"interval_seconds": 123, "run_immediately": False},
        },
    }
    observations = []

    async def get_world_stage(*args, **kwargs):
        observations.append("unexpected")
        raise AssertionError("disabled citywalk must not submit a world observation")

    def forbidden_run(*args, **kwargs):
        pytest.fail("disabled citywalk must not execute the report/ingestor workflow")

    monkeypatch.setattr(CitywalkRuntimeService, "run_once", forbidden_run)
    models = SimpleNamespace(register_llm_module=lambda *args: object(), register_vlm_module=lambda *args: object())
    system = SimpleNamespace(
        agent_runtime=SimpleNamespace(
            character_ids=("luotianyi",), default_character_id="luotianyi", vector_store=vectors
        ),
        database_manager=SimpleNamespace(event_store=events),
        llm_service=models,
        get_world_stage=get_world_stage,
    )
    world = WorldRuntime(config)
    try:
        world.wire_dependencies(server_runtime=system)
        assert config["citywalk"]["enabled"] is True
        assert len(world.citywalk_tasks) == 1
        task = world.citywalk_tasks[0]
        assert task.event_store is events
        assert task.citywalk_service is None
        assert task.get_task_params() == {"interval_seconds": 123, "run_immediately": False}
        assert set(world.world_clock._interval_actions) == {"try_citywalk:luotianyi"}
        result = await task.run_once()
        assert result.ok is True and result.skipped is True
        assert result.message == "citywalk service is unavailable"
        assert result.data == {}
        assert observations == []
        with events.sql_session_factory() as session:
            assert session.query(Event).count() == 0
        assert not (tmp_path / "citywalk_reports").exists()

        # 新实例向量恢复时保留原真实服务，未把 requested 开关写成 false。
        system.agent_runtime.vector_store = SimpleNamespace(enabled=True)
        restored = WorldRuntime(config)
        restored.wire_dependencies(server_runtime=system)
        assert restored.citywalk_tasks[0].citywalk_service is not None
        assert restored.citywalk_tasks[0].get_task_params() == task.get_task_params()
        await restored.stop_background_services()
    finally:
        await world.stop_background_services()
        vectors.close()
        engine.dispose()
