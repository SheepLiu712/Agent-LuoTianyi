"""未知歌曲愿望单只能由确认后的唱歌意图写入。"""

from types import SimpleNamespace

import pytest

from src.agent.skills.expression.singing.backend import SingingBackend


class _Manager:
    def __init__(self):
        self.wished_songs = []

    def pick_segment_for_song(self, song_name, *, excluded_segments=None):
        return song_name, None

    def add_wished_song(self, song_name):
        self.wished_songs.append(song_name)


@pytest.mark.asyncio
async def test_unknown_song_wishlist_requires_confirmed_intent():
    manager = _Manager()
    backend = object.__new__(SingingBackend)
    backend.default_character_id = "luotianyi"
    backend.singing_manager = {"luotianyi": manager}
    backend.song_emotion_tagger = SimpleNamespace()

    assert await backend.build_sing_plan("luotianyi", ["未知歌曲"]) == ("未知歌曲", None)
    assert manager.wished_songs == []

    assert await backend.build_sing_plan("luotianyi", ["未知歌曲"], confirmed_intent=True) == (
        "未知歌曲",
        None,
    )
    assert manager.wished_songs == ["未知歌曲"]
