"""Operator-visible stuck admission, user isolation, and real delivery acknowledgement."""

import asyncio
import json
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from support.stage_manager import make_stage_manager

from src.adapter.websocket.chat import WebSocketAdapter, _diagnostics
from src.application.admin.auth import AdminAuthService
from src.web.admin import admin_interface
from tests.integration.stage.test_chat_stage import RecordingAgent, StageContextFactory


async def until(predicate):
    async def poll():
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(poll(), 2)


@pytest.mark.asyncio
async def test_admin_sees_stalled_user_and_queued_reconnect_without_exposing_locals(tmp_path, monkeypatch):
    gate = asyncio.Event()

    class Factory(StageContextFactory):
        async def create(self, interaction_id, *, mode, user_id):
            private_value = "password-must-not-leak"
            if user_id == "owner":
                await gate.wait()
            assert private_value
            return await super().create(interaction_id, mode=mode, user_id=user_id)

    adapter = WebSocketAdapter()
    factory = Factory()
    manager = make_stage_manager(
        adapter=adapter, get_agent=lambda _: RecordingAgent(), get_context_factory=lambda _: factory
    )
    auth = AdminAuthService(tmp_path / "auth.json", tmp_path / "setup.token")
    auth.sessions["admin-session"] = time.time() + 60
    runtime = SimpleNamespace(
        chat_adapter=adapter,
        database_manager=SimpleNamespace(
            credential_service=SimpleNamespace(get_user_uuid_by_username=lambda name: {"刘": "owner"}.get(name))
        ),
    )
    shell = SimpleNamespace(auth=auth, runtime_supervisor=SimpleNamespace(runtime=runtime))
    monkeypatch.setattr(admin_interface, "get_admin_shell", lambda: shell)
    app = FastAPI()
    app.include_router(admin_interface.router)
    first = asyncio.create_task(adapter.open(user_id="owner", connection_id=object()))
    second = None
    try:
        await until(
            lambda: (
                adapter.connection_diagnostics("owner")["connections"][0]["phase"] == "initializing_stage"
                if adapter.connection_diagnostics("owner")["connections"]
                else False
            )
        )
        second = asyncio.create_task(adapter.open(user_id="owner", connection_id=object()))
        await until(lambda: adapter.connection_diagnostics("owner")["connection_count"] == 2)
        other = await adapter.open(user_id="other", connection_id=object())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            url = "/admin/api/runtime/chat-diagnostics"
            assert (await client.get(url, params={"username": "刘"})).status_code == 401
            response = await client.get(
                url, params={"username": "刘"}, headers={"Authorization": "Bearer admin-session"}
            )
            assert response.status_code == 200
            body = response.json()
            assert body["connection_count"] == 2
            assert {item["phase"] for item in body["connections"]} == {"initializing_stage", "waiting_admission_lock"}
            stage = body["connections"][0]["stage"]
            assert stage["state"] == "preparing"
            assert any(frame["function"] == "create" for frame in stage["tasks"]["initialization"]["frames"])
            assert "password-must-not-leak" not in response.text
            assert (
                await client.get(url, params={"username": "missing"}, headers={"Authorization": "Bearer admin-session"})
            ).status_code == 404
        assert not first.done() and not second.done()  # Inspecting does not release/cancel the stalled operation.
        await adapter.disconnect(other)
    finally:
        gate.set()
        await asyncio.gather(*[task for task in (first, second) if task is not None])
        await adapter.close()
        await manager.close()
    assert adapter.connection_diagnostics("owner")["connections"] == []


@pytest.mark.asyncio
async def test_slow_admission_warns_once_and_ready_means_network_completion(monkeypatch):
    warnings = []
    monkeypatch.setattr(_diagnostics, "_SLOW_READY_SECONDS", 0.01)
    monkeypatch.setattr(
        _diagnostics, "get_logger", lambda _: SimpleNamespace(warning=lambda *args: warnings.append(args))
    )
    adapter = WebSocketAdapter()
    manager = make_stage_manager(
        adapter=adapter, get_agent=lambda _: RecordingAgent(), get_context_factory=lambda _: StageContextFactory()
    )
    handle = await adapter.open(user_id="owner", connection_id=object())
    try:
        assert adapter.connection_diagnostics("owner")["connections"][0]["phase"] == "sending_ready"
        await until(lambda: warnings)
        assert len(warnings) == 1
        assert warnings[0][1] == "owner"
        assert warnings[0][2]["phase"] == "sending_ready"
        output = await adapter.next_output(handle)
        assert json.loads(output.message)["type"] == "chat.ready"
        adapter.complete_output(handle, output.delivery_id)
        await until(lambda: adapter.connection_diagnostics("owner")["connections"][0]["phase"] == "ready_sent")
        await asyncio.sleep(0.02)
        assert len(warnings) == 1
    finally:
        await adapter.close()
        await manager.close()


@pytest.mark.asyncio
async def test_disconnected_connection_remains_diagnosable_until_cleanup_finishes():
    from tests.integration.stage.test_chat_stage import plan, report, stimulus, take

    entered, gate = asyncio.Event(), asyncio.Event()

    async def handle(request, sink):
        from src.domain.agent import InteractionEnding

        if isinstance(request.stimulus, InteractionEnding):
            return report(request)
        value = plan(request)
        await sink.emit(value)
        return report(request, plans=(value.plan_id,))

    async def realize(value, context, sink):
        try:
            await asyncio.Event().wait()
        finally:
            entered.set()
            await gate.wait()

    agent = RecordingAgent(handle, realize)
    adapter = WebSocketAdapter()
    manager = make_stage_manager(
        adapter=adapter,
        get_agent=lambda _: agent,
        get_context_factory=lambda _: StageContextFactory(),
        config={"stage": {"response_wait": 0.01}},
    )
    connection = await adapter.open(user_id="user", connection_id=object())
    stage = adapter._bindings[connection].stage
    stage.stimulus_input_sink.submit(stimulus())
    await take(agent.executions)
    closing = asyncio.create_task(adapter.disconnect(connection))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        snapshot = adapter.connection_diagnostics("user")
        assert snapshot["connection_count"] == 1
        connection_state = snapshot["connections"][0]
        assert connection_state["phase"] == "stopping_stage_tasks"
        assert connection_state["closed"]
        assert connection_state["stage"]["tasks"]["reply"]["state"] == "pending"
        assert any(frame["function"] == "realize" for frame in connection_state["stage"]["tasks"]["reply"]["frames"])
    finally:
        gate.set()
        await closing
        await manager.close()
        await adapter.close()
    assert adapter.connection_diagnostics("user")["connection_count"] == 0
