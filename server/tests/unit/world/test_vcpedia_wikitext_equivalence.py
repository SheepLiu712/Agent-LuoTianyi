"""提取行为回归：记录哪些样例保持迁移前产出、哪些按契约有意改变。

每条样例给出人工配对的 wikitext 源码、渲染 HTML、迁移前实现的产出（`before`）与本切片契约
要求的产出（`after`）；`after` 为 `None` 表示该样例不改变行为。期望值固化在这里，测试不依赖
git 历史或已删除的实现。样例是人工配对，不是真实站点采样。
"""

from __future__ import annotations

import pytest

from src.world.get_new_songs.wikitext_parser import parse_details, parse_song_titles

TITLE = "固定样例"

# (wikitext 源码, 渲染 HTML, 迁移前产出, 本切片契约产出或 None, 理由)
DIVERGENCES = [
    (
        "{{VOCALOID_Songbox|演唱=洛天依|image=cover.jpg|width=300|style=red}}\n== 简介 ==\n人物正文。",
        '<table class="moe-infobox infobox"><tr><td>演唱</td><td>洛天依</td></tr></table>'
        "<h2>简介</h2><p>人物正文。</p>",
        {"type": "Person", "infobox": {"演唱": "洛天依"}, "summary": ["人物正文。"], "lyrics": "", "spaced_lyrics": ""},
        None,
        "无变化：单列信息框与首段简介沿用原选择。",
    ),
    (
        "== 简介 ==\n正文。\n{{创作者名单|group1=PV|list1=作者}}\n=== 背景 ===\n不可追加\n"
        "== 歌词 ==\n<poem>散文<span>第一句歌词</span><span>第二句歌词（副歌）</span>尾声</poem>\n"
        "<poem>第二版本</poem>",
        "<h2>简介</h2><p>正文。</p><div><table><tr><td>PV</td><td>作者</td></tr></table></div>"
        "<h3>背景</h3><p>不可追加</p><h2>歌词</h2>"
        '<div class="poem"><p>散文<span>第一句歌词</span><span>第二句歌词（副歌）</span>尾声</p></div>'
        '<div class="poem"><p>第二版本</p></div>',
        {
            "type": "Song", "infobox": {"PV": "作者"}, "summary": ["正文。"],
            "lyrics": "第一句歌词 第二句歌词", "spaced_lyrics": "第一句歌词 第二句歌词",
        },
        {
            "type": "Song", "infobox": {}, "summary": ["正文。\n不可追加"],
            "lyrics": "散文第一句歌词\n第二句歌词（副歌）\n尾声",
            "spaced_lyrics": "散文第一句歌词\n第二句歌词（副歌）\n尾声",
        },
        "歌词保留原文行、括号与和声，不再压成一行并删括号；简介纳入同级子标题段落；"
        "该页没有歌曲框，简介里的 staff 不再并入信息框（原实现按 boxes<=1 会把首框之前的也算进去）。",
    ),
    (
        "== 简介 ==\n开头。截至现在有123次播放，45次收藏。结尾。\n== 歌词 ==\n普通正文并非poem\n"
        "<poem>甲（副歌）<br/>乙</poem>",
        "<h2>简介</h2><p>开头。截至现在有123次播放，45次收藏。结尾。</p>"
        "<h2>歌词</h2><p>普通正文并非poem</p>"
        '<div class="poem"><p>甲（副歌）<br/>乙</p></div>',
        {
            "type": "Song", "infobox": {}, "summary": ["开头。。结尾。"],
            "lyrics": "甲乙", "spaced_lyrics": "甲乙",
        },
        {
            "type": "Song", "infobox": {}, "summary": ["开头。截至现在有123次播放，45次收藏。结尾。"],
            "lyrics": "甲（副歌）\n乙", "spaced_lyrics": "甲（副歌）\n乙",
        },
        "简介不再按固定词删除统计句（统计句改由计数政策处理）；歌词保留括号，br 转为换行。",
    ),
    (
        "<poem>无标题歌词</poem>\n=== 歌词 ===\n<poem>三级标题</poem>",
        '<div class="poem"><p>无标题歌词</p></div><h3>歌词</h3><div class="poem"><p>三级标题</p></div>',
        {"type": "Person", "infobox": {}, "summary": [], "lyrics": "", "spaced_lyrics": ""},
        {"type": "Song", "infobox": {}, "summary": [""], "lyrics": "三级标题", "spaced_lyrics": "三级标题"},
        "三级标题下的歌词可识别，页面因此判为 Song（原实现只看 h2）。",
    ),
    (
        "== 歌词 ==\n<poem>旧版</poem>\n== 新版歌词 ==\n<poem>新版一\n新版二</poem>",
        '<h2>歌词</h2><div class="poem"><p>旧版</p></div>'
        '<h2>新版歌词</h2><div class="poem"><p>新版一\n新版二</p></div>',
        {
            "type": "Song", "infobox": {}, "summary": [""],
            "lyrics": "新版一 新版二", "spaced_lyrics": "新版一 新版二",
        },
        {"type": "Song", "infobox": {}, "summary": [""], "lyrics": "旧版", "spaced_lyrics": "旧版"},
        "取源码顺序的首个歌词候选，不再按标题名挑版本。",
    ),
]


@pytest.mark.parametrize("source,html,before,after,reason", DIVERGENCES)
def test_divergence_matches_the_recorded_contract(source, html, before, after, reason):
    expected = before if after is None else after

    assert parse_details(source, TITLE) == {"name": TITLE, **expected}, reason


def test_every_divergence_is_documented():
    """差异清单本身可审阅：每条都要写明理由，且至少一条是有意改变。"""
    assert all(entry[4].strip() for entry in DIVERGENCES)
    assert any(entry[3] is not None for entry in DIVERGENCES)


def test_unchanged_case_still_matches_pre_migration_output():
    """清单必须包含仍等价的样例，否则等于把所有变化都当成合理。"""
    source, _html, before, after, _reason = DIVERGENCES[0]

    assert after is None
    assert parse_details(source, TITLE) == {"name": TITLE, **before}


LIST_SOURCE = """{{Navbox|title=[[洛天依]]|group1=[[原创曲]]|list1=
[[真名|显示名*]] [[另一页|显示名]] {{lj|目标|别名}} [[殿堂曲之梦]]
[[Help:说明|说明]] [[歌曲#歌词|锚点]] [[#五月|五月]] [[2026]]
[[Category:歌曲|分类显示]] [[Template:文档|模板显示]] [[普通|首页]]
[https://example.org 外部曲] [[用户:甲]] [[正常曲]]}}"""

LIST_EXPECTED = ["显示名", "别名", "说明", "锚点", "外部曲", "用户:甲", "正常曲"]


def test_song_list_display_names_are_unchanged():
    """列表显示名不属于提取改动范围，必须与迁移前一致。"""
    assert parse_song_titles(LIST_SOURCE) == LIST_EXPECTED
