"""其他资料/再生保持非统计分句；count 标记只用于剔除，不能成为布尔正文。"""

from __future__ import annotations

import pytest

from src.world.get_new_songs.wikitext_parser import parse_details


@pytest.mark.parametrize("field", ["其他资料", "再生"])
@pytest.mark.parametrize(
    "value,expected,is_missing",
    [
        ("发表于2026年，已重投；附[[链接|文字]]", "发表于2026年，已重投，附文字", False),
        ("播放{{BiliCount|1}}，发表于2026年；收藏{{FavCount|2}}，已重投", "发表于2026年，已重投", False),
        ("播放{{BiliCount|1}}\n收藏{{FavCount|2}}", None, False),
        ("{{BiliCount|1}}", None, False),
        ("", None, True),
        (" \n ", None, True),
    ],
)
def test_information_fields_keep_content_and_missing_status(field, value, expected, is_missing):
    source = "{{VOCALOID_Songbox|" + field + "=" + value + "}}"

    data, needed = parse_details(source, "样例", with_missing=True)

    assert data["infobox"] == ({} if expected is None else {field: expected})
    assert needed["infobox"] == ([field] if is_missing else [])


def test_count_field_processing_does_not_mutate_other_extraction_views():
    source = """{{VOCALOID Small Songbox
|其他资料=播放{{BiliCount|1}}，已重投
|再生=固定文字
|简介=开头。播放{{BiliCount|1}}次。结尾。
|歌词=完整歌词
}}"""

    data = parse_details(source, "样例")

    assert data["infobox"] == {"其他资料": "已重投", "再生": "固定文字"}
    assert data["summary"] == ["开头。结尾。"]
    assert data["lyrics"] == "完整歌词"
