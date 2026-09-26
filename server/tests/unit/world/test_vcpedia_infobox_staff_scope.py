"""信息框的 staff 邻接范围：只接纳首个歌曲框相邻的 staff。

契约：首个歌曲框的信息框及其相邻 staff 为信息框候选，后框不得覆盖；首个歌曲框之前的
staff、以及首个与第二个歌曲框之间的 staff 都不属于该信息框。
"""

from __future__ import annotations

import pytest

from src.world.get_new_songs.wikitext_parser import parse_details

TITLE = "固定样例"


def test_staff_before_the_first_songbox_is_not_infobox_material():
    source = "{{创作者名单|group1=曲绘|list1=前置作者}}\n{{VOCALOID_Songbox|演唱=洛天依}}\n== 简介 ==\n正文。"

    data = parse_details(source, TITLE)

    assert data["infobox"] == {"演唱": "洛天依"}, "首个歌曲框之前的 staff 不得并入信息框"


def test_staff_adjacent_to_the_first_songbox_is_kept():
    source = "{{VOCALOID_Songbox|演唱=洛天依}}\n{{创作者名单|group1=PV|list1=相邻作者}}\n== 简介 ==\n正文。"

    data = parse_details(source, TITLE)

    assert data["infobox"] == {"演唱": "洛天依", "PV": "相邻作者"}


@pytest.mark.parametrize("blank", ["\n", "\n\n\n"])
def test_blank_lines_between_box_and_staff_keep_adjacency(blank):
    """空行不算中间内容，相邻关系仍然成立。"""
    source = f"{{{{VOCALOID_Songbox|演唱=洛天依}}}}{blank}{{{{创作者名单|group1=PV|list1=相邻作者}}}}\n== 简介 ==\n正文。"

    assert parse_details(source, TITLE)["infobox"] == {"演唱": "洛天依", "PV": "相邻作者"}
