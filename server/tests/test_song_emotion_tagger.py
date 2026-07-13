import sys
from pathlib import Path

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

import pytest

from src.capabilities.singing.song_emotion_tagger import SongEmotionTagger
from src.capabilities.singing.singing import SingingCapability
from src.capabilities.singing.singing_manager import SingingManager
from src.domain.music_type import SongMetadata, SongSegment


class FakeEmotionLLM:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def generate_response(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def test_song_emotion_tags_are_normalized_and_restricted():
    tags = SongEmotionTagger.parse_tags(
        '{"emotion_tags":["温柔", "温柔", "无关标签", "帅气"]}'
    )

    assert tags == ["温柔", "帅气"]


@pytest.mark.asyncio
async def test_song_emotion_tagger_uses_distinct_modes():
    llm = FakeEmotionLLM('{"emotion_tags":["积极"]}')
    tagger = SongEmotionTagger()
    tagger.llm = llm

    assert await tagger.tag_song("测试歌", "歌词") == ["积极"]
    assert await tagger.infer_target_tags("最近对话") == ["积极"]
    assert llm.calls[0]["mode"] == "tag_song"
    assert llm.calls[1]["mode"] == "infer_target"


def _metadata(name: str, tags: list[str]) -> SongMetadata:
    return SongMetadata(
        song_name=name,
        title=name,
        description="",
        song_path="song.mp3",
        lrc_path="song.lrc",
        lrc_offset=0,
        segments=[SongSegment("段落1", 0, 1, [])],
        emotion_tags=tags,
    )


def test_random_selection_prefers_matching_emotion_tags():
    manager = SingingManager.__new__(SingingManager)
    manager.all_songs = {
        "帅气歌": _metadata("帅气歌", ["帅气"]),
        "温柔歌": _metadata("温柔歌", ["温柔"]),
    }
    manager.song_aliases = {}

    def fake_pick(song_name, excluded_segments=None):
        return song_name, "段落1"

    manager.pick_segment_for_song = fake_pick

    song, segment = manager.pick_random_song_and_segment(target_emotion_tags=["帅气"])

    assert (song, segment) == ("帅气歌", "段落1")


@pytest.mark.asyncio
async def test_random_singing_generates_target_tags_from_context(monkeypatch):
    capability = SingingCapability.__new__(SingingCapability)
    capability.default_character_id = "luotianyi"
    manager = SingingManager.__new__(SingingManager)
    manager.all_songs = {}
    manager.song_aliases = {}
    captured = {}

    def fake_pick(**kwargs):
        captured.update(kwargs)
        return "帅气歌", "段落1"

    manager.pick_random_song_and_segment = fake_pick
    capability.singing_manager = {"luotianyi": manager}

    class FakeTagger:
        async def infer_target_tags(self, context):
            captured["context"] = context
            return ["帅气"]

    capability.song_emotion_tagger = FakeTagger()

    result = await capability.build_sing_plan(
        "luotianyi",
        ["random_song"],
        emotion_context="当前话题：庆祝比赛胜利",
    )

    assert result == ("帅气歌", "段落1")
    assert captured["context"] == "当前话题：庆祝比赛胜利"
    assert captured["target_emotion_tags"] == ["帅气"]
