"""First installation in real temporary directories; no host packages or services are changed."""

import hashlib
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from integration.deployment.test_release_build import CLI, git, repo  # noqa: F401


@pytest.fixture
def bootstrap(repo, monkeypatch):  # noqa: F811
    monkeypatch.syspath_prepend(str(CLI.parent / "release"))
    monkeypatch.chdir(repo)
    import bootstrap as module

    asset = {
        "schema_version": 1,
        "asset_version": "test",
        "files": [
            {
                "path": "tts/gsv/g2p/en/nltk/taggers/model.json",
                "size": 2,
                "sha256": hashlib.sha256(b"{}").hexdigest(),
            }
        ],
    }
    (repo / "server/scripts/deploy/release/assets.lock.json").write_text(json.dumps(asset))
    git(repo, "commit", "-qam", "test assets")
    source = repo / "models"
    file = source / asset["files"][0]["path"]
    file.parent.mkdir(parents=True)
    file.write_bytes(b"{}")
    file.chmod(0o664)
    file.parent.chmod(0o775)
    root = repo / "production"
    module.initialize(root, "demo", 15674)
    return module, root, source, file


def test_init_creates_private_separate_paths_and_preserves_existing_instance(bootstrap):
    module, root, _, _ = bootstrap
    _, instance = module.settings(root)
    assert instance["root"] == str(root)
    assert instance["health_url"] == "http://127.0.0.1:15674/admin/api/health"
    assert instance["service"] == "agentluo-demo.service"
    for name in module.DIRECTORIES:
        assert (root / name).is_dir() and (root / name).stat().st_mode & 0o077 == 0
    secret = root / "config/secrets.local.env"
    before = secret.read_bytes()
    assert b"JWT_SECRET=" in before and secret.stat().st_mode & 0o077 == 0
    with pytest.raises(ValueError, match="非空"):
        module.initialize(root, "demo", 15674)
    assert secret.read_bytes() == before


def test_assets_verify_then_copy_and_remove_group_write_without_changing_source(bootstrap):
    module, root, source, file = bootstrap
    result = module.install_assets(root, source, "HEAD")
    destination = Path(result["assets"]) / file.relative_to(source)
    assert destination.read_bytes() == b"{}"
    assert file.stat().st_mode & 0o777 == 0o664
    for path in (destination, *destination.parents):
        assert not path.stat().st_mode & 0o022
        if path == root / "assets":
            break
    assert module.install_assets(root, source, "HEAD")["assets"] == result["assets"]


@pytest.mark.parametrize("fault", ["missing", "corrupt", "symlink"])
def test_bad_assets_never_publish_or_change_source(bootstrap, fault):
    module, root, source, file = bootstrap
    if fault == "missing":
        file.unlink()
    elif fault == "corrupt":
        file.write_bytes(b"tampered")
    else:
        other = source / "outside.json"
        other.write_bytes(b"{}")
        file.unlink()
        file.symlink_to(other)
    with pytest.raises(ValueError):
        module.install_assets(root, source, "HEAD")
    assert not (root / "assets/test").exists()


def prepared_install(bootstrap, monkeypatch):
    module, root, source, _ = bootstrap
    module.install_assets(root, source, "HEAD")

    def environment(root, release, manifest, lock):
        # Downloading GPU dependencies is an external boundary. All release/config effects remain real.
        target = root / "environments" / manifest["environment"]["environment_id"]
        (target / "bin").mkdir(parents=True)
        (target / "bin/python").write_text("test interpreter")
        return target

    monkeypatch.setattr(module, "prepare_environment", environment)
    monkeypatch.setattr(module, "check_startup", lambda *args: None)
    return module, root


def test_install_creates_config_and_bindings_without_systemd_or_old_database(bootstrap, monkeypatch):
    module, root = prepared_install(bootstrap, monkeypatch)
    secret = (root / "config/secrets.local.env").read_bytes()
    result = module.install(root, "HEAD")
    assert (root / "current").is_symlink()
    assert (root / "current").resolve().name == result["release_id"]
    assert not any((root / "data").iterdir())  # The real runtime owns fresh database initialization.
    config = json.loads((root / "config/config.json").read_text())
    assert config["is_debug"] is False and config["server"]["production_port"] == 15674
    assert (root / "config/secrets.local.env").read_bytes() == secret
    bindings = (root / "deployments/instance.env").read_text()
    for key, value in {"CONFIG": "config", "DATA": "data", "RUNTIME": ".runtime", "ASSET": "assets/test"}.items():
        assert f'AGENTLUO_{key}_DIR="{root / value}"' in bindings
    assert "AGENTLUO_PYTHON=" in bindings and "PLAYWRIGHT_BROWSERS_PATH=" in bindings
    with pytest.raises(ValueError, match="已部署"):
        module.install(root, "HEAD")
    assert (root / "config/secrets.local.env").read_bytes() == secret


