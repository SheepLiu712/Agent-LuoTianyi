"""覆盖率回归：两首在等价实现下抽不到歌词的页面，必须能抽出可检索的歌词。

固化的 wikitext 为 VCPedia 真实页面响应（`tests/support/vcpedia_lyrics_recovery.json`）。
这两个页面在迁移前的 HTML 实现下 `lyrics` 为空；本用例锁住"能取到"以及"取到的内容可用作
关键词"两件事。

说明：断言落在 `spaced_lyrics` 与关键词上，而不是"原文行数"。现存知识库里的 `lyrics`
有 99.2% 是单行去标点形态，行结构并非稳定契约；对下游有意义的是关键词（见
`docs/开发进程文档/vcpedia-keyword-baseline.md`）。
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

# 迁移前实现下 lyrics 为空的页面
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
