import sys
from pathlib import Path
from types import SimpleNamespace

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

import src.world.world_runtime as world_runtime_module
from src.world.world_runtime import WorldRuntime


class FakeClock:
    def __init__(self):
        self.actions = []

    def register_daily_action(self, *args, **kwargs):
        self.actions.append(("daily", args, kwargs))

    def register_interval_action(self, *args, **kwargs):
        self.actions.append(("interval", args, kwargs))


class FakeTask:
    def __init__(self, config=None):
        self.config = config or {}
        self.name = self.__class__.__name__
        self.task_name = self.name
        self.clock_config = self.config.get("clock_config", {})
        self.initialized_with = None

    def initialize(self, runtime):
        self.initialized_with = runtime

    def run_once(self):
        return None

    def get_task_type(self):
        return self.clock_config.get("type", "interval")

    def get_task_params(self):
        return self.clock_config.get("params", {})

    def get_task_name(self):
        return self.name


def test_world_runtime_distributes_task_config_from_world_section(monkeypatch):
    monkeypatch.setattr(world_runtime_module, "CitywalkTask", FakeTask)
    monkeypatch.setattr(world_runtime_module, "LearnSingSongsTask", FakeTask)
    monkeypatch.setattr(world_runtime_module, "VCPediaNewSongTask", FakeTask)
    monkeypatch.setattr(world_runtime_module, "BiliEventUpdateTask", FakeTask)
    monkeypatch.setattr(world_runtime_module, "ProactiveTopicCheckTask", FakeTask)
    monkeypatch.setattr(world_runtime_module, "ExpiredEventCleanupTask", FakeTask)

    world_config = {
        "citywalk": {"source": "world-citywalk"},
        "auto_song_learner": {"source": "world-learner"},
        "song_knowledge": {"source": "world-song-knowledge"},
        "bili_dynamic_fetcher": {"source": "world-bili", "fetch_interval_hours": 6},
        "proactive_topic_check": {"source": "world-proactive"},
        "expired_event_cleanup": {"source": "world-cleanup"},
    }
    runtime = WorldRuntime(
        config=world_config,
    )
    runtime.world_clock = FakeClock()
    system_runtime = SimpleNamespace(database_manager=SimpleNamespace(event_store=None))
    runtime.set_system_runtime(system_runtime)

    runtime.initialize_modules()

    assert runtime.citywalk_task.config == {"source": "world-citywalk"}
    assert runtime.learn_sing_songs_task.config == {"source": "world-learner"}
    assert runtime.vcpedia_new_song_task.config == {"source": "world-song-knowledge"}
    assert runtime.bili_event_update_task.config["source"] == "world-bili"
    assert runtime.proactive_topic_check_task.config == {"source": "world-proactive"}
    assert runtime.expired_event_cleanup_task.config == {"source": "world-cleanup"}
    assert runtime.citywalk_task.initialized_with is system_runtime
    assert runtime.learn_sing_songs_task.initialized_with is system_runtime
    assert runtime.vcpedia_new_song_task.initialized_with is system_runtime
    assert runtime.bili_event_update_task.initialized_with is system_runtime


def test_world_runtime_registers_clock_actions_from_task_clock_config():
    runtime = WorldRuntime(config={})
    runtime.world_clock = FakeClock()

    def make_task(name, clock_config):
        task = FakeTask({"clock_config": clock_config})
        task.name = name
        task.task_name = name
        return task

    daily_task = make_task("daily_task", {"type": "daily", "params": {"hour": 4, "minute": 5}})
    interval_task = make_task(
        "interval_task",
        {"type": "interval", "params": {"interval_seconds": 120, "run_immediately": True}},
    )
    runtime.tasks = [daily_task, interval_task]

    runtime._register_clock_actions()

    assert ("daily", ("daily_task", 4, 5, daily_task.run_once), {}) in runtime.world_clock.actions
    assert (
        "interval",
        ("interval_task",),
        {"interval_seconds": 120, "action": interval_task.run_once, "run_immediately": True},
    ) in runtime.world_clock.actions
