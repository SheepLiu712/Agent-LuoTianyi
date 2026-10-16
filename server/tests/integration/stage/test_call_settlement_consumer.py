import asyncio
import json
import threading
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from support.call_coherent_runtime import (
    DeterministicCallTTSModule,
    DeterministicLLMService,
    DeterministicVectorStore,
    NoopMediaResolver,
    runtime_config,
)

import src.agent.skills.expression.speaking.backend as speaking_backend
from src.agent_runtime import agent_runtime as runtime_module
from src.application.user.user_conversation_helper import UserConversationHelper
from src.domain.call import (
    CallAgentSettlementResult,
    CallEndReason,
    CallFinalSnapshot,
    CallFinalTurn,
    CallOutcome,
    CallReplyStatus,
    CallState,
    CallTerminalFacts,
    derive_call_conversation_id,
)
from src.infrastructure.persistence.call_sessions import (
    CallSessionRecord,
    SettlementStatus,
)
from src.infrastructure.persistence.database import DatabaseManager
from src.infrastructure.persistence.database.sql_database import (
    CallMaintenanceBatch,
    Conversation,
    User,
)
from src.stage.call_settlement import (
    CallAgentSettlement,
    CallSettlement,
    CallSettlementConsumerImpl,
    StaleCallRecoveryService,
)


class _FixedAgentSettlement:
    async def settle(self, *args, **kwargs):
        return CallAgentSettlementResult(summary="固定概要", maintenance_turn_seq=RuntimeError("maintenance failed"))


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_phase", ["conversation_write", "summary_cas", "maintenance_cas"])
async def test_durable_finalization_cancellation_finishes_both_status_lanes(tmp_path, blocked_phase):
    database = DatabaseManager({"sql_db_folder": str(tmp_path), "sql_db_file": f"cancel-{blocked_phase}.sqlite"})
    with database.open_sql_session() as sql:
        sql.add(User(uuid="user", username=f"cancel-{blocked_phase}", password="offline", description=""))
        sql.commit()
    call_id = uuid4()
    requested_at = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
    record = CallSessionRecord(
        call_id=call_id,
        client_request_id=f"cancel-{blocked_phase}",
        user_id="user",
        character_id="luotianyi",
        state=CallState.ENDED,
        requested_at=requested_at,
        created_at=requested_at,
        updated_at=requested_at,
        outcome=CallOutcome.CONNECTED,
        end_reason=CallEndReason.USER_HANGUP,
        connected_at=requested_at,
        ended_at=requested_at,
        active_duration_ms=1_000,
    )
    database.call_sessions.create_if_absent(record)
    snapshot = CallFinalSnapshot(
        CallTerminalFacts(call_id, CallOutcome.CONNECTED, CallEndReason.USER_HANGUP, 1_000, requested_at),
        (CallFinalTurn(1, "用户事实", CallReplyStatus.COMPLETED, "正式回复"),),
        0,
    )
    entered = threading.Event()
    release = threading.Event()

    def block_then_call(operation):
        def wrapped(*args, **kwargs):
            entered.set()
            if not release.wait(timeout=5):
                raise TimeoutError(f"{blocked_phase} barrier timed out")
            return operation(*args, **kwargs)

        return wrapped

    if blocked_phase == "conversation_write":
        database.conversation_service.add_call_conversation = block_then_call(
            database.conversation_service.add_call_conversation
        )
    elif blocked_phase == "summary_cas":
        database.call_sessions.update_summary_settlement = block_then_call(
            database.call_sessions.update_summary_settlement
        )
    else:
        database.call_sessions.update_maintenance_settlement = block_then_call(
            database.call_sessions.update_maintenance_settlement
        )

    consumer = CallSettlementConsumerImpl(
        agent_settlement=_FixedAgentSettlement(),
        call_sessions=database.call_sessions,
        conversation_service=database.conversation_service,
        call_maintenance_batches=database.call_maintenance_batches,
    )
    task = asyncio.create_task(consumer.settle(snapshot))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

        persisted = database.call_sessions.find_by_id(call_id)
        assert persisted.summary_status is SettlementStatus.SUCCEEDED
        assert persisted.maintenance_status is SettlementStatus.FAILED
        with database.open_sql_session() as sql:
            assert sql.query(Conversation).filter_by(user_id="user", type="call").count() == 1
        await asyncio.sleep(0.05)
        assert database.call_sessions.find_by_id(call_id) == persisted
        assert not [
            pending for pending in asyncio.all_tasks() if pending is not asyncio.current_task() and not pending.done()
        ]
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await database.shutdown()


