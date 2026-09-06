"""复用旧 runtime 配置测试的场景，保留真实任务构造与注册元数据。"""

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.world.world_runtime as runtime_module
from src.world.world_runtime import WorldRuntime


TASKS = {
    "citywalk": ("CitywalkTask", "try_citywalk", True),
    "auto_song_learner": ("LearnSingSongsTask", "learn_sing_songs", True),
    "qq_music_credential_refresh": ("QQMusicCredentialRefreshTask", "qq_music_credential_refresh", False),
    "song_knowledge": ("VCPediaNewSongTask", "sync_new_song_knowledge", False),
    "bili_dynamic_fetcher": ("BiliEventUpdateTask", "bili_event_update", True),
    "dynamic_interaction": ("DynamicInteractionTask", "dynamic_interaction", False),
    "diary": ("DiaryTask", "diary", True),
    "proactive_topic_check": ("ProactiveTopicCheckTask", "proactive_topic_check", False),
    "expired_event_cleanup": ("ExpiredEventCleanupTask", "purge_expired_events", False),
}


class RecordingClock:
    def __init__(self):
        self.actions = {}
        self.registrations = []
        self.started = False
        self.stop_error = None

    def register_daily_action(self, name, hour, minute, action):
        self.registrations.append(name)
        self.actions[name] = ("daily", {"hour": hour, "minute": minute}, action)

    def register_interval_action(self, name, interval_seconds, action, *, run_immediately=False):
        self.registrations.append(name)
        self.actions[name] = ("interval", {
            "interval_seconds": interval_seconds, "run_immediately": run_immediately,
        }, action)

    def start(self):
        self.started = True

    async def stop(self):
        if self.stop_error:
            raise self.stop_error
        self.started = False


@pytest.fixture
def world_config():
    path = Path(__file__).resolve().parents[2] / "config" / "config.json"
    return json.loads(path.read_text(encoding="utf-8"))["world"]


@pytest.fixture
def make_runtime(monkeypatch):
    # 以公开 WorldTask 生命周期替换业务装配；真实构造函数及元数据方法不变。
    # 这里证明任务注册，不证明数据库、模型或任务业务初始化。
    def initialize(task, system):
        task.system_runtime = system

    for class_name, _, _ in TASKS.values():
        cls = getattr(runtime_module, class_name)
        monkeypatch.setattr(cls, "initialize", initialize)
        monkeypatch.setattr(cls, "ensure_dependencies", lambda self: None)

    def make(config, *, managers=("luotianyi", "miku"), event_store=None):
        runtime = WorldRuntime(deepcopy(config))
        runtime.world_clock = RecordingClock()
        system = SimpleNamespace(
            agent_runtime=SimpleNamespace(
                character_runtimes={"luotianyi": object(), "miku": object()},
                default_character_id="luotianyi",
            ),
            capability_manager=SimpleNamespace(singing=SimpleNamespace(
                singing_manager={name: object() for name in managers},
            )),
            database_manager=SimpleNamespace(event_store=event_store),
        )
        runtime.set_system_runtime(system)
        runtime.initialize_modules()
        return runtime

    return make


def enable_all(config):
    config = deepcopy(config)
    for key in TASKS:
        config.setdefault(key, {})["enabled"] = True
        config[key].pop("characters", None)
        config[key].pop("per_character", None)
    config["bili_dynamic_fetcher"]["bilibili_uids"] = {"luotianyi": "1", "miku": "2"}
    return config


def test_all_nine_task_families_register_with_real_names_and_effective_schedules(make_runtime, world_config):
    config = enable_all(world_config)
    runtime = make_runtime(config)
    expected_names = {
        f"{name}:{character}" if per_character else name
        for _, name, per_character in TASKS.values()
        for character in (("luotianyi", "miku") if per_character else (None,))
    }
    assert set(runtime.world_clock.actions) == expected_names
    assert len(runtime.world_clock.registrations) == len(expected_names)
    for key, (class_name, name, per_character) in TASKS.items():
        matching = [task for task in runtime.tasks if type(task).__name__ == class_name]
        assert len(matching) == (2 if per_character else 1)
        for task in matching:
            kind, params, action = runtime.world_clock.actions[task.get_task_name()]
            # 从生效配置或真实任务默认值读取；不另外复制 04:00 / 300 秒等产品值。
            expected = config[key].get("clock_config", task.clock_config)
            assert kind == expected["type"]
            assert params == expected["params"]
            assert action == task.run_once
            assert task.system_runtime is runtime.system_runtime
    assert runtime.dynamic_interaction_task.character_id == "luotianyi"
    assert runtime.qq_music_credential_refresh_task.learn_sing_songs_tasks == runtime.learn_sing_songs_tasks
    before = list(runtime.world_clock.registrations)
    runtime.initialize_modules()
    assert runtime.world_clock.registrations == before


