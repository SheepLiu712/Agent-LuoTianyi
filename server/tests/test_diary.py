"""
DiaryCapability / DiaryTask 单元测试。
"""
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.capabilities.diary import DiaryCapability
from src.system.database.sql_database import (
    Base,
    Conversation,
    DynamicPost,
    User,
    _migrate_sqlite_schema,
)
from src.world.diary.task import DiaryTask


# ────────────────────── _parse_diary_result ──────────────────────


def test_parse_diary_result_standard_format():
    capability = DiaryCapability({})
    raw = (
        "心情：开心\n"
        "\n"
        "今天和主人聊了很多关于音乐的话题。\n"
        "\n"
        "晚上还一起听了新歌。"
    )
    result = capability._parse_diary_result(raw, target_date="2026-07-16")
    assert result == (
        "2026-07-16 · 心情: 开心\n"
        "\n"
        "今天和主人聊了很多关于音乐的话题。\n"
        "\n"
        "晚上还一起听了新歌。"
    )


def test_parse_diary_result_english_colon():
    capability = DiaryCapability({})
    raw = "心情: 温暖\n\n今天天气很好。"
    result = capability._parse_diary_result(raw, target_date="2026-07-16")
    assert result.startswith("2026-07-16 · 心情: 温暖")


def test_parse_diary_result_no_mood():
    capability = DiaryCapability({})
    raw = "今天只是平平淡淡的一天。"
    result = capability._parse_diary_result(raw, target_date="2026-07-16")
    assert result.startswith("2026-07-16")
    assert "心情" not in result.split("\n")[0]


def test_parse_diary_result_skips_title_and_summary():
    capability = DiaryCapability({})
    raw = (
        "标题：日记\n"
        "摘要：今天很好\n"
        "心情：平静\n"
        "\n"
        "正文内容。"
    )
    result = capability._parse_diary_result(raw, target_date="2026-07-16")
    assert "标题" not in result
    assert "摘要" not in result
    assert result.startswith("2026-07-16 · 心情: 平静")


def test_parse_diary_result_empty_input():
    capability = DiaryCapability({})
    assert capability._parse_diary_result("", target_date="2026-07-16") is None
    assert capability._parse_diary_result("   \n ", target_date="2026-07-16") is None


def test_parse_diary_result_think_only_is_empty():
    capability = DiaryCapability({})
    assert capability._parse_diary_result("<think>只返回思考</think>", target_date="2026-07-16") is None


def test_parse_diary_result_compresses_excess_blank_lines():
    capability = DiaryCapability({})
    raw = "心情：开心\n\n正文第一段。\n\n\n\n\n正文第二段。"
    result = capability._parse_diary_result(raw, target_date="2026-07-16")
    assert "\n\n\n" not in result


def test_parse_diary_result_accepts_inline_body_label():
    capability = DiaryCapability({})
    raw = "心情：平静\n正文：第一段。\n\n第二段。"

    result = capability._parse_diary_result(raw, target_date="2026-07-16")

    assert result.endswith("第一段。\n\n第二段。")


# ────────────────────── _strip_think_block ──────────────────────


def test_strip_think_block():
    capability = DiaryCapability({})
    raw = (
        "<think>用户今天提到了音乐，我应该围绕音乐写。</think>\n"
        "心情：感动\n\n今天主人教我唱新歌了。"
    )
    stripped = capability._strip_think_block(raw)
    assert "think" not in stripped
    assert stripped.startswith("心情：感动")


def test_strip_think_block_absent():
    capability = DiaryCapability({})
    raw = "心情：开心\n\n普通内容。"
    assert capability._strip_think_block(raw) == raw


# ────────────────────── generate_and_post_diary 前置检查 ──────────────────────


class FakeLLMModule:
    def __init__(self):
        self.calls = []

    async def generate_response(self, **kwargs):
        self.calls.append(kwargs)
        return "心情：开心\n\n测试日记内容。"


class FakeLLMService:
    llm_interfaces = {}

    def register_llm_module(self, name, config):
        return FakeLLMModule()


def _make_capability_with_llm() -> DiaryCapability:
    """构造带 LLM 配置的 DiaryCapability，并注册 Fake LLM。"""
    capability = DiaryCapability(
        {
            "diary_llm": {
                "llm_module": {
                    "llm": {"name": "qwen3.5-plus"},
                    "prompt_name": "diary_prompt",
                }
            }
        }
    )
    capability.create_llm_module(FakeLLMService())
    return capability


