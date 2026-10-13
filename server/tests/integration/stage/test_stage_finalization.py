"""Admission stays fenced until all chat/call finalization writes have stopped."""

import asyncio
from types import SimpleNamespace

import pytest
from support.realtime_speech import FakeRealtimeSpeechSessionFactory

import src.domain.agent as d
from src.adapter.websocket import WebSocketAdapter
from src.agent.context import ContextFactory
from src.application.user.reset_fence import UserResetFence
from src.domain.call import CallAnswerDecision, CallEndReason, CallState
from src.stage import StageManager
from src.stage.call_settlement import CallSettlementConsumerImpl
from src.web.websocket.service import WebSocketConnection

from . import test_call_stage
from .test_call_handoff import connected, manager
from .test_call_stage import (
    _agent,
    _ContextDatabase,
    _eventually,
    _Transport,
    _TurnHandler,
)
from .test_chat_stage import RecordingAgent, Socket, ending_plan


@pytest.fixture
def call_setup(tmp_path):
    return test_call_stage.call_setup.__wrapped__(tmp_path)


async def assert_finalizing(manager, user="user"):
    with pytest.raises(RuntimeError, match="INTERACTION_FINALIZING"):
        await manager.connect(WebSocketConnection(Socket(), user, user), "luotianyi")
    with pytest.raises(RuntimeError, match="INTERACTION_FINALIZING"):
        await manager.start_call(
            user_id=user, character_id="luotianyi", source_interaction_id=None, client_request_id="new-call"
        )
    with pytest.raises(RuntimeError, match="USER_INTERACTION_BUSY"):
        await manager.begin_user_data_reset(user)


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_chat_finalization_rejects_conflicts_and_failure_releases_admission(fail):
    entered, release = asyncio.Event(), asyncio.Event()

    async def handle(request, sink):
        if isinstance(request.stimulus, d.InteractionEnding):
            entered.set()
            await release.wait()
            if fail:
                raise RuntimeError("maintenance failed")
        return await ending_plan(request, sink)

    stages, _, _ = manager(
        agent=RecordingAgent(handle),
        user_reset_fence=UserResetFence(),
        config={"offline_timeout": 0, "stage": {"termination_timeout": 5}},
    )
    connection, old = await connected(stages)
    with pytest.raises(RuntimeError, match="USER_INTERACTION_BUSY"):
        await stages.begin_user_data_reset("user")
    assert not connection.is_closed
    await stages.disconnect(connection)
    await asyncio.wait_for(entered.wait(), 1)
    try:
        await assert_finalizing(stages)
        token = await stages.begin_user_data_reset("other")
        await stages.end_user_data_reset("other", token)
    finally:
        release.set()
        await stages._finalizations.close()
    token = await stages.begin_user_data_reset("user")
    await stages.end_user_data_reset("user", token)
    _, new = await connected(stages)
    assert new.interaction_id != old.interaction_id
    await stages.close()


@pytest.mark.asyncio
async def test_reset_admission_blocks_chat_and_call_until_end():
    stages, _, _ = manager(user_reset_fence=UserResetFence())
    token = await stages.begin_user_data_reset("user")
    with pytest.raises(RuntimeError, match="USER_DATA_RESET_IN_PROGRESS"):
        await connected(stages)
    with pytest.raises(RuntimeError, match="USER_DATA_RESET_IN_PROGRESS"):
        await stages.start_call(
            user_id="user", character_id="luotianyi", source_interaction_id=None, client_request_id="reset-race"
        )
    await stages.end_user_data_reset("user", token)
    await connected(stages)
    await stages.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["success", "failure", "timeout"])
