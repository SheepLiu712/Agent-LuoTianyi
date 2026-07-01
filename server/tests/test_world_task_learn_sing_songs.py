import os
import sys
from pathlib import Path
from types import SimpleNamespace

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.world.learn_sing_songs.task import LearnSingSongsTask
from src.world.learn_sing_songs.auto_song_learner import AutoSongLearner, WishlistManager


class FakeEventStore:
    def __init__(self):
        self.events = []

    async def add_event(self, event):
        self.events.append(event)
        return "event-id"


def test_learn_sing_songs_initialize_sets_event_store_and_learner(monkeypatch):
    task = LearnSingSongsTask({})
    learner = object()
    monkeypatch.setattr(task, "_build_auto_song_learner", lambda runtime: learner)
    event_store = object()
    runtime = SimpleNamespace(database_manager=SimpleNamespace(event_store=event_store))

    task.initialize(runtime)

    assert task.system_runtime is runtime
    assert task.event_store is event_store
    assert task.auto_song_learner is learner


def test_learn_sing_songs_build_learner_skips_without_wishlist():
    task = LearnSingSongsTask({})
    runtime = SimpleNamespace(capability_manager=SimpleNamespace(singing=SimpleNamespace(singing_manager={})))

    learner = task._build_auto_song_learner(runtime)

    assert learner is None
    assert "wishlist" in task._init_error


def test_learn_sing_songs_run_once_skips_without_learner():
    task = LearnSingSongsTask({})
    task._init_error = "missing learner"

    result = task.run_once()

    assert result.ok is True
    assert result.skipped is True
    assert result.message == "missing learner"


def test_learn_sing_songs_run_once_records_result_without_learned():
    learner = SimpleNamespace(
        check_qq_credential=lambda: True,
        try_learn_pending=lambda: SimpleNamespace(learned=[], abandoned=["A"], awaiting=["B"]),
    )
    task = LearnSingSongsTask({})
    task.auto_song_learner = learner

    result = task.run_once()

    assert result.ok is True
    assert result.data["credential_ok"] is True
    assert result.data["learned"] == []
    assert result.data["abandoned"] == ["A"]
    assert result.data["awaiting"] == ["B"]


def test_learn_sing_songs_run_once_writes_event_for_learned_songs():
    learner = SimpleNamespace(
        check_qq_credential=lambda: False,
        try_learn_pending=lambda: SimpleNamespace(learned=["Song A", "Song B"], abandoned=[], awaiting=[]),
    )
    event_store = FakeEventStore()
    task = LearnSingSongsTask({})
    task.auto_song_learner = learner
    task.event_store = event_store

    result = task.run_once()

    assert result.ok is True
    assert result.data["credential_ok"] is False
    assert event_store.events
    event = event_store.events[0]
    assert event["event_type"] == "new_song"
    assert event["source"] == "world_song_learner"
    assert "Song A" in event["description"]


def test_learn_sing_songs_write_learned_event_skips_without_store():
    task = LearnSingSongsTask({})

    import asyncio

    asyncio.run(task._write_learned_event(["Song A"]))


def test_auto_song_learner_builds_child_pythonpath(monkeypatch, tmp_path):
    monkeypatch.setattr(AutoSongLearner, "_check_songlearner_models", lambda self: True)
    monkeypatch.setattr(AutoSongLearner, "_validate_qq_credential", lambda self: True)
    monkeypatch.chdir(Path(__file__).resolve().parent.parent)

    wishlist = WishlistManager(str(tmp_path / "metadata.json"), SimpleNamespace(info=lambda *_: None, warning=lambda *_: None))
    learner = AutoSongLearner(
        {
            "resource_path": str(tmp_path / "music"),
            "songlearner_resource_dir": str(tmp_path / "song_learner_res"),
        },
        wishlist,
    )

    env = learner._build_songlearner_env()
    pythonpath_parts = env["PYTHONPATH"].split(os.pathsep)

    assert learner.resource_path == tmp_path / "music"
    assert str(Path(__file__).resolve().parent.parent) in pythonpath_parts
    assert str(learner.songlearner_dir / "src") in pythonpath_parts
    assert pythonpath_parts[:2] == [
        str(learner.songlearner_dir / "src"),
        str(Path(__file__).resolve().parent.parent),
    ]
