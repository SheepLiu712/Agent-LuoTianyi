"""从公开接入接口验证交接、取消与收尾占用，而非模拟 Manager 的中间步骤。"""

import asyncio
import threading

import pytest
from support.call_output import output_sink
from support.call_session_repository import InMemoryCallSessionRepository
from support.realtime_speech import FakeRealtimeSpeechSessionFactory
from support.stage_manager import make_stage_manager

from src.adapter.websocket.chat import WebSocketAdapter
from src.agent.context import ContextFactory
from src.application.user.reset_fence import UserResetFence
from src.domain.call import CallEndReason, CallState

from .test_call_handoff import connected, manager
from .test_call_stage import _agent, _ContextDatabase, _eventually, _Transport, _TurnHandler
from .test_chat_stage import stimulus


async def _get_call(stages, request="new-call"):
    return await stages.try_to_get_stage(
        user_id="user", character_id="luotianyi", stage_type="call", client_request_id=request
    )


@pytest.mark.asyncio
async def test_public_switch_record_failure_preserves_binding_and_chat_input():
    class Repository(InMemoryCallSessionRepository):
        def create_if_absent(self, record):
            raise RuntimeError("database unavailable")

    stages, _, _ = manager(repository=Repository())
    connection, chat = await connected(stages)
    try:
        await stages.prepare_call_transition(connection, character_id="luotianyi", client_request_id="switch")
        with pytest.raises(RuntimeError, match="database unavailable"):
            await _get_call(stages, "switch")
        assert not chat.context.closed
        assert not chat.input_suspended
        assert connection.stage is chat
        assert connection.submit(stimulus())
    finally:
        await stages.close()


@pytest.mark.asyncio
async def test_public_switch_constructor_failure_does_not_revive_old_chat(monkeypatch):
    stages, repository, _ = manager()
    connection, chat = await connected(stages)

    def fail(*_args, **_kwargs):
        raise RuntimeError("stage construction failed")

    monkeypatch.setattr(stages, "_call_stage_creator", fail)
    try:
        await stages.prepare_call_transition(connection, character_id="luotianyi", client_request_id="switch")
        with pytest.raises(RuntimeError, match="stage construction failed"):
            await _get_call(stages, "switch")
        assert chat.context.closed
        assert repository.find_by_request("switch").state is CallState.FAILED
        _, replacement = await connected(stages)
        assert replacement is not chat
    finally:
        await stages.close()


@pytest.mark.asyncio
async def test_cancelled_public_start_waiter_keeps_one_creation_and_reset_exclusion():
    entered, release = threading.Event(), threading.Event()

    class Repository(InMemoryCallSessionRepository):
        def __init__(self):
            super().__init__()
            self.creations = 0

        def create_if_absent(self, record):
            self.creations += 1
            entered.set()
            assert release.wait(5)
            return super().create_if_absent(record)

    repository = Repository()
    stages, _, _ = manager(repository=repository, user_reset_fence=UserResetFence())
    first = asyncio.create_task(_get_call(stages, "same-request"))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        with pytest.raises(RuntimeError, match="USER_INTERACTION_BUSY"):
            await stages.begin_user_data_reset("user")
        second = asyncio.create_task(_get_call(stages, "same-request"))
        release.set()
        stage = await asyncio.wait_for(second, 2)
        assert stage.state is CallState.PREPARING
        assert await _get_call(stages, "same-request") is stage
        assert repository.creations == 1
    finally:
        release.set()
        await stages.close()


@pytest.mark.asyncio
async def test_public_admission_remains_closed_through_settlement_and_context_close():
    settling, release_settlement = asyncio.Event(), asyncio.Event()
    closing, release_close = asyncio.Event(), asyncio.Event()
    stages = make_stage_manager(
        adapter=WebSocketAdapter(),
        get_agent=lambda _: _agent(_TurnHandler()),
        get_context_factory=lambda _: ContextFactory(character_id="luotianyi", database=_ContextDatabase()),
        call_output_sink=output_sink(_Transport()),
        call_sessions=InMemoryCallSessionRepository(),
        realtime_speech_factory=FakeRealtimeSpeechSessionFactory(),
        conversation_service=object(),
        call_maintenance_batches=object(),
        user_reset_fence=UserResetFence(),
    )

    async def settle(_snapshot, *, context):
        settling.set()
        await release_settlement.wait()

    try:
        stage = await _get_call(stages)
        stage._settlement._consumer.settle = settle
        await stage.start()
        context = stage.context
        original_close = context.close

        async def close_context():
            closing.set()
            await release_close.wait()
            await original_close()

        context.close = close_context
        ending = asyncio.create_task(stage.terminate(CallEndReason.USER_HANGUP))
        await asyncio.wait_for(settling.wait(), 1)
        assert not ending.done()
        for phase in ("settling", "closing"):
            if phase == "closing":
                release_settlement.set()
                await asyncio.wait_for(closing.wait(), 1)
            with pytest.raises(RuntimeError, match="INTERACTION_FINALIZING"):
                await _get_call(stages, "another-call")
            with pytest.raises(RuntimeError, match="INTERACTION_FINALIZING"):
                await connected(stages)
            with pytest.raises(RuntimeError, match="USER_INTERACTION_BUSY"):
                await stages.begin_user_data_reset("user")
        release_close.set()
        await ending
        await _eventually(lambda: not stages._finalizations.has_user("user"))
        replacement = await _get_call(stages, "another-call")
        assert replacement.call_id != stage.call_id
    finally:
        release_settlement.set()
        release_close.set()
        await stages.close()
