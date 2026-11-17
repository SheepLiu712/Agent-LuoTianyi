"""两页冻结源码的当前行为回归：非空歌词及可检索关键词。

输入是 `tests/support/vcpedia_lyrics_recovery.json` 的真实页面响应。本文件不加载旧 HTML，
因此不独立证明迁移前后提取率差异，也不验证整段歌词的内容完整性。配对内容验证见
`tests/support/vcpedia_corpus/README.md`；历史数字的证据边界见
`tests/support/vcpedia_review/README.md`。歌词格式契约与关键词消费口径分别验证。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.world.get_new_songs.daily_new_song_fetcher import _split_spaced_lyrics
from src.world.get_new_songs.wikitext_parser import parse_details

FIXTURES = json.loads(
    (Path(__file__).resolve().parents[2] / "support" / "vcpedia_lyrics_recovery.json").read_text(encoding="utf-8")
)

# 历史记录中报告恢复的页面；本文件只运行当前解析器。
RECOVERED = ["乐鸣东方", "人是猫"]


@pytest.mark.parametrize("title", RECOVERED)
def test_page_without_lyrics_before_now_yields_lyrics(title):
    data = parse_details(FIXTURES[title], title)

    assert data["type"] == "Song"
    assert str(data["lyrics"]).strip(), f"{title} 的歌词仍为空"


@pytest.mark.parametrize("title", RECOVERED)
def test_recovered_lyrics_produce_keywords(title):
    """恢复出的歌词必须能产出关键词，否则检索仍然认不出这首歌。"""
    data = parse_details(FIXTURES[title], title)
    keywords = _split_spaced_lyrics(str(data["spaced_lyrics"]))

    assert len(keywords) >= 6, f"{title} 只产出 {len(keywords)} 个关键词"
    assert all(len(item) >= 6 for item in keywords)


def test_recovered_page_keywords_are_distinctive_lines():
    """抽查实际关键词，确认是歌词句而不是零散字符。"""
    data = parse_details(FIXTURES["乐鸣东方"], "乐鸣东方")
    keywords = _split_spaced_lyrics(str(data["spaced_lyrics"]))

    assert len(keywords) >= 20
    assert "何时来自云上" in keywords