def test_diary_prompt_uses_prompt_manager_schema():
    prompt_path = Path(__file__).resolve().parents[1] / "res" / "agent" / "prompts" / "diary_prompt.json"
    with prompt_path.open("r", encoding="utf-8") as prompt_file:
        prompt = json.load(prompt_file)

    assert set(prompt) == {"name", "description", "template"}
    assert prompt["name"] == "diary_prompt"
    assert prompt["description"]
    assert isinstance(prompt["template"], list)
    assert "{{ character_name }}" in "\n".join(prompt["template"])


class FakeDynamicCapability:
    def __init__(self):
        self.published = []

    def publish_agent_dynamic(self, **kwargs):
        self.published.append(kwargs)
        return True, "ok", {"id": "dynamic-1"}


class FakeDatabaseManager:
    """提供日记素材收集所需的最小 DB 桩。"""

    def __init__(self, existing_dynamic=None):
        self.dynamic_store = SimpleNamespace(
            list_dynamics_for_user=lambda user_id, limit=50: {"items": []},
            get_dynamic_by_source=lambda **kwargs: existing_dynamic,
        )
        self.conversation_service = self
        self._prefs = {"nickname": "小洛"}
        self._desc = "喜欢音乐的测试用户"

    def get_user_preferences(self, user_id):
        return self._prefs

    def get_user_description(self, user_id):
        return self._desc

    def get_total_conversation_count(self, user_id, character_id=None):
        return 0

    def get_history_from_db(self, user_id, start, end, character_id=None):
        return []


def test_generate_and_post_diary_missing_dynamic_capability():
    capability = _make_capability_with_llm()
    ok, msg, _ = asyncio.run(capability.generate_and_post_diary("user-1"))
    assert ok is False
    assert "DynamicCapability" in msg


def test_generate_and_post_diary_missing_llm():
    capability = DiaryCapability({})
    dynamic_cap = FakeDynamicCapability()
    capability.wire_dependencies(database_manager=None, dynamic_capability=dynamic_cap)
    ok, msg, _ = asyncio.run(capability.generate_and_post_diary("user-1"))
    assert ok is False
    assert "LLM" in msg


def test_generate_and_post_diary_full_flow():
    capability = _make_capability_with_llm()
    dynamic_cap = FakeDynamicCapability()
    capability.wire_dependencies(
        database_manager=FakeDatabaseManager(),
        dynamic_capability=dynamic_cap,
    )

    ok, msg, item = asyncio.run(
        capability.generate_and_post_diary(
            "user-1",
            character_id="luotianyi",
            diary_date="2026-07-16",
        )
    )
    assert ok is True
    assert item is not None
    assert dynamic_cap.published
    payload = dynamic_cap.published[0]
    assert payload["source_type"] == "diary"
    assert payload["source_id"] == "diary:luotianyi:user-1:2026-07-16"
    assert payload["idempotent_by_source"] is True
    assert payload["visibility"] == "private"
    assert payload["owner_user_id"] == "user-1"
    assert payload["allow_comment"] is False
    assert "2026-07-16" in payload["content"]
    llm_call = capability._diary_llm.calls[0]
    assert set(llm_call) == {
        "character_name",
        "user_name",
        "diary_date",
        "user_description",
        "user_preferences",
        "conversation_materials",
        "character_persona",
        "speaking_style",
    }
    assert llm_call["diary_date"] == "2026-07-16"
    assert "system_prompt" not in llm_call
    assert "user_prompt" not in llm_call


def test_diary_capability_exposes_llm_readiness():
    capability = _make_capability_with_llm()
    assert capability.ensure_llm() is True
    assert DiaryCapability({}).ensure_llm() is False


