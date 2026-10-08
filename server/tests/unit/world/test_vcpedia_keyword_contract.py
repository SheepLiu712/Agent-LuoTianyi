"""关键词按空白切分、保留 6–50 字片段，不得含破坏索引格式的 "=>" 或换行。"""

from __future__ import annotations

from src.world.get_new_songs.daily_new_song_fetcher import _split_spaced_lyrics


def test_fragment_carrying_arrow_is_dropped():
    """含 "=>" 的片段会破坏 keyword=>value 索引行的格式，不得成为关键词。"""

    assert _split_spaced_lyrics("abcdef=>ghijkl") == []


def test_arrow_is_filtered_even_among_valid_fragments():
    keywords = _split_spaced_lyrics("正常片段第一  abcdef=>ghijkl  正常片段第二")

    assert keywords == ["正常片段第一", "正常片段第二"]


def test_length_bounds_are_enforced():
    assert _split_spaced_lyrics("五个字哦哦") == []
    assert _split_spaced_lyrics("六个字哦哦哦") == ["六个字哦哦哦"]
    assert _split_spaced_lyrics("字" * 51) == []
    assert _split_spaced_lyrics("字" * 50) == ["字" * 50]


def test_newlines_and_whitespace_never_survive():
    keywords = _split_spaced_lyrics("第一句歌词哦\n\r第二句歌词哦\t第三句歌词哦")

    assert keywords == ["第一句歌词哦", "第二句歌词哦", "第三句歌词哦"]
    assert all("\n" not in item and "\r" not in item and "=>" not in item for item in keywords)


def test_empty_input_returns_empty_list():
    assert _split_spaced_lyrics("") == []
    assert _split_spaced_lyrics(None) == []
