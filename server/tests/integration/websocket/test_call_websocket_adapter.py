import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from support.call_session_repository import InMemoryCallSessionRepository
from support.realtime_speech import FakeRealtimeSpeechSessionFactory
from support.stage_manager import make_stage_manager

import src.domain.agent as d
from src.adapter.websocket.call_v1 import CallTransportError, CallWebSocketAdapter
from src.adapter.websocket.call_v1._binding import Binding
from src.adapter.websocket.call_v1._session import Session
from src.adapter.websocket.call_v1._messages import TransportBackpressure
from src.adapter.websocket.chat import WebSocketAdapter
from src.agent.context import ContextFactory
from src.application.user.reset_fence import UserResetFence
from src.domain.call import CallAnswerDecision, CallEndReason, CallState
from src.infrastructure.persistence.call_sessions import SqlCallSessionRepository
from src.infrastructure.persistence.database.sql_database import Base
from src.stage.call_stage import CallStateChanged
from src.utils.logger import get_logger
from tests.integration.stage.test_call_stage import _ContextDatabase
from tests.integration.stage.test_chat_stage import RecordingAgent

# ruff: noqa: C901 - deterministic concurrency probes intentionally inline local fakes


def start_message(request_id="request-1"):
    return json.dumps(
        {
            "protocol": "call.v1",
            "type": "call.start",
            "seq": 1,
            "client_request_id": request_id,
            "character_id": "luotianyi",
            "audio": {"encoding": "pcm_s16le", "sample_rate": 16000, "channels": 1},
        },
        separators=(",", ":"),
    )


def resume_message(call_id):
    return json.dumps(
        {
            "protocol": "call.v1",
            "type": "call.resume",
            "call_id": call_id,
            "character_id": "luotianyi",
            "last_contiguous_server_seq": 0,
        },
        separators=(",", ":"),
    )


def manager(*, speech_factory, repository=None, wall_clock=None):
    repository = repository or InMemoryCallSessionRepository()
    stages = make_stage_manager(
        get_agent=lambda _character: RecordingAgent(),
        adapter=WebSocketAdapter(),
        get_context_factory=lambda _character: ContextFactory(character_id="luotianyi", database=_ContextDatabase()),
        call_sessions=repository,
        realtime_speech_factory=speech_factory,
        user_reset_fence=UserResetFence(),
        wall_clock=wall_clock or (lambda: datetime.now(timezone.utc)),
    )
    return stages, repository


def call_adapter(stages):
    return CallWebSocketAdapter(
        manager=stages,
        user_reset_fence=stages._user_reset_fence,
        enabled=True,
        supports_character=lambda _character_id: True,
    )


class _IncrementingClock:
    def __init__(self):
        self.value = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        self.value += timedelta(microseconds=1)
        return self.value


class BlockingSpeechFactory:
    is_configured = True

    def __init__(self):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def create(self, _call_id):
        self.calls += 1
        self.entered.set()
        await self.release.wait()
        raise RuntimeError("provider unavailable")


@pytest.mark.asyncio
async def test_unavailable_character_is_rejected_before_business_claim():
    speech = BlockingSpeechFactory()
    stages, repository = manager(speech_factory=speech)
    adapter = CallWebSocketAdapter(
        manager=stages,
        user_reset_fence=stages._user_reset_fence,
        enabled=True,
        supports_character=lambda character_id: character_id == "luotianyi",
    )
    raw = start_message().replace('"luotianyi"', '"other"')

    with pytest.raises(CallTransportError) as rejected:
        await adapter.open(initial_message=raw, user_id="user", connection_id=object())

    assert rejected.value.code == "CALL_CHARACTER_UNAVAILABLE"
    assert rejected.value.request_id == "request-1"
    assert repository.find_by_request("request-1") is None
    assert stages._call_claims == {}
    await adapter.close()
    await stages.close()


