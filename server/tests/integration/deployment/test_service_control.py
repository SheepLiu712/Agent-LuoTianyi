"""External service boundary: health semantics and systemd identity checks."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[3]


@pytest.fixture
def control(monkeypatch):
    monkeypatch.syspath_prepend(str(SERVER / "scripts/deploy/release"))
    import service_control

    return service_control


@pytest.mark.parametrize(
    "running,error,expected", [(True, None, True), (False, None, False), (True, {"code": "failed"}, False)]
)
def test_health_requires_running_runtime_without_error(control, running, error, expected):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            if self.path == "/health":
                self.wfile.write(
                    json.dumps(
                        {
                            "status": "ok",
                            "runtime": {
                                "state": "running" if running else "stopped",
                                "running": running,
                                "error": error,
                            },
                        }
                    ).encode()
                )
            else:
                self.wfile.write(b"<html>Admin</html>")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    address = f"http://127.0.0.1:{server.server_port}"
    try:
        result = control.health({"health_url": address + "/health", "admin_url": address + "/admin"})
        assert result["healthy"] is expected
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_wrong_systemd_binding_is_rejected_before_control(control, monkeypatch, tmp_path):
    from deployment_state import DeploymentError

    service = control.Systemd({"service": "test.service", "service_scope": "user"})
    monkeypatch.setattr(service, "query", lambda: {"LoadState": "loaded", "ExecStart": "/other/server"})
    with pytest.raises(DeploymentError, match="绑定本实例"):
        service.preflight(tmp_path)


def test_stop_requires_no_main_pid(control, monkeypatch):
    from deployment_state import DeploymentError

    service = control.Systemd({"service": "test.service", "service_scope": "user"})
    monkeypatch.setattr(control, "run", lambda *args, **kwargs: "")
    monkeypatch.setattr(service, "query", lambda: {"ActiveState": "inactive", "MainPID": "123"})
    with pytest.raises(DeploymentError, match="未完全停止"):
        service.stop()


def test_acceptance_rejects_wrong_instance_paths(control, monkeypatch, tmp_path):
    from deployment_state import DeploymentError

    class Service:
        def query(self):
            return {"ActiveState": "active", "NRestarts": "0"}

    monkeypatch.setattr(control, "actual_release", lambda *args: "target")
    monkeypatch.setattr(control, "health", lambda instance: {"healthy": True})
    monkeypatch.setattr(control, "process_bindings", lambda state: {"AGENTLUO_DATA_DIR": "/other-instance/data"})
    with pytest.raises(DeploymentError, match="路径与目标实例不一致"):
        control.await_healthy(
            Service(),
            {"root": str(tmp_path), "startup_timeout_seconds": 1},
            "target",
            {"AGENTLUO_DATA_DIR": str(tmp_path / "data")},
        )


def test_status_cli_unhealthy_is_successful_read_only_query(tmp_path):
    import os
    import subprocess
    import sys

    binary = tmp_path / "bin"
    binary.mkdir()
    systemctl = binary / "systemctl"
    systemctl.write_text("#!/bin/sh\nprintf 'LoadState=not-found\\nActiveState=inactive\\nMainPID=0\\n'\n")
    systemctl.chmod(0o755)
    root = tmp_path / "absent-instance"
    config = tmp_path / "deploy.toml"
    config.write_text(f'[instances.test]\nroot = "{root}"\nservice = "test.service"\n')
    process = subprocess.run(
        [
            sys.executable,
            str(SERVER / "scripts/deploy/deploy.py"),
            "--config",
            str(config),
            "status",
            "--instance",
            "test",
            "--json",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": str(binary) + os.pathsep + os.environ["PATH"]},
    )
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)["healthy"] is False
    assert not root.exists()


def test_environment_preparation_is_isolated_and_reused(control, monkeypatch, tmp_path):
    import prepare_release

    root = tmp_path / "instance"
    release = root / "releases/new"
    release.mkdir(parents=True)
    old = root / "environments/old"
    old.mkdir(parents=True)
    (old / "sentinel").write_bytes(b"running")
    target = root / "environments/new-env"
    commands = []

    def run(command, *, env, **kwargs):
        commands.append((command, env))
        target.mkdir(exist_ok=True)
        if "playwright" in command:
            Path(env["PLAYWRIGHT_BROWSERS_PATH"]).mkdir()
        return ""

    monkeypatch.setattr(prepare_release, "run", run)
    monkeypatch.setattr(prepare_release.shutil, "which", lambda name: "/fake/uv")
    monkeypatch.setattr(prepare_release, "check_environment", lambda *args: [])
    manifest = {"environment": {"environment_id": "new-env", "python_version": "3.10.22"}}
    assert prepare_release.prepare_environment(root, release, manifest, {}) == target
    assert commands[0][1]["UV_PROJECT_ENVIRONMENT"] == str(target)
    assert commands[1][1]["PLAYWRIGHT_BROWSERS_PATH"] == str(target / "browsers")
    assert (old / "sentinel").read_bytes() == b"running"
    prepare_release.prepare_environment(root, release, manifest, {})
    assert len(commands) == 2


def test_startup_preflight_cannot_initialize_production_data(control, tmp_path):
    import sys

    import prepare_release

    root = tmp_path / "instance"
    (root / "deployments").mkdir(parents=True)
    (root / "config").mkdir()
    (root / "config/secrets.local.env").write_text("SECRET=preserve")
    release = root / "releases/new"
    (release / "config").mkdir(parents=True)
    (release / "config/config.json").write_text('{"is_debug": false, "server": {"production_port": 1}}')
    (release / "server_main.py").write_text(
        "import os,sys,json\nfrom pathlib import Path\n"
        'assert sys.argv[1] == "--check-startup"\n'
        'config=json.loads((Path(os.environ["AGENTLUO_CONFIG_DIR"])/"config.json").read_text())\n'
        'assert config["server"]["production_port"] == 12345\n'
        'data=Path(os.environ["AGENTLUO_DATA_DIR"]);data.mkdir();(data/"probe").write_text("temporary")\n'
    )
    environment = root / "environments/test"
    (environment / "bin").mkdir(parents=True)
    (environment / "bin/python").symlink_to(sys.executable)
    prepare_release.check_startup(
        root, release, environment, root / "assets/test", {"health_url": "http://127.0.0.1:12345/health"}
    )
    assert not (root / "data").exists()
    assert (root / "config/secrets.local.env").read_text() == "SECRET=preserve"
    assert list((root / "deployments").iterdir()) == []


def test_privileged_writer_check_detects_foreign_user_process_without_resolving_target(control, tmp_path):
    from check_writers import check

    root = tmp_path / "instance"
    proc = tmp_path / "proc"
    process = proc / "99999999"
    (process / "fd").mkdir(parents=True)
    (process / "cwd").symlink_to(tmp_path)
    (process / "fd/3").symlink_to(root / "data/database/main.db")
    check(root, check_only=True, proc=proc)
    with pytest.raises(RuntimeError, match="PID 99999999"):
        check(root, proc=proc)
    (process / "fd/3").unlink()
    (process / "fd/3").symlink_to(root / ".runtime/server.lock")
    check(root, proc=proc)


def test_environment_lock_honors_platform_markers_and_optional_extras(control):
    from probe_environment import selected_dependencies

    lock = {
        "package": [
            {
                "name": "agentluo-linux-deployment",
                "source": {"virtual": "."},
                "dependencies": [
                    {"name": "core", "extra": ["speech"]},
                    {"name": "pypy-only", "marker": "platform_python_implementation == 'PyPy'"},
                ],
            },
            {
                "name": "core",
                "source": {"registry": "test"},
                "version": "1",
                "optional-dependencies": {"speech": [{"name": "jaraco.functools"}]},
            },
            {"name": "pypy-only", "source": {"registry": "test"}, "version": "2"},
            {"name": "jaraco.functools", "source": {"registry": "test"}, "version": "3"},
        ]
    }
    assert selected_dependencies(lock) == {"core": "1", "jaraco-functools": "3"}
