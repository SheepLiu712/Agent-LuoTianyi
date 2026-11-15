import json
import wave
from pathlib import Path

from src.agent.skills.expression.singing.manager import SingingManager
from src.domain.music_type import SongSegment
from src.infrastructure.media.song_asset_validation import playable_segments


def write_song(root: Path, name: str, segments: list[dict]) -> Path:
    song_dir = root / "songs" / name
    song_dir.mkdir(parents=True)
    with wave.open(str(song_dir / f"{name}.mp3"), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x01\x00" * 16000)
    (song_dir / f"{name}.lrc").write_text("[00:00.00]歌词", encoding="utf-8")
    (song_dir / f"{name}.json").write_text(
        json.dumps({"title": name, "segments": segments}, ensure_ascii=False), encoding="utf-8"
    )
    return song_dir


def test_song_catalog_advertises_only_segments_that_can_render(tmp_path):
    good = {"description": "副歌", "start_time": 0.1, "end_time": 1.0, "lyrics": []}
    invalid = [
        {"description": "空片段", "start_time": 1, "end_time": 1, "lyrics": []},
        {"description": "越界", "start_time": 1, "end_time": 3, "lyrics": []},
        {"description": "缺时间", "start_time": None, "end_time": 1, "lyrics": []},
        {"description": "坏歌词", "start_time": 0, "end_time": 1, "lyrics": [{"duration": "bad"}]},
    ]
    write_song(tmp_path, "部分可唱", [good, *invalid])
    write_song(tmp_path, "完全不可唱", invalid)

    manager = SingingManager({"resource_path": str(tmp_path)})

    assert manager.can_i_sing_song("部分可唱") == ("部分可唱", ["副歌"])
    assert manager.can_i_sing_song("完全不可唱") == ("", [])
    assert manager.get_songs_can_sing() == {"部分可唱": ""}
    assert manager.get_song_segment("部分可唱", "越界") == (None, None)
    _, audio = manager.get_song_segment("部分可唱", "副歌")
    assert audio is not None and audio[:4] == b"RIFF"

    manager.get_song_metadata("部分可唱").segments = [SongSegment("越界", 2.1, 3, [])]
    assert manager.can_i_sing_song("部分可唱") == ("", [])
    assert manager.get_songs_can_sing() == {}


def test_asset_validation_rejects_duplicate_and_missing_audio(tmp_path):
    song_dir = write_song(
        tmp_path,
        "歌曲",
        [
            {"description": "同名", "start_time": 0, "end_time": 1, "lyrics": []},
            {"description": "同名", "start_time": 1, "end_time": 2, "lyrics": []},
        ],
    )
    audio_path = song_dir / "歌曲.mp3"
    config = json.loads((song_dir / "歌曲.json").read_text(encoding="utf-8"))

    assert [segment.description for segment in playable_segments(config["segments"], audio_path)] == ["同名"]
    audio_path.unlink()
    assert playable_segments(config["segments"], audio_path) == []


def test_underestimated_mp3_duration_preserves_tail_and_rendering(tmp_path, monkeypatch):
    from src.infrastructure.media import song_asset_validation

    write_song(tmp_path, "尾段", [{"description": "结尾", "start_time": 1.5, "end_time": 2, "lyrics": []}])
    monkeypatch.setattr(song_asset_validation, "mediainfo", lambda _: {"duration": "1.2"})
    manager = SingingManager({"resource_path": str(tmp_path)})
    assert manager.can_i_sing_song("尾段") == ("尾段", ["结尾"])
    _, audio = manager.get_song_segment("尾段", "结尾")
    assert manager.get_song_metadata("尾段").segments[0].end_time == 2
    assert audio is not None


def test_true_tail_overrun_clips_audio_and_lyrics_but_not_outside_start(tmp_path):
    segments = [
        {
            "description": "结尾",
            "start_time": 1,
            "end_time": 3,
            "lyrics": [{"duration": 0.5, "content": "保留"}, {"duration": 1.5, "content": "尾句"}],
        }
    ]
    directory = write_song(tmp_path, "截断", segments)
    valid = playable_segments(segments, directory / "截断.mp3")
    assert valid[0].end_time == 2
    assert [line.duration for line in valid[0].lyrics] == [0.5, 0.5]
    segments[0]["start_time"] = 2.1
    assert playable_segments(segments, directory / "截断.mp3") == []


def test_unfinished_learning_is_not_reported_as_broken_song(tmp_path, monkeypatch):
    directory = write_song(tmp_path, "未完成", [])
    (directory / "未完成.json").unlink()
    (directory / "workflow_status.json").write_text('{"generate_song_json": false}', encoding="utf-8")
    from unittest.mock import Mock

    from src.agent.skills.expression.singing import manager as module

    logger = Mock()
    monkeypatch.setattr(module, "get_logger", lambda _: logger)
    manager = SingingManager({"resource_path": str(tmp_path)})
    assert manager.get_songs_can_sing() == {}
    logger.warning.assert_not_called()
    (directory / "workflow_status.json").unlink()
    manager.reload_songs()
    assert any("Config file missing" in str(call) for call in logger.warning.call_args_list)


def test_verified_duration_survives_restart_and_invalidates_when_audio_changes(tmp_path, monkeypatch):
    from src.infrastructure.media import song_asset_validation as validation

    directory = write_song(tmp_path, "时长", [{"description": "尾段", "start_time": 1, "end_time": 2, "lyrics": []}])
    monkeypatch.setattr(validation, "mediainfo", lambda _: {"duration": "1.2"})
    SingingManager({"resource_path": str(tmp_path)})
    config = json.loads((directory / "时长.json").read_text())
    assert config["audio_duration"]["seconds"] == 2
    validation._duration_state.cache_clear()  # Simulate losing process memory on restart.
    with monkeypatch.context() as unavailable:

        def fail_decode(_):
            raise AssertionError("unchanged audio should use its persisted duration")

        unavailable.setattr(validation, "_decode_duration", fail_decode)
        manager = SingingManager({"resource_path": str(tmp_path)})
        assert manager.can_i_sing_song("时长") == ("时长", ["尾段"])
    audio_path = directory / "时长.mp3"
    with wave.open(str(audio_path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x01\x00" * 24000)
    assert validation.audio_duration_seconds(audio_path, exact=True, metadata=config) == 3
    assert config["audio_duration"]["seconds"] == 3
