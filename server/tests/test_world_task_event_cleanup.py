import sys
from pathlib import Path
from types import SimpleNamespace

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.world.event_cleanup_task import ExpiredEventCleanupTask
from src.world.world_runtime import WorldRuntime


class FakeEventStore:
    def __init__(self, purged=0):
        self.purged = purged
        self.calls = 0

    def purge_expired_events(self):
        self.calls += 1
        return self.purged


def test_expired_event_cleanup_initialize_reads_event_store():
    event_store = FakeEventStore()
    runtime = SimpleNamespace(database_manager=SimpleNamespace(event_store=event_store))
    task = ExpiredEventCleanupTask()

    task.initialize(runtime)

    assert task.event_store is event_store


def test_expired_event_cleanup_skips_without_store():
    task = ExpiredEventCleanupTask()

    result = task.run_once()

    assert result.ok is True
    assert result.skipped is True


def test_expired_event_cleanup_purges_events():
    event_store = FakeEventStore(purged=4)
    task = ExpiredEventCleanupTask()
    task.event_store = event_store

    result = task.run_once()

    assert result.ok is True
    assert result.data["purged"] == 4
    assert event_store.calls == 1


def test_world_runtime_registers_cleanup_at_midnight():
    runtime = WorldRuntime(config={})
    actions = []

    class FakeClock:
        def register_daily_action(self, name, hour, minute, action):
            actions.append(("daily", name, hour, minute, action))

        def register_interval_action(self, name, interval_seconds, action, run_immediately=False):
            actions.append(("interval", name, interval_seconds, run_immediately, action))

    def fake_task(name, clock_config):
        return SimpleNamespace(
            task_name=name,
            run_once=lambda: None,
            get_task_name=lambda: name,
            get_task_type=lambda: clock_config["type"],
            get_task_params=lambda: clock_config["params"],
        )

    runtime.world_clock = FakeClock()
    runtime.citywalk_task = fake_task("try_citywalk", {"type": "daily", "params": {"hour": 4, "minute": 0}})
    runtime.learn_sing_songs_task = fake_task("learn_sing_songs", {"type": "daily", "params": {"hour": 4, "minute": 0}})
    runtime.vcpedia_new_song_task = fake_task("sync_new_song_knowledge", {"type": "daily", "params": {"hour": 4, "minute": 0}})
    runtime.expired_event_cleanup_task = fake_task("purge_expired_events", {"type": "daily", "params": {"hour": 0, "minute": 0}})
    runtime.tasks = [
        runtime.citywalk_task,
        runtime.learn_sing_songs_task,
        runtime.vcpedia_new_song_task,
        runtime.expired_event_cleanup_task,
    ]
    runtime._register_clock_actions()

    assert ("daily", "purge_expired_events", 0, 0, runtime.expired_event_cleanup_task.run_once) in actions
    assert ("daily", "try_citywalk", 4, 0, runtime.citywalk_task.run_once) in actions
    assert ("daily", "learn_sing_songs", 4, 0, runtime.learn_sing_songs_task.run_once) in actions
    assert ("daily", "sync_new_song_knowledge", 4, 0, runtime.vcpedia_new_song_task.run_once) in actions
