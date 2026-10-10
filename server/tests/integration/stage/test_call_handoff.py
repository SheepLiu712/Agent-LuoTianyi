import asyncio
import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from support.call_session_repository import InMemoryCallSessionRepository

import src.domain.agent as d
from src.adapter.websocket import WebSocketAdapter
from src.domain.call import CallEndReason, CallState
from src.infrastructure.persistence.call_sessions import SqlCallSessionRepository
from src.infrastructure.persistence.database.sql_database import Base
from src.stage import StageManager
from src.stage.interaction_lease import InteractionLeaseRegistry, InteractionSource
from src.web.websocket.service import WebSocketConnection

from .test_chat_stage import RecordingAgent, Socket, StageContextFactory


def manager(*, agent=None, clock=None, config=None, repository=None, lease_registry=None):
    adapter = WebSocketAdapter()
    repository = repository or InMemoryCallSessionRepository()
    factory = StageContextFactory()
    manager = StageManager(
        get_agent=lambda _character: agent or RecordingAgent(),
        adapter=adapter,
        get_context_factory=lambda _character: factory,
        call_sessions=repository,
        lease_registry=lease_registry,
        wall_clock=clock or (lambda: datetime.now(timezone.utc)),
        config=config or {"offline_timeout": 60.0, "stage": {"termination_timeout": 0.2}},
    )
    return manager, repository, factory


async def connected(manager, user="user"):
    connection = WebSocketConnection(Socket(), user, user)
    stage = await manager.connect(connection, "luotianyi")
    return connection, stage


@pytest.mark.asyncio
async def test_prepare_requires_current_bound_connection_and_is_one_shot():
    stage_manager, _, _ = manager()
    connection, stage = await connected(stage_manager)
    other = WebSocketConnection(Socket(), "user", "other-device")

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

    assert stage_manager._adapter.is_business_input_suspended(connection)
    acceptance = await stage_manager._adapter.try_accept_event(
        connection,
        SimpleNamespace(event_type="user_text", payload={}, client_msg_id="msg-1"),
    )
    assert acceptance.code == "CALL_SWITCH_PENDING"
    assert acceptance.retryable is True
    await asyncio.sleep(max(0.0, intent.expires_at - asyncio.get_running_loop().time()) + 0.01)
    assert not stage_manager._adapter.is_business_input_suspended(connection)
    assert stage.state.value == "online"


@pytest.mark.asyncio
async def test_call_start_closes_chat_context_before_returning_call_claim():
    stage_manager, repository, _ = manager()
    connection, stage = await connected(stage_manager)
    await stage_manager.prepare_call_transition(connection, character_id="luotianyi", client_request_id="request-1")

    claim = await stage_manager.start_call(
        user_id="user",
        character_id="luotianyi",
        source_interaction_id=stage.interaction_id,
        client_request_id="request-1",
    )

    assert stage.context.closed is True
    assert stage.state.value == "terminated"
    assert claim.record.state is CallState.PREPARING
    assert claim.lease.source is InteractionSource.CALL
    assert repository.find_by_request("request-1") == claim.record


@pytest.mark.asyncio
async def test_duplicate_call_start_returns_same_claim_without_intent():
    stage_manager, _, _ = manager()
    connection, stage = await connected(stage_manager)
    await stage_manager.prepare_call_transition(connection, character_id="luotianyi", client_request_id="request-1")
    first = await stage_manager.start_call(
        user_id="user",
        character_id="luotianyi",
        source_interaction_id=stage.interaction_id,
        client_request_id="request-1",
    )
    duplicate = await stage_manager.start_call(
        user_id="user",
        character_id="luotianyi",
        source_interaction_id="already-retired",
        client_request_id="request-1",
    )

    assert duplicate.record.call_id == first.record.call_id
    assert duplicate.duplicate is True
    assert duplicate.lease == first.lease


