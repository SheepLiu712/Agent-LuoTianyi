import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[3]
CLI = SERVER / "scripts/deploy/deploy.py"


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


@pytest.fixture
def repo(tmp_path):
    server = tmp_path / "server"
    shutil.copytree(CLI.parent, server / "scripts/deploy", ignore=shutil.ignore_patterns("__pycache__"))
    for path in ("server_main.py", "README.md", "pyproject.toml", "src/server_runtime.py"):
        (server / path).parent.mkdir(exist_ok=True)
        shutil.copyfile(SERVER / path, server / path)
    resource = "res/agent/prompts/example.txt"
    (server / resource).parent.mkdir(parents=True)
    (server / resource).write_bytes(b"original")
    resources = {"files": [{"path": resource, "sha256": hashlib.sha256(b"original").hexdigest(), "size": 8}]}
    (server / "scripts/deploy/resources.lock.json").write_text(json.dumps(dict(schema_version=1, **resources)))
    for path in ("app/secret", "server/config/config.json", "server/res/tts/model.bin", "server/data/music.wav"):
        target = tmp_path / path
        target.parent.mkdir(exist_ok=True, parents=True)
        target.write_bytes(b"instance")
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "core.autocrlf", "false")
    git(tmp_path, "config", "user.email", "build-test@example.invalid")
    git(tmp_path, "config", "user.name", "build test")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "baseline")
    return tmp_path


def build(repo, ref):
    return subprocess.run(
        [sys.executable, str(CLI), "build", "--ref", ref, "--json"], cwd=repo, capture_output=True, check=False
    )


def test_build_from_commit_with_dirty_worktree_and_existing_package(repo):
    commit = git(repo, "rev-parse", "HEAD")
    (repo / "server/res/agent/prompts/example.txt").write_bytes(b"dirty")
    (repo / "server/src/untracked.py").write_bytes(b"dirty")
    first = build(repo, commit)
    assert first.returncode == 0, first.stderr
    result = json.loads(first.stdout)
    package = Path(result["package"])
    assert result["commit_sha"] == commit
    assert hashlib.sha256(package.read_bytes()).hexdigest() == result["package_sha256"]
    with tarfile.open(package) as archive:
        manifest = json.load(archive.extractfile("release.json"))
        files = {row["path"]: row for row in manifest["files"]}
        assert set(archive.getnames()) == set(files) | {"release.json"}
        assert {"server_main.py", "src/server_runtime.py", "scripts/deploy/deploy.py"} <= set(files)
        assert not {"config/config.json", "data/music.wav", "res/tts/model.bin", "src/untracked.py"} & set(files)
        assert not any(path.startswith("app/") for path in files)
        for path, row in files.items():
            content = archive.extractfile(path).read()
            assert (len(content), hashlib.sha256(content).hexdigest()) == (row["size"], row["sha256"])
        assert archive.extractfile("res/agent/prompts/example.txt").read() == b"original"
        assets = manifest["assets"]
        assert json.load(archive.extractfile(assets["lock"]))["asset_version"] == assets["version"]
        assert files[assets["lock"]]["sha256"] == assets["lock_sha256"]
        env = manifest["environment"]
        assert files[env["dependency_lock"]]["sha256"] == env["dependency_lock_sha256"]
        assert env["python_version"] and env["torch_version"] and env["platform"]
    assert json.loads(build(repo, "HEAD").stdout) == result
    package.write_bytes(b"existing different package")
    assert build(repo, commit).returncode != 0
    assert package.read_bytes() == b"existing different package"


@pytest.mark.parametrize("missing", [False, True], ids=["changed", "missing"])
def test_build_rejects_commit_with_modified_or_missing_resource(repo, missing):
    resource = repo / "server/res/agent/prompts/example.txt"
    if missing:
        resource.unlink()
    else:
        resource.write_bytes(b"modified")
    git(repo, "commit", "-qam", "change without lock update")
    failed = build(repo, "HEAD")
    assert failed.returncode != 0
    assert b"res/agent/prompts/example.txt" in failed.stderr
    assert not (repo / "dist").exists()
