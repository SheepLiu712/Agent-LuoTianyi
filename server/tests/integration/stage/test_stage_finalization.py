"""Admission stays fenced until all chat/call finalization writes have stopped."""

import asyncio
import threading

import pytest
from support.chat_connection import StubChatConnection
from support.realtime_speech import FakeRealtimeSpeechSessionFactory
from support.stage_manager import create_call_stage, make_stage_manager

import src.domain.agent as d
from src.adapter.websocket.chat import WebSocketAdapter
from src.agent.context import ContextFactory
from src.application.user.reset_fence import UserResetFence
from src.domain.call import CallAnswerDecision, CallEndReason, CallState
from src.stage._call_history import CallHistory

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
        await manager._test_chat_adapter._open(StubChatConnection(Socket(), user, user), "luotianyi")
    with pytest.raises(RuntimeError, match="INTERACTION_FINALIZING"):
        await manager._claim_call(
            user_id=user,
            character_id="luotianyi",
            source_interaction_id=None,
            client_request_id="new-call",
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
    await stages._test_chat_adapter._close_connection(connection)
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
        await stages._claim_call(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id=None,
            client_request_id="reset-race",
        )
    await stages.end_user_data_reset("user", token)
    await connected(stages)
    await stages.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["success", "failure"])
@pytest.mark.parametrize("shutdown", [False, True])
async def test_call_finalization_remains_busy_through_cleanup_and_shutdown(call_setup, mode, shutdown, monkeypatch):
    repository, _, _, clock = call_setup
    entered, release, cancelling = asyncio.Event(), asyncio.Event(), asyncio.Event()
    cleaned = []

    class Consumer:
        is_ready = True

        async def settle(self, snapshot, *, result=None):
            entered.set()
            try:
                await release.wait()
                if mode == "failure":
                    raise RuntimeError("settlement failed")
            except asyncio.CancelledError:
                cancelling.set()
                await release.wait()
                raise

    monkeypatch.setattr(CallHistory, "save", Consumer.settle)
    stages = make_stage_manager(
        get_agent=lambda _: _agent(_TurnHandler()),
        adapter=WebSocketAdapter(),
        get_context_factory=lambda _: ContextFactory(character_id="luotianyi", database=_ContextDatabase()),
        call_sessions=repository,
        conversation_service=object(),
        call_maintenance_batches=object(),
        user_reset_fence=UserResetFence(),
        wall_clock=clock.now,
        monotonic=clock.tick,
    )
    assert stages.call_business_ready
    claim = await stages._claim_call(
        user_id="user",
        character_id="luotianyi",
        source_interaction_id=None,
        client_request_id="finalization-call",
    )
    with pytest.raises(RuntimeError, match="USER_INTERACTION_BUSY"):
        await stages.begin_user_data_reset("user")
    stage = await create_call_stage(
        stages,
        claim,
        user_id="user",
        character_id="luotianyi",
        client_request_id="finalization-call",
        transport=_Transport(),
        speech_factory=FakeRealtimeSpeechSessionFactory(),
    )
    await stage.apply_answer(
        d.AnswerCall(
            action_id="answer",
            call_id=claim.prepared._record.call_id,
            decision=CallAnswerDecision.ACCEPT,
        )
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
    await stage.wait_realtime_stopped()
    assert not ending.done()
    await asyncio.wait_for(entered.wait(), 1)
    try:
        await assert_finalizing(stages)
        if mode == "timeout":
            await asyncio.wait_for(cancelling.wait(), 1)
            await assert_finalizing(stages)
        assert stage.begin_termination(CallEndReason.USER_HANGUP) is stage._termination
        if shutdown:
            closing = asyncio.create_task(stages.close())
            await asyncio.sleep(0)
            assert not closing.done()
    finally:
        release.set()
        await stages._finalizations.close()
        if mode == "failure":
            with pytest.raises(RuntimeError, match="settlement failed"):
                await ending
        else:
            await ending
    if not shutdown:
        token = await stages.begin_user_data_reset("user")
        await stages.end_user_data_reset("user", token)
        await stages._claim_call(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id=None,
            client_request_id="after-finalization",
        )
    await stages.close()
    assert cleaned == []
    assert not stages._finalizations.has_user("user")


@pytest.mark.asyncio
async def test_call_termination_waiter_cancellation_keeps_one_owned_task_and_first_reason(
    call_setup,
):
    repository, _, _, clock = call_setup
    stages = make_stage_manager(
        get_agent=lambda _: _agent(_TurnHandler()),
        adapter=WebSocketAdapter(),
        get_context_factory=lambda _: ContextFactory(character_id="luotianyi", database=_ContextDatabase()),
        call_sessions=repository,
        conversation_service=object(),
        call_maintenance_batches=object(),
        user_reset_fence=UserResetFence(),
        wall_clock=clock.now,
        monotonic=clock.tick,
    )

    async def settle(_snapshot, *, result=None):
        pass

    claim = await stages._claim_call(
        user_id="user",
        character_id="luotianyi",
        source_interaction_id=None,
        client_request_id="terminate-owned",
    )
    stage = await create_call_stage(
        stages,
        claim,
        user_id="user",
        character_id="luotianyi",
        client_request_id="terminate-owned",
        transport=_Transport(),
        speech_factory=FakeRealtimeSpeechSessionFactory(),
    )
    stage._save_history = settle
    entered, release = asyncio.Event(), asyncio.Event()
    settlement_entered, settlement_release = asyncio.Event(), asyncio.Event()
    original_close = stage._provider.close
    close_calls = 0

    async def close_provider():
        nonlocal close_calls
        close_calls += 1
        entered.set()
        await release.wait()
        await original_close()

    settlement_calls = 0

    async def settle(_snapshot, *, result=None):
        nonlocal settlement_calls
        settlement_calls += 1
        settlement_entered.set()
        await settlement_release.wait()

    stage._save_history = settle

    stage._provider.close = close_provider
    first = asyncio.create_task(stage.terminate(CallEndReason.USER_HANGUP))
    await asyncio.wait_for(entered.wait(), 1)
    second = asyncio.create_task(stage.terminate(CallEndReason.SYSTEM_FAILURE))
    second.cancel()
    with pytest.raises(asyncio.CancelledError):
        await second
    assert not first.done()
    assert close_calls == 1
    await assert_finalizing(stages)
    release.set()
    await asyncio.wait_for(settlement_entered.wait(), 1)
    assert not first.done()
    snapshot = stage.snapshot
    assert snapshot.terminal.end_reason is CallEndReason.USER_HANGUP
    assert close_calls == 1
    assert settlement_calls == 1
    third = asyncio.create_task(stage.terminate(CallEndReason.PROVIDER_FAILED))
    await asyncio.sleep(0)
    assert not third.done()
    assert settlement_calls == 1
    settlement_release.set()
    assert await first is snapshot
    assert await third is snapshot
    await stages.close()


@pytest.mark.asyncio
async def test_terminate_during_context_initialization_prevents_late_resources(
    call_setup,
):
    repository, _, _, clock = call_setup
    create_entered, create_release = asyncio.Event(), asyncio.Event()
    created_contexts = []
    speech_factory = FakeRealtimeSpeechSessionFactory()

    class CapturingTransport(_Transport):
        def bind_stage(self, stage):
            self.stage = stage

    transport = CapturingTransport()

    class SlowFactory:
        async def create(self, *args, **kwargs):
            create_entered.set()
            await create_release.wait()
            context = await ContextFactory(character_id="luotianyi", database=_ContextDatabase()).create(
                *args, **kwargs
            )
            created_contexts.append(context)
            return context

    stages = make_stage_manager(
        get_agent=lambda _: _agent(_TurnHandler()),
        adapter=WebSocketAdapter(),
        get_context_factory=lambda _: SlowFactory(),
        call_sessions=repository,
        conversation_service=object(),
        call_maintenance_batches=object(),
        user_reset_fence=UserResetFence(),
        wall_clock=clock.now,
        monotonic=clock.tick,
    )
    claim = await stages._claim_call(
        user_id="user",
        character_id="luotianyi",
        source_interaction_id=None,
        client_request_id="terminate-start",
    )
    creation = asyncio.create_task(
        create_call_stage(
            stages,
            claim,
            user_id="user",
            character_id="luotianyi",
            client_request_id="terminate-start",
            transport=transport,
            stage_created=transport.bind_stage,
            speech_factory=speech_factory,
        )
    )
    await asyncio.wait_for(create_entered.wait(), 1)
    ownership = stages._current_call_ownership(str(claim.prepared._record.call_id))
    assert ownership is not None
    stage = transport.stage
    stage._save_history = lambda *args, **kwargs: asyncio.sleep(0)
    snapshot = await stage.terminate(CallEndReason.USER_HANGUP)
    assert snapshot.terminal.end_reason is CallEndReason.USER_HANGUP
    create_release.set()
    assert await creation is stage
    await asyncio.sleep(0)
    assert created_contexts == []
    assert speech_factory.sessions == {}
    assert stages._call_stages.get(str(claim.prepared._record.call_id)) is None
    await stages.close()


class _RecordingContextFactory:
    def __init__(self, contexts):
        self.contexts = contexts

    async def create(self, *args, **kwargs):
        context = await ContextFactory(character_id="luotianyi", database=_ContextDatabase()).create(*args, **kwargs)
        original_close = context.close

        async def close():
            context.was_closed = True
            await original_close()

        context.was_closed = False
        context.close = close
        self.contexts.append(context)
        return context


class _BlockingProvider:
    def __init__(self, blocked_phase, entered, release):
        self.blocked_phase, self.entered, self.release = blocked_phase, entered, release
        self.closed = False

    async def start(self, _config):
        if self.blocked_phase == "provider_start":
            self.entered.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                await self.release.wait()
                raise

    async def close(self):
        self.closed = True

    async def events(self):
        if False:
            yield None

    async def wait_failure(self):
        await asyncio.Event().wait()


class _BlockingSpeechFactory:
    def __init__(self, blocked_phase, entered, release, providers):
        self.blocked_phase, self.entered, self.release = blocked_phase, entered, release
        self.providers = providers

    async def create(self, _call_id):
        provider = _BlockingProvider(self.blocked_phase, self.entered, self.release)
        self.providers.append(provider)
        if self.blocked_phase == "provider_create":
            self.entered.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                await self.release.wait()
                return provider
        return provider


class _CapturingTransport(_Transport):
    def bind_stage(self, stage):
        self.stage = stage


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_phase", ["provider_create", "provider_start"])
async def test_terminate_after_context_creation_closes_partial_provider_resources(call_setup, blocked_phase):
    repository, _, _, clock = call_setup
    entered, release = asyncio.Event(), asyncio.Event()
    contexts, providers = [], []
    context_factory = _RecordingContextFactory(contexts)
    speech_factory = _BlockingSpeechFactory(blocked_phase, entered, release, providers)
    transport = _CapturingTransport()
    stages = make_stage_manager(
        get_agent=lambda _: _agent(_TurnHandler()),
        adapter=WebSocketAdapter(),
        get_context_factory=lambda _: context_factory,
        call_sessions=repository,
        conversation_service=object(),
        call_maintenance_batches=object(),
        user_reset_fence=UserResetFence(),
        wall_clock=clock.now,
        monotonic=clock.tick,
    )
    claim = await stages._claim_call(
        user_id="user",
        character_id="luotianyi",
        source_interaction_id=None,
        client_request_id=blocked_phase,
    )
    creation = asyncio.create_task(
        create_call_stage(
            stages,
            claim,
            user_id="user",
            character_id="luotianyi",
            client_request_id=blocked_phase,
            transport=transport,
            stage_created=transport.bind_stage,
            speech_factory=speech_factory,
        )
    )
    await asyncio.wait_for(entered.wait(), 1)
    transport.stage._save_history = lambda _snapshot, **_kwargs: asyncio.sleep(0)
    ending = asyncio.create_task(transport.stage.terminate(CallEndReason.USER_HANGUP))
    await asyncio.sleep(0)
    assert not ending.done()
    release.set()
    snapshot = await ending
    assert snapshot.terminal.end_reason is CallEndReason.USER_HANGUP
    assert await creation is transport.stage
    await stages._finalizations.close()
    assert len(contexts) == 1 and contexts[0].was_closed
    assert len(providers) == 1 and providers[0].closed
    assert stages._call_stages.get(str(claim.prepared._record.call_id)) is None
    await stages.close()


@pytest.mark.asyncio
async def test_full_termination_waits_for_real_thread_write_before_releasing_admission(call_setup, monkeypatch):
    repository, _, _, clock = call_setup
    thread_started, thread_release, thread_finished = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )

    class Consumer:
        is_ready = True

        async def settle(self, _snapshot, *, result=None):
            from src.utils.owned_operation import complete_owned

            def write():
                thread_started.set()
                thread_release.wait()
                thread_finished.set()

            await complete_owned(asyncio.to_thread(write))

    monkeypatch.setattr(CallHistory, "save", Consumer.settle)
    stages = make_stage_manager(
        get_agent=lambda _: _agent(_TurnHandler()),
        adapter=WebSocketAdapter(),
        get_context_factory=lambda _: ContextFactory(character_id="luotianyi", database=_ContextDatabase()),
        call_sessions=repository,
        conversation_service=object(),
        call_maintenance_batches=object(),
        user_reset_fence=UserResetFence(),
        wall_clock=clock.now,
        monotonic=clock.tick,
    )
    claim = await stages._claim_call(
        user_id="user",
        character_id="luotianyi",
        source_interaction_id=None,
        client_request_id="thread-write",
    )
    stage = await create_call_stage(
        stages,
        claim,
        user_id="user",
        character_id="luotianyi",
        client_request_id="thread-write",
        transport=_Transport(),
        speech_factory=FakeRealtimeSpeechSessionFactory(),
    )
    ending = asyncio.create_task(stage.terminate(CallEndReason.USER_HANGUP))
    await asyncio.wait_for(asyncio.to_thread(thread_started.wait, 3), 4)
    assert not ending.done()
    await asyncio.sleep(0.02)
    assert not thread_finished.is_set()
    await assert_finalizing(stages)
    closing = asyncio.create_task(stages.close())
    await asyncio.sleep(0)
    assert not closing.done()
    thread_release.set()
    await closing
    await ending
    assert thread_finished.is_set()


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


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_count", [1, 2])
async def test_cancelled_finalization_waiter_keeps_context_close_and_admission_owned(call_setup, cancel_count):
    repository, _, _, clock = call_setup
    close_entered, close_release = threading.Event(), threading.Event()
    contexts = []
    context_factory = _RecordingContextFactory(contexts)

    class Consumer:
        is_ready = True

        async def settle(self, _snapshot, *, result=None):
            pass

    stages = make_stage_manager(
        get_agent=lambda _: _agent(_TurnHandler()),
        adapter=WebSocketAdapter(),
        get_context_factory=lambda _: context_factory,
        call_sessions=repository,
        conversation_service=object(),
        call_maintenance_batches=object(),
        user_reset_fence=UserResetFence(),
        wall_clock=clock.now,
        monotonic=clock.tick,
    )
    claim = await stages._claim_call(
        user_id="user",
        character_id="luotianyi",
        source_interaction_id=None,
        client_request_id="close-owned",
    )
    stage = await create_call_stage(
        stages,
        claim,
        user_id="user",
        character_id="luotianyi",
        client_request_id="close-owned",
        transport=_Transport(),
        speech_factory=FakeRealtimeSpeechSessionFactory(),
    )
    stage._save_history = Consumer().settle
    await stage.apply_answer(
        d.AnswerCall(
            action_id="answer",
            call_id=claim.prepared._record.call_id,
            decision=CallAnswerDecision.ACCEPT,
        )
    )
    context = contexts[0]
    original_close = context.close

    async def blocked_close():
        close_entered.set()
        await asyncio.to_thread(close_release.wait, 5)
        await original_close()

    context.close = blocked_close
    ending = asyncio.create_task(stage.terminate(CallEndReason.USER_HANGUP))
    assert await asyncio.to_thread(close_entered.wait, 2)
    finalization = stages._finalizations._tasks[str(claim.prepared._record.call_id)].finalization
    for _ in range(cancel_count):
        finalization.cancel()
        await asyncio.sleep(0)

    assert finalization.done() is False
    assert context.was_closed is False
    with pytest.raises(RuntimeError, match="USER_INTERACTION_BUSY"):
        await stages.begin_user_data_reset("user")
    close_release.set()
    result = await asyncio.gather(finalization, return_exceptions=True)
    with pytest.raises(asyncio.CancelledError):
        await ending

    assert isinstance(result[0], asyncio.CancelledError)
    assert context.was_closed is True
    token = await stages.begin_user_data_reset("user")
    await stages.end_user_data_reset("user", token)
    await stages.close()