@pytest.mark.asyncio
async def test_call_start_during_finalization_returns_retryable_public_error(
    monkeypatch,
):
    speech = BlockingSpeechFactory()
    stages, repository = manager(speech_factory=speech)
    adapter = call_adapter(stages)

    async def reject_finalizing(*_args, **_kwargs):
        from src.stage import InteractionFinalizing

        raise InteractionFinalizing()

    monkeypatch.setattr(stages, "_get_call_stage", reject_finalizing)
    with pytest.raises(CallTransportError) as rejected:
        await adapter.open(initial_message=start_message(), user_id="user", connection_id=object())

    assert rejected.value.code == "INTERACTION_FINALIZING"
    assert rejected.value.retryable is True
    assert rejected.value.request_id == "request-1"
    assert repository.find_by_request("request-1") is None
    assert adapter._sessions == {}
    await adapter.close()
    await stages.close()


@pytest.mark.asyncio
async def test_open_orders_preparing_before_ack_and_repeated_start_keeps_identity_and_deadline():
    speech = BlockingSpeechFactory()
    stages, repository = manager(speech_factory=speech)
    adapter = call_adapter(stages)
    first = await asyncio.wait_for(
        adapter.open(initial_message=start_message(), user_id="user", connection_id=object()), 2
    )
    preparing = json.loads((await adapter.next_output(first)).message)
    ack = json.loads((await adapter.next_output(first)).message)
    call_id = preparing["call_id"]
    deadline = stages._call_setup_deadlines["request-1"]
    assert preparing["type"] == "call.state" and preparing["state"] == "preparing"
    assert ack == {
        "protocol": "call.v1",
        "type": "ack",
        "call_id": call_id,
        "ack_seq": 1,
    }
    await adapter.disconnect(first)

    second = await adapter.open(initial_message=start_message(), user_id="user", connection_id=object())
    second_ack = json.loads((await adapter.next_output(second)).message)
    assert second_ack["call_id"] == call_id
    assert stages._call_setup_deadlines["request-1"] == deadline
    assert repository.find_by_request("request-1").call_id == uuid4().__class__(call_id)
    speech.release.set()
    await asyncio.wait_for(adapter.close(), 2)
    await asyncio.wait_for(stages.close(), 2)


@pytest.mark.asyncio
async def test_initialization_hangup_cancels_stage_preparation_without_waiting_for_provider():
    speech = BlockingSpeechFactory()
    stages, _ = manager(speech_factory=speech)
    adapter = call_adapter(stages)
    connection = await adapter.open(initial_message=start_message(), user_id="user", connection_id=object())
    await adapter.next_output(connection)
    await adapter.next_output(connection)
    await asyncio.wait_for(speech.entered.wait(), 1)
    call_id = next(iter(stages._call_stages)).strip()
    hangup = json.dumps(
        {
            "protocol": "call.v1",
            "type": "call.hangup",
            "seq": 2,
            "call_id": call_id,
            "reason": "user_hangup",
        }
    )
    receiving = asyncio.create_task(adapter.receive(connection, hangup))
    await asyncio.wait_for(receiving, 1)
    assert not speech.release.is_set()
    assert not stages._call_stages
    assert not stages._call_ownerships
    assert speech.calls == 1
    await adapter.close()
    await stages.close()


@pytest.mark.asyncio
async def test_unknown_resume_and_active_connection_takeover_are_rejected_without_new_identity():
    speech = BlockingSpeechFactory()
    stages, repository = manager(speech_factory=speech)
    adapter = call_adapter(stages)
    with pytest.raises(CallTransportError, match="CALL_NOT_FOUND"):
        await adapter.open(initial_message=resume_message(str(uuid4())), user_id="user", connection_id=object())
    assert repository.find_by_request("missing") is None
    await adapter.open(initial_message=start_message(), user_id="user", connection_id=object())
    with pytest.raises(CallTransportError, match="CALL_CONNECTION_ACTIVE"):
        await adapter.open(initial_message=start_message(), user_id="user", connection_id=object())
    speech.release.set()
    await adapter.close()
    await stages.close()