def test_generate_and_post_diary_publishes_via_agent_dynamic():
    """验证日记内容通过 publish_agent_dynamic 发布为 agent 动态。"""
    capability = _make_capability_with_llm()
    dynamic_cap = FakeDynamicCapability()
    capability.wire_dependencies(
        database_manager=FakeDatabaseManager(),
        dynamic_capability=dynamic_cap,
    )

    ok, msg, _ = asyncio.run(
        capability.generate_and_post_diary("user-1", diary_date="2026-07-16")
    )
    assert ok is True
    # publish_agent_dynamic 内部硬编码 author_type="agent"，
    # 此处验证角色 ID 与可见性已正确传递
    assert dynamic_cap.published[0]["character_id"] == "luotianyi"
    assert dynamic_cap.published[0]["visibility"] == "private"


def test_generate_and_post_diary_returns_existing_source_without_regeneration():
    capability = _make_capability_with_llm()
    dynamic_cap = FakeDynamicCapability()
    existing = {
        "id": "existing-diary",
        "owner_user_id": "user-1",
        "source_id": "diary:luotianyi:user-1:2026-07-16",
    }
    capability.wire_dependencies(
        database_manager=FakeDatabaseManager(existing_dynamic=existing),
        dynamic_capability=dynamic_cap,
    )

    ok, msg, item = asyncio.run(
        capability.generate_and_post_diary("user-1", diary_date="2026-07-16")
    )

    assert ok is True
    assert msg == "日记已存在"
    assert item == existing
    assert dynamic_cap.published == []


def test_generate_and_post_diary_rejects_noncanonical_date():
    capability = _make_capability_with_llm()
    dynamic_cap = FakeDynamicCapability()
    capability.wire_dependencies(
        database_manager=FakeDatabaseManager(),
        dynamic_capability=dynamic_cap,
    )

    ok, msg, item = asyncio.run(
        capability.generate_and_post_diary("user-1", diary_date="20260716")
    )

    assert ok is False
    assert msg == "日记日期格式无效"
    assert item is None
    assert dynamic_cap.published == []


# ────────────────────── DiaryTask 默认配置 ──────────────────────


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


# ────────────────────── _find_active_users 随机抽样 ──────────────────────


def test_run_once_randomly_samples_when_exceeding_limit():
    """活跃用户数超过上限时，应随机抽样而非固定取前 N 个。"""
    selected = []

    class FakeDiaryCapability:
        def ensure_llm(self):
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

    # 多次运行应覆盖多个不同用户（随机抽样保证公平性）
    samples = set()
    for _ in range(50):
        asyncio.run(task.run_once())
        samples.update(selected)
        selected.clear()
    assert len(samples) > 3


def test_run_once_all_users_when_below_limit():
    selected = []

    class FakeDiaryCapability:
        def ensure_llm(self):
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


def _diary_query_database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    return engine, session_factory


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


def test_diary_source_key_has_database_uniqueness():
    engine, session_factory = _diary_query_database()
    session = session_factory()
    try:
        session.add(User(uuid="user-1", username="user-1", password="hash"))
        session.commit()
        common = {
            "author_type": "agent",
            "author_id": "luotianyi",
            "owner_user_id": "user-1",
            "visibility": "private",
            "content": "diary",
            "source_type": "diary",
            "source_id": "diary:luotianyi:user-1:2026-07-16",
            "status": "published",
        }
        session.add(DynamicPost(id="diary-1", **common))
        session.commit()
        session.add(DynamicPost(id="diary-2", **common))

        with pytest.raises(IntegrityError):
            session.commit()
    finally:
        session.rollback()
        session.close()
        engine.dispose()


def test_diary_migration_rejects_duplicate_source_keys_without_deleting_rows():
    engine, session_factory = _diary_query_database()
    session = session_factory()
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP INDEX uq_dynamic_posts_diary_source")
        session.add(User(uuid="user-1", username="user-1", password="hash"))
        common = {
            "author_type": "agent",
            "author_id": "luotianyi",
            "owner_user_id": "user-1",
            "visibility": "private",
            "content": "diary",
            "source_type": "diary",
            "source_id": "diary:luotianyi:user-1:2026-07-16",
            "status": "published",
        }
        session.add_all(
            [
                DynamicPost(id="duplicate-diary-1", **common),
                DynamicPost(id="duplicate-diary-2", **common),
            ]
        )
        session.commit()

        with pytest.raises(RuntimeError, match="duplicate diary source keys"):
            _migrate_sqlite_schema(engine)

        assert session.query(DynamicPost).filter_by(source_type="diary").count() == 2
    finally:
        session.close()
        engine.dispose()