@pytest.mark.asyncio
async def test_real_agent_settlement_persists_one_private_call_record_and_progress(monkeypatch, tmp_path):
    vector = DeterministicVectorStore()
    monkeypatch.setattr(runtime_module, "get_vector_store", lambda: vector)
    monkeypatch.setattr(runtime_module, "clear_vector_store", lambda expected: expected is vector)
    monkeypatch.setattr(
        speaking_backend,
        "init_tts_module",
        lambda _config: DeterministicCallTTSModule(),
    )
    database = DatabaseManager({"sql_db_folder": str(tmp_path), "sql_db_file": "settlement.sqlite"})
    with database.open_sql_session() as sql:
        sql.add(
            User(
                uuid="user",
                username="settlement-user",
                password="offline",
                description="",
            )
        )
        sql.commit()
    runtime = runtime_module.AgentRuntime(
        runtime_config(tmp_path),
        DeterministicLLMService(),
        database,
        media_resolver=NoopMediaResolver(),
    )
    call_id = uuid4()
    requested_at = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
    record = CallSessionRecord(
        call_id=call_id,
        client_request_id="settlement-request",
        user_id="user",
        character_id="luotianyi",
        state=CallState.ENDED,
        requested_at=requested_at,
        created_at=requested_at,
        updated_at=requested_at,
        outcome=CallOutcome.CONNECTED,
        end_reason=CallEndReason.USER_HANGUP,
        connected_at=requested_at,
        ended_at=requested_at,
        active_duration_ms=65_000,
    )
    database.call_sessions.create_if_absent(record)
    snapshot = CallFinalSnapshot(
        CallTerminalFacts(
            call_id,
            CallOutcome.CONNECTED,
            CallEndReason.USER_HANGUP,
            65_000,
            requested_at,
        ),
        (CallFinalTurn(1, "用户说喜欢音乐", CallReplyStatus.COMPLETED, "角色回应会记住"),),
        0,
    )
    consumer = CallSettlementConsumerImpl(
        agent_settlement=CallAgentSettlement(
            get_agent=runtime.get_agent,
            get_context_factory=lambda character_id: runtime.context_factories[character_id],
        ),
        call_sessions=database.call_sessions,
        conversation_service=database.conversation_service,
        call_maintenance_batches=database.call_maintenance_batches,
    )

    try:
        await consumer.settle(snapshot)
        await consumer.settle(snapshot)

        persisted = database.call_sessions.find_by_id(call_id)
        assert persisted.summary_status is SettlementStatus.SUCCEEDED
        assert persisted.maintenance_status is SettlementStatus.SUCCEEDED
        assert persisted.maintenance_turn_seq == 1
        assert persisted.conversation_id == derive_call_conversation_id(
            user_id="user", character_id="luotianyi", call_id=call_id
        )
        with database.open_sql_session() as sql:
            rows = sql.query(Conversation).filter_by(user_id="user", type="call").all()
            assert len(rows) == 1
            assert "讨论了音乐喜好" in rows[0].content
            metadata = json.loads(rows[0].meta_data)
            assert metadata["summary"] == "用户与角色讨论了音乐喜好，并约定之后继续交流。"
            assert "用户说喜欢音乐" not in rows[0].meta_data
            batch = sql.query(CallMaintenanceBatch).filter_by(call_id=str(call_id)).one()
            assert batch.status == "completed"
            assert "用户说喜欢音乐" not in batch.candidates
            assert "角色回应会记住" not in batch.candidates
            assert all(
                set(candidate) == {"candidate_index", "memory_type", "content"}
                for candidate in json.loads(batch.candidates)
            )
        frozen_batch = database.call_maintenance_batches.load(
            call_id=call_id,
            user_id="user",
            character_id="luotianyi",
            previous_turn_seq=0,
            target_turn_seq=1,
        )
        assert frozen_batch.status == "completed"
        history = await UserConversationHelper(database).handle_history_request("user", 10, -1)
        assert history["history"] == [
            {
                "uuid": str(persisted.conversation_id),
                "content": "[语音通话] 01:05",
                "source": "user",
                "timestamp": "2026-10-11 20:00:00",
                "type": "call",
                "outcome": "connected",
                "active_duration_ms": 65_000,
            }
        ]
    finally:
        await runtime.shutdown()
        await database.shutdown()