@pytest.mark.asyncio
async def test_cancelled_open_after_prepare_has_no_session_lease_or_request_task(monkeypatch):
    speech = BlockingSpeechFactory()
    stages, repository = manager(speech_factory=speech)
    adapter = call_adapter(stages)
    original = Session.attach
    registered = asyncio.Event()
    release = asyncio.Event()

    async def blocked_register(*args, **kwargs):
        await original(*args, **kwargs)
        registered.set()
        await release.wait()

    monkeypatch.setattr(Session, "attach", blocked_register)
    opening = asyncio.create_task(adapter.open(initial_message=start_message(), user_id="user", connection_id=object()))
    await asyncio.wait_for(registered.wait(), 1)
    opening.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await opening
    await asyncio.sleep(0)

    assert adapter._sessions == {}
    assert stages._call_open_tasks == {}
    assert stages._call_claims == {}
    assert stages._call_ownerships == {}
    assert stages._lease_registry.current("user", "luotianyi") is None
    record = repository.find_by_request("request-1")
    assert record is not None and record.state is CallState.FAILED
    with pytest.raises(CallTransportError) as duplicate:
        await adapter.open(initial_message=start_message(), user_id="user", connection_id=object())
    assert duplicate.value.code == "CALL_START_FAILED"
    assert duplicate.value.call_id == str(record.call_id)
    await adapter.close()
    await stages.close()


@pytest.mark.asyncio
async def test_concurrent_same_request_uses_one_transport_and_rejects_second_connection():
    speech = BlockingSpeechFactory()
    stages, repository = manager(speech_factory=speech)
    adapter = call_adapter(stages)
    first, second = await asyncio.gather(
        adapter.open(initial_message=start_message(), user_id="user", connection_id=object()),
        adapter.open(initial_message=start_message(), user_id="user", connection_id=object()),
        return_exceptions=True,
    )
    connections = [result for result in (first, second) if not isinstance(result, BaseException)]
    failures = [result for result in (first, second) if isinstance(result, BaseException)]
    assert len(connections) == 1
    assert len(failures) == 1 and "CALL_CONNECTION_ACTIVE" in str(failures[0])
    assert speech.calls <= 1
    assert len(adapter._sessions) == 1
    await adapter.next_output(connections[0])
    speech.release.set()
    await adapter.close()
    await stages.close()


@pytest.mark.asyncio
async def test_cross_identity_request_conflict_is_normalized_without_call_details():
    speech = BlockingSpeechFactory()
    stages, _ = manager(speech_factory=speech)
    adapter = call_adapter(stages)
    connection = await adapter.open(initial_message=start_message(), user_id="user-a", connection_id=object())
    await adapter.next_output(connection)
    await adapter.next_output(connection)
    with pytest.raises(CallTransportError) as rejected:
        await adapter.open(initial_message=start_message(), user_id="user-b", connection_id=object())
    assert rejected.value.code == "CALL_START_REJECTED"
    assert rejected.value.request_id == "request-1"
    assert rejected.value.request_seq == 1
    assert rejected.value.retryable is False
    assert rejected.value.close_code == 1013
    speech.release.set()
    await adapter.close()
    await stages.close()


@pytest.mark.asyncio
async def test_adapter_close_waits_for_cancelled_open_compensation_before_closing_transport(monkeypatch):
    speech = BlockingSpeechFactory()
    stages, _ = manager(speech_factory=speech)
    adapter = call_adapter(stages)
    original = Session.attach
    registered = asyncio.Event()
    release = asyncio.Event()

    async def blocked_register(*args, **kwargs):
        await original(*args, **kwargs)
        registered.set()
        await release.wait()

    monkeypatch.setattr(Session, "attach", blocked_register)
    opening = asyncio.create_task(adapter.open(initial_message=start_message(), user_id="user", connection_id=object()))
    await asyncio.wait_for(registered.wait(), 1)
    closing = asyncio.create_task(adapter.close())
    await asyncio.sleep(0)
    assert not closing.done()
    release.set()
    await asyncio.wait_for(closing, 1)
    with pytest.raises(asyncio.CancelledError):
        await opening
    assert adapter._sessions == {}
    assert stages._call_claims == {}
    assert stages._call_ownerships == {}
    assert stages._lease_registry.current("user", "luotianyi") is None
    await stages.close()


