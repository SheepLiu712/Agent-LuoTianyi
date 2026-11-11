"""Deployment effects with real files/databases and a controlled systemd boundary."""

import hashlib
import importlib.util
import json
import shlex
import sqlite3
import sys
import tarfile
from contextlib import closing
from pathlib import Path

import pytest
from integration.deployment.test_release_build import CLI, SERVER, build, git, repo  # noqa: F401


def initialize_databases(root, manifest):
    for kind, requirement in manifest["databases"].items():
        source = "database/sql_database.py" if kind == "main" else "song_knowledge.py"
        spec = importlib.util.spec_from_file_location(
            "deployment_" + kind, SERVER / "src/infrastructure/persistence" / source
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        path = root / requirement["path"]
        if kind == "main":
            module.init_sql_db(str(path.parent), path.name)
        else:
            module.init_song_db({"db_folder": str(path.parent), "db_file": path.name})
        module.engine.dispose()
        with closing(sqlite3.connect(path)) as connection:
            if kind == "main":
                connection.execute("INSERT INTO users(uuid, username, password) VALUES('u', 'kept', 'hash')")
            connection.execute("PRAGMA user_version=0")
            connection.commit()


@pytest.fixture
def deployment(repo, monkeypatch):  # noqa: F811
    monkeypatch.syspath_prepend(str(CLI.parent / "release"))
    monkeypatch.syspath_prepend(str(SERVER))
    import apply as executor
    import plan
    import prepare_release
    import service_control
    import status

    asset = {
        "schema_version": 1,
        "asset_version": "test",
        "files": [{"path": "tts/model", "size": 5, "sha256": hashlib.sha256(b"model").hexdigest()}],
    }
    (repo / "server/scripts/deploy/release/assets.lock.json").write_text(json.dumps(asset))
    git(repo, "commit", "-qam", "small asset")
    built = json.loads(build(repo, "HEAD").stdout)
    package = Path(built["package"])
    root = repo / "instance"
    old = root / "releases/old"
    old.mkdir(parents=True)
    with tarfile.open(package) as archive:
        archive.extractall(old)  # Trusted test package.
    manifest = json.loads((old / "release.json").read_text())
    manifest["release_id"] = "old"
    (old / "release.json").write_text(json.dumps(manifest))
    (root / "current").symlink_to(old)
    (root / "config").mkdir()
    (root / "config/config.json").write_bytes((old / "config/config.json").read_bytes())
    (root / "config/secrets.local.env").write_text("QWEN_API_KEY=keep-private")
    (root / "assets/test/tts").mkdir(parents=True)
    (root / "assets/test/tts/model").write_bytes(b"model")
    environment = root / "environments" / manifest["environment"]["environment_id"]
    (environment / "bin").mkdir(parents=True)
    (environment / "bin/python").write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) + ' "$@"\n')
    (environment / "bin/python").chmod(0o755)
    initialize_databases(root, manifest)
    config = repo / "deploy.toml"
    config.write_text(
        f'[instances.test]\nroot = "{root}"\nservice = "test.service"\n'
        'health_url = "http://127.0.0.1:12345/admin/api/health"\n'
        'admin_url = "http://127.0.0.1:12345/admin"\n'
    )
    # GPU environment validity is independently checked by plan; avoid needing CUDA in coordinator tests.
    monkeypatch.setattr(plan, "check_environment", lambda *args: [])
    monkeypatch.setattr(prepare_release, "check_environment", lambda *args: [])

    class Controller:
        active = True
        stops = 0
        starts = 0

        def preflight(self, root):
            return self.query()

        def query(self):
            return {"ActiveState": "active" if self.active else "inactive", "MainPID": "123" if self.active else "0"}

        def stop(self):
            self.stops += 1
            self.active = False

        def start(self):
            self.starts += 1
            self.active = True

    controller = Controller()
    # System process visibility is a separate boundary; unrelated host daemons may hide /proc/fd.
    monkeypatch.setattr(executor, "verify_writers", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "check_startup", lambda *args: None)
    monkeypatch.setattr(executor, "Systemd", lambda instance: controller)
    monkeypatch.setattr(status, "Systemd", lambda instance: controller)

    def actual(state, root):
        return (root / "current").resolve().name if controller.active else None

    def healthy(instance):
        return {"healthy": controller.active}

    from offline_steps import runtime_bindings

    def bindings(state):
        return (
            runtime_bindings(root, (root / "current").resolve(), environment, root / "assets/test")
            if controller.active
            else {}
        )

    monkeypatch.setattr(service_control, "process_bindings", bindings)
    monkeypatch.setattr(status, "process_bindings", bindings)
    monkeypatch.setattr(service_control, "actual_release", actual)
    monkeypatch.setattr(service_control, "health", healthy)
    monkeypatch.setattr(status, "actual_release", actual)
    monkeypatch.setattr(status, "health", healthy)
    monkeypatch.setattr(executor, "await_healthy", lambda *args: {"healthy": True})
    out = repo / "plan.json"
    report = plan.plan(package, config, "test", out)
    assert report["executable"], report["blockers"]
    return executor, plan, status, root, config, package, out, controller, manifest


