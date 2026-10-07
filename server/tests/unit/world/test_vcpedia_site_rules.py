"""Site vocabulary and parameter roles come from the same validated rule resource."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.world.get_new_songs import template_rules
from src.world.get_new_songs.daily_new_song_fetcher import _extract_song_fields
from src.world.get_new_songs.wikitext_parser import heading_section, parse_details, parse_song_candidates


@pytest.fixture
def rules_config(monkeypatch, tmp_path):
    data = json.loads(template_rules._rules_path().read_text(encoding="utf-8"))

    def install():
        path = tmp_path / "site-rules.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(template_rules, "_rules_path", lambda: path)
        rules, names = template_rules._load_rules()
        monkeypatch.setattr(template_rules, "_RULES", rules)
        monkeypatch.setattr(template_rules, "_BY_NAME", names)

    return data, install


def test_link_aliases_and_slots_use_descriptor_without_treating_all_inline_as_links(rules_config):
    data, install = rules_config
    link = next(rule for rule in data["templates"] if "lj" in rule["names"])
    link.update(names=["自訂連結"], text_params=["显示", "目标"], target_params=["目标"])
    install()

    assert parse_song_candidates("{{自订连结|目标=页面|显示=别名}}{{自订连结|目标=另一页}}") == [
        ("别名", "页面"), ("另一页", "另一页"),
    ]
    assert parse_song_candidates("{{lj|页面|旧别名}}{{color|red|不是链接}}") == []
    assert parse_song_candidates("{{自订连结|目标=页面|显示=}}") == []


def test_ruby_slots_and_aliases_preserve_base_priority_and_annotation_fallback(rules_config):
    data, install = rules_config
    ruby = next(rule for rule in data["templates"] if rule.get("kind") == "ruby")
    ruby.update(names=["标音"], base_params=["表层"], annotation_params=["读音"])
    install()
    source = (
        "== 歌词 ==\n<poem>{{标音|表层=表层文字|读音={{未知|不选缺口}}}}"
        "{{标音|表层=|读音=回退标注}}</poem>"
    )
    parsed, needed = parse_details(source, "自定义槽位", with_missing=True)

    assert parsed["lyrics"] == "表层文字回退标注"
    assert not needed["lyrics"]
    assert parse_details("== 歌词 ==\n<poem>{{ruby|旧表层|旧标注}}</poem>", "旧别名")["lyrics"] == ""


def test_section_aliases_affect_source_headings_with_fixed_intro_precedence(rules_config):
    data, install = rules_config
    data["section_aliases"] = {"歌词": ["唱詞"], "简介": ["背景"]}
    install()
    parsed = parse_details("== 背景 ==\n介绍内容\n== 唱词 ==\n<poem>歌词正文</poem>", "新章节")

    assert parsed["summary"] == ["介绍内容"] and parsed["lyrics"] == "歌词正文"
    assert heading_section("背景唱詞") == "简介"
    assert heading_section("简介") == heading_section("歌词") == ""


def test_song_list_filter_words_are_configurable_but_syntax_filters_remain(rules_config):
    data, install = rules_config
    data["song_list_filters"] = {"exact": ["测试导航"], "contains": ["版式"]}
    install()

    assert parse_song_candidates(
        "[[测试导航]][[旧版式说明]][[查看]][[Template:帮助]][[#锚点|锚点]][[2026]]"
    ) == [("查看", "查看")]
    data["song_list_filters"] = {"exact": [], "contains": []}
    install()
    assert parse_song_candidates("[[测试导航]][[Template:帮助]]") == [("测试导航", "测试导航")]


def test_song_field_sources_preserve_first_nonempty_priority_without_rewriting_infobox(rules_config):
    data, install = rules_config
    data["song_field_sources"] = {"uploader": ["自订发布", "UP主"], "singers": ["自订歌手", "演唱"]}
    install()
    infobox = {"自订发布": "", "UP主": "原投稿者", "自订歌手": "新歌手", "演唱": "原歌手"}
    original = dict(infobox)
    fields = _extract_song_fields({"infobox": infobox})

    assert fields["uploader"] == "原投稿者" and fields["singers"] == "新歌手"
    assert infobox == original
    infobox["自订发布"] = "新投稿者"
    assert _extract_song_fields({"infobox": infobox})["uploader"] == "新投稿者"


@pytest.mark.parametrize("group,key,invalid", [
    ("section_aliases", "简介", []),
    ("section_aliases", "歌词", "歌词"),
    ("song_list_filters", "exact", [""]),
    ("song_list_filters", "contains", None),
    ("song_field_sources", "uploader", []),
    ("song_field_sources", "singers", [1]),
])
def test_site_rule_list_values_fail_with_field_location(rules_config, group, key, invalid):
    data, install = rules_config
    data[group][key] = invalid
    with pytest.raises(ValueError, match=rf"{group}\.{key}:"):
        install()


@pytest.mark.parametrize("group", ["section_aliases", "song_list_filters", "song_field_sources"])
@pytest.mark.parametrize("invalid", [None, [], {}, {"unknown": ["value"]}])
def test_site_rule_groups_reject_missing_unknown_or_nonmapping_keys(rules_config, group, invalid):
    data, install = rules_config
    data[group] = invalid
    with pytest.raises(ValueError, match=rf"{group}: expected keys"):
        install()


@pytest.mark.parametrize("kind,key", [
    ("inline", "target_params"), ("ruby", "base_params"), ("ruby", "annotation_params"),
])
@pytest.mark.parametrize("invalid", [[], None, "1", [1], [""]])
def test_parameter_role_lists_must_be_nonempty_strings(rules_config, kind, key, invalid):
    data, install = rules_config
    rule = next(rule for rule in data["templates"] if rule.get("kind") == kind)
    rule[key] = invalid
    with pytest.raises(ValueError, match=rf"templates\[\d+\]\.{key}:"):
        install()


def test_new_site_rules_are_frozen_with_resource(rules_config):
    _, install = rules_config
    install()
    with pytest.raises(TypeError):
        template_rules._RULES["section_aliases"]["歌词"] = ("changed",)
    assert isinstance(template_rules._RULES["song_list_filters"]["exact"], tuple)


def test_packaged_resource_has_same_site_rules():
    packaged = Path(template_rules.__file__).with_name("vcpedia_templates.json")
    assert json.loads(packaged.read_text(encoding="utf-8")) == json.loads(
        template_rules._rules_path().read_text(encoding="utf-8")
    )