@pytest.mark.asyncio
async def test_preanswer_call_records_without_agent_model_or_turn_progress(tmp_path):
    database = DatabaseManager({"sql_db_folder": str(tmp_path), "sql_db_file": "preanswer.sqlite"})
    with database.open_sql_session() as sql:
        sql.add(User(uuid="user", username="preanswer", password="offline", description=""))
        sql.commit()
    call_id = uuid4()
    requested_at = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
    record = CallSessionRecord(
        call_id=call_id,
        client_request_id="preanswer-request",
        user_id="user",
        character_id="luotianyi",
        state=CallState.ENDED,
        requested_at=requested_at,
        created_at=requested_at,
        updated_at=requested_at,
        outcome=CallOutcome.DECLINED,
        end_reason=CallEndReason.DECLINED,
        ended_at=requested_at,
    )
    database.call_sessions.create_if_absent(record)
    snapshot = CallFinalSnapshot(
        CallTerminalFacts(call_id, CallOutcome.DECLINED, CallEndReason.DECLINED, 0, requested_at),
        (),
        0,
    )

    class AgentPort:
        async def settle(self, *args, **kwargs):
            raise AssertionError("pre-answer settlement must not call Agent")

    consumer = CallSettlementConsumerImpl(
        agent_settlement=AgentPort(),
        call_sessions=database.call_sessions,
        conversation_service=database.conversation_service,
    )
    await consumer.settle(snapshot)

    persisted = database.call_sessions.find_by_id(call_id)
    assert persisted.summary_status is SettlementStatus.SUCCEEDED
    assert persisted.maintenance_status is SettlementStatus.SUCCEEDED
    assert persisted.maintenance_turn_seq == 0
    with database.open_sql_session() as sql:
        row = sql.query(Conversation).filter_by(uuid=str(persisted.conversation_id)).one()
        assert row.content == "[语音通话] 未接听"
        assert json.loads(row.meta_data)["summary"] is None
    await database.shutdown()


@pytest.mark.asyncio
async def test_committed_call_winner_skips_summary_model_and_repairs_pending_cas(monkeypatch, tmp_path):
    vector = DeterministicVectorStore()
    monkeypatch.setattr(runtime_module, "get_vector_store", lambda: vector)
    monkeypatch.setattr(runtime_module, "clear_vector_store", lambda expected: expected is vector)
    monkeypatch.setattr(
        speaking_backend,
        "init_tts_module",
        lambda _config: DeterministicCallTTSModule(),
    )
    database = DatabaseManager({"sql_db_folder": str(tmp_path), "sql_db_file": "winner.sqlite"})
    with database.open_sql_session() as sql:
        sql.add(User(uuid="user", username="winner", password="offline", description=""))
        sql.commit()
    llm = DeterministicLLMService()
    runtime = runtime_module.AgentRuntime(runtime_config(tmp_path), llm, database, media_resolver=NoopMediaResolver())
    call_id = uuid4()
    requested_at = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
    record = CallSessionRecord(
        call_id=call_id,
        client_request_id="winner-request",
        user_id="user",
        character_id="luotianyi",
        state=CallState.ENDED,
        requested_at=requested_at,
        created_at=requested_at,
        updated_at=requested_at,
        outcome=CallOutcome.CONNECTED,
        end_reason=CallEndReason.USER_HANGUP,
        connected_at=requested_at,
        ended_at=requested_at,
        active_duration_ms=1000,
    )
    database.call_sessions.create_if_absent(record)
    snapshot = CallFinalSnapshot(
        CallTerminalFacts(
            call_id,
            CallOutcome.CONNECTED,
            CallEndReason.USER_HANGUP,
            1000,
            requested_at,
        ),
        (CallFinalTurn(1, "用户事实", CallReplyStatus.COMPLETED, "正式回复"),),
        0,
    )
    conversation_id = derive_call_conversation_id(user_id="user", character_id="luotianyi", call_id=call_id)
    from src.domain.conversation_type import ConversationItem

    database.conversation_service.add_call_conversation(
        "user",
        "luotianyi",
        ConversationItem(
            uuid=str(conversation_id),
            timestamp=record.requested_at.replace(tzinfo=None).isoformat(sep=" ", timespec="microseconds"),
            source="user",
            type="call",
            content="[语音通话]既有胜者概要",
            data={
                "call_id": str(call_id),
                "outcome": "connected",
                "active_duration_ms": 1000,
                "summary": "既有胜者概要",
                "end_reason": "user_hangup",
            },
        ),
    )
    consumer = CallSettlementConsumerImpl(
        agent_settlement=CallAgentSettlement(
            get_agent=runtime.get_agent,
            get_context_factory=lambda character_id: runtime.context_factories[character_id],
        ),
        call_sessions=database.call_sessions,
        conversation_service=database.conversation_service,
        call_maintenance_batches=database.call_maintenance_batches,
    )

    try:
        await consumer.settle(snapshot)
        persisted = database.call_sessions.find_by_id(call_id)
        assert persisted.summary_status is SettlementStatus.SUCCEEDED
        assert persisted.conversation_id == conversation_id
        assert llm.modules["luotianyi_call_summary"].calls == []
        with database.open_sql_session() as sql:
            assert sql.query(Conversation).filter_by(type="call").count() == 1
    finally:
        await runtime.shutdown()
        await database.shutdown()


