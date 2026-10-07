"""规则资源随包交付：单副本加载、校验与冻结，没有部署级覆盖路径。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.world.get_new_songs import template_rules
from src.world.get_new_songs.template_rules import _rules_path


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
