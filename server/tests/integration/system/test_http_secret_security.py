from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import server_main
from src.system.admin import admin_interface
from src.system.admin.secret_store import SecretStore
from src.system.user_interface.types import (
    DynamicCommentListQuery,
    DynamicListQuery,
    DynamicUnreadQuery,
    HistoryQuery,
    RegisterRequest,
    ResetAccountRequest,
)


class RecordingUserInterface:
    def __init__(self):
        self.calls = []

    async def get_history(self, username, token, count, end_index, runtime):
        self.calls.append(("history", token))
        return {}

    async def list_dynamics(self, request, runtime):
        self.calls.append(("dynamics", request.token))
        return {}

    async def get_dynamic_unread(self, request, runtime):
        self.calls.append(("unread", request.token))
        return {}

    async def list_dynamic_comments(self, dynamic_id, request, runtime):
        self.calls.append(("comments", request.token))
        return {}

    async def register(self, request, runtime, http_request):
        return {"ok": True}

    async def reset_account(self, request, runtime, http_request):
        return {"ok": True}


@pytest.mark.asyncio
async def test_user_get_routes_accept_tokens_only_from_bearer_header():
    user_interface = RecordingUserInterface()
    runtime = SimpleNamespace(user_interface=user_interface)

    assert "token" not in HistoryQuery.model_fields
    assert "token" not in DynamicListQuery.model_fields
    assert "token" not in DynamicUnreadQuery.model_fields
    assert "token" not in DynamicCommentListQuery.model_fields

    await server_main.get_history(HistoryQuery(username="alice"), "Bearer header-token", runtime)
    await server_main.list_dynamics(DynamicListQuery(username="alice"), "Bearer header-token", runtime)
    await server_main.get_dynamic_unread(DynamicUnreadQuery(username="alice"), "Bearer header-token", runtime)
    await server_main.list_dynamic_comments(
        "dynamic-id",
        DynamicCommentListQuery(username="alice"),
        "Bearer header-token",
        runtime,
    )

    assert user_interface.calls == [
        ("history", "header-token"),
        ("dynamics", "header-token"),
        ("unread", "header-token"),
        ("comments", "header-token"),
    ]


@pytest.mark.parametrize("header", [None, "", "Basic token", "Bearer", "Bearer token extra"])
def test_bearer_header_rejects_missing_or_malformed_values(header):
    with pytest.raises(HTTPException) as exc_info:
        server_main.require_bearer_token(header)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_register_and_reset_route_logs_do_not_contain_invite_code(monkeypatch):
    messages = []

    def record(message, *args):
        messages.append(message % args if args else message)

    monkeypatch.setattr(server_main.logger, "info", record)
    runtime = SimpleNamespace(user_interface=RecordingUserInterface())
    invite_code = "SECRET-INVITE-CODE"

    await server_main.register(
        RegisterRequest(username="alice", password="encrypted", invite_code=invite_code),
        runtime,
        None,
    )
    await server_main.reset_account(
        ResetAccountRequest(
            invite_code=invite_code,
            new_username="alice-renamed",
            new_password="encrypted",
        ),
        runtime,
        None,
    )

    assert invite_code not in "\n".join(messages)


def test_secret_deletion_restores_original_environment(tmp_path, monkeypatch):
    key = "SECRET_STORE_RESTORE_TEST"
    monkeypatch.setenv(key, "deployment-value")
    store = SecretStore(tmp_path / "secrets.env")
    store.write({key: "stored-value"})
    store.load_into_environment()
    assert store.update({key: None}) == {}
    assert __import__("os").environ[key] == "deployment-value"


def test_secret_deletion_removes_environment_key_without_original(tmp_path, monkeypatch):
    key = "SECRET_STORE_REMOVE_TEST"
    monkeypatch.delenv(key, raising=False)
    store = SecretStore(tmp_path / "secrets.env")
    store.write({key: "stored-value"})
    store.load_into_environment()
    store.update({key: None})
    assert key not in __import__("os").environ


@pytest.mark.asyncio
async def test_secret_update_marks_running_runtime_for_restart(tmp_path, monkeypatch):
    store = SecretStore(tmp_path / "secrets.env")
    shell = SimpleNamespace(
        secret_store=store,
        config_store=SimpleNamespace(read_raw=lambda: {}),
        runtime_supervisor=SimpleNamespace(is_running=lambda: True),
    )
    monkeypatch.setattr(admin_interface, "get_admin_shell", lambda: shell)

    result = await admin_interface.update_secrets({"RUNTIME_SECRET_TEST": "new-value"})

    assert result["restart_required"] is True
    assert result["changed_keys"] == ["RUNTIME_SECRET_TEST"]