@pytest.mark.asyncio
async def test_same_call_different_snapshot_digest_rejects_before_agent_or_writes(
    tmp_path,
):
    database = DatabaseManager({"sql_db_folder": str(tmp_path), "sql_db_file": "conflict.sqlite"})
    with database.open_sql_session() as sql:
        sql.add(User(uuid="user", username="conflict", password="offline", description=""))
        sql.commit()
    call_id = uuid4()
    requested_at = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
    record = CallSessionRecord(
        call_id=call_id,
        client_request_id="conflict-request",
        user_id="user",
        character_id="luotianyi",
        state=CallState.ENDED,
        requested_at=requested_at,
        created_at=requested_at,
        updated_at=requested_at,
        outcome=CallOutcome.CONNECTED,
        end_reason=CallEndReason.USER_HANGUP,
        connected_at=requested_at,
        ended_at=requested_at,
        active_duration_ms=1000,
    )
    database.call_sessions.create_if_absent(record)
    first = CallFinalSnapshot(
        CallTerminalFacts(
            call_id,
            CallOutcome.CONNECTED,
            CallEndReason.USER_HANGUP,
            1000,
            requested_at,
        ),
        (CallFinalTurn(1, "原始事实", CallReplyStatus.NOT_STARTED, None),),
        0,
    )
    changed = CallFinalSnapshot(
        first.terminal,
        (CallFinalTurn(1, "冲突事实", CallReplyStatus.NOT_STARTED, None),),
        0,
    )
    calls = 0

    class AgentPort:
        async def settle(self, *args, **kwargs):
            nonlocal calls
            calls += 1
            raise RuntimeError("stop after digest claim")

    consumer = CallSettlementConsumerImpl(
        agent_settlement=AgentPort(),
        call_sessions=database.call_sessions,
        conversation_service=database.conversation_service,
        call_maintenance_batches=database.call_maintenance_batches,
    )
    with pytest.raises(RuntimeError, match="stop after digest claim"):
        await consumer.settle(first)
    with pytest.raises(ValueError, match="SETTLEMENT_INPUT_CONFLICT"):
        await consumer.settle(changed)

    assert calls == 1
    with database.open_sql_session() as sql:
        assert sql.query(Conversation).count() == 0
        assert sql.query(CallMaintenanceBatch).count() == 0
    await database.shutdown()


@pytest.mark.asyncio
async def test_scoped_call_lookup_rejects_wrong_owner_and_character(tmp_path):
    database = DatabaseManager({"sql_db_folder": str(tmp_path), "sql_db_file": "scope.sqlite"})
    with database.open_sql_session() as sql:
        sql.add(User(uuid="user", username="scope", password="offline", description=""))
        sql.commit()
    from src.domain.conversation_type import ConversationItem

    conversation_id = uuid4()
    database.conversation_service.add_call_conversation(
        "user",
        "luotianyi",
        ConversationItem(
            uuid=str(conversation_id),
            timestamp="2026-10-11 20:00:00",
            source="user",
            type="call",
            content="[语音通话]概要",
            data={
                "call_id": str(uuid4()),
                "outcome": "connected",
                "active_duration_ms": 1,
                "summary": "概要",
                "end_reason": "user_hangup",
            },
        ),
    )
    from src.infrastructure.persistence.database.services.conversation_service import (
        ConversationIdentityConflict,
    )

    with pytest.raises(ConversationIdentityConflict):
        database.conversation_service.get_call_conversation(
            str(conversation_id), user_id="other", character_id="luotianyi"
        )
    with pytest.raises(ConversationIdentityConflict):
        database.conversation_service.get_call_conversation(str(conversation_id), user_id="user", character_id="other")
    await database.shutdown()


