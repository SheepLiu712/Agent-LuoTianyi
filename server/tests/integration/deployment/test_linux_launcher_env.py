"""Exercise the real launcher with lightweight code and no network/model services."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[3]


def make_code(directory):
    launcher = directory / "scripts/deploy/startup/start_linux.sh"
    launcher.parent.mkdir(parents=True)
    shutil.copyfile(SERVER / "scripts/deploy/startup/start_linux.sh", launcher)
    utils = directory / "src/utils"
    utils.mkdir(parents=True)
    shutil.copyfile(SERVER / "src/utils/server_paths.py", utils / "server_paths.py")
    (directory / "server_main.py").write_text(
        'import os, json, sys\nprint(json.dumps([os.environ["AGENTLUO_CONFIG_DIR"], sys.argv[1:]]))\n'
    )
    return launcher


def run(launcher, **values):
    env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTLUO_")}
    return subprocess.run(
        ["bash", str(launcher), "--check-startup"], env={**env, **values}, capture_output=True, text=True, timeout=10
    )


def write_env(path, root):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'AGENTLUO_PYTHON="{sys.executable}"\n'
        f'AGENTLUO_CONFIG_DIR="{root}/config"\nAGENTLUO_RUNTIME_DIR="{root}/runtime"\n'
    )


def test_current_loads_its_own_instance_without_exported_settings(tmp_path):
    for name in ("first", "second"):
        root = tmp_path / name
        code = root / "releases/version"
        make_code(code)
        (code / "release.json").write_text("{}")
        (root / "current").symlink_to(code)
        write_env(root / "deployments/instance.env", root)
        result = run(root / "current/scripts/deploy/startup/start_linux.sh")
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == [str(root / "config"), ["--check-startup"]]


@pytest.mark.parametrize("explicit", [False, True])
def test_source_checkout_preserves_exports_or_loads_explicit_file(tmp_path, explicit):
    launcher = make_code(tmp_path / "source")
    values = {
        "AGENTLUO_PYTHON": sys.executable,
        "AGENTLUO_CONFIG_DIR": str(tmp_path / "config"),
        "AGENTLUO_RUNTIME_DIR": str(tmp_path / "runtime"),
    }
    if explicit:
        file = tmp_path / "custom.env"
        write_env(file, tmp_path)
        values = {"AGENTLUO_INSTANCE_ENV": str(file)}
    result = run(launcher, **values)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)[0] == str(tmp_path / "config")


def test_missing_instance_environment_fails_before_start(tmp_path):
    code = tmp_path / "releases/version"
    launcher = make_code(code)
    (code / "release.json").write_text("{}")
    (tmp_path / "current").symlink_to(code)
    result = run(launcher)
    assert result.returncode != 0 and "无法读取实例环境文件" in result.stderr
    assert not result.stdout


def test_old_release_cannot_load_current_settings(tmp_path):
    code = tmp_path / "releases/old"
    launcher = make_code(code)
    (code / "release.json").write_text("{}")
    (tmp_path / "current").symlink_to(tmp_path / "releases/new")
    result = run(launcher)
    assert result.returncode != 0 and "current" in result.stderr
