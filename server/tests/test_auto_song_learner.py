import json
import os
import subprocess
import sys
from pathlib import Path


cwd = os.getcwd()
sys.path.insert(0, str(cwd))

from src.plugins.music import auto_song_learner as asl


class DummyLogger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        print(message)
        self.messages.append(("info", message))

    def warning(self, message):
        print(message)
        self.messages.append(("warning", message))

    def error(self, message):
        print(message)
        self.messages.append(("error", message))


def _create_songlearner_resources(base_dir: Path) -> tuple[Path, Path]:

    return r"E:\Agent-LuoTianyi\server\src\plugins\music\song_learner", r"E:\Agent-LuoTianyi\server\res\song_learner"


def _ensure_only_pending_song(learner: asl.AutoSongLearner, song_name: str) -> None:
    unified_name = asl.get_unified_song_name(song_name)

    for key in list(learner.wishlist.wished_songs.keys()):
        entry = learner.wishlist.wished_songs[key]
        if key != unified_name and entry.status == "abandoned":
            learner.wishlist.wished_songs.pop(key, None)

    learner.wishlist.wished_songs[unified_name] = asl.WishEntry(
        safe_name=song_name,
        unified_name=unified_name,
        status="pending",
        request_count=1,
        attempt_count=0,
        first_requested="2026-05-08",
    )
    learner.wishlist._save()


def test_wishlist_manager_public_interfaces(tmp_path):
    logger = DummyLogger()
    metadata_path = tmp_path / "metadata.json"
    manager = asl.WishlistManager(str(metadata_path), logger)

    assert manager.get_all() == {}
    assert manager.get_pending() == []

    assert manager.add("不停歇的旅途") is True
    assert manager.add("不停歇的旅途") is False
    assert manager.add("待同步的旅途") is True

    all_entries = manager.get_all()
    assert set(all_entries) == {"不停歇的旅途", "待同步的旅途"}
    assert all_entries["不停歇的旅途"].request_count == 2
    assert all_entries["不停歇的旅途"].status == "pending"

    manager.mark_awaiting_audio("不停歇的旅途", reason="缺少音频")
    awaiting_entry = manager.get_all()["不停歇的旅途"]
    assert awaiting_entry.status == "awaiting_audio"
    assert awaiting_entry.attempt_count == 1
    assert awaiting_entry.failure_reason == "缺少音频"
    assert awaiting_entry.last_attempt

    pending_names = {entry.safe_name for entry in manager.get_pending()}
    assert pending_names == {"不停歇的旅途", "待同步的旅途"}

    assert manager.add("已放弃的旅途") is True

    manager.mark_abandoned("已放弃的旅途", reason="多次失败")
    abandoned_entry = manager.get_all()["已放弃的旅途"]
    assert abandoned_entry.status == "abandoned"
    assert abandoned_entry.attempt_count == 1
    assert abandoned_entry.failure_reason == "多次失败"

    manager.sync_existing_songs({"待同步的旅途"})
    synced_entry = manager.get_all()["待同步的旅途"]
    assert synced_entry.status == "learned"
    assert synced_entry.learned_date

    manager.mark_learned("不停歇的旅途")
    learned_entry = manager.get_all()["不停歇的旅途"]
    assert learned_entry.status == "learned"
    assert learned_entry.learned_date

    recently_learned = set(manager.get_recently_learned())
    assert recently_learned == {"不停歇的旅途"}
    assert manager.get_recently_learned() == []


def test_try_learn_pending_learns_butingxiedelvtu(tmp_path, monkeypatch):
    songlearner_dir, songlearner_resource_dir = _create_songlearner_resources(tmp_path)
    resource_path = os.getcwd() + os.sep + "res" + os.sep + "music"

    logger = DummyLogger()
    monkeypatch.setattr(asl, "get_logger", lambda name: logger)

    learned_notifications = []

    def fake_notify(self, learned):
        learned_notifications.extend(learned)

    monkeypatch.setattr(asl.AutoSongLearner, "_notify_new_songs", fake_notify)

    learner = asl.AutoSongLearner(
        config={
            "resource_path": str(resource_path),
            "songlearner_dir": str(songlearner_dir),
            "songlearner_resource_dir": str(songlearner_resource_dir),
        }
    )

    assert learner.songlearner_available is True

    song_name = "不停歇的旅途"
    assert learner.wishlist.add(song_name) is True

    def fake_run(cmd, cwd, capture_output, text, encoding, errors, timeout, env):
        assert cmd[2] == song_name

        output_dir = learner.songs_dir / song_name
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{song_name}.cleaned.mp3").write_bytes(b"fake mp3 data")
        (output_dir / f"{song_name}.json").write_text(
            json.dumps({"title": "", "segments": []}, ensure_ascii=False),
            encoding="utf-8",
        )

        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(asl.subprocess, "run", fake_run)

    result = learner.try_learn_pending()

    assert result.learned == [song_name]
    assert result.abandoned == []
    assert result.awaiting == []
    assert learned_notifications == [song_name]

    learned_entry = learner.wishlist.get_all()[song_name]
    assert learned_entry.status == "learned"
    assert learned_entry.learned_date

    target_dir = learner.songs_dir / song_name
    json_path = target_dir / f"{song_name}.json"
    assert json_path.exists()

    saved_json = json.loads(json_path.read_text(encoding="utf-8"))
    assert saved_json["title"] == song_name
    assert saved_json["description"] == f"洛天依演唱的歌曲《{song_name}》"
    assert (target_dir / f"{song_name}.cleaned.mp3").exists()


def test_try_learn_pending_real_learner_single_pending_song(tmp_path, monkeypatch):
    songlearner_dir, songlearner_resource_dir = _create_songlearner_resources(tmp_path)
    resource_path = os.getcwd() + os.sep + "res" + os.sep + "music"

    logger = DummyLogger()
    monkeypatch.setattr(asl, "get_logger", lambda name: logger)

    learner = asl.AutoSongLearner(
        config={
            "resource_path": str(resource_path),
            "songlearner_dir": str(songlearner_dir),
            "songlearner_resource_dir": str(songlearner_resource_dir),
        }
    )

    assert learner.songlearner_available is True

    song_name = "不停歇的旅途"
    _ensure_only_pending_song(learner, song_name)

    learned_notifications = []

    def fake_notify(self, learned):
        learned_notifications.extend(learned)

    monkeypatch.setattr(asl.AutoSongLearner, "_notify_new_songs", fake_notify)

    result = learner.try_learn_pending()

    assert result.learned == [song_name]
    assert result.abandoned == []
    assert result.awaiting == []
    assert learned_notifications == [song_name]

    learned_entry = learner.wishlist.get_all()[song_name]
    assert learned_entry.status == "learned"
    assert learned_entry.learned_date

    target_dir = learner.songs_dir / song_name
    json_path = target_dir / f"{song_name}.json"
    assert json_path.exists()

    saved_json = json.loads(json_path.read_text(encoding="utf-8"))
    assert saved_json["title"] == song_name
    assert saved_json["description"] == f"洛天依演唱的歌曲《{song_name}》"