def test_install_refuses_old_data_and_missing_assets(bootstrap):
    module, root, _, _ = bootstrap
    with pytest.raises(ValueError, match="缺少文件"):
        module.install(root, "HEAD")
    assert not (root / "current").exists()
    database = root / "data/old.db"
    database.write_bytes(b"existing business data")
    with pytest.raises(ValueError, match="已有数据"):
        module.install(root, "HEAD")
    assert database.read_bytes() == b"existing business data"


def test_failed_environment_does_not_switch_or_write_config(bootstrap, monkeypatch):
    module, root = prepared_install(bootstrap, monkeypatch)

    def fail(*args):
        raise OSError("download failed")

    monkeypatch.setattr(module, "prepare_environment", fail)
    with pytest.raises(OSError, match="download failed"):
        module.install(root, "HEAD")
    assert not (root / "current").exists()
    assert not (root / "config/config.json").exists()


def test_systemd_uses_current_user_and_instance_and_refuses_other_units(bootstrap, monkeypatch, tmp_path):
    module, root = prepared_install(bootstrap, monkeypatch)
    module.install(root, "HEAD")
    instance, content = module.service_file(root)
    assert f"WorkingDirectory={root}/current" in content
    assert f"EnvironmentFile={root}/deployments/instance.env" in content
    assert f"User={module.pwd.getpwuid(os.getuid()).pw_name}" in content
    assert "@INSTANCE_ROOT@" not in content
    units = tmp_path / "systemd"
    units.mkdir()
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[:2] == ["systemctl", "show"]:
            return SimpleNamespace(stdout="LoadState=not-found\nFragmentPath=\n", returncode=1)
        if command[:2] == ["sudo", "install"]:
            shutil.copyfile(command[-2], command[-1])

    monkeypatch.setattr(module.subprocess, "run", run)
    module.install_service(root, unit_directory=units)
    unit = units / instance["service"]
    assert unit.read_text() == content
    assert ["sudo", "systemctl", "enable", "--now", instance["service"]] in calls
    unit.write_text("another service")
    calls.clear()
    with pytest.raises(ValueError, match="不会覆盖"):
        module.install_service(root, unit_directory=units)
    assert not calls and unit.read_text() == "another service"


def test_symlinked_instance_component_is_rejected(bootstrap, tmp_path):
    module, root, _, _ = bootstrap
    (root / "assets").rmdir()
    (root / "assets").symlink_to(tmp_path)
    with pytest.raises(ValueError, match="符号链接"):
        module.settings(root)


def test_cli_init_and_assets_work_from_repository(bootstrap):
    import subprocess
    import sys

    _, root, source, _ = bootstrap
    target = root.parent / "cli-instance"
    initialized = subprocess.run(
        [sys.executable, str(CLI), "init", "--root", str(target)], capture_output=True, text=True
    )
    if os.getuid() == 0:
        assert initialized.returncode != 0 and "普通服务账号" in initialized.stdout
        return
    assert initialized.returncode == 0, initialized.stdout + initialized.stderr
    assert 'service = "agentluo.service"' in (target / "deployments/deploy.toml").read_text()
    assert "JWT_SECRET=" not in initialized.stdout
    imported = subprocess.run(
        [sys.executable, str(CLI), "assets", "--root", str(target), "--source", str(source)],
        capture_output=True,
        text=True,
    )
    assert imported.returncode == 0, imported.stdout + imported.stderr
    assert (target / "assets/test/tts/gsv/g2p/en/nltk/taggers/model.json").read_bytes() == b"{}"


@pytest.mark.parametrize(
    "name,instance_name,service",
    [
        (None, "production", "agentluo.service"),
        ("test", "test", "agentluo-test.service"),
        ("production", "production", "agentluo-production.service"),
    ],
)
def test_init_service_name_suffix(bootstrap, name, instance_name, service):
    module, root, _, _ = bootstrap
    target = root.parent / "named-instance"
    module.initialize(target, name, 15673)
    record, instance = module.settings(target)
    assert record["name"] == instance_name
    assert instance["service"] == service