@pytest.mark.asyncio
async def test_legacy_null_digest_batch_fails_only_maintenance_and_releases_resources(monkeypatch, tmp_path):
    vector = DeterministicVectorStore()
    monkeypatch.setattr(runtime_module, "get_vector_store", lambda: vector)
    monkeypatch.setattr(runtime_module, "clear_vector_store", lambda expected: expected is vector)
    monkeypatch.setattr(
        speaking_backend,
        "init_tts_module",
        lambda _config: DeterministicCallTTSModule(),
    )
    database = DatabaseManager({"sql_db_folder": str(tmp_path), "sql_db_file": "legacy-null.sqlite"})
    with database.open_sql_session() as sql:
        sql.add(User(uuid="user", username="legacy", password="offline", description=""))
        sql.commit()
    runtime = runtime_module.AgentRuntime(
        runtime_config(tmp_path),
        DeterministicLLMService(),
        database,
        media_resolver=NoopMediaResolver(),
    )
    call_id = uuid4()
    requested_at = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
    record = CallSessionRecord(
        call_id=call_id,
        client_request_id="legacy-null-request",
        user_id="user",
        character_id="luotianyi",
        state=CallState.ENDED,
        requested_at=requested_at,
        created_at=requested_at,
        updated_at=requested_at,
        outcome=CallOutcome.CONNECTED,
        end_reason=CallEndReason.USER_HANGUP,
        connected_at=requested_at,
        ended_at=requested_at,
        active_duration_ms=1000,
    )
    database.call_sessions.create_if_absent(record)
    snapshot = CallFinalSnapshot(
        CallTerminalFacts(
            call_id,
            CallOutcome.CONNECTED,
            CallEndReason.USER_HANGUP,
            1000,
            requested_at,
        ),
        (CallFinalTurn(1, "敏感用户事实", CallReplyStatus.COMPLETED, "正式回复"),),
        0,
    )
    with database.open_sql_session() as sql:
        sql.add(
            CallMaintenanceBatch(
                maintenance_id="legacy-null",
                call_id=str(call_id),
                user_id="user",
                character_id="luotianyi",
                previous_turn_seq=0,
                target_turn_seq=1,
                settlement_input_digest=None,
                candidates="[]",
                proposed_profile=None,
                status="frozen",
                created_at=requested_at.replace(tzinfo=None),
                updated_at=requested_at.replace(tzinfo=None),
            )
        )
        sql.commit()
    memory = runtime.skills.call_maintenance._memories["luotianyi"]
    extract_calls = write_calls = 0

    async def no_extract(**kwargs):
        nonlocal extract_calls
        extract_calls += 1
        return ()

    async def no_write(**kwargs):
        nonlocal write_calls
        write_calls += 1

    memory.extract_maintenance_candidates = no_extract
    memory.write_maintenance_candidates = no_write
    consumer = CallSettlementConsumerImpl(
        agent_settlement=CallAgentSettlement(
            get_agent=runtime.get_agent,
            get_context_factory=lambda character_id: runtime.context_factories[character_id],
        ),
        call_sessions=database.call_sessions,
        conversation_service=database.conversation_service,
        call_maintenance_batches=database.call_maintenance_batches,
    )
    settlement = CallSettlement(consumer=consumer, timeout_seconds=1)
    try:
        await settlement.settle(snapshot)

        persisted = database.call_sessions.find_by_id(call_id)
        assert persisted.maintenance_status is not SettlementStatus.SUCCEEDED
        assert extract_calls == 0
        assert write_calls == 0
        with database.open_sql_session() as sql:
            row = sql.query(CallMaintenanceBatch).filter_by(maintenance_id="legacy-null").one()
            assert row.candidates == "[]"
            assert row.settlement_input_digest is None
    finally:
        await runtime.shutdown()
        await database.shutdown()