def test_apply_migrates_preserves_credentials_and_records_verified_success(deployment):
    executor, _, observer, root, config, _, out, controller, manifest = deployment
    result, code = executor.apply(out)
    assert code == 0, result
    assert result["outcome"] == "succeeded"
    assert controller.stops == controller.starts == 1
    assert (root / "config/secrets.local.env").read_text() == "QWEN_API_KEY=keep-private"
    assert json.loads((root / "config/config.json").read_text())["server"]["debug_port"] == 12345
    database = root / manifest["databases"]["main"]["path"]
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute("SELECT username FROM users WHERE uuid='u'").fetchone() == ("kept",)
    backup = Path(result["backup"])
    with closing(sqlite3.connect(backup / "main.sqlite")) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
    state = observer.status(config, "test")
    assert state["healthy"] and state["actual_release"] == result["target_release"]
    assert state["last_success"]["release_id"] == result["target_release"]
    # Reusing the successful plan performs no stop, migration or backup.
    repeated, code = executor.apply(out)
    assert code == 0 and repeated["outcome"] == "unchanged"
    assert controller.stops == 1


@pytest.mark.parametrize("change", ["package", "credentials", "mapping", "schema"])
def test_stale_plan_refused_before_stop(deployment, change):
    executor, _, _, root, config, package, out, controller, manifest = deployment
    from deployment_state import DeploymentError

    if change == "package":
        package.write_bytes(b"corrupted")
    elif change == "credentials":
        (root / "config/secrets.local.env").write_text("QWEN_API_KEY=changed")
    elif change == "mapping":
        config.write_text(config.read_text() + "startup_timeout_seconds = 60\n")
    else:
        with closing(sqlite3.connect(root / manifest["databases"]["main"]["path"])) as connection:
            connection.execute("PRAGMA user_version=9")
    with pytest.raises(DeploymentError) as error:
        executor.apply(out)
    assert error.value.code == 3
    assert controller.stops == 0
    assert (root / "current").resolve().name == "old"


def test_business_writes_do_not_invalidate_plan(deployment):
    executor, _, _, root, _, _, out, _, manifest = deployment
    with closing(sqlite3.connect(root / manifest["databases"]["main"]["path"])) as connection:
        connection.execute("INSERT INTO users(uuid, username, password) VALUES('new', 'after-plan', 'hash')")
        connection.commit()
    result, code = executor.apply(out)
    assert code == 0, result


def test_acceptance_failure_stops_service_keeps_backup_and_blocks_retry(deployment, monkeypatch):
    executor, _, observer, root, config, _, out, controller, _ = deployment
    from deployment_state import DeploymentError

    def fail(*args):
        raise DeploymentError("runtime not running")

    monkeypatch.setattr(executor, "await_healthy", fail)
    result, code = executor.apply(out)
    assert code == 5 and result["outcome"] == "failed"
    assert not controller.active and Path(result["backup"]).is_dir()
    assert not (root / "deployments/current.json").exists()
    state = observer.status(config, "test")
    assert not state["healthy"] and state["latest_operation"]["outcome"] == "failed"
    with pytest.raises(DeploymentError, match="未完成操作"):
        executor.apply(out)


def test_instance_lock_excludes_second_apply(deployment):
    executor, _, _, root, _, _, out, controller, _ = deployment
    from deployment_state import DeploymentError

    with executor.deployment_lock(root):
        with pytest.raises(DeploymentError) as error:
            executor.apply(out)
    assert error.value.code == 4 and controller.stops == 0


