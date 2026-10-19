"""创建只装配本次通话；耗时初始化与共享资源缺失有明确的接入边界。"""

from dataclasses import replace
from uuid import uuid4

import pytest
from support.call_output import output_sink
from support.call_session_repository import InMemoryCallSessionRepository
from support.chat_connection import StubChatConnection
from support.realtime_speech import FakeRealtimeSpeechSessionFactory

from src.adapter.websocket.chat import WebSocketAdapter
from src.domain.call import CallState
from src.stage import StageManager
from src.stage._call_records import PreparedCall
from src.stage.call_stage import bind_call_stage_creator

from . import test_call_stage
from .test_call_stage import _Transport
from .test_chat_stage import RecordingAgent, Socket, StageContextFactory


@pytest.mark.asyncio
async def test_bound_creator_returns_preparing_without_starting_resources_and_owns_each_settlement(tmp_path):
    repository, record, ownership, clock = test_call_stage.call_setup.__wrapped__(tmp_path)
    agent = RecordingAgent()
    resolutions = []

    class Factory:
        async def create(self, *args, **kwargs):
            pytest.fail("creating a Stage must not initialize Context or Provider")

    factory = Factory()

    def resolve_agent(character_id):
        resolutions.append(character_id)
        return agent

    creator = bind_call_stage_creator(
        get_agent=resolve_agent,
        get_context_factory=lambda _: factory,
        call_sessions=repository,
        conversation_service=object(),
        call_maintenance_batches=object(),
        speech_factory=factory,
        output_sink=output_sink(_Transport()),
        monotonic=clock.tick,
        wall_clock=clock.now,
    )
    first = await creator(PreparedCall(record), ownership=ownership)
    next_record = record.with_update(call_id=uuid4(), client_request_id="next")
    second = await creator(
        PreparedCall(next_record),
        ownership=replace(ownership, call_id=str(next_record.call_id), client_request_id="next"),
    )

    assert first.state is second.state is CallState.PREPARING
    assert first.context is second.context is None
    assert first._initialization is second._initialization is None
    assert resolutions == ["luotianyi", "luotianyi"]
    assert first._settlement is not second._settlement
    assert first._settlement._consumer is not second._settlement._consumer
    assert first._settlement._consumer._agent_settlement._agent is agent
    # No initialization has run, so there are no tasks or external resources to close.


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "missing",
    [
        "call_sessions",
        "conversation_service",
        "call_maintenance_batches",
        "realtime_speech_factory",
        "call_output_sink",
    ],
)
async def test_incomplete_creation_dependencies_reject_call_before_ledger_or_chat_handoff(missing):
    adapter = WebSocketAdapter()
    repository = InMemoryCallSessionRepository()
    resources = dict(
        call_sessions=repository,
        conversation_service=object(),
        call_maintenance_batches=object(),
        realtime_speech_factory=FakeRealtimeSpeechSessionFactory(),
        call_output_sink=output_sink(_Transport()),
    )
    resources[missing] = None
    manager = StageManager(
        get_agent=lambda _: RecordingAgent(),
        get_context_factory=lambda _: StageContextFactory(),
        chat_output_sink=adapter.output_sink,
        detach_stage_binding=adapter.detach_stage_binding,
        **resources,
    )
    adapter.initialize(manager)
    connection = StubChatConnection(Socket(), "user", "device")
    try:
        await manager.initialize()
        assert not manager.call_business_ready
        chat = await adapter._open(connection, "luotianyi")
        with pytest.raises(RuntimeError, match="CALL_INGRESS_UNAVAILABLE"):
            await manager.try_to_get_stage(
                user_id="user", character_id="luotianyi", stage_type="call", client_request_id="unavailable"
            )
        assert repository.find_by_request("unavailable") is None
        assert connection.stage is chat
        assert not chat.input_suspended
        assert not chat.context.closed
    finally:
        await manager.close()
