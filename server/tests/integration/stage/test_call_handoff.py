import asyncio
import json
import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from support.call_output import output_sink
from support.call_session_repository import InMemoryCallSessionRepository
from support.chat_connection import StubChatConnection
from support.stage_manager import create_call_stage, make_stage_manager

import src.domain.agent as d
from src.adapter.websocket.chat import WebSocketAdapter
from src.agent.context import ContextFactory, ConversationMode
from src.application.user.reset_fence import UserResetFence
from src.domain.call import CallEndReason, CallState
from src.domain.stage.lifecycle import StageEndReason, StageStartAborted
from src.infrastructure.persistence.call_sessions import SqlCallSessionRepository
from src.infrastructure.persistence.database.sql_database import Base
from src.stage.interaction_lease import InteractionLeaseRegistry, InteractionSource
from tests.integration.stage.test_call_stage import _ContextDatabase, _eventually, _Transport

from .test_chat_stage import RecordingAgent, Socket, StageContextFactory, stimulus


def manager(
    *,
    agent=None,
    clock=None,
    config=None,
    repository=None,
    lease_registry=None,
    user_reset_fence=None,
):
    adapter = WebSocketAdapter()
    repository = repository or InMemoryCallSessionRepository()

    class Factory(StageContextFactory):
        async def create(self, interaction_id, *, mode, user_id, **kwargs):
            if mode is ConversationMode.CALL:
                return await ContextFactory(character_id=self.character_id, database=_ContextDatabase()).create(
                    interaction_id, mode=mode, user_id=user_id, **kwargs
                )
            context = await super().create(interaction_id, mode=mode, user_id=user_id)

            async def refresh():
                pass

            context.conversation.refresh = refresh
            return context

    factory = Factory()
    manager = make_stage_manager(
        get_agent=lambda _character: agent or RecordingAgent(),
        adapter=adapter,
        get_context_factory=lambda _character: factory,
        call_sessions=repository,
        call_output_sink=output_sink(_Transport()),
        lease_registry=lease_registry,
        user_reset_fence=user_reset_fence,
        wall_clock=clock or (lambda: datetime.now(timezone.utc)),
        config=config or {"offline_timeout": 60.0, "stage": {"termination_timeout": 0.2}},
    )
    return manager, repository, factory


async def connected(manager, user="user"):
    connection = StubChatConnection(Socket(), user, user)
    stage = await manager._test_chat_adapter._open(connection, "luotianyi")
    return connection, stage


@pytest.mark.asyncio
async def test_prepare_requires_current_bound_connection_and_is_one_shot():
    stage_manager, _, _ = manager()
    connection, stage = await connected(stage_manager)
    other = StubChatConnection(Socket(), "user", "other-device")

    intent = await stage_manager.prepare_call_transition(
        connection,
        character_id="luotianyi",
        client_request_id="request-1",
    )
    repeated = await stage_manager.prepare_call_transition(
        connection,
        character_id="luotianyi",
        client_request_id="request-1",
    )

    assert intent == repeated
    assert intent.source_interaction_id == stage.interaction_id
    with pytest.raises(ValueError, match="not bound"):
        await stage_manager.prepare_call_transition(other, character_id="luotianyi", client_request_id="request-2")
    with pytest.raises(ValueError, match="already exists"):
        await stage_manager.prepare_call_transition(
            connection,
            character_id="luotianyi",
            client_request_id="request-2",
        )


@pytest.mark.asyncio
async def test_prepare_suspends_business_input_and_expiry_restores_it():
    stage_manager, _, _ = manager(
        config={"offline_timeout": 60.0},
        lease_registry=InteractionLeaseRegistry(intent_ttl_seconds=0.01),
    )
    connection, stage = await connected(stage_manager)

    intent = await stage_manager.prepare_call_transition(
        connection,
        character_id="luotianyi",
        client_request_id="request-1",
    )

    assert stage.input_suspended
    assert not stage.stimulus_input_sink.can_accept(stimulus())
    assert not stage.stimulus_input_sink.submit(stimulus())
    acceptance = await stage_manager._test_chat_adapter._receive(
        connection,
        SimpleNamespace(event_type="user_text", payload={}, client_msg_id="msg-1"),
    )
    assert acceptance.code == "CALL_SWITCH_PENDING"
    assert acceptance.retryable is True
    await asyncio.sleep(max(0.0, intent.expires_at - asyncio.get_running_loop().time()) + 0.01)
    assert not stage.input_suspended
    assert stage.state.value == "online"


@pytest.mark.asyncio
async def test_adapter_routes_switch_prepare_and_keeps_binding_until_commit():
    stage_manager, _, _ = manager()
    connection, stage = await connected(stage_manager)
    adapter = stage_manager._test_chat_adapter
    raw = {
        "protocol": "call.v1",
        "type": "call.switch_prepare",
        "client_request_id": "request-1",
        "character_id": "luotianyi",
    }
    event = SimpleNamespace(event_type="call.switch_prepare", raw_event=raw, raw_text=json.dumps(raw))
    try:
        result = await adapter._receive(connection, event)
        assert result["type"] == "call.switch_ready"
        assert stage.input_suspended
        assert adapter._routes[stage.interaction_id] is connection
        claim = await stage_manager._claim_call(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id=stage.interaction_id,
            client_request_id="request-1",
        )
        assert claim.prepared._record.call_id
        assert stage.interaction_id in adapter._routes
        await stage_manager._create_call_stage(
            claim, user_id="user", character_id="luotianyi", client_request_id="request-1"
        )
        assert stage.interaction_id not in adapter._routes
    finally:
        await stage_manager.close()


