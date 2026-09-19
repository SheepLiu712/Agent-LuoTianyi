from types import SimpleNamespace

import pytest

from src.system.admin import admin_interface
from src.system.admin.runtime_supervisor import RuntimeSupervisor


def _supervisor(tmp_path):
    return RuntimeSupervisor(
        config_store=SimpleNamespace(),
        secret_store=SimpleNamespace(),
        validator=SimpleNamespace(),
        observability=SimpleNamespace(),
    )


def test_public_status_exposes_only_stable_error_metadata(tmp_path):
    supervisor = _supervisor(tmp_path)
    supervisor.state = "failed"
    supervisor.last_error = "Traceback (most recent call last): C:\\secret\\runtime.py"
    supervisor.last_error_code = "RUNTIME_START_FAILED"
    supervisor.last_error_trace_id = "runtime-test123"

    public = supervisor.public_status()

    assert public["error"] == {
        "code": "RUNTIME_START_FAILED",
        "trace_id": "runtime-test123",
    }
    assert "last_error" not in public
    assert "secret" not in str(public)
    assert "Traceback" not in str(public)
    assert "Traceback" in supervisor.status()["last_error"]


@pytest.mark.asyncio
async def test_unauthenticated_health_uses_public_runtime_status(monkeypatch, tmp_path):
    supervisor = _supervisor(tmp_path)
    supervisor.state = "failed"
    supervisor.last_error = "Traceback: C:\\private\\server.py"
    supervisor.last_error_code = "RUNTIME_START_FAILED"
    supervisor.last_error_trace_id = "runtime-test456"
    shell = SimpleNamespace(
        auth=SimpleNamespace(status=lambda: {"configured": True}),
        runtime_supervisor=supervisor,
        observability=object(),
    )
    monkeypatch.setattr(admin_interface, "get_admin_shell", lambda: shell)

    response = await admin_interface.admin_health()

    assert response["runtime"]["error"]["code"] == "RUNTIME_START_FAILED"
    assert "Traceback" not in str(response)
    assert "private" not in str(response)
