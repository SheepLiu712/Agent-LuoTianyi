"""plan 的只读约束、准备清单和阻断行为。"""

import json
import subprocess
import sys
from pathlib import Path

from integration.deployment.test_release_build import CLI, build, repo  # noqa: F401


def invoke(package, config, out, name="production"):
    return subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--config",
            str(config),
            "plan",
            "--package",
            str(package),
            "--instance",
            name,
            "--out",
            str(out),
            "--json",
        ],
        capture_output=True,
        text=True,
    )


def test_plan_reports_preparation_without_changing_instance(repo):  # noqa: F811
    built = json.loads(build(repo, "HEAD").stdout)
    root = repo / "production"
    (root / "config").mkdir(parents=True)
    (root / "config/config.json").write_text('{"secret":"must-not-leak"}')
    config = repo / "deploy.toml"
    config.write_text(f'[instances.production]\nroot = "{root}"\nservice = "agentluo.service"\n')
    before = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    out = repo / "plan.json"
    command = invoke(built["package"], config, out)
    assert command.returncode == 3, command.stderr
    result = json.loads(command.stdout)
    assert result == json.loads(out.read_text())
    assert result["executable"] is False
    assert result["first_takeover"] is True
    assert all(c["action"] == "prepare" for c in result["components"].values())
    assert "must-not-leak" not in command.stdout
    assert {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before
    assert not (root / "releases").exists()
    assert not (root / "environments").exists()


def test_bad_package_and_unknown_instance_are_not_successful(tmp_path):
    package = tmp_path / "bad.tar.gz"
    package.write_bytes(b"broken")
    config = tmp_path / "deploy.toml"
    config.write_text(f'[instances.production]\nroot = "{tmp_path / "target"}"\nservice = "test.service"\n')
    out = tmp_path / "plan.json"
    result = invoke(package, config, out)
    assert result.returncode == 3
    assert json.loads(out.read_text())["blockers"]
    result = invoke(package, config, tmp_path / "unknown.json", "unknown")
    assert result.returncode == 2
    assert not (tmp_path / "unknown.json").exists()


def test_output_cannot_overwrite_instance(tmp_path):
    config = tmp_path / "deploy.toml"
    config.write_text(f'[instances.production]\nroot = "{tmp_path}"\nservice = "test.service"\n')
    result = invoke(Path("missing"), config, tmp_path / "config.json")
    assert result.returncode == 2
    assert not (tmp_path / "config.json").exists()


def test_existing_release_corruption_blocks_reuse(repo):  # noqa: F811
    built = json.loads(build(repo, "HEAD").stdout)
    root = repo / "production"
    release = root / "releases" / built["release_id"]
    release.mkdir(parents=True)
    (release / "server_main.py").write_bytes(b"corrupted")
    config = repo / "deploy.toml"
    config.write_text(f'[instances.production]\nroot = "{root}"\nservice = "agentluo.service"\n')
    result = invoke(built["package"], config, repo / "plan.json")
    assert result.returncode == 3
    component = json.loads(result.stdout)["components"]["release"]
    assert component["action"] == "blocked"
    assert any("server_main.py" in error for error in component["problems"])
    assert (release / "server_main.py").read_bytes() == b"corrupted"


def test_asset_content_is_checked_not_only_directory_name(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(CLI.parent / "release"))
    import hashlib

    from plan import check_tree

    asset = tmp_path / "model.bin"
    asset.write_bytes(b"model")
    entries = [{"path": "model.bin", "size": 5, "sha256": hashlib.sha256(b"model").hexdigest()}]
    assert check_tree(tmp_path, entries) == []
    asset.write_bytes(b"other")
    assert check_tree(tmp_path, entries) == ["校验不一致：model.bin"]
    asset.unlink()
    assert check_tree(tmp_path, entries) == ["缺少文件：model.bin"]


def test_environment_without_interpreter_is_blocked(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(CLI.parent / "release"))
    from plan import check_environment

    assert check_environment(tmp_path, {}, {}) == ["Python 解释器缺失"]


def test_plan_generates_database_migration_and_allows_compatible_release(repo):  # noqa: F811
    import hashlib
    import sqlite3
    import tarfile

    from integration.deployment.test_release_build import git

    asset_data = b"model"
    asset_lock = {
        "schema_version": 1,
        "asset_version": "test-assets",
        "files": [{"path": "tts/model.bin", "size": len(asset_data), "sha256": hashlib.sha256(asset_data).hexdigest()}],
    }
    (repo / "server/scripts/deploy/release/assets.lock.json").write_text(json.dumps(asset_lock))
    git(repo, "commit", "-qam", "test asset requirement")
    built = json.loads(build(repo, "HEAD").stdout)
    root = repo / "production"
    release = root / "releases" / built["release_id"]
    release.mkdir(parents=True)
    with tarfile.open(built["package"]) as archive:
        archive.extractall(release)  # Trusted fixture generated by build.
    (root / "current").symlink_to(release)
    (root / "assets/test-assets/tts").mkdir(parents=True)
    (root / "assets/test-assets/tts/model.bin").write_bytes(asset_data)
    (root / "config").mkdir()
    (root / "config/config.json").write_bytes((release / "config/config.json").read_bytes())
    (root / "config/secrets.local.env").write_text("QWEN_API_KEY=private-value")
    manifest = json.loads((release / "release.json").read_text())
    for kind, requirement in manifest["databases"].items():
        path = root / requirement["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as connection:
            # Existing pre-version databases: plan may schedule migration but must not run it.
            connection.execute("CREATE TABLE " + ("users(uuid TEXT)" if kind == "main" else "songs(uuid TEXT)"))
    config = repo / "deploy.toml"
    config.write_text(f'[instances.production]\nroot = "{root}"\nservice = "agentluo.service"\n')
    config.write_text(
        config.read_text() + 'health_url = "http://127.0.0.1:12345/health"\n'
        'admin_url = "http://127.0.0.1:12345/admin"\n'
    )
    result = invoke(built["package"], config, repo / "migration-plan.json")
    assert result.returncode == 0, result.stdout + result.stderr
    document = json.loads(result.stdout)
    assert len(document["migrations"]) == 2
    assert all(item["from"] == 0 and item["to"] == 1 for item in document["migrations"])
    assert document["configuration"]["policy"] == "replace_file_only"
    assert "private-value" not in result.stdout
    for requirement in manifest["databases"].values():
        with sqlite3.connect(root / requirement["path"]) as connection:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
    assert not list(root.rglob("*.schema-0-backup-*"))
    # No route exists from a future database schema; never downgrade or reset it.
    with sqlite3.connect(root / manifest["databases"]["main"]["path"]) as connection:
        connection.execute("PRAGMA user_version=9")
    result = invoke(built["package"], config, repo / "future-plan.json")
    assert result.returncode == 3
    assert any("schema 9" in problem for problem in json.loads(result.stdout)["blockers"])