@pytest.mark.asyncio
async def test_failed_adapter_bind_releases_connection_and_expires_stage(monkeypatch):
    stage_manager, _, _ = manager(config={"offline_timeout": 0})
    adapter = stage_manager._test_chat_adapter
    connection = StubChatConnection(Socket(), "user", "user")

    async def fail_bind(*args):
        raise RuntimeError("bind failed")

    monkeypatch.setattr(adapter, "_bind", fail_bind)
    with pytest.raises(RuntimeError, match="bind failed"):
        await adapter._open(connection, "luotianyi")
    assert not stage_manager._connections
    await asyncio.sleep(0)
    await stage_manager.close()
    assert not adapter._routes


@pytest.mark.asyncio
async def test_call_start_closes_chat_context_before_returning_call_claim():
    stage_manager, repository, _ = manager()
    connection, stage = await connected(stage_manager)
    await stage_manager.prepare_call_transition(connection, character_id="luotianyi", client_request_id="request-1")

    claim = await start_claim(
        stage_manager,
        user_id="user",
        character_id="luotianyi",
        source_interaction_id=stage.interaction_id,
        client_request_id="request-1",
    )

    assert stage.context.closed is True
    assert stage.state.value == "terminated"
    assert claim.prepared._record.state is CallState.PREPARING
    assert stage_manager._lease_registry.current("user", "luotianyi").source is InteractionSource.CALL
    assert repository.find_by_request("request-1").call_id == claim.prepared._record.call_id


@pytest.mark.asyncio
async def test_duplicate_call_start_returns_same_claim_without_intent():
    stage_manager, _, _ = manager()
    connection, stage = await connected(stage_manager)
    await stage_manager.prepare_call_transition(connection, character_id="luotianyi", client_request_id="request-1")
    first = await stage_manager._claim_call(
        user_id="user",
        character_id="luotianyi",
        source_interaction_id=stage.interaction_id,
        client_request_id="request-1",
    )
    duplicate = await stage_manager._claim_call(
        user_id="user",
        character_id="luotianyi",
        source_interaction_id="already-retired",
        client_request_id="request-1",
    )

    assert duplicate.prepared._record.call_id == first.prepared._record.call_id
    assert duplicate.duplicate is True
    assert duplicate.lease == first.lease
    assert duplicate.setup_deadline == first.setup_deadline


@pytest.mark.asyncio
async def test_take_call_claim_validates_identity_and_preserves_deadline_for_duplicates():
    stage_manager, _, _ = manager()
    connection, stage = await connected(stage_manager)
    await stage_manager.prepare_call_transition(connection, character_id="luotianyi", client_request_id="request-1")
    claim = await stage_manager._claim_call(
        user_id="user",
        character_id="luotianyi",
        source_interaction_id=stage.interaction_id,
        client_request_id="request-1",
    )

    with pytest.raises(ValueError, match="identity mismatch"):
        stage_manager._take_call_claim(
            claim,
            user_id="other",
            character_id="luotianyi",
            client_request_id="request-1",
        )
    ownership = stage_manager._take_call_claim(
        claim,
        user_id="user",
        character_id="luotianyi",
        client_request_id="request-1",
    )
    with pytest.raises(ValueError, match="not pending"):
        stage_manager._take_call_claim(
            claim,
            user_id="user",
            character_id="luotianyi",
            client_request_id="request-1",
        )
    duplicate = await stage_manager._claim_call(
        user_id="user",
        character_id="luotianyi",
        source_interaction_id="retired",
        client_request_id="request-1",
    )

    assert ownership.setup_deadline == claim.setup_deadline == duplicate.setup_deadline
    assert stage_manager._current_call_ownership(str(claim.prepared._record.call_id)) == ownership


@pytest.mark.asyncio
async def test_release_call_rejects_stale_or_wrong_ownership_and_cleans_deadline():
    stage_manager, _, _ = manager()
    claim = await stage_manager._claim_call(
        user_id="user",
        character_id="luotianyi",
        source_interaction_id=None,
        client_request_id="request-direct",
    )
    ownership = stage_manager._take_call_claim(
        claim,
        user_id="user",
        character_id="luotianyi",
        client_request_id="request-direct",
    )
    wrong = type(ownership)(
        call_id="wrong",
        user_id=ownership.user_id,
        character_id=ownership.character_id,
        client_request_id=ownership.client_request_id,
        setup_deadline=ownership.setup_deadline,
        generation=ownership.generation,
    )

    assert not stage_manager._release_call(wrong)
    stage_manager._finish_transition(stage_manager._handoffs[ownership.call_id].ownership, call_id=ownership.call_id)
    assert stage_manager._release_call(ownership)
    assert not stage_manager._release_call(ownership)
    assert stage_manager._current_call_ownership(ownership.call_id) is None
    assert "request-direct" not in stage_manager._call_setup_deadlines