@pytest.mark.parametrize("key", [
    "citywalk", "auto_song_learner", "bili_dynamic_fetcher", "diary",
    "qq_music_credential_refresh", "dynamic_interaction",
])
def test_disabled_optional_family_is_not_registered(make_runtime, world_config, key):
    config = enable_all(world_config)
    config[key]["enabled"] = False
    runtime = make_runtime(config)
    names = set(runtime.world_clock.actions)
    prefix = TASKS[key][1]
    assert not any(name == prefix or name.startswith(prefix + ":") for name in names)
    if key == "auto_song_learner":
        assert "qq_music_credential_refresh" not in names
    assert "purge_expired_events" in names


@pytest.mark.parametrize("key", ["citywalk", "auto_song_learner", "bili_dynamic_fetcher", "diary"])
def test_character_override_disables_only_selected_character(make_runtime, world_config, key):
    config = enable_all(world_config)
    config[key]["characters"] = {"miku": {"enabled": False}}
    names = make_runtime(config).world_clock.actions
    prefix = TASKS[key][1]
    assert f"{prefix}:luotianyi" in names
    assert f"{prefix}:miku" not in names


def test_singing_managers_and_bili_uid_mapping_limit_character_expansion(make_runtime, world_config):
    config = enable_all(world_config)
    config["bili_dynamic_fetcher"]["bilibili_uids"] = {"miku": "2"}
    runtime = make_runtime(config, managers=("luotianyi",))
    names = runtime.world_clock.actions
    assert "learn_sing_songs:luotianyi" in names
    assert "learn_sing_songs:miku" not in names
    assert "bili_event_update:miku" in names
    assert "bili_event_update:luotianyi" not in names
    assert runtime.bili_event_update_task.config["bilibili_uids"] == {"miku": "2"}
    names = make_runtime(config, managers=()).world_clock.actions
    assert not any(name.startswith("learn_sing_songs:") for name in names)
    assert "qq_music_credential_refresh" not in names


def test_clock_config_overrides_reach_registration(make_runtime, world_config):
    config = enable_all(world_config)
    config["citywalk"]["clock_config"] = {"type": "daily", "params": {"hour": 4, "minute": 5}}
    config["proactive_topic_check"]["clock_config"] = {
        "type": "interval", "params": {"interval_seconds": 120, "run_immediately": True},
    }
    actions = make_runtime(config).world_clock.actions
    assert actions["try_citywalk:luotianyi"][:2] == ("daily", {"hour": 4, "minute": 5})
    assert actions["proactive_topic_check"][:2] == (
        "interval", {"interval_seconds": 120, "run_immediately": True},
    )


def test_unconditional_tasks_remain_registered_with_disabled_flag(make_runtime, world_config):
    config = enable_all(world_config)
    for key in ("song_knowledge", "proactive_topic_check", "expired_event_cleanup"):
        config[key]["enabled"] = False
    names = make_runtime(config).world_clock.actions
    assert {"sync_new_song_knowledge", "proactive_topic_check", "purge_expired_events"} <= names.keys()


@pytest.mark.asyncio
async def test_holidays_are_startup_initialization_not_a_clock_action(make_runtime, world_config):
    initialized = asyncio.Event()

    async def ensure_holidays():
        initialized.set()
        await asyncio.Future()

    runtime = make_runtime(enable_all(world_config), event_store=SimpleNamespace(ensure_holidays=ensure_holidays))
    assert not initialized.is_set()
    names = list(runtime.world_clock.registrations)
    runtime.start_background_services()
    try:
        await asyncio.wait_for(initialized.wait(), 1)
        assert runtime.world_clock.started
        assert runtime.world_clock.registrations == names
        assert "ensure_holidays" not in names
    finally:
        await runtime.stop_background_services()
    assert not runtime.world_clock.started


@pytest.mark.asyncio
async def test_runtime_propagates_clock_shutdown_failure(make_runtime, world_config):
    runtime = make_runtime(world_config)
    runtime.world_clock.stop_error = RuntimeError("world task still stopping")
    with pytest.raises(RuntimeError, match="still stopping"):
        await runtime.stop_background_services()
    runtime.world_clock.stop_error = None
    await runtime.stop_background_services()