def test_stop_failure_never_migrates_or_switches(deployment, monkeypatch):
    executor, _, _, root, _, _, out, controller, _ = deployment
    from deployment_state import DeploymentError

    def fail():
        raise DeploymentError("still running")

    monkeypatch.setattr(controller, "stop", fail)
    result, code = executor.apply(out)
    assert code == 5 and result["cleanup_error"]
    assert (root / "current").resolve().name == "old"
    assert not (root / "deployments/backups").exists()


def test_online_preparation_failure_leaves_old_service_running(deployment, monkeypatch):
    executor, _, _, root, _, _, out, controller, _ = deployment
    from deployment_state import DeploymentError

    def fail(*args):
        raise DeploymentError("environment unavailable")

    monkeypatch.setattr(executor, "prepare_environment", fail)
    result, code = executor.apply(out)
    assert code == 5 and not result["requires_recovery"]
    assert controller.active and controller.stops == 0
    assert (root / "current").resolve().name == "old"


def test_migration_failure_retains_backup_without_switching(deployment, monkeypatch):
    executor, _, _, root, _, _, out, controller, _ = deployment
    from deployment_state import DeploymentError

    def fail(*args):
        raise DeploymentError("migration failed")

    monkeypatch.setattr(executor, "migrate", fail)
    result, code = executor.apply(out)
    assert code == 5 and Path(result["backup"]).exists()
    assert not controller.active and controller.starts == 0
    assert (root / "current").resolve().name == "old"


def test_runtime_lock_refuses_migration(deployment):
    executor, _, _, root, _, _, out, controller, _ = deployment
    from offline_steps import runtime_lock

    with runtime_lock(root):
        result, code = executor.apply(out)
    assert code == 5 and "写入锁" in result["error"]
    assert controller.starts == 0 and (root / "current").resolve().name == "old"
    assert not (root / "deployments/backups").exists()


def test_status_does_not_claim_success_from_healthy_http_alone(deployment, monkeypatch):
    _, _, observer, _, config, _, _, controller, _ = deployment
    monkeypatch.setattr(observer, "health", lambda instance: {"healthy": True})
    controller.active = False
    result = observer.status(config, "test")
    assert result["health"]["healthy"] and not result["healthy"]
    assert result["actual_release"] is None


def test_assets_can_be_prepared_from_verified_local_source(deployment):
    executor, planner, _, root, config, package, _, controller, _ = deployment
    source = root.parent / "asset-source"
    (root / "assets/test").rename(source)
    config.write_text(config.read_text() + f'asset_source = "{source}"\n')
    out = root.parent / "asset-plan.json"
    report = planner.plan(package, config, "test", out)
    assert report["executable"]
    assert report["components"]["assets"]["action"] == "prepare"
    result, code = executor.apply(out)
    assert code == 0, result
    assert (root / "assets/test/tts/model").read_bytes() == (source / "tts/model").read_bytes()
    assert controller.stops == 1


def test_apply_reuses_verified_offline_backup_without_copying_again(deployment):
    import shutil

    from cli import file_digest
    from deployment_state import atomic_json

    executor, planner, _, root, config, package, _, _, manifest = deployment
    existing = root / "deployments/takeover/offline"
    existing.mkdir(parents=True)
    shutil.copytree(root / "config", existing / "config")
    source_files = {str(p.relative_to(root)): file_digest(p) for p in (root / "config").rglob("*") if p.is_file()}
    for kind, requirement in manifest["databases"].items():
        path = root / requirement["path"]
        with closing(sqlite3.connect(path)) as source, closing(
            sqlite3.connect(existing / (kind + ".sqlite"))
        ) as target:
            source.execute("PRAGMA user_version=1")
            source.commit()
            source.backup(target)
            target.execute("PRAGMA journal_mode=DELETE")
        source_files[requirement["path"]] = file_digest(path)
    backup_files = {str(p.relative_to(existing)): file_digest(p) for p in existing.rglob("*") if p.is_file()}
    atomic_json(
        existing / "reuse.json",
        {
            "schema_version": 1,
            "root": str(root),
            "current_release_sha256": file_digest(root / "current/release.json"),
            "source_files": source_files,
            "backup_files": backup_files,
        },
    )
    out = root.parent / "reuse-plan.json"
    assert planner.plan(package, config, "test", out)["migrations"] == []
    result, code = executor.apply(out, reuse_backup=existing)
    assert code == 0, result
    assert result["backup"] == str(existing)
    assert not (root / "deployments/backups").exists()
    assert not list((root / "data").rglob("*.schema-0-backup-*"))