@pytest.mark.asyncio
async def test_issue_324_maintenance_deadline_recovers_one_call_history_once(monkeypatch, tmp_path):
    vector = DeterministicVectorStore()
    monkeypatch.setattr(runtime_module, "get_vector_store", lambda: vector)
    monkeypatch.setattr(runtime_module, "clear_vector_store", lambda expected: expected is vector)
    monkeypatch.setattr(
        speaking_backend,
        "init_tts_module",
        lambda _config: DeterministicCallTTSModule(),
    )
    database = DatabaseManager({"sql_db_folder": str(tmp_path), "sql_db_file": "issue-324.sqlite"})
    with database.open_sql_session() as sql:
        sql.add(User(uuid="user", username="issue-324", password="offline", description=""))
        sql.commit()
    runtime = runtime_module.AgentRuntime(
        runtime_config(tmp_path),
        DeterministicLLMService(),
        database,
        media_resolver=NoopMediaResolver(),
    )
    call_id = uuid4()
    requested_at = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
    record = CallSessionRecord(
        call_id=call_id,
        client_request_id="issue-324-request",
        user_id="user",
        character_id="luotianyi",
        state=CallState.ENDED,
        requested_at=requested_at,
        created_at=requested_at,
        updated_at=requested_at,
        outcome=CallOutcome.CONNECTED,
        end_reason=CallEndReason.USER_HANGUP,
        connected_at=requested_at,
        ended_at=requested_at,
        active_duration_ms=5_000,
    )
    database.call_sessions.create_if_absent(record)
    snapshot = CallFinalSnapshot(
        CallTerminalFacts(call_id, CallOutcome.CONNECTED, CallEndReason.USER_HANGUP, 5_000, requested_at),
        (CallFinalTurn(1, "用户事实", CallReplyStatus.COMPLETED, "正式回复"),),
        0,
    )
    maintenance_started = asyncio.Event()

    async def blocked_maintenance(*args, **kwargs):
        maintenance_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(runtime.skills.call_maintenance, "maintain_ending", blocked_maintenance)
    consumer = CallSettlementConsumerImpl(
        agent_settlement=CallAgentSettlement(
            get_agent=runtime.get_agent,
            get_context_factory=lambda character_id: runtime.context_factories[character_id],
        ),
        call_sessions=database.call_sessions,
        conversation_service=database.conversation_service,
        call_maintenance_batches=database.call_maintenance_batches,
    )
    settlement = CallSettlement(consumer=consumer, timeout_seconds=0.3)

    class ProjectionVerifier:
        def verify_completed_batch(self, batch):
            raise AssertionError("the blocked maintenance lane must not have a completed batch")

    recovery = StaleCallRecoveryService(
        call_sessions=database.call_sessions,
        conversation_service=database.conversation_service,
        call_maintenance_batches=database.call_maintenance_batches,
        projection_verifier=ProjectionVerifier(),
        wall_clock=lambda: requested_at,
    )
    try:
        await settlement.settle(snapshot)
        assert maintenance_started.is_set()
        timed_out = database.call_sessions.find_by_id(call_id)
        with database.open_sql_session() as sql:
            live_rows = sql.query(Conversation).filter_by(user_id="user", type="call").all()
            assert sql.query(CallMaintenanceBatch).filter_by(call_id=str(call_id)).count() == 0
        assert timed_out.summary_status is SettlementStatus.SUCCEEDED
        assert timed_out.maintenance_status is SettlementStatus.FAILED
        assert len(live_rows) == 1

        first = await recovery.reconcile()
        second = await recovery.reconcile()
        persisted = database.call_sessions.find_by_id(call_id)
        with database.open_sql_session() as sql:
            conversations = sql.query(Conversation).filter_by(user_id="user", type="call").all()
            batches = sql.query(CallMaintenanceBatch).filter_by(call_id=str(call_id)).all()

        assert first.scanned == 0
        assert second.scanned == 0
        assert persisted.summary_status is SettlementStatus.SUCCEEDED
        assert persisted.maintenance_status is SettlementStatus.FAILED
        assert len(conversations) == 1
        assert batches == []
        assert not [task for task in asyncio.all_tasks() if task is not asyncio.current_task() and not task.done()]
    finally:
        await runtime.shutdown()
        await database.shutdown()


@pytest.mark.asyncio
async def test_issue_324_summary_deadline_persists_static_fallback_and_stops_task(monkeypatch, tmp_path):
    vector = DeterministicVectorStore()
    monkeypatch.setattr(runtime_module, "get_vector_store", lambda: vector)
    monkeypatch.setattr(runtime_module, "clear_vector_store", lambda expected: expected is vector)
    monkeypatch.setattr(speaking_backend, "init_tts_module", lambda _config: DeterministicCallTTSModule())
    database = DatabaseManager({"sql_db_folder": str(tmp_path), "sql_db_file": "summary-timeout.sqlite"})
    with database.open_sql_session() as sql:
        sql.add(User(uuid="user", username="summary-timeout", password="offline", description=""))
        sql.commit()
    runtime = runtime_module.AgentRuntime(
        runtime_config(tmp_path), DeterministicLLMService(), database, media_resolver=NoopMediaResolver()
    )
    call_id = uuid4()
    requested_at = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
    database.call_sessions.create_if_absent(
        CallSessionRecord(
            call_id=call_id,
            client_request_id="summary-timeout-request",
            user_id="user",
            character_id="luotianyi",
            state=CallState.ENDED,
            requested_at=requested_at,
            created_at=requested_at,
            updated_at=requested_at,
            outcome=CallOutcome.CONNECTED,
            end_reason=CallEndReason.USER_HANGUP,
            connected_at=requested_at,
            ended_at=requested_at,
            active_duration_ms=5_000,
        )
    )
    snapshot = CallFinalSnapshot(
        CallTerminalFacts(call_id, CallOutcome.CONNECTED, CallEndReason.USER_HANGUP, 5_000, requested_at),
        (CallFinalTurn(1, "用户事实", CallReplyStatus.COMPLETED, "正式回复"),),
        0,
    )
    summary_started = asyncio.Event()
    summary_stopped = asyncio.Event()

    async def no_maintenance(*args, **kwargs):
        return 1

    async def blocked_summary(*args, **kwargs):
        summary_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            summary_stopped.set()

    monkeypatch.setattr(runtime.skills.call_maintenance, "maintain_ending", no_maintenance)
    monkeypatch.setattr(runtime.skills.call_summary, "summarize", blocked_summary)
    settlement = CallSettlement(
        consumer=CallSettlementConsumerImpl(
            agent_settlement=CallAgentSettlement(
                get_agent=runtime.get_agent,
                get_context_factory=lambda character_id: runtime.context_factories[character_id],
            ),
            call_sessions=database.call_sessions,
            conversation_service=database.conversation_service,
            call_maintenance_batches=database.call_maintenance_batches,
        ),
        timeout_seconds=0.3,
    )
    try:
        await settlement.settle(snapshot)
        persisted = database.call_sessions.find_by_id(call_id)
        with database.open_sql_session() as sql:
            row = sql.query(Conversation).filter_by(user_id="user", type="call").one()
        assert summary_started.is_set()
        assert summary_stopped.is_set()
        assert persisted.summary_status is SettlementStatus.SUCCEEDED
        assert persisted.maintenance_status is SettlementStatus.SUCCEEDED
        assert json.loads(row.meta_data)["summary"] == "本次通话未能形成可用概要"
        assert not [task for task in asyncio.all_tasks() if task is not asyncio.current_task() and not task.done()]
    finally:
        await runtime.shutdown()
        await database.shutdown()