@pytest.mark.asyncio
async def test_setup_deadline_is_captured_before_background_task_runs():
    calls = []

    def monotonic():
        calls.append(len(calls))
        return 100.0 + len(calls) - 1

    stage_manager, _, _ = manager()
    stage_manager._monotonic = monotonic

    claim = await stage_manager._claim_call(
        user_id="user",
        character_id="luotianyi",
        source_interaction_id=None,
        client_request_id="request-direct",
    )

    assert claim.setup_deadline == 110.0
    assert calls[0] == 0


@pytest.mark.asyncio
async def test_concurrent_duplicate_start_shares_one_handoff_and_one_winner():
    stage_manager, repository, _ = manager()
    connection, stage = await connected(stage_manager)
    await stage_manager.prepare_call_transition(connection, character_id="luotianyi", client_request_id="request-1")

    first, second = await asyncio.gather(
        stage_manager._claim_call(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id=stage.interaction_id,
            client_request_id="request-1",
        ),
        stage_manager._claim_call(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id=stage.interaction_id,
            client_request_id="request-1",
        ),
    )

    assert first.prepared._record.call_id == second.prepared._record.call_id
    assert first.setup_deadline == second.setup_deadline
    assert repository.find_by_request("request-1").call_id == first.prepared._record.call_id
    assert stage.context.closed is False


@pytest.mark.asyncio
async def test_wrong_request_or_source_does_not_retire_chat():
    stage_manager, repository, _ = manager()
    connection, stage = await connected(stage_manager)
    await stage_manager.prepare_call_transition(connection, character_id="luotianyi", client_request_id="request-1")

    with pytest.raises(ValueError, match="matching call transition"):
        await stage_manager._claim_call(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id=stage.interaction_id,
            client_request_id="wrong",
        )

    assert stage.state.value == "online"
    assert stage.context.closed is False
    assert repository.find_by_request("wrong") is None


@pytest.mark.asyncio
async def test_termination_maintenance_failure_marks_ledger_failed_and_releases_ownership():
    async def failed_realize(_plan, _context, _sink):
        return SimpleNamespace(
            status=d.ExecutionStatus.FAILED,
            error_code=d.ExecutionErrorCode.INTERNAL_ERROR,
        )

    stage_manager, repository, _ = manager(agent=RecordingAgent(realize=failed_realize))
    connection, stage = await connected(stage_manager)
    await stage_manager.prepare_call_transition(connection, character_id="luotianyi", client_request_id="request-1")

    with pytest.raises(RuntimeError, match="initialization failed"):
        await start_claim(
            stage_manager,
            user_id="user",
            character_id="luotianyi",
            source_interaction_id=stage.interaction_id,
            client_request_id="request-1",
        )

    assert stage.context.closed is True
    record = repository.find_by_request("request-1")
    assert record.state is CallState.FAILED
    assert record.end_reason is CallEndReason.SYSTEM_FAILURE


@pytest.mark.asyncio
async def test_ledger_create_failure_restores_chat_and_requires_reprepare():
    class FailingRepository(InMemoryCallSessionRepository):
        def create_if_absent(self, record):
            raise RuntimeError("database unavailable")

    stage_manager, _, _ = manager(repository=FailingRepository())
    connection, stage = await connected(stage_manager)
    await stage_manager.prepare_call_transition(connection, character_id="luotianyi", client_request_id="request-1")

    with pytest.raises(RuntimeError, match="database unavailable"):
        await stage_manager._claim_call(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id=stage.interaction_id,
            client_request_id="request-1",
        )

    assert stage.state.value == "online"
    assert stage.context.closed is False
    assert not stage.input_suspended
    with pytest.raises(ValueError, match="matching call transition"):
        await stage_manager._claim_call(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id=stage.interaction_id,
            client_request_id="request-1",
        )


@pytest.mark.asyncio
async def test_same_request_other_operation_is_rejected_without_leaking_claim():
    gate = asyncio.Event()

    async def blocking_realize(_plan, _context, _sink):
        await gate.wait()
        return SimpleNamespace(status=d.ExecutionStatus.COMPLETED, error_code=None)

    stage_manager, _, _ = manager(agent=RecordingAgent(realize=blocking_realize))
    connection, stage = await connected(stage_manager)
    await stage_manager.prepare_call_transition(connection, character_id="luotianyi", client_request_id="request-1")
    first = asyncio.create_task(
        stage_manager._claim_call(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id=stage.interaction_id,
            client_request_id="request-1",
        )
    )
    await asyncio.sleep(0)

    with pytest.raises(ValueError, match="another call"):
        await stage_manager._claim_call(
            user_id="other-user",
            character_id="luotianyi",
            source_interaction_id=stage.interaction_id,
            client_request_id="request-1",
        )
    gate.set()
    await first