@pytest.mark.asyncio
async def test_concurrent_duplicate_start_shares_one_handoff_and_one_winner():
    stage_manager, repository, _ = manager()
    connection, stage = await connected(stage_manager)
    await stage_manager.prepare_call_transition(connection, character_id="luotianyi", client_request_id="request-1")

    first, second = await asyncio.gather(
        stage_manager.start_call(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id=stage.interaction_id,
            client_request_id="request-1",
        ),
        stage_manager.start_call(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id=stage.interaction_id,
            client_request_id="request-1",
        ),
    )

    assert first.record.call_id == second.record.call_id
    assert repository.find_by_request("request-1").call_id == first.record.call_id
    assert stage.context.closed is True


@pytest.mark.asyncio
async def test_wrong_request_or_source_does_not_retire_chat():
    stage_manager, repository, _ = manager()
    connection, stage = await connected(stage_manager)
    await stage_manager.prepare_call_transition(connection, character_id="luotianyi", client_request_id="request-1")

    with pytest.raises(ValueError, match="matching call transition"):
        await stage_manager.start_call(
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
        return SimpleNamespace(status=d.ExecutionStatus.FAILED, error_code=d.ExecutionErrorCode.INTERNAL_ERROR)

    stage_manager, repository, _ = manager(agent=RecordingAgent(realize=failed_realize))
    connection, stage = await connected(stage_manager)
    await stage_manager.prepare_call_transition(connection, character_id="luotianyi", client_request_id="request-1")

    with pytest.raises(RuntimeError, match="maintenance failed"):
        await stage_manager.start_call(
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
        await stage_manager.start_call(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id=stage.interaction_id,
            client_request_id="request-1",
        )

    assert stage.state.value == "online"
    assert stage.context.closed is False
    assert not stage_manager._adapter.is_business_input_suspended(connection)
    with pytest.raises(ValueError, match="matching call transition"):
        await stage_manager.start_call(
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
        stage_manager.start_call(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id=stage.interaction_id,
            client_request_id="request-1",
        )
    )
    await asyncio.sleep(0)

    with pytest.raises(ValueError, match="another call"):
        await stage_manager.start_call(
            user_id="other-user",
            character_id="luotianyi",
            source_interaction_id=stage.interaction_id,
            client_request_id="request-1",
        )
    gate.set()
    await first


@pytest.mark.asyncio
async def test_cancelled_start_completes_owned_handoff_before_propagating_cancel():
    gate = asyncio.Event()

    async def blocking_realize(_plan, _context, _sink):
        await gate.wait()
        return SimpleNamespace(status=d.ExecutionStatus.COMPLETED, error_code=None)

    stage_manager, repository, _ = manager(agent=RecordingAgent(realize=blocking_realize))
    connection, stage = await connected(stage_manager)
    await stage_manager.prepare_call_transition(connection, character_id="luotianyi", client_request_id="request-1")
    task = asyncio.create_task(
        stage_manager.start_call(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id=stage.interaction_id,
            client_request_id="request-1",
        )
    )
    await asyncio.sleep(0)
    task.cancel()
    gate.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    record = repository.find_by_request("request-1")
    assert stage.context.closed is True
    assert record.state is CallState.PREPARING


@pytest.mark.asyncio
async def test_normal_disconnect_keeps_chat_for_60_second_reconnect():
    stage_manager, _, _ = manager(config={"offline_timeout": 60.0})
    connection, stage = await connected(stage_manager)

    await stage_manager.disconnect(connection)
    replacement = WebSocketConnection(Socket(), "user", "replacement")
    reconnected = await stage_manager.connect(replacement, "luotianyi")

    assert reconnected is stage
    assert stage.context.closed is False


@pytest.mark.asyncio
async def test_direct_start_without_chat_claims_empty_slot_and_persists_ledger():
    stage_manager, repository, _ = manager()

    claim = await stage_manager.start_call(
        user_id="user",
        character_id="luotianyi",
        source_interaction_id=None,
        client_request_id="request-direct",
    )

    assert claim.lease.source is InteractionSource.CALL
    assert repository.find_by_request("request-direct") == claim.record


@pytest.mark.asyncio
async def test_direct_start_cannot_steal_offline_retained_chat():
    stage_manager, repository, _ = manager(config={"offline_timeout": 60.0})
    connection, stage = await connected(stage_manager)
    await stage_manager.disconnect(connection)

    with pytest.raises(ValueError, match="already owned"):
        await stage_manager.start_call(
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
        stage_manager.start_call(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id=None,
            client_request_id="request-direct",
        ),
        stage_manager.start_call(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id=None,
            client_request_id="request-direct",
        ),
    )

    assert first.record.call_id == second.record.call_id
    assert repository.find_by_request("request-direct").call_id == first.record.call_id


@pytest.mark.asyncio
async def test_direct_ledger_failure_releases_transition_ownership():
    class FailingRepository(InMemoryCallSessionRepository):
        def create_if_absent(self, record):
            raise RuntimeError("database unavailable")

    stage_manager, _, _ = manager(repository=FailingRepository())

    with pytest.raises(RuntimeError, match="database unavailable"):
        await stage_manager.start_call(
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
        stage_manager.start_call(
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
        stage_manager.start_call(
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
    claim = await stage_manager.start_call(
        user_id="user",
        character_id="luotianyi",
        source_interaction_id=stage.interaction_id,
        client_request_id="request-1",
    )

    assert claim.record.requested_at.utcoffset().total_seconds() == 8 * 3600
    assert repository.find_by_request("request-1").updated_at == claim.record.updated_at


@pytest.mark.asyncio
async def test_handoff_persists_preparing_claim_in_real_sqlite(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'handoff.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    repository = SqlCallSessionRepository(sessionmaker(bind=engine))
    stage_manager, _, _ = manager(repository=repository)
    connection, stage = await connected(stage_manager)
    await stage_manager.prepare_call_transition(connection, character_id="luotianyi", client_request_id="request-1")

    claim = await stage_manager.start_call(
        user_id="user",
        character_id="luotianyi",
        source_interaction_id=stage.interaction_id,
        client_request_id="request-1",
    )

    assert repository.find_by_request("request-1") == claim.record
    assert stage.context.closed is True
    engine.dispose()


@pytest.mark.asyncio
async def test_manager_shutdown_releases_call_lease():
    stage_manager, _, _ = manager()
    connection, stage = await connected(stage_manager)
    await stage_manager.prepare_call_transition(connection, character_id="luotianyi", client_request_id="request-1")
    claim = await stage_manager.start_call(
        user_id="user",
        character_id="luotianyi",
        source_interaction_id=stage.interaction_id,
        client_request_id="request-1",
    )

    await stage_manager.close()

    assert stage_manager._lease_registry.current("user", "luotianyi") is None
    assert claim.lease.source is InteractionSource.CALL


@pytest.mark.asyncio
async def test_shutdown_waits_blocked_handoff_and_never_grants_call_lease():
    gate = asyncio.Event()

    async def blocking_realize(_plan, _context, _sink):
        await gate.wait()
        return SimpleNamespace(status=d.ExecutionStatus.COMPLETED, error_code=None)

    stage_manager, repository, _ = manager(agent=RecordingAgent(realize=blocking_realize))
    connection, stage = await connected(stage_manager)
    await stage_manager.prepare_call_transition(connection, character_id="luotianyi", client_request_id="request-1")
    start = asyncio.create_task(
        stage_manager.start_call(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id=stage.interaction_id,
            client_request_id="request-1",
        )
    )
    for _ in range(1000):
        if repository.find_by_request("request-1") is not None:
            break
        await asyncio.sleep(0.001)
    assert repository.find_by_request("request-1") is not None
    closing = asyncio.create_task(stage_manager.close())
    await asyncio.sleep(0)
    assert not closing.done()
    gate.set()
    await closing
    with pytest.raises((RuntimeError, ValueError), match="closed"):
        await start

    assert stage.context.closed is True
    assert repository.find_by_request("request-1").state is CallState.FAILED
    assert stage_manager._lease_registry.current("user", "luotianyi") is None


@pytest.mark.asyncio
async def test_setup_timeout_waits_for_owned_termination_before_releasing_transition():
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocking_realize(_plan, _context, _sink):
        entered.set()
        await release.wait()
        return SimpleNamespace(status=d.ExecutionStatus.COMPLETED, error_code=None)

    stage_manager, repository, _ = manager(
        agent=RecordingAgent(realize=blocking_realize),
        config={"offline_timeout": 60.0, "call_setup_timeout": 0.01},
    )
    connection, stage = await connected(stage_manager)
    await stage_manager.prepare_call_transition(connection, character_id="luotianyi", client_request_id="request-1")
    start = asyncio.create_task(
        stage_manager.start_call(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id=stage.interaction_id,
            client_request_id="request-1",
        )
    )
    await entered.wait()
    await asyncio.sleep(0.02)

    lease = stage_manager._lease_registry.current("user", "luotianyi")
    assert lease.source is InteractionSource.CALL_TRANSITION
    assert not start.done()
    assert stage.context.closed is False
    with pytest.raises(ValueError, match="already owned"):
        await stage_manager.start_call(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id=None,
            client_request_id="request-direct",
        )
    with pytest.raises(ValueError, match="already owned"):
        await stage_manager.connect(WebSocketConnection(Socket(), "user", "replacement"), "luotianyi")

    release.set()
    with pytest.raises(TimeoutError, match="timed out"):
        await start

    record = repository.find_by_request("request-1")
    assert stage.context.closed is True
    assert stage.state.value == "terminated"
    assert record.state is CallState.FAILED
    assert record.end_reason is CallEndReason.SETUP_TIMEOUT
    assert stage_manager._lease_registry.current("user", "luotianyi") is None
    assert stage_manager._call_starts == {}


@pytest.mark.asyncio
async def test_caller_cancel_after_setup_deadline_still_completes_timeout_cleanup():
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocking_realize(_plan, _context, _sink):
        entered.set()
        await release.wait()
        return SimpleNamespace(status=d.ExecutionStatus.COMPLETED, error_code=None)

    stage_manager, repository, _ = manager(
        agent=RecordingAgent(realize=blocking_realize),
        config={"offline_timeout": 60.0, "call_setup_timeout": 0.01},
    )
    connection, stage = await connected(stage_manager)
    await stage_manager.prepare_call_transition(connection, character_id="luotianyi", client_request_id="request-1")
    start = asyncio.create_task(
        stage_manager.start_call(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id=stage.interaction_id,
            client_request_id="request-1",
        )
    )
    await entered.wait()
    await asyncio.sleep(0.02)
    start.cancel()
    await asyncio.sleep(0)
    assert not start.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await start

    record = repository.find_by_request("request-1")
    assert stage.context.closed is True
    assert record.state is CallState.FAILED
    assert record.end_reason is CallEndReason.SETUP_TIMEOUT
    assert stage_manager._lease_registry.current("user", "luotianyi") is None
    assert stage_manager._call_starts == {}


@pytest.mark.asyncio
async def test_call_ledger_rejects_naive_wall_clock_without_retiring_chat():
    stage_manager, repository, _ = manager(clock=lambda: datetime(2026, 10, 11))
    connection, stage = await connected(stage_manager)
    await stage_manager.prepare_call_transition(connection, character_id="luotianyi", client_request_id="request-1")

    with pytest.raises(ValueError, match="timezone-aware"):
        await stage_manager.start_call(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id=stage.interaction_id,
            client_request_id="request-1",
        )

    assert repository.find_by_request("request-1") is None
    assert stage.state.value == "online"
    assert stage.context.closed is False