@pytest.mark.asyncio
async def test_issue_324_write_failure_marks_stable_summary_failed_and_finishes_maintenance(monkeypatch, tmp_path):
    vector = DeterministicVectorStore()
    monkeypatch.setattr(runtime_module, "get_vector_store", lambda: vector)
    monkeypatch.setattr(runtime_module, "clear_vector_store", lambda expected: expected is vector)
    monkeypatch.setattr(speaking_backend, "init_tts_module", lambda _config: DeterministicCallTTSModule())
    database = DatabaseManager({"sql_db_folder": str(tmp_path), "sql_db_file": "write-failure.sqlite"})
    with database.open_sql_session() as sql:
        sql.add(User(uuid="user", username="write-failure", password="offline", description=""))
        sql.commit()
    runtime = runtime_module.AgentRuntime(
        runtime_config(tmp_path), DeterministicLLMService(), database, media_resolver=NoopMediaResolver()
    )
    call_id = uuid4()
    requested_at = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
    database.call_sessions.create_if_absent(
        CallSessionRecord(
            call_id=call_id,
            client_request_id="write-failure-request",
            user_id="user",
            character_id="luotianyi",
            state=CallState.ENDED,
            requested_at=requested_at,
            created_at=requested_at,
            updated_at=requested_at,
            outcome=CallOutcome.CONNECTED,
            end_reason=CallEndReason.USER_HANGUP,
            connected_at=requested_at,
            ended_at=requested_at,
            active_duration_ms=5_000,
        )
    )
    snapshot = CallFinalSnapshot(
        CallTerminalFacts(call_id, CallOutcome.CONNECTED, CallEndReason.USER_HANGUP, 5_000, requested_at),
        (CallFinalTurn(1, "用户事实", CallReplyStatus.COMPLETED, "正式回复"),),
        0,
    )
    original_write = database.conversation_service.add_call_conversation

    def fail_write(*args, **kwargs):
        raise OSError("injected write failure")

    monkeypatch.setattr(database.conversation_service, "add_call_conversation", fail_write)
    settlement = CallSettlement(
        consumer=CallSettlementConsumerImpl(
            agent_settlement=CallAgentSettlement(
                get_agent=runtime.get_agent,
                get_context_factory=lambda character_id: runtime.context_factories[character_id],
            ),
            call_sessions=database.call_sessions,
            conversation_service=database.conversation_service,
            call_maintenance_batches=database.call_maintenance_batches,
        ),
        timeout_seconds=1,
    )

    class ProjectionVerifier:
        def verify_completed_batch(self, batch):
            return True

    try:
        await settlement.settle(snapshot)
        failed = database.call_sessions.find_by_id(call_id)
        assert failed.summary_status is SettlementStatus.FAILED
        assert failed.maintenance_status is SettlementStatus.SUCCEEDED
        monkeypatch.setattr(database.conversation_service, "add_call_conversation", original_write)
        recovery = StaleCallRecoveryService(
            call_sessions=database.call_sessions,
            conversation_service=database.conversation_service,
            call_maintenance_batches=database.call_maintenance_batches,
            projection_verifier=ProjectionVerifier(),
            wall_clock=lambda: requested_at,
        )
        first = await recovery.reconcile()
        second = await recovery.reconcile()
        repaired = database.call_sessions.find_by_id(call_id)
        with database.open_sql_session() as sql:
            assert sql.query(Conversation).filter_by(user_id="user", type="call").count() == 0
        assert first.scanned == 0
        assert second.scanned == 0
        assert repaired.summary_status is SettlementStatus.FAILED
        assert repaired.maintenance_status is SettlementStatus.SUCCEEDED
    finally:
        await runtime.shutdown()
        await database.shutdown()


