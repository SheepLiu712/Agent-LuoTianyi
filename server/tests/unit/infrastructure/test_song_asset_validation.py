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

    manager.get_song_metadata("部分可唱").segments = [SongSegment("越界", 1, 3, [])]
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