@pytest.mark.asyncio
async def test_cancelled_start_waiter_does_not_cancel_committed_chat_finalization():
    entered, gate = asyncio.Event(), asyncio.Event()

    async def blocking_realize(_plan, _context, _sink):
        entered.set()
        await gate.wait()
        return SimpleNamespace(status=d.ExecutionStatus.COMPLETED, error_code=None)

    stages, _, _ = manager(agent=RecordingAgent(realize=blocking_realize), config={"stage": {"termination_timeout": 5}})
    connection, chat = await connected(stages)
    call = await preparing_call(stages, chat, connection)
    waiter = asyncio.create_task(call.start())
    await asyncio.wait_for(entered.wait(), 1)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert not chat.context.closed
    gate.set()
    await call.start()
    assert chat.context.closed
    await stages.close()


@pytest.mark.asyncio
async def test_normal_disconnect_keeps_chat_for_60_second_reconnect():
    stage_manager, _, _ = manager(config={"offline_timeout": 60.0})
    connection, stage = await connected(stage_manager)

    await stage_manager._test_chat_adapter._close_connection(connection)
    replacement = StubChatConnection(Socket(), "user", "replacement")
    reconnected = await stage_manager._test_chat_adapter._open(replacement, "luotianyi")

    assert reconnected is stage
    assert stage.context.closed is False


@pytest.mark.asyncio
async def test_direct_start_without_chat_claims_empty_slot_and_persists_ledger():
    stage_manager, repository, _ = manager()

    claim = await stage_manager._claim_call(
        user_id="user",
        character_id="luotianyi",
        source_interaction_id=None,
        client_request_id="request-direct",
    )

    assert claim.lease.source is InteractionSource.CALL_TRANSITION
    assert repository.find_by_request("request-direct") == claim.prepared._record


@pytest.mark.asyncio
async def test_direct_start_cannot_steal_offline_retained_chat():
    stage_manager, repository, _ = manager(config={"offline_timeout": 60.0})
    connection, stage = await connected(stage_manager)
    await stage_manager._test_chat_adapter._close_connection(connection)

    with pytest.raises(ValueError, match="already owned"):
        await stage_manager._claim_call(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id=None,
            client_request_id="request-direct",
        )

    assert repository.find_by_request("request-direct") is None
    assert stage.context.closed is False


@pytest.mark.asyncio
async def test_two_direct_devices_race_to_one_request_winner():
    stage_manager, repository, _ = manager()

    first, second = await asyncio.gather(
        stage_manager._claim_call(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id=None,
            client_request_id="request-direct",
        ),
        stage_manager._claim_call(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id=None,
            client_request_id="request-direct",
        ),
    )

    assert first.prepared._record.call_id == second.prepared._record.call_id
    assert repository.find_by_request("request-direct").call_id == first.prepared._record.call_id


@pytest.mark.asyncio
async def test_direct_ledger_failure_releases_transition_ownership():
    class FailingRepository(InMemoryCallSessionRepository):
        def create_if_absent(self, record):
            raise RuntimeError("database unavailable")

    stage_manager, _, _ = manager(repository=FailingRepository())

    with pytest.raises(RuntimeError, match="database unavailable"):
        await stage_manager._claim_call(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id=None,
            client_request_id="request-direct",
        )

    assert stage_manager._lease_registry.current("user", "luotianyi") is None


@pytest.mark.asyncio
async def test_blocking_repository_runs_off_loop_and_late_create_is_failed_after_deadline():
    started = threading.Event()
    release = threading.Event()

    class BlockingRepository(InMemoryCallSessionRepository):
        def create_if_absent(self, record):
            started.set()
            assert release.wait(5)
            return super().create_if_absent(record)

    stage_manager, repository, _ = manager(
        repository=BlockingRepository(),
        config={"offline_timeout": 60.0, "call_setup_timeout": 0.02},
    )
    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while not started.is_set():
            await asyncio.sleep(0)
        for _ in range(3):
            ticks += 1
            await asyncio.sleep(0)

    start = asyncio.create_task(
        stage_manager._claim_call(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id=None,
            client_request_id="request-direct",
        )
    )
    pulse = asyncio.create_task(heartbeat())
    await asyncio.to_thread(started.wait, 1)
    await pulse
    assert ticks == 3
    time.sleep(0.03)
    release.set()
    with pytest.raises(TimeoutError, match="timed out"):
        await start

    assert repository.find_by_request("request-direct").state is CallState.FAILED
    assert stage_manager._lease_registry.current("user", "luotianyi") is None


@pytest.mark.asyncio
async def test_shutdown_waits_for_blocking_direct_repository_and_cleans_late_ledger():
    started = threading.Event()
    release = threading.Event()

    class BlockingRepository(InMemoryCallSessionRepository):
        def create_if_absent(self, record):
            started.set()
            assert release.wait(5)
            return super().create_if_absent(record)

    stage_manager, repository, _ = manager(repository=BlockingRepository())
    start = asyncio.create_task(
        stage_manager._claim_call(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id=None,
            client_request_id="request-direct",
        )
    )
    await asyncio.to_thread(started.wait, 1)
    closing = asyncio.create_task(stage_manager.close())
    await asyncio.sleep(0)
    assert not closing.done()
    release.set()
    await closing
    with pytest.raises((RuntimeError, ValueError), match="closed"):
        await start

    assert repository.find_by_request("request-direct").state is CallState.FAILED
    assert stage_manager._lease_registry.current("user", "luotianyi") is None


