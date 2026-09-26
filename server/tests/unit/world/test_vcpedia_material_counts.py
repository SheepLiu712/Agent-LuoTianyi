"""材料侧计数剔除：政策由行的结构决定，不由行内标点决定。

契约：散文行移除含计数模板的完整句子，模板参数值仅移除含计数的分句；判据是模板名后缀
`count`。这里直接观察模型材料（`material_text`），不经过网络或模型。
"""

from __future__ import annotations

import pytest

from src.world.get_new_songs.source_extraction import material_text

COUNT = "{{bilibiliCount|id=1}}"


def test_prose_drops_a_sentence_that_carries_a_count():
    material = material_text(f"开头。已有{COUNT}播放，45次收藏。结尾。")

    assert "bilibiliCount" not in material
    assert "45次收藏" not in material
    assert "开头。" in material
    assert "结尾。" in material


def test_prose_without_sentence_punctuation_drops_everything_it_carries():
    """审查点名的边界：无句末标点的散文不得留下"达成殿堂"这类残句。"""
    material = material_text(f"达成殿堂，已有{COUNT}播放")

    assert "bilibiliCount" not in material
    assert "达成殿堂" not in material


def test_parameter_value_keeps_its_other_clauses():
    material = material_text(f"{{{{Songbox|简介=发布信息，播放{COUNT}，2024年投稿}}}}")

    assert "bilibiliCount" not in material
    assert "发布信息" in material
    assert "2024年投稿" in material


def test_parameter_value_disappears_when_nothing_but_counts_remains():
    material = material_text(f"{{{{Songbox|数据={COUNT}，{COUNT}}}}}")

    assert "bilibiliCount" not in material
    assert "数据" not in material


def test_non_count_templates_are_kept():
    """只有后缀 `count` 的模板按计数处理，其它模板原样保留。"""
    material = material_text("{{黑幕|隐藏内容}} 保留这句。")

    assert "黑幕" in material
    assert "隐藏内容" in material


def test_material_without_counts_is_unchanged_apart_from_conversion():
    source = "== 简介 ==\n没有统计的正文。"

    assert material_text(source) == source


@pytest.mark.parametrize("suffix", ["Count", "COUNT"])
def test_count_matching_ignores_case(suffix):
    material = material_text(f"开头。已有{{{{bilibili{suffix}|id=1}}}}播放。结尾。")

    assert "bilibili" not in material
    assert "开头。" in material
