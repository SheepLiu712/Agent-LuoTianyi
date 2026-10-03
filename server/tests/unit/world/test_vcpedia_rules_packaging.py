"""规则文件的位置与双副本一致性：源码运行用 server/config，wheel 安装回退包内副本。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.world.get_new_songs import template_rules
from src.world.get_new_songs.template_rules import _rules_path


def _source_config() -> Path:
    return Path(__file__).resolve().parents[3] / "config/vcpedia_templates.json"


def test_source_config_takes_priority_in_source_layout():
    assert _source_config().exists(), "源码布局下 server/config 的规则文件必须存在"
    assert _rules_path() == _source_config()


def test_packaged_copy_exists_and_matches_source_config():
    packaged = Path(template_rules.__file__).resolve().parent / "vcpedia_templates.json"

    assert packaged.exists(), "包内副本缺失：wheel 安装将无法加载模板规则"
    assert _source_config().read_text(encoding="utf-8") == packaged.read_text(encoding="utf-8"), (
        "server/config 与包内副本漂移：修改规则时两份必须同步更新"
    )


@pytest.mark.parametrize("invalid", [{}, "not-a-list", None, 1, True])
def test_templates_requires_a_list_with_resource_location(monkeypatch, tmp_path, invalid):
    data = json.loads(_source_config().read_text(encoding="utf-8"))
    data["templates"] = invalid
    path = tmp_path / "invalid-rules.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(template_rules, "_rules_path", lambda: path)

    with pytest.raises(ValueError) as caught:
        template_rules._load_rules()

    assert f"{path}: templates: expected list" in str(caught.value)


@pytest.mark.parametrize("values", [[], "pic", None, [""], [1]])
def test_skip_if_values_are_nonempty_string_lists(monkeypatch, tmp_path, values):
    data = json.loads(_source_config().read_text(encoding="utf-8"))
    data["templates"] = [{"kind": "inline", "names": ["demo"], "text_params": ["1"], "skip_if": {"4": values}}]
    path = tmp_path / "invalid-rules.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(template_rules, "_rules_path", lambda: path)

    with pytest.raises(ValueError) as caught:
        template_rules._load_rules()

    assert f"{path}: templates[0].skip_if.4:" in str(caught.value)


def test_empty_templates_list_is_valid_and_rules_remain_immutable(monkeypatch, tmp_path):
    data = json.loads(_source_config().read_text(encoding="utf-8"))
    data["templates"] = []
    path = tmp_path / "empty-rules.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(template_rules, "_rules_path", lambda: path)

    rules, names = template_rules._load_rules()

    assert rules["templates"] == ()
    assert dict(names) == {}
    with pytest.raises(TypeError):
        rules["description"] = "mutated"


@pytest.mark.parametrize("broken", ["{not-json", '{"templates": {}}'])
def test_broken_source_config_never_silently_uses_valid_packaged_copy(monkeypatch, tmp_path, broken):
    module_path = tmp_path / "src/world/get_new_songs/template_rules.py"
    module_path.parent.mkdir(parents=True)
    source = tmp_path / "config/vcpedia_templates.json"
    source.parent.mkdir()
    source.write_text(broken, encoding="utf-8")
    packaged = module_path.with_name("vcpedia_templates.json")
    packaged.write_text(_source_config().read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(template_rules, "__file__", str(module_path))

    assert template_rules._rules_path() == source
    with pytest.raises(ValueError) as caught:
        template_rules._load_rules()
    assert f"{source}: resource:" in str(caught.value)


def test_source_absent_uses_packaged_copy_from_arbitrary_cwd(monkeypatch, tmp_path):
    module_path = tmp_path / "site/src/world/get_new_songs/template_rules.py"
    module_path.parent.mkdir(parents=True)
    packaged = module_path.with_name("vcpedia_templates.json")
    packaged.write_text(_source_config().read_text(encoding="utf-8"), encoding="utf-8")
    cwd = tmp_path / "unrelated"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(template_rules, "__file__", str(module_path))

    assert template_rules._rules_path() == packaged
    _, names = template_rules._load_rules()
    assert names["lyrics"]["kind"] == "lyrics"
