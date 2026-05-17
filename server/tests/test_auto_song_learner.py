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
"""
Unit tests for auto_song_learner.py

Tests focus on:
  - WishlistManager: persistence, CRUD, v1→v2 migration
  - AutoSongLearner: path traversal guard, routing, LRC parsing, auto-segmentation
  - Utility functions: _segment_labels
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

# Ensure src is importable
cwd = os.getcwd()
if cwd not in sys.path:
    sys.path.insert(0, cwd)

import pytest

from src.plugins.music.auto_song_learner import (
    AutoSongLearner,
    WishlistManager,
    LearnResult,
    _segment_labels,
)


# =========================================================================
# _segment_labels
# =========================================================================

class TestSegmentLabels:
    def test_1_segment(self):
        assert _segment_labels(1) == ["完整版"]

    def test_2_segments(self):
        assert _segment_labels(2) == ["前段", "后段"]

    def test_3_segments(self):
        assert _segment_labels(3) == ["前段", "中段", "后段"]

    def test_4_segments(self):
        assert _segment_labels(4) == ["前奏", "主歌", "副歌", "尾声"]

    def test_5_segments(self):
        result = _segment_labels(5)
        assert len(result) == 5
        assert result[:4] == ["第1段", "第2段", "第3段", "第4段"]
        assert result[4] == "尾声"

    def test_6_segments(self):
        result = _segment_labels(6)
        assert len(result) == 6
        assert result[0] == "第1段"
        assert result[4] == "第5段"
        assert result[5] == "尾声"

    def test_zero_segments(self):
        """Zero <= 1, so it returns ['完整版']."""
        result = _segment_labels(0)
        assert result == ["完整版"]


# =========================================================================
# WishlistManager
# =========================================================================

class TestWishlistManager:
    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as d:
            yield Path(d)

    @pytest.fixture
    def manager(self, temp_dir):
        meta_path = temp_dir / "metadata.json"
        logger = MagicMock()
        return WishlistManager(str(meta_path), logger)

    # -- basic CRUD --

    def test_add_new_song(self, manager):
        assert manager.add("万古生香") is True
        assert "万古生香" in manager.wished_songs
        assert manager.wished_songs["万古生香"].status == "pending"

    def test_add_duplicate_increments_count(self, manager):
        manager.add("万古生香")
        assert manager.add("万古生香") is False
        assert manager.wished_songs["万古生香"].request_count == 2

    def test_add_strips_brackets(self, manager):
        assert manager.add("《万古生香》") is True
        assert "万古生香" in manager.wished_songs

    def test_add_empty_returns_false(self, manager):
        assert manager.add("") is False
        assert manager.add("  ") is False

    def test_get_pending_returns_new_songs(self, manager):
        manager.add("song_a")
        manager.add("song_b")
        pending = manager.get_pending()
        assert len(pending) == 2

    def test_get_pending_excludes_learned(self, manager):
        manager.add("song_a")
        manager.mark_learned("song_a")
        pending = manager.get_pending()
        assert len(pending) == 0

    def test_get_pending_excludes_abandoned(self, manager):
        manager.add("song_a")
        manager.mark_abandoned("song_a", "too hard")
        pending = manager.get_pending()
        assert len(pending) == 0

    def test_get_pending_excludes_exhausted(self, manager):
        manager.add("song_a")
        for _ in range(3):
            manager.mark_awaiting_audio("song_a", "retry")
        pending = manager.get_pending()
        assert len(pending) == 0

    def test_mark_learned(self, manager):
        manager.add("song_a")
        manager.mark_learned("song_a")
        entry = manager.wished_songs["song_a"]
        assert entry.status == "learned"
        assert entry.learned_date is not None

    def test_mark_awaiting_audio_increments_attempts(self, manager):
        manager.add("song_a")
        manager.mark_awaiting_audio("song_a", "no audio")
        assert manager.wished_songs["song_a"].attempt_count == 1
        assert manager.wished_songs["song_a"].status == "awaiting_audio"

    def test_mark_abandoned(self, manager):
        manager.add("song_a")
        manager.mark_abandoned("song_a", "too hard")
        assert manager.wished_songs["song_a"].status == "abandoned"
        assert manager.wished_songs["song_a"].attempt_count == 1

    def test_get_recently_learned(self, manager):
        manager.add("song_a")
        manager.mark_learned("song_a")
        result = manager.get_recently_learned()
        assert "song_a" in result
        # second call should return empty
        assert manager.get_recently_learned() == []

    def test_get_all(self, manager):
        manager.add("a")
        manager.add("b")
        all_songs = manager.get_all()
        assert set(all_songs.keys()) == {"a", "b"}

    def test_sync_existing_songs(self, manager):
        manager.add("song_a")
        manager.sync_existing_songs({"song_a", "song_b"})
        assert manager.wished_songs["song_a"].status == "learned"
        # song_b wasn't wished, so nothing to mark

    # -- persistence --

    def test_persist_and_reload(self, temp_dir):
        meta_path = temp_dir / "metadata.json"
        logger = MagicMock()

        # Create and add data
        m1 = WishlistManager(str(meta_path), logger)
        m1.add("song_a")
        m1.add("song_b")
        m1.mark_learned("song_a")

        # Create new instance (reloads from file)
        m2 = WishlistManager(str(meta_path), logger)
        assert "song_a" in m2.wished_songs
        assert "song_b" in m2.wished_songs
        assert m2.wished_songs["song_a"].status == "learned"

    def test_v1_to_v2_migration(self, temp_dir):
        """v1 used flat list, v2 uses dict of WishEntry."""
        meta_path = temp_dir / "metadata.json"
        v1_data = {"wished_songs": ["song_a", "song_b"], "recently_learned": []}
        meta_path.write_text(json.dumps(v1_data, ensure_ascii=False), encoding="utf-8")

        logger = MagicMock()
        manager = WishlistManager(str(meta_path), logger)
        assert "song_a" in manager.wished_songs
        assert "song_b" in manager.wished_songs
        assert manager.wished_songs["song_a"].status == "pending"

    def test_corrupted_json_starts_fresh(self, temp_dir):
        meta_path = temp_dir / "metadata.json"
        meta_path.write_text("not json", encoding="utf-8")
        logger = MagicMock()
        manager = WishlistManager(str(meta_path), logger)
        assert manager.wished_songs == {}

    def test_mark_on_nonexistent_song_does_nothing(self, manager):
        manager.mark_learned("nonexistent")
        manager.mark_awaiting_audio("nonexistent", "reason")
        manager.mark_abandoned("nonexistent", "reason")
        # No exception should be raised


# =========================================================================
# AutoSongLearner
# =========================================================================

class TestAutoSongLearner:
    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as d:
            yield Path(d)

    @pytest.fixture
    def learner(self, temp_dir):
        """Create AutoSongLearner with isolated paths, Songlearner unavailable."""
        music_dir = temp_dir / "res/music"
        music_dir.mkdir(parents=True)
        # Point songlearner_dir to a nonexistent path so models won't be found
        return AutoSongLearner(config={
            "resource_path": str(music_dir),
            "songlearner_dir": str(temp_dir / "songlearner"),
        })

    def test_init_creates_directories(self, temp_dir):
        music_dir = temp_dir / "res/music"
        learner = AutoSongLearner(config={
            "resource_path": str(music_dir),
            "songlearner_dir": str(temp_dir / "songlearner"),
        })
        assert (music_dir / "songs").exists()
        assert (music_dir / "staging").exists()

    def test_songlearner_available_false_when_models_missing(self, temp_dir):
        music_dir = temp_dir / "res/music"
        music_dir.mkdir(parents=True)
        learner = AutoSongLearner(config={
            "resource_path": str(music_dir),
            "songlearner_dir": str(temp_dir / "songlearner"),
        })
        assert learner.songlearner_available is False

    def test_songlearner_available_true_when_models_present(self, temp_dir):
        music_dir = temp_dir / "res/music"
        music_dir.mkdir(parents=True)

        sl_dir = temp_dir / "songlearner"
        pretrain = sl_dir / "res/msst/pretrain"
        pretrain.mkdir(parents=True)
        # Create placeholder model files
        (pretrain / "model_bs_roformer_ep_317_sdr_12.9755.ckpt").write_text("fake")
        (pretrain / "dereverb_mel_band_roformer_anvuew_sdr_19.1729.ckpt").write_text("fake")

        learner = AutoSongLearner(config={
            "resource_path": str(music_dir),
            "songlearner_dir": str(sl_dir),
        })
        assert learner.songlearner_available is True

    def test_try_learn_pending_none(self, learner):
        result = learner.try_learn_pending()
        assert len(result.learned) == 0
        assert len(result.abandoned) == 0
        assert len(result.awaiting) == 0

    def test_try_learn_pending_with_wish(self, learner):
        learner.wishlist.add("test_song")
        result = learner.try_learn_pending()
        # Without Songlearner models, falls to staging which won't find the dir
        assert "test_song" in result.awaiting or "test_song" in result.abandoned

    # -- path traversal protection --

    @pytest.mark.parametrize("malicious", [
        "../etc/passwd",
        "..\\windows\\system32",
        "foo/bar",
        "foo\\bar",
        "",
    ])
    def test_path_traversal_rejected(self, learner, malicious):
        """_try_learn_one should reject names with path separators or '..'."""
        # Force songlearner_available so it goes through routing
        learner.songlearner_available = False
        result = learner._try_learn_one(malicious)
        assert result is False

    def test_valid_safe_name_allowed(self, learner):
        """Normal names should not be blocked."""
        learner.songlearner_available = False
        # No staging dir exists so it will fail at staging check, not at traversal check
        # We just verify it doesn't return False from the traversal check
        with patch.object(learner, '_learn_via_staging', return_value=False) as mock:
            learner._try_learn_one("万古生香")
            mock.assert_called_once()

    # -- _parse_lrc_file --

    def test_parse_lrc_basic(self, learner):
        """Standard LRC format should parse correctly."""
        lrc_path = Path(tempfile.mktemp(suffix=".lrc"))
        try:
            lrc_path.write_text(
                "[00:01.00]第一句歌词\n"
                "[00:05.50]第二句歌词\n"
                "[00:10.00]第三句歌词\n",
                encoding="utf-8",
            )
            result = learner._parse_lrc_file(lrc_path)
            assert len(result) == 3
            assert result[0] == (1.0, "第一句歌词")
            assert result[1] == (5.5, "第二句歌词")
            assert result[2] == (10.0, "第三句歌词")
        finally:
            lrc_path.unlink(missing_ok=True)

    def test_parse_lrc_with_milliseconds(self, learner):
        """Support both [mm:ss.xx] and [mm:ss:xxx] variants."""
        lrc_path = Path(tempfile.mktemp(suffix=".lrc"))
        try:
            lrc_path.write_text(
                "[00:01:500]第一句\n"  # 3-digit = ms
                "[00:02:25]第二句\n",  # 2-digit = centiseconds
                encoding="utf-8",
            )
            result = learner._parse_lrc_file(lrc_path)
            # 1:500 = 1.5s, 2:25 = 2.25s
            assert len(result) == 2
            assert abs(result[0][0] - 1.5) < 0.01
            assert abs(result[1][0] - 2.25) < 0.01
        finally:
            lrc_path.unlink(missing_ok=True)

    def test_parse_lrc_sorts_by_time(self, learner):
        """Entries should be sorted by timestamp even if LRC is out of order."""
        lrc_path = Path(tempfile.mktemp(suffix=".lrc"))
        try:
            lrc_path.write_text(
                "[00:10.00]later\n"
                "[00:01.00]earlier\n",
                encoding="utf-8",
            )
            result = learner._parse_lrc_file(lrc_path)
            assert result[0][1] == "earlier"
            assert result[1][1] == "later"
        finally:
            lrc_path.unlink(missing_ok=True)

    def test_parse_lrc_empty_lines_ignored(self, learner):
        """Empty lyric text after timestamp should be skipped."""
        lrc_path = Path(tempfile.mktemp(suffix=".lrc"))
        try:
            lrc_path.write_text(
                "[00:01.00]\n"  # empty
                "[00:02.00]valid\n",
                encoding="utf-8",
            )
            result = learner._parse_lrc_file(lrc_path)
            assert len(result) == 1
            assert result[0][1] == "valid"
        finally:
            lrc_path.unlink(missing_ok=True)

    def test_parse_lrc_nonexistent_file(self, learner):
        """Missing file should return empty list, not crash."""
        result = learner._parse_lrc_file(Path("/nonexistent/file.lrc"))
        assert result == []

    def test_parse_lrc_instrumental(self, learner):
        """Valid LRC with only timestamps and no text should return empty."""
        lrc_path = Path(tempfile.mktemp(suffix=".lrc"))
        try:
            lrc_path.write_text(
                "[00:01.00] \n[00:02.00]  \n",
                encoding="utf-8",
            )
            result = learner._parse_lrc_file(lrc_path)
            assert result == []
        finally:
            lrc_path.unlink(missing_ok=True)

    # -- _auto_segment --

    def test_auto_segment_zero_duration(self, learner):
        result = learner._auto_segment("test", [(0.0, "hello")], 0)
        assert result == []

    def test_auto_segment_negative_duration(self, learner):
        result = learner._auto_segment("test", [(0.0, "hello")], -1)
        assert result == []

    def test_auto_segment_no_lyrics(self, learner):
        result = learner._auto_segment("test", [], 100)
        assert len(result) == 1
        assert result[0]["description"] == "完整版"
        assert result[0]["end_time"] == 100

    def test_auto_segment_few_lyrics(self, learner):
        """Less than 3 lines should produce a single '完整版' segment."""
        result = learner._auto_segment("test", [(0.0, "a"), (10.0, "b")], 60)
        assert len(result) == 1
        assert result[0]["description"] == "完整版"

    def test_auto_segment_normal(self, learner):
        """Normal lyrics should produce multiple segments."""
        lyrics = [(i * 10.0, f"line_{i}") for i in range(15)]
        result = learner._auto_segment("test", lyrics, 150.0)
        assert len(result) == 5  # max_segments=5
        assert len(result[0]["lyrics"]) > 0
        assert result[0]["start_time"] >= 0
        assert result[0]["end_time"] > result[0]["start_time"]

    def test_auto_segment_segment_boundaries(self, learner):
        """Check that segment boundaries are correct."""
        lyrics = [(10.0, "first"), (30.0, "second"), (50.0, "third")]
        result = learner._auto_segment("test", lyrics, 60.0, max_segments=3)
        assert len(result) == 3
        assert result[0]["description"] == "前段"
        assert result[1]["description"] == "中段"
        assert result[2]["description"] == "后段"

    def test_auto_segment_lyrics_within_bounds(self, learner):
        """Lyrics should only appear in their own segment."""
        lyrics = [(5.0, "early"), (25.0, "middle"), (45.0, "late")]
        result = learner._auto_segment("test", lyrics, 60.0, max_segments=3)
        # 3 segments of 20s each: [0-20), [20-40), [40-60)
        seg0_texts = [l["content"] for l in result[0]["lyrics"]]
        seg1_texts = [l["content"] for l in result[1]["lyrics"]]
        seg2_texts = [l["content"] for l in result[2]["lyrics"]]
        assert "early" in seg0_texts
        assert "middle" in seg1_texts
        assert "late" in seg2_texts

    # -- LearnResult --

    def test_learn_result_defaults(self):
        r = LearnResult()
        assert r.learned == []
        assert r.abandoned == []
        assert r.awaiting == []


# =========================================================================
# Integration: routing logic
# =========================================================================

class TestRouting:
    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as d:
            yield Path(d)

    def test_routes_to_staging_when_songlearner_unavailable(self, temp_dir):
        music_dir = temp_dir / "res/music"
        music_dir.mkdir(parents=True)
        learner = AutoSongLearner(config={
            "resource_path": str(music_dir),
            "songlearner_dir": str(temp_dir / "songlearner_nonexist"),
        })
        assert learner.songlearner_available is False

        with patch.object(learner, '_learn_via_staging', return_value=True) as mock:
            learner._try_learn_one("test_song")
            mock.assert_called_once_with("test_song")

    def test_routes_to_songlearner_when_available(self, temp_dir):
        music_dir = temp_dir / "res/music"
        music_dir.mkdir(parents=True)
        sl_dir = temp_dir / "sl"
        pretrain = sl_dir / "res/msst/pretrain"
        pretrain.mkdir(parents=True)
        (pretrain / "model_bs_roformer_ep_317_sdr_12.9755.ckpt").write_text("x")
        (pretrain / "dereverb_mel_band_roformer_anvuew_sdr_19.1729.ckpt").write_text("x")

        learner = AutoSongLearner(config={
            "resource_path": str(music_dir),
            "songlearner_dir": str(sl_dir),
        })
        assert learner.songlearner_available is True

        with patch.object(learner, '_learn_via_songlearner', return_value=True) as mock:
            learner._try_learn_one("test_song")
            mock.assert_called_once_with("test_song")


# =========================================================================
# Staging fallback: file copying safety
# =========================================================================

class TestStagingFallback:
    @pytest.fixture
    def learner_with_staging(self, temp_dir):
        music_dir = temp_dir / "res/music"
        music_dir.mkdir(parents=True)

        # Create staging dir with test song files
        staging = music_dir / "staging" / "test_song"
        staging.mkdir(parents=True)
        (staging / "test_song.mp3").write_text("fake mp3 content")
        (staging / "test_song.lrc").write_text(
            "[00:01.00]第一句\n[00:05.00]第二句\n[00:09.00]第三句\n"
        )

        learner = AutoSongLearner(config={
            "resource_path": str(music_dir),
            "songlearner_dir": str(temp_dir / "songlearner"),
        })
        # Mock pydub to avoid real audio loading
        mock_audio = MagicMock()
        mock_audio.duration_seconds = 10.0
        return learner, staging, mock_audio

    def test_staging_moves_to_songs(self, temp_dir):
        """After successful staging learning, files should be in songs/."""
        music_dir = temp_dir / "res/music"
        music_dir.mkdir(parents=True)
        staging = music_dir / "staging" / "test_song"
        staging.mkdir(parents=True)
        (staging / "test_song.mp3").write_text("x")
        (staging / "test_song.lrc").write_text("[00:01.00]歌词\n")

        learner = AutoSongLearner(config={
            "resource_path": str(music_dir),
            "songlearner_dir": str(temp_dir / "songlearner"),
        })
        learner.songlearner_available = False

        # Mock pydub (AudioSegment is imported inside _learn_via_staging)
        mock_audio = MagicMock()
        mock_audio.duration_seconds = 10.0
        with patch("pydub.AudioSegment") as MockAudioSegment:
            MockAudioSegment.from_file.return_value = mock_audio
            result = learner._try_learn_one("test_song")

        assert result is True
        assert (music_dir / "songs" / "test_song" / "test_song.mp3").exists()
        assert (music_dir / "songs" / "test_song" / "test_song.lrc").exists()
        assert (music_dir / "songs" / "test_song" / "test_song.json").exists()

    def test_staging_missing_dir_returns_false(self, learner_with_staging):
        learner, _, _ = learner_with_staging
        result = learner._try_learn_one("nonexistent")
        assert result is False


# =========================================================================
# _finalize_song: JSON fixes and file copying
# =========================================================================

class TestFinalizeSong:
    @pytest.fixture
    def learner_and_dirs(self, temp_dir):
        music_dir = temp_dir / "res/music"
        music_dir.mkdir(parents=True)
        learner = AutoSongLearner(config={
            "resource_path": str(music_dir),
            "songlearner_dir": str(temp_dir / "songlearner"),
        })
        src = temp_dir / "sl_output" / "test_song"
        src.mkdir(parents=True)
        (src / "test_song.cleaned.mp3").write_text("audio")
        (src / "test_song.lrc").write_text("lyrics")
        (src / "test_song.mp3").write_text("raw audio")
        # JSON without 'description'
        (src / "test_song.json").write_text(
            json.dumps({"title": "test_song", "lrc_offset": 0, "segments": []})
        )
        return learner, src, music_dir / "songs" / "test_song"

    def test_json_gets_description_added(self, learner_and_dirs):
        learner, src, target = learner_and_dirs
        result = learner._finalize_song("test_song", src)
        assert result is True

        json_path = target / "test_song.json"
        data = json.loads(json_path.read_text("utf-8"))
        assert "description" in data
        assert "洛天依" in data["description"]

    def test_fallback_to_raw_mp3(self, learner_and_dirs):
        learner, src, target = learner_and_dirs
        # Remove cleaned.mp3
        (src / "test_song.cleaned.mp3").unlink()
        # Add raw mp3
        (src / "test_song.mp3").write_text("raw audio")

        result = learner._finalize_song("test_song", src)
        assert result is True
        assert (target / "test_song.cleaned.mp3").exists()
        assert (target / "test_song.cleaned.mp3").read_text() == "raw audio"

    def test_missing_critical_files_returns_false(self, learner_and_dirs):
        learner, src, _ = learner_and_dirs
        (src / "test_song.cleaned.mp3").unlink()
        (src / "test_song.json").unlink()
        (src / "test_song.mp3").unlink()  # no fallback either

        result = learner._finalize_song("test_song", src)
        assert result is False


# =========================================================================
# temp_dir fixture
# =========================================================================

@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)
