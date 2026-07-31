"""
DiaryCapability / DiaryTask 单元测试。
"""
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.capabilities.diary import DiaryCapability
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


def test_parse_diary_result_compresses_excess_blank_lines():
    capability = DiaryCapability({})
    raw = "心情：开心\n\n正文第一段。\n\n\n\n\n正文第二段。"
    result = capability._parse_diary_result(raw, target_date="2026-07-16")
    assert "\n\n\n" not in result


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
    async def generate_async(self, system_prompt=None, user_prompt=None):
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
    capability.create_diary_llm_module(FakeLLMService())
    return capability


class FakeDynamicCapability:
    def __init__(self):
        self.published = []

    def publish_agent_dynamic(self, **kwargs):
        self.published.append(kwargs)
        return True, "ok", {"id": "dynamic-1"}


class FakeDatabaseManager:
    """提供日记素材收集所需的最小 DB 桩。"""

    def __init__(self):
        self.dynamic_store = SimpleNamespace(
            list_dynamics_for_user=lambda user_id, limit=50: {"items": []}
        )
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
    assert payload["visibility"] == "private"
    assert payload["owner_user_id"] == "user-1"
    assert payload["allow_comment"] is False
    assert "2026-07-16" in payload["content"]


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