async def _eventually(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(0.001)

    await asyncio.wait_for(wait(), 2)


async def _opened(adapter):
    connection = await adapter.open(initial_message=start_message(), user_id="user", connection_id=object())
    preparing = await adapter.next_output(connection)
    call_id = json.loads(preparing.message)["call_id"]
    adapter.complete_output(connection, preparing.delivery_id)
    ack = await adapter.next_output(connection)
    adapter.complete_output(connection, ack.delivery_id)
    return connection, call_id


async def _activate(stages, call_id):
    stage = stages._call_stages[call_id]
    await _eventually(lambda: stage.state is CallState.RINGING)
    await stage.apply_answer(
        d.AnswerCall(action_id="answer", call_id=stage._record.call_id, decision=CallAnswerDecision.ACCEPT)
    )
    assert stage.state is CallState.ACTIVE
    return stage


@pytest.mark.asyncio
@pytest.mark.parametrize("repeat_start", [False, True])
async def test_preparing_disconnect_keeps_stage_and_pending_answer_until_rebound(repeat_start):
    class DelayedSpeech(FakeRealtimeSpeechSessionFactory):
        def __init__(self):
            super().__init__()
            self.release = asyncio.Event()

        async def create(self, call_id):
            await self.release.wait()
            return await super().create(call_id)

    speech = DelayedSpeech()
    stages, _ = manager(speech_factory=speech)
    adapter = call_adapter(stages)
    old, call_id = await _opened(adapter)
    stage = stages._call_stages[call_id]
    session = adapter._sessions[call_id]
    deadline = stages._call_setup_deadlines["request-1"]
    assert stage.state is CallState.PREPARING
    await adapter.disconnect(old)
    assert stage.can_reconnect()
    assert not stage._connection_available
    speech.release.set()
    await _eventually(lambda: stage.state is CallState.RINGING)
    await stage.apply_answer(
        d.AnswerCall(action_id="answer", call_id=stage._record.call_id, decision=CallAnswerDecision.ACCEPT)
    )
    assert stage.state is CallState.RINGING
    new = await adapter.open(
        initial_message=start_message() if repeat_start else resume_message(call_id),
        user_id="user",
        connection_id=object(),
    )
    first = json.loads((await adapter.next_output(new)).message)
    assert first["type"] == ("ack" if repeat_start else "call.resumed")
    assert stage.state is CallState.ACTIVE
    assert stages._call_stages[call_id] is stage
    assert adapter._sessions[call_id] is session
    assert stages._call_setup_deadlines["request-1"] == deadline
    assert len(speech.sessions) == 1
    await adapter.close()
    await stages.close()


@pytest.mark.asyncio
async def test_failed_resume_precheck_preserves_cursor_and_allows_retry(monkeypatch):
    speech = BlockingSpeechFactory()
    stages, _ = manager(speech_factory=speech)
    adapter = call_adapter(stages)
    old, call_id = await _opened(adapter)
    await adapter.disconnect(old)
    stage = stages._call_stages[call_id]
    session = adapter._sessions[call_id]
    before = session._delivery.server_ack_cursor

    async def reject():
        return False

    with monkeypatch.context() as patch:
        patch.setattr(stage, "reconnect", reject)
        with pytest.raises(CallTransportError, match="CALL_RESUME_UNAVAILABLE"):
            await adapter.open(initial_message=resume_message(call_id), user_id="user", connection_id=object())
    assert session._delivery.server_ack_cursor == before
    assert session._binding is None
    new = await adapter.open(initial_message=resume_message(call_id), user_id="user", connection_id=object())
    assert json.loads((await adapter.next_output(new)).message)["type"] == "call.resumed"
    await adapter.close()
    await stages.close()


@pytest.mark.asyncio
async def test_resume_replays_original_bytes_before_new_output_and_old_binding_is_permanently_invalid(monkeypatch):
    speech = BlockingSpeechFactory()
    stages, _ = manager(speech_factory=speech)
    adapter = call_adapter(stages)
    old, call_id = await _opened(adapter)
    old_binding = adapter._bindings[old]
    session = adapter._sessions[call_id]
    await adapter.submit_output(call_id, CallStateChanged(call_id, CallState.RINGING, "request-1"))
    sent = await adapter.next_output(old)
    adapter.complete_output(old, sent.delivery_id)
    assert session._delivery.server_ack_cursor == 0  # 网络完成不等于客户端 ACK。
    await adapter.receive(old, json.dumps({"protocol": "call.v1", "type": "ack", "call_id": call_id, "ack_seq": 1}))
    waiting = asyncio.create_task(adapter.next_output(old))
    await asyncio.sleep(0)
    await adapter.disconnect(old)
    with pytest.raises(ConnectionError):
        await waiting
    stage = stages._call_stages[call_id]
    original = stage.reconnect

    async def reconnect_with_output():
        await adapter.submit_output(call_id, CallStateChanged(call_id, CallState.RINGING, "request-1"))
        return await original()

    monkeypatch.setattr(stage, "reconnect", reconnect_with_output)
    raw = json.loads(resume_message(call_id))
    raw["last_contiguous_server_seq"] = 1
    new = await adapter.open(initial_message=json.dumps(raw), user_id="user", connection_id=object())
    resumed = await adapter.next_output(new)
    replayed = await adapter.next_output(new)
    fresh = await adapter.next_output(new)
    assert json.loads(resumed.message)["type"] == "call.resumed"
    assert replayed.message == sent.message
    assert json.loads(fresh.message)["seq"] > json.loads(replayed.message)["seq"]
    assert adapter._bindings[new] is not old_binding
    assert old_binding.is_closed
    with pytest.raises(CallTransportError, match="STALE_CALL_CONNECTION"):
        await adapter.receive(old, start_message())
    with pytest.raises(CallTransportError, match="STALE_CALL_CONNECTION"):
        await old_binding.receive(None)
    adapter.complete_output(old, fresh.delivery_id)
    assert fresh.delivery_id in adapter._bindings[new]._outbox._pending
    await adapter.disconnect(old)
    assert not adapter._bindings[new].is_closed
    await adapter.close()
    await stages.close()


@pytest.mark.asyncio
async def test_concurrent_resume_has_one_winner_without_cursor_side_effect():
    speech = BlockingSpeechFactory()
    stages, _ = manager(speech_factory=speech)
    adapter = call_adapter(stages)
    old, call_id = await _opened(adapter)
    await adapter.disconnect(old)
    results = await asyncio.gather(
        *[
            adapter.open(initial_message=resume_message(call_id), user_id="user", connection_id=object())
            for _ in range(2)
        ],
        return_exceptions=True,
    )
    assert sum(not isinstance(item, BaseException) for item in results) == 1
    assert any(isinstance(item, CallTransportError) and item.code == "CALL_CONNECTION_ACTIVE" for item in results)
    assert adapter._sessions[call_id]._delivery.server_ack_cursor == 0
    await adapter.close()
    await stages.close()


@pytest.mark.asyncio
async def test_active_resume_waits_for_old_disconnect_and_keeps_same_stage():
    speech = FakeRealtimeSpeechSessionFactory()
    stages, _ = manager(speech_factory=speech)
    adapter = call_adapter(stages)
    old, call_id = await _opened(adapter)
    stage = await _activate(stages, call_id)
    opening = asyncio.create_task(
        adapter.open(initial_message=resume_message(call_id), user_id="user", connection_id=object())
    )
    await asyncio.sleep(0.01)
    assert not opening.done()
    await adapter.disconnect(old)
    new = await asyncio.wait_for(opening, 1)
    assert stage.state is CallState.ACTIVE
    assert stages._call_stages[call_id] is stage
    assert json.loads((await adapter.next_output(new)).message)["type"] == "call.resumed"
    await adapter.close()
    await stages.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["cursor", "enqueue", "overflow", "cancel"])