@pytest.mark.asyncio
async def test_issue_324_summary_cas_failure_repairs_persisted_winner_without_model_or_duplicate(monkeypatch, tmp_path):
    vector = DeterministicVectorStore()
    monkeypatch.setattr(runtime_module, "get_vector_store", lambda: vector)
    monkeypatch.setattr(runtime_module, "clear_vector_store", lambda expected: expected is vector)
    monkeypatch.setattr(speaking_backend, "init_tts_module", lambda _config: DeterministicCallTTSModule())
    database = DatabaseManager({"sql_db_folder": str(tmp_path), "sql_db_file": "cas-failure.sqlite"})
    with database.open_sql_session() as sql:
        sql.add(User(uuid="user", username="cas-failure", password="offline", description=""))
        sql.commit()
    llm = DeterministicLLMService()
    runtime = runtime_module.AgentRuntime(runtime_config(tmp_path), llm, database, media_resolver=NoopMediaResolver())
    call_id = uuid4()
    requested_at = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
    database.call_sessions.create_if_absent(
        CallSessionRecord(
            call_id=call_id,
            client_request_id="cas-failure-request",
            user_id="user",
            character_id="luotianyi",
            state=CallState.ENDED,
            requested_at=requested_at,
            created_at=requested_at,
            updated_at=requested_at,
            outcome=CallOutcome.CONNECTED,
            end_reason=CallEndReason.USER_HANGUP,
            connected_at=requested_at,
            ended_at=requested_at,
            active_duration_ms=5_000,
        )
    )
    snapshot = CallFinalSnapshot(
        CallTerminalFacts(call_id, CallOutcome.CONNECTED, CallEndReason.USER_HANGUP, 5_000, requested_at),
        (CallFinalTurn(1, "用户事实", CallReplyStatus.COMPLETED, "正式回复"),),
        0,
    )
    original_update = database.call_sessions.update_summary_settlement
    failed_once = False

    def fail_first_summary_cas(*args, **kwargs):
        nonlocal failed_once
        if not failed_once:
            failed_once = True
            return False
        return original_update(*args, **kwargs)

    monkeypatch.setattr(database.call_sessions, "update_summary_settlement", fail_first_summary_cas)
    settlement = CallSettlement(
        consumer=CallSettlementConsumerImpl(
            agent_settlement=CallAgentSettlement(
                get_agent=runtime.get_agent,
                get_context_factory=lambda character_id: runtime.context_factories[character_id],
            ),
            call_sessions=database.call_sessions,
            conversation_service=database.conversation_service,
            call_maintenance_batches=database.call_maintenance_batches,
        ),
        timeout_seconds=1,
    )

    class ProjectionVerifier:
        def verify_completed_batch(self, batch):
            return True

    try:
        await settlement.settle(snapshot)
        pending = database.call_sessions.find_by_id(call_id)
        with database.open_sql_session() as sql:
            assert sql.query(Conversation).filter_by(user_id="user", type="call").count() == 1
        summary_calls = len(llm.modules["luotianyi_call_summary"].calls)
        recovery = StaleCallRecoveryService(
            call_sessions=database.call_sessions,
            conversation_service=database.conversation_service,
            call_maintenance_batches=database.call_maintenance_batches,
            projection_verifier=ProjectionVerifier(),
            wall_clock=lambda: requested_at,
        )
        first = await recovery.reconcile()
        second = await recovery.reconcile()
        repaired = database.call_sessions.find_by_id(call_id)
        with database.open_sql_session() as sql:
            assert sql.query(Conversation).filter_by(user_id="user", type="call").count() == 1
        assert pending.summary_status is SettlementStatus.PENDING
        assert first.recovered == 1
        assert second.scanned == 0
        assert repaired.summary_status is SettlementStatus.SUCCEEDED
        assert len(llm.modules["luotianyi_call_summary"].calls) == summary_calls
    finally:
        await runtime.shutdown()
        await database.shutdown()
