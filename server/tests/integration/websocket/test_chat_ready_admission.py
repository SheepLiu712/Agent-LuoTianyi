import asyncio
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect

from src.stage import InteractionFinalizing
from src.stage.interaction_lease import InteractionLease, InteractionLeaseRegistry, InteractionSource
from src.stage.stage_manager import InteractionOwnedByCallAdmission, StageManager
from src.web.websocket import endpoint
from src.web.websocket.service import WebSocketConnection, WebSocketService


class Socket:
    def __init__(self):
        self.sent = []
        self.close_codes = []

    async def accept(self):
        pass

    async def send_json(self, event):
        self.sent.append(event)

    async def close(self, code):
        self.close_codes.append(code)


class BoundManager:
    def __init__(self, *, owned_by_call=False, finalizing=False):
        self.finalizing = finalizing
        self.owned_by_call = owned_by_call
        self.connected = []
        self.disconnected = []

    async def connect(self, connection, character_id):
        self.connected.append((connection, character_id))
        if self.finalizing:
            raise InteractionFinalizing()
        if self.owned_by_call:
            raise InteractionOwnedByCallAdmission(InteractionSource.CALL)
        return SimpleNamespace(interaction_id="chat-interaction")

    async def disconnect(self, connection):
        self.disconnected.append(connection)


async def _authenticate(self, _service, _database):
    self.set_user("owner", "alice")
    return True


def _runtime(manager):
    return SimpleNamespace(
        websocket_service=WebSocketService(),
        database_manager=SimpleNamespace(),
        stage_manager=manager,
        agent_runtime=SimpleNamespace(default_character_id="luotianyi"),
        client_llm_executor=SimpleNamespace(clear_user=lambda *_args: None),
    )


@pytest.mark.asyncio
async def test_chat_ready_is_sent_only_after_stage_binding(monkeypatch):
    socket = Socket()
    manager = BoundManager()
    monkeypatch.setattr(
        endpoint,
        "get_admin_shell",
        lambda: SimpleNamespace(runtime_supervisor=SimpleNamespace(runtime=_runtime(manager))),
    )
    monkeypatch.setattr(WebSocketConnection, "auth", _authenticate)

    async def disconnect_after_ready(_runtime, _connection):
        raise WebSocketDisconnect()

    monkeypatch.setattr(endpoint, "_receive_events", disconnect_after_ready)
    await endpoint.chat_ws(socket)

    assert [event["type"] for event in socket.sent] == ["system_ready", "chat.ready"]
    assert socket.sent[-1]["payload"] == {
        "character_id": "luotianyi",
        "interaction_id": "chat-interaction",
        "schema_version": 1,
    }
    assert manager.disconnected


@pytest.mark.asyncio
@pytest.mark.parametrize("finalizing", [False, True])
async def test_busy_chat_admission_sends_retryable_error_without_chat_ready(monkeypatch, finalizing):
    socket = Socket()
    manager = BoundManager(owned_by_call=True, finalizing=finalizing)
    monkeypatch.setattr(
        endpoint,
        "get_admin_shell",
        lambda: SimpleNamespace(runtime_supervisor=SimpleNamespace(runtime=_runtime(manager))),
    )
    monkeypatch.setattr(WebSocketConnection, "auth", _authenticate)

    await endpoint.chat_ws(socket)

    assert [event["type"] for event in socket.sent] == ["system_ready", "error"]
    assert socket.sent[-1]["payload"] == {
        "code": "INTERACTION_FINALIZING" if finalizing else "INTERACTION_OWNED_BY_CALL",
        "message": "interaction is temporarily unavailable",
        "retryable": True,
    }
    assert socket.close_codes == [1013]


@pytest.mark.asyncio
async def test_stage_manager_rejects_call_ownership_before_chat_stage_creation():
    registry = InteractionLeaseRegistry()
    assert registry.claim(InteractionLease("owner", "luotianyi", "call-id", InteractionSource.CALL))
    created = []
    manager = StageManager(
        get_agent=lambda _character_id: created.append(True),
        get_context_factory=lambda _character_id: None,
        adapter=SimpleNamespace(),
        lease_registry=registry,
    )
    connection = WebSocketConnection(Socket(), "owner", "alice")

    with pytest.raises(InteractionOwnedByCallAdmission) as error:
        await manager.connect(connection, "luotianyi")

    assert error.value.source is InteractionSource.CALL
    assert created == []
    await manager.close()


@pytest.mark.asyncio
async def test_chat_lease_is_not_rejected_by_typed_call_admission_gate():
    registry = InteractionLeaseRegistry()
    assert registry.claim(InteractionLease("owner", "luotianyi", "chat-id", InteractionSource.CHAT))
    assert registry.current("owner", "luotianyi").source is InteractionSource.CHAT
    await asyncio.sleep(0)
