"""真实管理鉴权/配置路由与临时存储；受控Supervisor不冒称实际浏览器A4。"""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.admin.auth import AdminAuthService
from src.infrastructure.config.secrets import SecretStore
from src.infrastructure.config.store import ConfigStore
from src.infrastructure.config.validation import RuntimeConfigValidator
from src.web.admin import admin_interface
from src.web.http import rate_limits
from tests.integration.system.test_admin_runtime import minimal_config


class SupervisorPort:
    def __init__(self, validator, config_store):
        self.validator = validator
        self.config_store = config_store
        self.running = False
        self.calls = []
        self.last_validation = None

    def is_running(self):
        return self.running

    def status(self):
        return {"state": "running" if self.running else "stopped", "running": self.running}

    def validate_current_config(self):
        self.calls.append("validate_current")
        self.last_validation = self.validator.validate(self.config_store.read_resolved())
        return self.last_validation

    async def restart(self):
        self.calls.append("restart")
        return self.status()


@pytest.fixture
def admin_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-jwt")
    rate_limits._reset_rate_limit_state()
    config = minimal_config(tmp_path)
    config["world"]["citywalk"]["enabled"] = False
    store = ConfigStore(tmp_path / "config.json", root_dir=tmp_path)
    store.write_raw(config)
    secrets = SecretStore(tmp_path / "secrets.local.env")
    validator = RuntimeConfigValidator(root_dir=tmp_path, secret_store=secrets)
    auth = AdminAuthService(tmp_path / "admin-auth.json", tmp_path / "setup-token.txt")
    supervisor = SupervisorPort(validator, store)
    shell = SimpleNamespace(
        auth=auth, config_store=store, secret_store=secrets, validator=validator, runtime_supervisor=supervisor
    )
    monkeypatch.setattr(admin_interface, "get_admin_shell", lambda: shell)
    app = FastAPI()
    app.include_router(admin_interface.router)
    with TestClient(app, raise_server_exceptions=False) as client:
        setup = client.post(
            "/admin/api/admin-auth/setup",
            json={
                "setup_token": (tmp_path / "setup-token.txt").read_text(encoding="utf-8"),
                "password": "isolated-admin-password",
            },
        )
        assert setup.status_code == 200
        login = client.post("/admin/api/admin-auth/login", json={"password": "isolated-admin-password"})
        assert login.status_code == 200
        headers = {"Authorization": "Bearer " + login.json()["token"]}
        yield SimpleNamespace(client=client, headers=headers, shell=shell, config=config, root=tmp_path)


def test_admin_get_projects_default_component_startup_with_auth(admin_client):
    state = admin_client
    state.client.cookies.clear()
    assert state.client.get("/admin/api/llm/config").status_code == 401
    response = state.client.get("/admin/api/llm/config", headers=state.headers)

    assert response.status_code == 200
    assert response.json()["component_startup"] == {"speaking_enabled": True, "vector_store_enabled": True}


@pytest.mark.parametrize(
    "payload,path",
    [
        ({"component_startup": {"speaking_enabled": "false"}}, "component_startup.speaking_enabled"),
        ({"component_startup": {"vector_store_enabled": 0}}, "component_startup.vector_store_enabled"),
        ({"component_startup": {"unknown": False}}, "component_startup.unknown"),
        ({"component_startup": None}, "component_startup"),
    ],
)
def test_invalid_component_draft_is_422_and_does_not_write_or_restart(admin_client, payload, path):
    state = admin_client
    before = state.shell.config_store.path.read_bytes()
    state.shell.runtime_supervisor.running = True
    response = state.client.post("/admin/api/llm/config/apply", headers=state.headers, json=payload)

    assert response.status_code == 422
    assert path in str(response.json()["detail"])
    assert state.shell.config_store.path.read_bytes() == before
    assert state.shell.runtime_supervisor.calls == []


@pytest.mark.parametrize("running", [False, True])
def test_valid_component_save_preserves_other_fields_and_restarts_only_running_owner(admin_client, running):
    state = admin_client
    supervisor = state.shell.runtime_supervisor
    supervisor.running = running
    before = state.shell.config_store.read_raw()
    before_bytes = state.shell.config_store.path.read_bytes()
    response = state.client.post(
        "/admin/api/llm/config/apply",
        headers=state.headers,
        json={
            "component_startup": {"speaking_enabled": False},
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["ok"] is True and result["written"] is True
    assert result["restarted"] is running
    assert result["config"]["component_startup"] == {"speaking_enabled": False, "vector_store_enabled": True}
    current = state.shell.config_store.read_raw()
    assert current["agent_runtime"]["skills"]["speaking"].pop("enabled") is False
    assert current == before
    assert supervisor.calls == (["restart"] if running else ["validate_current"])
    backups = list((state.root / "backups").glob("config.*.json"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == before_bytes


def test_failed_validation_does_not_write_or_stop_existing_owner(admin_client):
    state = admin_client
    config = state.shell.config_store.read_raw()
    config["agent_runtime"]["skills"]["reply"] = {}
    state.shell.config_store.write_raw(config)
    before = state.shell.config_store.path.read_bytes()
    state.shell.runtime_supervisor.running = True
    response = state.client.post(
        "/admin/api/llm/config/apply",
        headers=state.headers,
        json={
            "component_startup": {"speaking_enabled": False},
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["ok"] is False and result["written"] is False and result["restarted"] is False
    assert state.shell.config_store.path.read_bytes() == before
    assert state.shell.runtime_supervisor.calls == []
    assert state.shell.runtime_supervisor.running is True


@pytest.mark.parametrize("stop_fails", [False, True])
def test_component_save_uses_real_supervisor_safe_restart_before_new_runtime(admin_client, monkeypatch, stop_fails):
    from src.application.admin.runtime_supervisor import RuntimeSupervisor
    from src.server_runtime import ServerRuntime

    state = admin_client
    calls = []

    class OwnedRuntime:
        async def shutdown(self):
            calls.append("old.shutdown")
            if stop_fails:
                raise RuntimeError("cleanup incomplete")

    class NextRuntime:
        async def shutdown(self):
            calls.append("new.shutdown")

    async def initialize(config, **kwargs):
        calls.append("new.initialize")
        assert config["agent_runtime"]["skills"]["speaking"]["enabled"] is False
        return NextRuntime()

    monkeypatch.setattr(ServerRuntime, "initialize", initialize)
    supervisor = RuntimeSupervisor(
        config_store=state.shell.config_store,
        secret_store=state.shell.secret_store,
        validator=state.shell.validator,
        observability=object(),
    )
    old = OwnedRuntime()
    supervisor._runtime = old
    supervisor.state = "running"
    state.shell.runtime_supervisor = supervisor
    try:
        response = state.client.post(
            "/admin/api/llm/config/apply",
            headers=state.headers,
            json={
                "component_startup": {"speaking_enabled": False},
            },
        )
        assert response.status_code == 200
        result = response.json()
        assert result["written"] is True and result["restarted"] is True
        if stop_fails:
            assert calls == ["old.shutdown"]
            assert supervisor._runtime is old
            assert result["runtime"]["state"] == "failed" and not result["runtime"]["running"]
        else:
            assert calls == ["old.shutdown", "new.initialize"]
            assert result["runtime"]["state"] == "running" and result["runtime"]["running"]
    finally:
        if not stop_fails:
            state.client.portal.call(supervisor.stop)
        from src.server_runtime import set_server_runtime

        set_server_runtime(None)
