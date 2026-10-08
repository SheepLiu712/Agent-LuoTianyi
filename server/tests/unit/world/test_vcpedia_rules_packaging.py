"""规则资源随包交付：单副本加载、校验与冻结，没有部署级覆盖路径。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.world.get_new_songs import template_rules
from src.world.get_new_songs.template_rules import _rules_path
from src.world.get_new_songs.wikitext_parser import parse_details


def _resource() -> Path:
    return Path(template_rules.__file__).with_name("vcpedia_templates.json")


def test_rules_load_from_the_packaged_resource():
    assert _resource().exists(), "包内规则资源缺失：解析功能与 wheel 部署都会失败"
    assert _rules_path() == _resource()


@pytest.mark.parametrize("invalid", [{}, "not-a-list", None, 1, True])
def test_templates_requires_a_list_with_resource_location(monkeypatch, tmp_path, invalid):
    data = json.loads(_resource().read_text(encoding="utf-8"))
    data["templates"] = invalid
    path = tmp_path / "invalid-rules.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(template_rules, "_rules_path", lambda: path)

    with pytest.raises(ValueError) as caught:
        template_rules._load_rules()

    assert f"{path}: templates: expected list" in str(caught.value)


@pytest.mark.parametrize("values", [[], "pic", None, [""], [1]])
def test_skip_if_values_are_nonempty_string_lists(monkeypatch, tmp_path, values):
    data = json.loads(_resource().read_text(encoding="utf-8"))
    data["templates"] = [{"kind": "inline", "names": ["demo"], "text_params": ["1"], "skip_if": {"4": values}}]
    path = tmp_path / "invalid-rules.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(template_rules, "_rules_path", lambda: path)

    with pytest.raises(ValueError) as caught:
        template_rules._load_rules()

    assert f"{path}: templates[0].skip_if.4:" in str(caught.value)


def _load_custom_rules(monkeypatch, tmp_path, templates):
    data = json.loads(_resource().read_text(encoding="utf-8"))
    data["templates"] = templates
    path = tmp_path / "custom-rules.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(template_rules, "_rules_path", lambda: path)
    return template_rules._load_rules()


@pytest.mark.parametrize("kind_fields", [{}, {"kind": "inline", "text_params": ["1"]}])
@pytest.mark.parametrize("invalid", ["true", "false", 0, 1, None, [], {}])
def test_non_lyric_requires_boolean_with_field_location(monkeypatch, tmp_path, kind_fields, invalid):
    with pytest.raises(ValueError) as caught:
        _load_custom_rules(monkeypatch, tmp_path, [{**kind_fields, "names": ["demo"], "non_lyric": invalid}])

    assert f"{tmp_path / 'custom-rules.json'}: templates[0].non_lyric: expected boolean" in str(caught.value)


@pytest.mark.parametrize("invalid_rule", [
    {"names": ["demo"]},
    {"names": ["demo"], "non_lyric": True, "ignore_in": ["lyrics"]},
    {"names": ["demo"], "non_lyric": True, "kind": "not-a-kind"},
    {"names": ["demo"], "non_lyric": True, "kind": "inline"},
    {"names": [], "non_lyric": True},
])
def test_non_lyric_does_not_bypass_other_descriptor_checks(monkeypatch, tmp_path, invalid_rule):
    with pytest.raises(ValueError) as caught:
        _load_custom_rules(monkeypatch, tmp_path, [invalid_rule])

    assert f"{tmp_path / 'custom-rules.json'}: templates[0]" in str(caught.value)


def test_non_lyric_aliases_share_existing_conflict_checks(monkeypatch, tmp_path):
    rules = [{"names": ["REFN"], "non_lyric": True}, {"kind": "break", "names": ["refn"]}]
    with pytest.raises(ValueError, match="conflicting template alias"):
        _load_custom_rules(monkeypatch, tmp_path, rules)


@pytest.mark.parametrize("non_lyric", [True, False])
@pytest.mark.parametrize("kind_fields", [{}, {"kind": "inline", "text_params": ["1"]}])
def test_non_lyric_config_controls_only_lyrics(monkeypatch, tmp_path, non_lyric, kind_fields):
    rules, names = _load_custom_rules(monkeypatch, tmp_path, [
        {**kind_fields, "names": ["Template:自訂_控件"], "non_lyric": non_lyric},
    ])
    monkeypatch.setattr(template_rules, "_RULES", rules)
    monkeypatch.setattr(template_rules, "_BY_NAME", names)
    source = "== 简介 ==\n简介{{自订 控件|1=说明}}\n== 歌词 ==\n<poem>歌词{{自订 控件|1=说明}}</poem>"

    data, needed = parse_details(source, "配置范围", with_missing=True)

    assert data["summary"] == (["简介说明"] if kind_fields else ["简介"])
    assert needed["summary"] is (not bool(kind_fields))
    assert data["lyrics"] == ("歌词说明" if kind_fields and not non_lyric else "歌词")
    assert needed["lyrics"] is (not non_lyric and not kind_fields)
    assert names["自订 控件"]["non_lyric"] is non_lyric
    with pytest.raises(TypeError):
        names["自订 控件"]["non_lyric"] = not non_lyric


def test_non_lyric_defaults_false_for_existing_rendering_rule(monkeypatch, tmp_path):
    rules, names = _load_custom_rules(monkeypatch, tmp_path, [
        {"kind": "inline", "names": ["普通文字"], "text_params": ["1"]},
    ])
    monkeypatch.setattr(template_rules, "_RULES", rules)
    monkeypatch.setattr(template_rules, "_BY_NAME", names)
    source = "== 简介 ==\n{{普通文字|原文}}\n== 歌词 ==\n<poem>{{普通文字|原文}}</poem>"
    data, needed = parse_details(source, "默认范围", with_missing=True)

    assert data["summary"] == ["原文"]
    assert data["lyrics"] == "原文"
    assert not needed["summary"] and not needed["lyrics"]


@pytest.mark.parametrize("name", ["refn", "Photrans/button", "LDC"])
def test_default_non_lyric_names_remain_summary_gaps(name):
    call = "{{" + name + "|1=说明}}"
    source = "== 简介 ==\n简介" + call + "\n== 歌词 ==\n<poem>歌词" + call + "</poem>"
    data, needed = parse_details(source, "默认名单", with_missing=True)

    assert data["summary"] == ["简介"] and needed["summary"]
    assert data["lyrics"] == "歌词" and not needed["lyrics"]


def test_removing_non_lyric_names_from_config_removes_exemption(monkeypatch, tmp_path):
    rules, names = _load_custom_rules(monkeypatch, tmp_path, [])
    monkeypatch.setattr(template_rules, "_RULES", rules)
    monkeypatch.setattr(template_rules, "_BY_NAME", names)
    source = "== 歌词 ==\n<poem>歌词{{refn|说明}}{{Photrans/button}}{{LDC|类型=歌词}}</poem>"
    data, needed = parse_details(source, "没有代码名单", with_missing=True)

    assert data["lyrics"] == "歌词"
    assert needed["lyrics"]


def test_empty_templates_list_is_valid_and_rules_remain_immutable(monkeypatch, tmp_path):
    data = json.loads(_resource().read_text(encoding="utf-8"))
    data["templates"] = []
    path = tmp_path / "empty-rules.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(template_rules, "_rules_path", lambda: path)

    rules, names = template_rules._load_rules()

    assert rules["templates"] == ()
    assert dict(names) == {}
    with pytest.raises(TypeError):
        rules["description"] = "mutated"


def test_resource_loads_from_arbitrary_cwd(monkeypatch, tmp_path):
    cwd = tmp_path / "unrelated"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    assert _rules_path() == _resource()
    _, names = template_rules._load_rules()
    assert names["lyrics"]["kind"] == "lyrics"
    assert names["refn"]["non_lyric"] is True