@pytest.mark.asyncio
async def test_call_ledger_timestamp_is_aware_beijing_and_strictly_advances():
    instant = datetime(2026, 10, 11, tzinfo=timezone.utc)
    stage_manager, repository, _ = manager(clock=lambda: instant)
    connection, stage = await connected(stage_manager)
    await stage_manager.prepare_call_transition(connection, character_id="luotianyi", client_request_id="request-1")
    claim = await stage_manager._claim_call(
        user_id="user",
        character_id="luotianyi",
        source_interaction_id=stage.interaction_id,
        client_request_id="request-1",
    )

    assert claim.prepared._record.requested_at.utcoffset().total_seconds() == 8 * 3600
    assert repository.find_by_request("request-1").updated_at == claim.prepared._record.updated_at


@pytest.mark.asyncio
async def test_handoff_persists_preparing_claim_in_real_sqlite(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'handoff.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    repository = SqlCallSessionRepository(sessionmaker(bind=engine))
    stage_manager, _, _ = manager(repository=repository)
    connection, stage = await connected(stage_manager)
    await stage_manager.prepare_call_transition(connection, character_id="luotianyi", client_request_id="request-1")

    claim = await start_claim(
        stage_manager,
        user_id="user",
        character_id="luotianyi",
        source_interaction_id=stage.interaction_id,
        client_request_id="request-1",
    )

    assert repository.find_by_request("request-1").call_id == claim.prepared._record.call_id
    assert stage.context.closed is True
    await stage_manager.close()
    engine.dispose()


@pytest.mark.asyncio
async def test_manager_shutdown_releases_call_lease():
    stage_manager, _, _ = manager()
    connection, stage = await connected(stage_manager)
    await stage_manager.prepare_call_transition(connection, character_id="luotianyi", client_request_id="request-1")
    claim = await stage_manager._claim_call(
        user_id="user",
        character_id="luotianyi",
        source_interaction_id=stage.interaction_id,
        client_request_id="request-1",
    )

    await stage_manager.close()

    assert stage_manager._lease_registry.current("user", "luotianyi") is None
    assert claim.lease.source is InteractionSource.CALL_TRANSITION


@pytest.mark.asyncio
async def test_shutdown_waits_committed_chat_cleanup_and_prevents_call_context_creation():
    entered, gate = asyncio.Event(), asyncio.Event()

    async def blocking_realize(_plan, _context, _sink):
        entered.set()
        await gate.wait()
        return SimpleNamespace(status=d.ExecutionStatus.COMPLETED, error_code=None)

    stages, repository, _ = manager(
        agent=RecordingAgent(realize=blocking_realize), config={"stage": {"termination_timeout": 5}}
    )
    connection, chat = await connected(stages)
    call = await preparing_call(stages, chat, connection)
    await asyncio.wait_for(entered.wait(), 1)
    closing = asyncio.create_task(stages.close())
    await _eventually(lambda: call.interaction_ended)
    assert not closing.done() and call.context is None
    gate.set()
    await closing
    assert chat.context.closed
    assert repository.find_by_request("request-1").state is CallState.FAILED
    assert stages._lease_registry.current("user", "luotianyi") is None


@pytest.mark.asyncio
async def test_setup_timeout_emits_terminal_without_waiting_for_committed_chat_cleanup():
    entered, gate = asyncio.Event(), asyncio.Event()

    async def blocking_realize(_plan, _context, _sink):
        entered.set()
        await gate.wait()
        return SimpleNamespace(status=d.ExecutionStatus.COMPLETED, error_code=None)

    stages, repository, _ = manager(
        agent=RecordingAgent(realize=blocking_realize),
        config={"call_setup_timeout": 0.1, "stage": {"termination_timeout": 5}},
    )
    connection, chat = await connected(stages)
    call = await preparing_call(stages, chat, connection)
    await asyncio.wait_for(entered.wait(), 1)
    await _eventually(lambda: call.interaction_ended)
    result = await asyncio.wait_for(call.terminate(StageEndReason.USER_REQUESTED), 1)
    assert result.reason is StageEndReason.INITIALIZATION_FAILED and result.resources_released
    assert not chat.context.closed and call.context is None
    assert stages._lease_registry.current("user", "luotianyi").source is InteractionSource.CALL_TRANSITION
    with pytest.raises(RuntimeError, match="USER_INTERACTION_BUSY"):
        await stages.begin_user_data_reset("user")
    gate.set()
    await stages.close()
    assert repository.find_by_request("request-1").end_reason is CallEndReason.SETUP_TIMEOUT


@pytest.mark.asyncio
async def test_hangup_after_commit_finishes_call_before_chat_and_never_restores_old_chat():
    entered, gate = asyncio.Event(), asyncio.Event()

    async def blocking_realize(_plan, _context, _sink):
        entered.set()
        await gate.wait()
        return SimpleNamespace(status=d.ExecutionStatus.COMPLETED, error_code=None)

    stages, repository, _ = manager(
        agent=RecordingAgent(realize=blocking_realize), config={"stage": {"termination_timeout": 5}}
    )
    connection, chat = await connected(stages)
    call = await preparing_call(stages, chat, connection)
    await asyncio.wait_for(entered.wait(), 1)
    result = await asyncio.wait_for(call.terminate(StageEndReason.USER_REQUESTED), 1)
    assert result.resources_released and not chat.context.closed
    assert call.context is None
    with pytest.raises(StageStartAborted):
        await call.start()
    assert repository.find_by_request("request-1").end_reason is CallEndReason.USER_HANGUP
    gate.set()
    await _eventually(lambda: not stages._scope_releases)
    _, replacement = await connected(stages)
    assert replacement is not chat
    await stages.close()


@pytest.mark.asyncio
async def test_call_ledger_rejects_naive_wall_clock_without_retiring_chat():
    stage_manager, repository, _ = manager(clock=lambda: datetime(2026, 10, 11))
    connection, stage = await connected(stage_manager)
    await stage_manager.prepare_call_transition(connection, character_id="luotianyi", client_request_id="request-1")

    with pytest.raises(ValueError, match="timezone-aware"):
        await stage_manager._claim_call(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id=stage.interaction_id,
            client_request_id="request-1",
        )

    assert repository.find_by_request("request-1") is None
    assert stage.state.value == "online"
    assert stage.context.closed is False


class _BlockingSqlCallRepository(SqlCallSessionRepository):
    def __init__(self, sessions, started, release):
        super().__init__(sessions)
        self._started = started
        self._release = release

    def create_if_absent(self, record):
        self._started.set()
        self._release.wait(5)
        return super().create_if_absent(record)


@pytest.mark.asyncio
async def test_user_reset_invalidates_blocking_sql_start_and_leaves_no_live_claim(
    tmp_path,
):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'reset-start.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    started = threading.Event()
    release = threading.Event()
    repository = _BlockingSqlCallRepository(sessionmaker(bind=engine), started, release)
    fence = UserResetFence()
    stage_manager, _, _ = manager(repository=repository, user_reset_fence=fence)
    start = asyncio.create_task(
        stage_manager._claim_call(
            user_id="owner",
            character_id="luotianyi",
            source_interaction_id=None,
            client_request_id="reset-race",
        )
    )
    assert await asyncio.to_thread(started.wait, 3)
    token = await fence.begin("owner")
    release.set()
    result = await asyncio.gather(start, return_exceptions=True)

    assert isinstance(result[0], RuntimeError)
    assert str(result[0]) == "USER_DATA_RESET_INVALIDATED_OPERATION"
    record = repository.find_by_request("reset-race")
    assert record is not None and record.state is CallState.FAILED
    assert not any(claim.prepared._record.user_id == "owner" for claim in stage_manager._call_claims.values())
    assert not any(item.user_id == "owner" for item in stage_manager._call_ownerships.values())
    assert stage_manager._lease_registry.current("owner", "luotianyi") is None
    await fence.end("owner", token)
    await stage_manager.close()
    engine.dispose()


@pytest.mark.asyncio
async def test_user_reset_waits_creation_after_claim_take_and_fence_is_registry_backstop(
    monkeypatch,
):
    from src.stage.call.call_stage import CallStage

    fence = UserResetFence()
    stage_manager, _, _ = manager(user_reset_fence=fence)
    claim = await stage_manager._claim_call(
        user_id="owner",
        character_id="luotianyi",
        source_interaction_id=None,
        client_request_id="creation-race",
    )
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocking_start(self):
        del self
        entered.set()
        await asyncio.wait_for(release.wait(), timeout=3)
        raise RuntimeError("CREATION_ABORTED")

    monkeypatch.setattr(CallStage, "start", blocking_start)
    creation = asyncio.create_task(
        create_call_stage(
            stage_manager,
            claim,
            user_id="owner",
            character_id="luotianyi",
            client_request_id="creation-race",
            speech_factory=SimpleNamespace(),
            transport=None,
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=3)
    inner = next(task for task, owner in stage_manager._call_stage_creations.items() if owner == "owner")
    stage_manager._call_stage_creations.pop(inner)
    token = await fence.begin("owner")
    waiting = asyncio.create_task(fence.wait("owner"))
    await asyncio.sleep(0)
    assert not waiting.done()
    release.set()
    assert isinstance((await asyncio.gather(creation, return_exceptions=True))[0], RuntimeError)
    await asyncio.wait_for(waiting, timeout=3)
    assert not stage_manager._call_ownerships
    assert not stage_manager._call_stages
    await fence.end("owner", token)
    await stage_manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_seam", ["constructor", "publication"])
async def test_postclaim_setup_failure_only_existing_stage_emits_and_releases_ownership(monkeypatch, failure_seam):
    from src.stage.call import call_stage as call_stage_module

    stage_manager, repository, _ = manager()
    claim = await stage_manager._claim_call(
        user_id="owner",
        character_id="luotianyi",
        source_interaction_id=None,
        client_request_id=failure_seam,
    )

    class Transport:
        def __init__(self):
            self.failures = []

        def stage_created(self, _stage):
            if failure_seam == "publication":
                raise RuntimeError("PUBLICATION_FAILED")

        async def send_failed(self, reason):
            self.failures.append(reason)

    transport = Transport()
    if failure_seam == "constructor":
        original = call_stage_module.CallStage

        class FailingCallStage(call_stage_module.CallStage):
            def __init__(self, **_kwargs):
                raise RuntimeError("CONSTRUCTOR_FAILED")

        monkeypatch.setattr(call_stage_module, "CallStage", FailingCallStage)
    try:
        with pytest.raises(RuntimeError, match="FAILED"):
            await create_call_stage(
                stage_manager,
                claim,
                user_id="owner",
                character_id="luotianyi",
                client_request_id=failure_seam,
                speech_factory=SimpleNamespace(),
                transport=transport,
                stage_created=transport.stage_created,
            )
    finally:
        if failure_seam == "constructor":
            monkeypatch.setattr(call_stage_module, "CallStage", original)

    assert transport.failures == ([] if failure_seam == "constructor" else [CallEndReason.SYSTEM_FAILURE])
    assert stage_manager._current_call_ownership(str(claim.prepared._record.call_id)) is None
    assert stage_manager._call_stages.get(str(claim.prepared._record.call_id)) is None
    failed = repository.find_by_request(failure_seam)
    assert failed is not None
    assert failed.call_id == claim.prepared._record.call_id
    assert failed.state is CallState.FAILED
    assert failed.end_reason is CallEndReason.SYSTEM_FAILURE
    with pytest.raises(RuntimeError, match="CALL_START_FAILED") as repeated:
        await stage_manager._claim_call(
            user_id="owner",
            character_id="luotianyi",
            source_interaction_id=None,
            client_request_id=failure_seam,
        )
    assert repeated.value.call_id == str(claim.prepared._record.call_id)
    await stage_manager.close()


@pytest.mark.asyncio
async def test_postclaim_setup_failure_marks_real_sqlite_failed_and_duplicate_keeps_identity(tmp_path, monkeypatch):
    from src.stage.call import call_stage as call_stage_module

    engine = create_engine(f"sqlite:///{tmp_path / 'postclaim.sqlite'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    repository = SqlCallSessionRepository(sessions)
    stage_manager, _, _ = manager(repository=repository)
    claim = await stage_manager._claim_call(
        user_id="owner",
        character_id="luotianyi",
        source_interaction_id=None,
        client_request_id="sqlite-postclaim",
    )

    class FailingCallStage(call_stage_module.CallStage):
        def __init__(self, **_kwargs):
            raise RuntimeError("CONSTRUCTOR_FAILED")

    class Transport:
        async def send_failed(self, _reason):
            return None

    monkeypatch.setattr(call_stage_module, "CallStage", FailingCallStage)
    with pytest.raises(RuntimeError, match="CONSTRUCTOR_FAILED"):
        await create_call_stage(
            stage_manager,
            claim,
            user_id="owner",
            character_id="luotianyi",
            client_request_id="sqlite-postclaim",
            speech_factory=SimpleNamespace(),
            transport=Transport(),
        )

    failed = repository.find_by_request("sqlite-postclaim")
    assert failed is not None
    assert failed.call_id == claim.prepared._record.call_id
    assert failed.state is CallState.FAILED
    assert failed.end_reason is CallEndReason.SYSTEM_FAILURE
    with pytest.raises(RuntimeError, match="CALL_START_FAILED") as repeated:
        await stage_manager._claim_call(
            user_id="owner",
            character_id="luotianyi",
            source_interaction_id=None,
            client_request_id="sqlite-postclaim",
        )
    assert repeated.value.call_id == str(claim.prepared._record.call_id)
    await stage_manager.close()
    engine.dispose()


@pytest.mark.asyncio
async def test_old_claim_generation_and_reset_owner_are_rejected_while_other_user_continues():
    fence = UserResetFence()
    stage_manager, _, _ = manager(user_reset_fence=fence)
    old_claim = await stage_manager._claim_call(
        user_id="owner",
        character_id="luotianyi",
        source_interaction_id=None,
        client_request_id="old-claim",
    )
    token = await fence.begin("owner")
    other = await stage_manager._claim_call(
        user_id="other",
        character_id="luotianyi",
        source_interaction_id=None,
        client_request_id="other-call",
    )
    assert other.prepared._record.user_id == "other"
    with pytest.raises(RuntimeError, match="RESET_IN_PROGRESS"):
        await stage_manager._claim_call(
            user_id="owner",
            character_id="luotianyi",
            source_interaction_id=None,
            client_request_id="new-owner",
        )
    await fence.end("owner", token)
    with pytest.raises(RuntimeError, match="INVALIDATED_OPERATION"):
        await create_call_stage(
            stage_manager,
            old_claim,
            user_id="owner",
            character_id="luotianyi",
            client_request_id="old-claim",
            speech_factory=SimpleNamespace(),
            transport=None,
        )
    await stage_manager.close()


@pytest.mark.asyncio
async def test_blocked_provider_initialization_does_not_hold_manager_lock():
    entered, gate = asyncio.Event(), asyncio.Event()

    class Speech:
        async def create(self, call_id):
            entered.set()
            await gate.wait()
            raise RuntimeError("provider unavailable")

    stages, _, _ = manager(user_reset_fence=UserResetFence())
    from src.stage.call.call_stage import bind_call_stage_creator

    resources = dict(stages._test_call_resources, speech_factory=Speech())
    stages._call_stage_creator = bind_call_stage_creator(**resources)
    call = await stages.try_to_get_stage(
        stage_type="call", user_id="owner", character_id="luotianyi", client_request_id="blocked"
    )
    await asyncio.wait_for(entered.wait(), 1)
    token = await asyncio.wait_for(stages.begin_user_data_reset("other"), 1)
    await stages.end_user_data_reset("other", token)
    await asyncio.wait_for(stages.close(), 1)
    assert call.context is None and not stages._call_stages


async def start_claim(manager, **kwargs):
    claim = await manager._claim_call(**kwargs)
    await manager._create_call_stage(
        claim,
        user_id=kwargs["user_id"],
        character_id=kwargs["character_id"],
        client_request_id=kwargs["client_request_id"],
    )
    return claim


async def preparing_call(manager, chat, connection, request="request-1"):
    await manager.prepare_call_transition(connection, character_id="luotianyi", client_request_id=request)
    return await manager.try_to_get_stage(
        stage_type="call", user_id="user", character_id="luotianyi", client_request_id=request
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("expired", [False, True])
async def test_precommit_hangup_preserves_original_chat_offline_deadline(expired):
    entered = asyncio.Event()

    class Speech:
        async def create(self, call_id):
            entered.set()
            await asyncio.Event().wait()

    stages, _, _ = manager(config={"offline_timeout": 0.02 if expired else 60})
    from src.stage.call.call_stage import bind_call_stage_creator

    stages._call_stage_creator = bind_call_stage_creator(**dict(stages._test_call_resources, speech_factory=Speech()))
    connection, chat = await connected(stages)
    call = await preparing_call(stages, chat, connection)
    await asyncio.wait_for(entered.wait(), 1)
    await stages._test_chat_adapter._close_connection(connection)
    deadline = chat.offline_deadline
    if expired:
        await asyncio.sleep(0.04)
    assert not chat.context.closed
    await call.terminate(StageEndReason.USER_REQUESTED)
    if expired:
        await _eventually(lambda: chat.context.closed)
        _, replacement = await connected(stages)
        assert replacement is not chat
    else:
        assert chat.offline_deadline == deadline
        _, resumed = await connected(stages)
        assert resumed is chat
    await stages.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_at", ["ledger", "constructor"])
async def test_failed_call_creation_restores_original_offline_expiry(monkeypatch, failure_at):
    stages, _, _ = manager(config={"offline_timeout": 0.1})
    connection, chat = await connected(stages)
    await stages.prepare_call_transition(connection, character_id="luotianyi", client_request_id="failed-start")
    await stages._test_chat_adapter._close_connection(connection)
    deadline = chat.offline_deadline

    async def unavailable(*args, **kwargs):
        raise OSError("call creation unavailable")

    if failure_at == "ledger":
        monkeypatch.setattr(stages._call_records, "prepare_start", unavailable)
    else:
        monkeypatch.setattr(stages, "_call_stage_creator", unavailable)
    try:
        with pytest.raises(OSError, match="call creation unavailable"):
            await stages.try_to_get_stage(
                stage_type="call", user_id="user", character_id="luotianyi", client_request_id="failed-start"
            )
        assert chat.offline_deadline == deadline
        await _eventually(lambda: chat.context.closed)
        assert time.monotonic() >= deadline
        await chat.terminate(StageEndReason.IDLE_TIMEOUT)
        assert stages._lease_registry.current("user", "luotianyi") is None
    finally:
        await stages.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("during_refresh", ["resume", "expire", "shutdown"])
async def test_chat_restore_rechecks_admission_after_history_sync(monkeypatch, during_refresh):
    from src.stage.call.call_stage import bind_call_stage_creator

    class Speech:
        async def create(self, call_id):
            await asyncio.Event().wait()

    stages, _, _ = manager()
    clock = [time.monotonic()]
    stages._monotonic = lambda: clock[0]
    stages._call_stage_creator = bind_call_stage_creator(**dict(stages._test_call_resources, speech_factory=Speech()))
    connection, chat = await connected(stages)
    entered, release = asyncio.Event(), asyncio.Event()

    async def refresh():
        entered.set()
        await release.wait()

    monkeypatch.setattr(chat.context.conversation, "refresh", refresh)
    call = await preparing_call(stages, chat, connection)
    ending = asyncio.create_task(call.terminate(StageEndReason.USER_REQUESTED))
    shutdown = None
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert chat.input_suspended and not chat.stimulus_input_sink.can_accept(stimulus())
        # 一个用户的历史同步不占住 Manager 全局锁。
        await asyncio.wait_for(connected(stages, user="other"), 1)
        if during_refresh == "expire":
            await stages._test_chat_adapter._close_connection(connection)
            clock[0] = chat.offline_deadline + 1
        elif during_refresh == "shutdown":
            shutdown = asyncio.create_task(stages.close())
            await _eventually(lambda: stages.is_closed)
        release.set()
        await asyncio.wait_for(ending, 1)
        if during_refresh == "resume":
            assert not chat.input_suspended and chat.stimulus_input_sink.can_accept(stimulus())
            _, resumed = await connected(stages)
            assert resumed is chat
        else:
            await _eventually(lambda: chat.context.closed)
            assert not chat.stimulus_input_sink.can_accept(stimulus())
    finally:
        release.set()
        await ending
        if shutdown is not None:
            await shutdown
        await stages.close()
