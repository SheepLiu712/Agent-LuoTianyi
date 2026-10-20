import json
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
    CallEndingResult,
    CallEndReason,
    CallFinalSnapshot,
    CallFinalTurn,
    CallOutcome,
    CallReplyStatus,
    CallState,
    CallSummarySource,
    CallTerminalFacts,
    derive_call_conversation_id,
)
from src.infrastructure.persistence.call_sessions import (
    CallSessionRecord,
    SettlementStatus,
)
from src.infrastructure.persistence.database import DatabaseManager
from src.infrastructure.persistence.database.sql_database import (
    Conversation,
    User,
)
from src.stage._call_history import CallHistory


@pytest.mark.asyncio
async def test_history_persists_one_private_call_record_and_progress(monkeypatch, tmp_path):
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
    consumer = CallHistory(call_sessions=database.call_sessions, conversation_service=database.conversation_service)

    try:
        await consumer.save(
            snapshot,
            result=(
                CallEndingResult("用户与角色讨论了音乐喜好，并约定之后继续交流。", CallSummarySource.GENERATED, True, 1)
                if record.outcome is CallOutcome.CONNECTED
                else None
            ),
        )
        await consumer.save(
            snapshot,
            result=(
                CallEndingResult("用户与角色讨论了音乐喜好，并约定之后继续交流。", CallSummarySource.GENERATED, True, 1)
                if record.outcome is CallOutcome.CONNECTED
                else None
            ),
        )

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

    consumer = CallHistory(call_sessions=database.call_sessions, conversation_service=database.conversation_service)
    await consumer.save(
        snapshot,
        result=(
            CallEndingResult("用户与角色讨论了音乐喜好，并约定之后继续交流。", CallSummarySource.GENERATED, True, 1)
            if record.outcome is CallOutcome.CONNECTED
            else None
        ),
    )

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
async def test_history_preserves_committed_winner_and_repairs_pending_cas(monkeypatch, tmp_path):
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
    consumer = CallHistory(call_sessions=database.call_sessions, conversation_service=database.conversation_service)

    try:
        await consumer.save(
            snapshot,
            result=(
                CallEndingResult("用户与角色讨论了音乐喜好，并约定之后继续交流。", CallSummarySource.GENERATED, True, 1)
                if record.outcome is CallOutcome.CONNECTED
                else None
            ),
        )
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
@pytest.mark.parametrize("committed", [False, True])
@pytest.mark.parametrize("maintenance_succeeded", [False, True])
async def test_history_write_failure_does_not_skip_maintenance_status(
    tmp_path, monkeypatch, committed, maintenance_succeeded
):
    database = DatabaseManager({"sql_db_folder": str(tmp_path), "sql_db_file": "write-failure.sqlite"})
    with database.open_sql_session() as sql:
        sql.add(User(uuid="user", username="write-failure", password="offline", description=""))
        sql.commit()
    now = datetime.now(timezone.utc)
    call_id = uuid4()
    record = CallSessionRecord(
        call_id=call_id,
        client_request_id=str(call_id),
        user_id="user",
        character_id="luotianyi",
        state=CallState.ENDED,
        requested_at=now,
        created_at=now,
        updated_at=now,
        connected_at=now,
        ended_at=now,
        outcome=CallOutcome.CONNECTED,
        end_reason=CallEndReason.USER_HANGUP,
        active_duration_ms=1,
    )
    database.call_sessions.create_if_absent(record)
    snapshot = CallFinalSnapshot(
        CallTerminalFacts(call_id, CallOutcome.CONNECTED, CallEndReason.USER_HANGUP, 1, now), (), 0
    )
    original = database.conversation_service.add_call_conversation

    def broken(*args):
        if committed:
            original(*args)
        raise OSError("write response lost" if committed else "write failed")

    monkeypatch.setattr(database.conversation_service, "add_call_conversation", broken)
    history = CallHistory(call_sessions=database.call_sessions, conversation_service=database.conversation_service)
    result = CallEndingResult("[和用户打了一通电话]", CallSummarySource.DEFAULT, maintenance_succeeded, 0)
    try:
        if committed:
            await history.save(snapshot, result=result)
            await history.save(snapshot, result=result)
        else:
            with pytest.raises(OSError, match="write failed"):
                await history.save(snapshot, result=result)
        persisted = database.call_sessions.find_by_id(call_id)
        assert persisted.summary_status is (SettlementStatus.SUCCEEDED if committed else SettlementStatus.FAILED)
        assert persisted.maintenance_status is (
            SettlementStatus.SUCCEEDED if maintenance_succeeded else SettlementStatus.FAILED
        )
        with database.open_sql_session() as sql:
            assert sql.query(Conversation).filter_by(type="call").count() == int(committed)
    finally:
        await database.shutdown()