async def test_failed_resume_after_business_commit_terminates_real_sqlite_stage(monkeypatch, tmp_path, fault):
    engine = create_engine(f"sqlite:///{tmp_path / 'call.sqlite'}")
    Base.metadata.create_all(engine)
    repository = SqlCallSessionRepository(sessionmaker(bind=engine))
    speech = FakeRealtimeSpeechSessionFactory()
    stages, _ = manager(speech_factory=speech, repository=repository, wall_clock=_IncrementingClock())
    adapter = call_adapter(stages)
    old, call_id = await _opened(adapter)
    stage = await _activate(stages, call_id)
    await adapter.disconnect(old)
    session = adapter._sessions[call_id]

    def fail(*args, **kwargs):
        raise RuntimeError("resume fault")

    if fault == "cursor":
        monkeypatch.setattr(session._delivery, "acknowledge_server", fail)
    elif fault == "enqueue":
        monkeypatch.setattr(Binding, "enqueue", fail)
    elif fault == "overflow":
        original = stage.reconnect

        async def overflowing():
            await original()
            for _ in range(257):
                await adapter.submit_output(call_id, CallStateChanged(call_id, CallState.RINGING, "request-1"))
            return True

        monkeypatch.setattr(stage, "reconnect", overflowing)
    else:
        entered, release = asyncio.Event(), asyncio.Event()
        original = Session.attach

        async def blocking_attach(*args, **kwargs):
            await original(*args, **kwargs)
            entered.set()
            await release.wait()

        monkeypatch.setattr(Session, "attach", blocking_attach)
    opening = asyncio.create_task(
        adapter.open(initial_message=resume_message(call_id), user_id="user", connection_id=object())
    )
    if fault == "cancel":
        await asyncio.wait_for(entered.wait(), 1)
        opening.cancel()
        release.set()
    expected = asyncio.CancelledError if fault == "cancel" else RuntimeError
    with pytest.raises(expected):
        await asyncio.wait_for(opening, 2)
    await asyncio.wait_for(stage.wait_closed(), 2)
    await _eventually(lambda: not adapter._sessions)
    await stages._finalizations.close()
    record = repository.find_by_id(call_id)
    assert record.state is CallState.ENDED and record.end_reason is CallEndReason.SYSTEM_FAILURE
    assert stage.context is None
    assert speech.sessions[stage._record.call_id].closed
    assert not stages._call_ownerships
    assert stages._lease_registry.current("user", "luotianyi") is None
    assert not adapter._open_tasks
    await adapter.close()
    await stages.close()
    engine.dispose()


