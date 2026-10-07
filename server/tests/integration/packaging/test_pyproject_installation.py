from __future__ import annotations

import json
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path
from zipfile import ZipFile

SERVER_ROOT = Path(__file__).resolve().parents[3]


def test_wheel_contains_regular_and_namespace_packages(tmp_path: Path) -> None:
    source = tmp_path / "server"
    source.mkdir()
    for name in ("pyproject.toml", "README.md", "server_main.py"):
        shutil.copy2(SERVER_ROOT / name, source / name)
    shutil.copytree(
        SERVER_ROOT / "src",
        source / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "temp"),
    )

    result = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", "dist"],
        cwd=source,
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        text=True,
        timeout=180,
    )
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    assert result.returncode == 0, output

    wheels = tuple((source / "dist").glob("agentluo_server-*.whl"))
    assert len(wheels) == 1, output
    with ZipFile(wheels[0]) as wheel:
        members = set(wheel.namelist())

    assert {
        "server_main.py",
        "src/agent/facade.py",
        "src/agent/skills/adapters/memory/facade.py",
        "src/agent/skills/cognitive/response_generation.py",
        "src/infrastructure/persistence/song_knowledge.py",
        "src/world/get_new_songs/task.py",
        "src/world/get_new_songs/vcpedia_templates.json",
        "src/world/learn_sing_songs/task.py",
        "src/world/types/task_result.py",
    } <= members
    assert not any(member.startswith(("src/chat_session/", "src/subconscious/", "src/legacy/")) for member in members)
    _assert_wheel_rules_import_and_parse(wheels[0], tmp_path)


def _assert_wheel_rules_import_and_parse(wheel_path: Path, tmp_path: Path) -> None:
    """Use wheel code, stdlib and existing dependencies only; no source/site hooks or installs."""
    installed = tmp_path / "wheel-site"
    with ZipFile(wheel_path) as wheel:
        wheel.extractall(installed)
    assert not (installed / "config").exists()
    cwd = tmp_path / "unrelated-cwd"
    cwd.mkdir()
    dependencies = sorted({sysconfig.get_path("purelib"), sysconfig.get_path("platlib")})
    script = r"""
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
dependencies = json.loads(sys.argv[2])
source = Path(sys.argv[3]).resolve()
# -I -S skips PYTHONPATH, cwd, user site, .pth and editable-install hooks.
# Add only the extracted wheel and the existing interpreter's dependencies.
sys.path[:] = [str(root), *sys.path, *dependencies]
assert not any(Path(item).resolve() == source for item in sys.path if item)

import src
from src.world.get_new_songs import template_rules, wikitext_parser

assert Path(src.__file__).resolve().is_relative_to(root)
for module in (template_rules, wikitext_parser):
    assert Path(module.__file__).resolve().is_relative_to(root), module.__file__
for name, module in tuple(sys.modules.items()):
    if name.startswith("src.") and getattr(module, "__file__", None):
        assert Path(module.__file__).resolve().is_relative_to(root), (name, module.__file__)
rules_path = template_rules._rules_path()
assert rules_path == root / "src/world/get_new_songs/vcpedia_templates.json"
assert not (root / "config/vcpedia_templates.json").exists()
source_text = "{{VOCALOID Small Songbox|演唱=洛天依|简介=简介正文|歌词=最小歌词}}"
data = wikitext_parser.parse_details(source_text, "wheel sample")
assert data["infobox"] == {"演唱": "洛天依"}, data
assert data["summary"] == ["简介正文"], data
assert data["lyrics"] == "最小歌词", data
assert data["type"] == "Song", data
assert template_rules.descriptor("refn")["non_lyric"] is True
source_text = "== 简介 ==\n简介{{refn|说明}}\n== 歌词 ==\n<poem>歌词{{refn|说明}}{{Photrans/button}}{{LDC}}</poem>"
data, needed = wikitext_parser.parse_details(source_text, "wheel scope", with_missing=True)
assert data["lyrics"] == "歌词" and not needed["lyrics"], (data, needed)
assert data["summary"] == ["简介"] and needed["summary"], (data, needed)
print("WHEEL_IMPORT_PARSE_OK")
"""
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", script, str(installed), json.dumps(dependencies), str(SERVER_ROOT)],
        cwd=cwd,
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        text=True,
        timeout=120,
    )
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    assert result.returncode == 0, output
    assert "WHEEL_IMPORT_PARSE_OK" in result.stdout, output
