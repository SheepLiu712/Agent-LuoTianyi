import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.world.learn_sing_songs.task import LearnSingSongsTask
from src.world.learn_sing_songs.auto_song_learner import AutoSongLearner, WishlistManager
from src.world.learn_sing_songs.song_learner.src.pipeline.download_qq_song import (
    ensure_title_matches,
    rank_songs_by_title,
    safe_name as qq_safe_name,
)


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


def test_learn_sing_songs_build_learner_uses_manager_resource_path(monkeypatch, tmp_path):
    monkeypatch.setattr(AutoSongLearner, "_check_songlearner_models", lambda self: True)
    monkeypatch.setattr(AutoSongLearner, "_validate_qq_credential", lambda self: True)
    monkeypatch.chdir(Path(__file__).resolve().parent.parent)

    wishlist = WishlistManager(
        str(tmp_path / "metadata.json"),
        SimpleNamespace(info=lambda *_: None, warning=lambda *_: None),
    )
    manager = SimpleNamespace(
        wishlist=wishlist,
        resource_path=tmp_path / "character_music",
    )
    task = LearnSingSongsTask({"songlearner_resource_dir": str(tmp_path / "song_learner_res")})
    runtime = SimpleNamespace(
        capability_manager=SimpleNamespace(
            singing=SimpleNamespace(singing_manager={"luotianyi": manager})
        )
    )

    learner = task._build_auto_song_learner(runtime)

    assert learner is not None
    assert learner.resource_path == tmp_path / "character_music"


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
    assert event["character"] == "luotianyi"
    assert event["event_type"] == "new_song"
    assert event["source"] == "world_song_learner"
    assert "Song A" in event["description"]


def test_learn_sing_songs_run_once_reloads_singing_library_for_learned_songs():
    learner = SimpleNamespace(
        check_qq_credential=lambda: True,
        try_learn_pending=lambda: SimpleNamespace(learned=["Song A"], abandoned=[], awaiting=[]),
    )
    calls = []
    singing = SimpleNamespace(reload_songs=lambda character_id: calls.append(character_id))
    task = LearnSingSongsTask({}, character_id="luotianyi")
    task.auto_song_learner = learner
    task.system_runtime = SimpleNamespace(capability_manager=SimpleNamespace(singing=singing))

    result = task.run_once()

    assert result.ok is True
    assert calls == ["luotianyi"]


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
            "songlearner_resource_dir": str(tmp_path / "song_learner_res"),
        },
        wishlist,
        resource_path=tmp_path / "music",
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
    assert env["TEST_SONGS_DIR"] == str(learner.songs_dir)
    assert env["SONGLEARNER_RESOURCE_DIR"] == str(learner.songlearner_resource_dir)


def test_auto_song_learner_formats_structured_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(AutoSongLearner, "_check_songlearner_models", lambda self: True)
    monkeypatch.setattr(AutoSongLearner, "_validate_qq_credential", lambda self: True)
    monkeypatch.chdir(Path(__file__).resolve().parent.parent)

    wishlist = WishlistManager(str(tmp_path / "metadata.json"), SimpleNamespace(info=lambda *_: None, warning=lambda *_: None))
    learner = AutoSongLearner(
        {
            "songlearner_resource_dir": str(tmp_path / "song_learner_res"),
        },
        wishlist,
        resource_path=tmp_path / "music",
    )
    proc = subprocess.CompletedProcess(
        args=[],
        returncode=40,
        stderr="[SONGLEARNER_ERROR] code=SL040 exit_code=40 step=clean_audio message=清洗后音频不存在\n",
    )

    assert learner._format_songlearner_failure(proc) == "SL040 clean_audio: 清洗后音频不存在 (exit_code=40)"


def test_songlearner_safe_name_strips_trailing_spaces():
    assert qq_safe_name("虚拟歌舞《戏游九州》 ") == "虚拟歌舞《戏游九州》"


def test_songlearner_title_ranking_rejects_unrelated_match():
    songs = [
        {"title": "虚拟歌舞《戏游九州》"},
        {"title": "恋爱色魔法"},
    ]
    ranked = rank_songs_by_title(songs, "恋爱色魔法")

    assert ranked[0]["title"] == "恋爱色魔法"
    try:
        ensure_title_matches({"title": "虚拟歌舞《戏游九州》"}, "恋爱色魔法", songs)
    except RuntimeError as exc:
        assert "最佳标题与请求不匹配" in str(exc)
    else:
        raise AssertionError("Expected unrelated title to be rejected")
