import asyncio
from datetime import datetime
from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.system.database.sql_database import Base, Conversation, DynamicPost, User
from src.world.diary.task import DiaryTask


def _diary_query_database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    return engine, session_factory


def test_diary_task_default_clock_config_is_daily():
    task = DiaryTask({}, character_id="luotianyi")
    assert task.get_task_type() == "daily"
    params = task.get_task_params()
    assert params.get("hour") == 0
    assert params.get("minute") == 0


def test_diary_task_name_includes_character_id():
    task = DiaryTask({}, character_id="miku")
    assert task.get_task_name() == "diary:miku"
    assert task.character_id == "miku"


def test_diary_task_config_overrides():
    task = DiaryTask(
        {"min_daily_conversations": 10, "max_users_per_run": 5},
        character_id="luotianyi",
    )
    assert task.min_daily_conversations == 10
    assert task.max_users_per_run == 5


def test_run_once_randomly_samples_when_exceeding_limit(monkeypatch):
    """活跃用户数超过上限时，应随机抽样而非固定取前 N 个。"""
    selected = []

    class FakeDiaryCapability:
        def ensure_dependencies(self):
            return True

        async def generate_and_post_diary(self, **kwargs):
            selected.append(kwargs["user_id"])
            return True, "ok", None

    class FakeCharacterRuntime:
        def dynamic_context(self):
            return SimpleNamespace(character_persona="人设", speaking_style="风格")

    class FakeSystemRuntime:
        class FakeAgentRuntime:
            def get_character_runtime(self, character_id):
                return FakeCharacterRuntime()

        agent_runtime = FakeAgentRuntime()
        capability_manager = SimpleNamespace(diary=FakeDiaryCapability())
        database_manager = None

    class FakeDatabaseManager:
        def get_sql_session(self):
            return None

    task = DiaryTask({"max_users_per_run": 3}, character_id="luotianyi")
    task.system_runtime = FakeSystemRuntime()
    task.database_manager = FakeDatabaseManager()
    task.character_runtime = FakeCharacterRuntime()

    active_users = [f"user-{i}" for i in range(20)]
    task._find_active_users = lambda target_date: active_users

    # 控制随机边界，证明采用抽样结果而非固定取前 N 个。
    def sample(population, count):
        assert population == active_users
        assert count == 3
        return population[-count:]

    monkeypatch.setattr("src.world.diary.task.random.sample", sample)
    result = asyncio.run(task.run_once())
    assert selected == active_users[-3:]
    assert result.data["diaries_created"] == 3


def test_run_once_all_users_when_below_limit():
    selected = []

    class FakeDiaryCapability:
        def ensure_dependencies(self):
            return True

        async def generate_and_post_diary(self, **kwargs):
            selected.append(kwargs["user_id"])
            return True, "ok", None

    class FakeCharacterRuntime:
        def dynamic_context(self):
            return SimpleNamespace(character_persona="", speaking_style="")

    class FakeSystemRuntime:
        class FakeAgentRuntime:
            def get_character_runtime(self, character_id):
                return FakeCharacterRuntime()

        agent_runtime = FakeAgentRuntime()
        capability_manager = SimpleNamespace(diary=FakeDiaryCapability())
        database_manager = None

    class FakeDatabaseManager:
        def get_sql_session(self):
            return None

    task = DiaryTask({"max_users_per_run": 5}, character_id="luotianyi")
    task.system_runtime = FakeSystemRuntime()
    task.database_manager = FakeDatabaseManager()
    task.character_runtime = FakeCharacterRuntime()

    active_users = ["user-1", "user-2", "user-3"]
    task._find_active_users = lambda target_date: active_users

    result = asyncio.run(task.run_once())
    assert set(selected) == set(active_users)
    assert result.data.get("diaries_created") == 3


def test_find_active_users_isolated_by_character_and_source_date():
    engine, session_factory = _diary_query_database()
    target_date = "2026-07-16"
    session = session_factory()
    try:
        session.add(User(uuid="user-1", username="user-1", password="hash"))
        session.add(
            Conversation(
                uuid="conversation-1",
                user_id="user-1",
                character_id="miku",
                timestamp=datetime(2026, 7, 16, 12, 0),
                source="user",
                type="text",
                content="hello",
            )
        )
        session.add(
            DynamicPost(
                id="luotianyi-diary",
                author_type="agent",
                author_id="luotianyi",
                owner_user_id="user-1",
                visibility="private",
                content="other character diary",
                source_type="diary",
                source_id="diary:luotianyi:user-1:2026-07-16",
                status="published",
                created_at=datetime(2026, 7, 16, 23, 59),
            )
        )
        session.commit()

        task = DiaryTask({"min_daily_conversations": 1}, character_id="miku")
        task.database_manager = SimpleNamespace(get_sql_session=session_factory)
        assert task._find_active_users(target_date) == ["user-1"]

        session.add(
            DynamicPost(
                id="miku-diary",
                author_type="agent",
                author_id="miku",
                owner_user_id="user-1",
                visibility="private",
                content="target diary",
                source_type="diary",
                source_id="diary:miku:user-1:2026-07-16",
                status="published",
                created_at=datetime(2026, 7, 17, 0, 1),
            )
        )
        session.commit()

        assert task._find_active_users(target_date) == []
    finally:
        session.close()
        engine.dispose()