@pytest.mark.asyncio
async def test_async_initialization_failure_releases_session_and_rejects_same_request():
    speech = BlockingSpeechFactory()
    stages, repository = manager(speech_factory=speech)
    adapter = call_adapter(stages)
    connection, call_id = await _opened(adapter)
    stage = stages._call_stages[call_id]
    await speech.entered.wait()
    speech.release.set()
    failed = await asyncio.wait_for(adapter.next_output(connection), 1)
    assert json.loads(failed.message)["type"] == "error"
    assert json.loads(failed.message)["code"] == "CALL_SETUP_FAILED"
    adapter.complete_output(connection, failed.delivery_id)
    await stage.wait_closed()
    await _eventually(lambda: not adapter._sessions)
    assert not stages._call_ownerships
    assert repository.find_by_request("request-1").state is CallState.FAILED
    with pytest.raises(CallTransportError, match="CALL_START_FAILED"):
        await adapter.open(initial_message=start_message(), user_id="user", connection_id=object())
    await adapter.close()
    await stages.close()


@pytest.mark.asyncio
async def test_protocol_ack_bypasses_blocked_business_input_and_hangup_ack_precedes_release(monkeypatch):
    speech = BlockingSpeechFactory()
    stages, _ = manager(speech_factory=speech)
    adapter = call_adapter(stages)
    connection, call_id = await _opened(adapter)
    session = adapter._sessions[call_id]
    stage = stages._call_stages[call_id]
    entered, release = asyncio.Event(), asyncio.Event()
    original = stage.terminate

    async def delayed_terminate(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(stage, "terminate", delayed_terminate)
    receiving = asyncio.create_task(
        adapter.receive(
            connection,
            json.dumps(
                {"protocol": "call.v1", "type": "call.hangup", "seq": 2, "call_id": call_id, "reason": "user_hangup"}
            ),
        )
    )
    await entered.wait()

    async def ack(target):
        await adapter.receive(
            connection, json.dumps({"protocol": "call.v1", "type": "ack", "call_id": target, "ack_seq": 1})
        )

    with pytest.raises(CallTransportError, match="CALL_OWNERSHIP_MISMATCH"):
        await ack(str(uuid4()))
    assert session._delivery.server_ack_cursor == 0
    await asyncio.wait_for(ack(call_id), 0.5)
    assert session._delivery.server_ack_cursor == 1
    received = []

    async def pump():
        while True:
            try:
                item = await adapter.next_output(connection)
            except (ConnectionError, CallTransportError):
                return
            received.append(json.loads(item.message))
            adapter.complete_output(connection, item.delivery_id)

    pumping = asyncio.create_task(pump())
    release.set()
    await asyncio.wait_for(receiving, 1)
    await asyncio.wait_for(pumping, 3)
    assert any(item["type"] == "call.ended" for item in received)
    assert any(item["type"] == "ack" and item["ack_seq"] == 2 for item in received)
    assert not adapter._bindings and not adapter._sessions
    await adapter.close()
    await stages.close()


@pytest.mark.asyncio
async def test_call_lifecycle_versions_advance_when_wall_clock_does_not():
    fixed = datetime(2026, 10, 18, tzinfo=timezone.utc)
    stages, repository = manager(speech_factory=FakeRealtimeSpeechSessionFactory(), wall_clock=lambda: fixed)
    adapter = call_adapter(stages)
    connection, call_id = await _opened(adapter)
    stage = await _activate(stages, call_id)
    await adapter.disconnect(connection)
    await adapter.open(initial_message=resume_message(call_id), user_id="user", connection_id=object())
    await stage.terminate()
    record = repository.find_by_request("request-1")
    assert record.state is CallState.ENDED
    assert record.updated_at > record.created_at
    await adapter.close()
    await stages.close()


@pytest.mark.asyncio
async def test_resume_rollback_preserves_original_failure_even_if_cleanup_and_logger_fail(monkeypatch):
    stages, _ = manager(speech_factory=FakeRealtimeSpeechSessionFactory())
    adapter = call_adapter(stages)
    connection, call_id = await _opened(adapter)
    stage = await _activate(stages, call_id)
    await adapter.disconnect(connection)
    session = adapter._sessions[call_id]
    original = stage.terminate

    async def cleanup_failure(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("cleanup fault")

    def cursor_failure(_cursor):
        raise RuntimeError("original cursor fault")

    class Logger:
        def error(self, *_args):
            raise RuntimeError("logger fault")

    monkeypatch.setattr(stage, "terminate", cleanup_failure)
    monkeypatch.setattr(session._delivery, "acknowledge_server", cursor_failure)
    monkeypatch.setattr("src.adapter.websocket.call_v1._session.get_logger", lambda *_args: Logger())
    with pytest.raises(RuntimeError, match="original cursor fault"):
        await adapter.open(initial_message=resume_message(call_id), user_id="user", connection_id=object())
    await _eventually(lambda: not adapter._sessions)
    assert stage.state is CallState.ENDED
    assert not adapter._bindings
    await adapter.close()
    await stages.close()