@pytest.mark.parametrize("shutdown", [False, True])
async def test_call_finalization_remains_busy_through_cleanup_and_shutdown(call_setup, mode, shutdown, monkeypatch):
    repository, _, _, clock = call_setup
    entered, release, cancelling = asyncio.Event(), asyncio.Event(), asyncio.Event()
    cleaned = []

    class Consumer:
        is_ready = True

        async def settle(self, snapshot):
            entered.set()
            try:
                await release.wait()
                if mode == "failure":
                    raise RuntimeError("settlement failed")
            except asyncio.CancelledError:
                cancelling.set()
                await release.wait()
                raise

    monkeypatch.setattr(CallSettlementConsumerImpl, "settle", Consumer.settle)
    stages = StageManager(
        get_agent=lambda _: _agent(_TurnHandler()),
        adapter=WebSocketAdapter(),
        get_context_factory=lambda _: ContextFactory(character_id="luotianyi", database=_ContextDatabase()),
        call_sessions=repository,
        conversation_service=object(),
        call_maintenance_batches=object(),
        call_resources=SimpleNamespace(release_call_maintenance=cleaned.append),
        user_reset_fence=UserResetFence(),
        wall_clock=clock.now,
        monotonic=clock.tick,
    )
    assert stages.call_settlement_ready
    stages._call_settlement._timeout = 0.01 if mode == "timeout" else 5
    claim = await stages.start_call(
        user_id="user", character_id="luotianyi", source_interaction_id=None, client_request_id="finalization-call"
    )
    with pytest.raises(RuntimeError, match="USER_INTERACTION_BUSY"):
        await stages.begin_user_data_reset("user")
    stage = await stages.create_call_stage(
        claim,
        user_id="user",
        character_id="luotianyi",
        client_request_id="finalization-call",
        transport=_Transport(),
        speech_factory=FakeRealtimeSpeechSessionFactory(),
    )
    await stage.apply_answer(
        d.AnswerCall(action_id="answer", call_id=claim.record.call_id, decision=CallAnswerDecision.ACCEPT)
    )
    await _eventually(lambda: stage.state is CallState.ACTIVE)
    with pytest.raises(RuntimeError, match="USER_INTERACTION_BUSY"):
        await stages.begin_user_data_reset("user")
    # Real-time cleanup is also a busy phase, before the snapshot reaches the runner.
    cleanup_entered, cleanup_release = asyncio.Event(), asyncio.Event()
    original_close = stage._provider.close

    async def close_provider():
        cleanup_entered.set()
        await cleanup_release.wait()
        await original_close()

    stage._provider.close = close_provider
    ending = asyncio.create_task(stage.terminate(CallEndReason.USER_HANGUP))
    await asyncio.wait_for(cleanup_entered.wait(), 1)
    try:
        await assert_finalizing(stages)
    finally:
        cleanup_release.set()
    await ending
    await asyncio.wait_for(entered.wait(), 1)
    try:
        await assert_finalizing(stages)
        if mode == "timeout":
            await asyncio.wait_for(cancelling.wait(), 1)
            await assert_finalizing(stages)
        await stage.terminate(CallEndReason.USER_HANGUP)
        if shutdown:
            closing = asyncio.create_task(stages.close())
            await asyncio.sleep(0)
            assert not closing.done()
        assert cleaned == []
    finally:
        release.set()
        await stages._finalizations.close()
    if not shutdown:
        token = await stages.begin_user_data_reset("user")
        await stages.end_user_data_reset("user", token)
        await stages.start_call(
            user_id="user", character_id="luotianyi", source_interaction_id=None, client_request_id="after-finalization"
        )
    await stages.close()
    assert cleaned == [claim.record.call_id]
    assert not stages._finalizations.has_user("user")


@pytest.mark.asyncio
@pytest.mark.parametrize("reset_first", [False, True])
async def test_reset_and_chat_admission_cannot_both_succeed(reset_first):
    stages, _, _ = manager(user_reset_fence=UserResetFence())
    operations = [stages.begin_user_data_reset("user"), connected(stages)]
    if not reset_first:
        operations.reverse()
    results = await asyncio.gather(*operations, return_exceptions=True)
    if not reset_first:
        results.reverse()
    reset, chat = results
    assert isinstance(reset, RuntimeError) != isinstance(chat, RuntimeError)
    if isinstance(reset, RuntimeError):
        assert str(reset) == "USER_INTERACTION_BUSY"
    else:
        assert str(chat) == "USER_DATA_RESET_IN_PROGRESS"
        await stages.end_user_data_reset("user", reset)
    await stages.close()
