import json
import wave

import pytest

from src.world.learn_sing_songs.song_learner.src.pipeline.make_song_json import generate_song_json


def song_files(tmp_path, lrc):
    directory = tmp_path / "歌曲"
    directory.mkdir()
    with wave.open(str(directory / "歌曲.cleaned.mp3"), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x01\x00" * 16000)
    (directory / "歌曲.lrc").write_text(lrc, encoding="utf-8")
    (directory / "歌曲.llm.lrc").write_text("尾句", encoding="utf-8")
    return directory


@pytest.mark.parametrize("lrc", ["[00:01.00]尾句\n[00:03.00]", "[00:01.00]尾句"])
def test_generated_tail_ends_at_real_audio_end(tmp_path, lrc):
    directory = song_files(tmp_path, lrc)
    result = json.loads(generate_song_json(directory).read_text())
    assert result["segments"][0]["end_time"] == 2
    assert result["segments"][0]["lyrics"] == [{"duration": 1, "content": "尾句"}]


def test_unrecoverable_lyrics_do_not_publish_song_json(tmp_path):
    directory = song_files(tmp_path, "[00:03.00]尾句\n[00:04.00]")
    with pytest.raises(ValueError, match="歌词起点超出音频"):
        generate_song_json(directory)
    assert not (directory / "歌曲.json").exists()


@pytest.mark.parametrize("lrc", ["普通歌词没有时间戳", "[00:00:00]此歌曲为没有填词的纯音乐，请您欣赏"])
def test_missing_lyric_timeline_fails_before_llm_segmentation(tmp_path, lrc):
    from src.world.learn_sing_songs.song_learner.src.pipeline.make_clear_lrc import generate_clear_lrc

    directory = song_files(tmp_path, lrc)
    (directory / "boundary_inst.txt").write_text("00:00.00\n00:02.00", encoding="utf-8")
    with pytest.raises(ValueError, match="没有带有效时间戳的歌词"):
        generate_clear_lrc(directory)
    assert not (directory / "歌曲.clear.lrc").exists()
