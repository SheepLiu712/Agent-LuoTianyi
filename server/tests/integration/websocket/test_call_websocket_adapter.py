import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from support.call_session_repository import InMemoryCallSessionRepository
from support.realtime_speech import FakeRealtimeSpeechSessionFactory

import src.domain.agent as d
from src.adapter.websocket import WebSocketAdapter
from src.adapter.websocket.call_v1 import CallTransportError, CallWebSocketAdapter
from src.adapter.websocket.call_v1.transport import CallTransportBackpressure
from src.agent.context import ContextFactory
from src.application.user.reset_fence import UserResetFence
from src.domain.call import CallAnswerDecision, CallEndReason, CallState
from src.infrastructure.models.realtime_speech import ProviderFailed
from src.infrastructure.persistence.call_sessions import SqlCallSessionRepository
from src.infrastructure.persistence.database.sql_database import Base
from src.stage import StageManager
from src.stage.call_stage import CallStateChanged
from src.stage.stage_manager import CallControl, CallIdentity, CallOpenRequest
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


def manager(
    *, speech_factory, repository=None, wall_clock=None, monotonic=None, config=None, agent=None, context_factory=None
):
    repository = repository or InMemoryCallSessionRepository()
    stages = StageManager(
        get_agent=lambda _character: agent or RecordingAgent(),
        adapter=WebSocketAdapter(),
        get_context_factory=lambda _character: context_factory
        or ContextFactory(character_id="luotianyi", database=_ContextDatabase()),
        call_sessions=repository,
        realtime_speech_factory=speech_factory,
        user_reset_fence=UserResetFence(),
        wall_clock=wall_clock or (lambda: datetime.now(timezone.utc)),
        **({} if monotonic is None else {"monotonic": monotonic}),
        config=config,
    )
    return stages, repository


@pytest.mark.asyncio
async def test_public_open_emits_warning_at_five_seconds_and_time_limits_at_seven_seconds():
    class Clock:
        value = 100.0

        def __call__(self):
            return self.value

        def advance(self, seconds):
            self.value += seconds

    class CallAgent(RecordingAgent):
        async def handle_stimulus(self, request, sink, *, context=None):
            self.requests.put_nowait(request)
            actions = ()
            if isinstance(request.stimulus, d.CallAnswerRequested):
                actions = (
                    d.AnswerCall(
                        action_id="answer",
                        call_id=request.stimulus.call_id,
                        decision=CallAnswerDecision.ACCEPT,
                    ),
                )
            elif isinstance(request.stimulus, d.CallTimeLimitWarning):
                actions = (
                    d.Say(
                        action_id="warning",
                        content="通话时间快到了，我们很快就要结束啦。",
                        sound_content=None,
                        prepared_audio_ref=None,
                        tone=d.Tone(value="normal"),
                        expression=None,
                        delivery=d.OutputDelivery.EPHEMERAL_REACTION,
                        call_delivery=d.CallSpeechDelivery(
                            audio_route=d.CallAudioRoute.CALL,
                            display_in_chat=False,
                            is_ephemeral=True,
                            response_id="warning-response",
                        ),
                    ),
                )
            plan_ids = ()
            if actions:
                plan = d.ActionPlan(
                    plan_id=f"plan-{request.stimulus.kind.value}",
                    origin_request_id=request.request_id,
                    plan_ordinal=0,
                    target_character_id="luotianyi",
                    interaction_id=request.interaction.interaction_id,
                    basis_interaction_revision=request.interaction.interaction_revision,
                    source_stimulus_ids=(request.stimulus.stimulus_id,),
                    actions=actions,
                )
                await sink.emit(plan)
                plan_ids = (plan.plan_id,)
            return d.HandlingReport(
                request_id=request.request_id,
                trigger_stimulus_id=request.stimulus.stimulus_id,
                basis_interaction_revision=request.interaction.interaction_revision,
                request_status=d.HandlingRequestStatus.COMPLETED,
                considered_pending_stimulus_ids=(),
                consumed_pending_stimulus_ids=(),
                retained_pending_stimulus_ids=(),
                emitted_plan_ids=plan_ids,
                error_code=None,
                retryable=False,
            )

        async def realize_action_plan(self, value, context, sink):
            self.executions.put_nowait((value, context, sink))
            results = tuple(
                d.ActionResult(
                    action_id=action.action_id,
                    status=d.ActionExecutionStatus.COMPLETED,
                    error_code=None,
                    irreversible_effect_committed=False,
                    effect_ref=None,
                )
                for action in value.actions
            )
            return d.ExecutionReport(
                execution_id=context.execution_id,
                plan_id=value.plan_id,
                status=d.ExecutionStatus.COMPLETED,
                action_results=results,
                output_started=False,
                error_code=None,
                retryable=False,
            )

    clock = Clock()
    agent = CallAgent()
    speech = FakeRealtimeSpeechSessionFactory()
    stages, repository = manager(
        speech_factory=speech,
        monotonic=clock,
        agent=agent,
        config={"call_stage": {"time_limit_seconds": 7, "time_limit_warning_seconds": 2}},
    )
    adapter = call_adapter(stages)
    connection = await adapter.open(raw=start_message(), user_id="user", connection_id=object())
    call_id = json.loads((await adapter.next_output(connection)).text)["call_id"]
    await adapter.next_output(connection)
    control = stages.current_call_control(call_id)
    await asyncio.wait_for(control._stage_available.wait(), 1)
    while control._stage.state is not CallState.ACTIVE:
        await asyncio.sleep(0)

    clock.advance(4.9)
    control._stage._time_limit_changed.set()
    await asyncio.sleep(0)
    observed = []
    while not agent.requests.empty():
        observed.append(agent.requests.get_nowait().stimulus)
    assert not any(isinstance(item, d.CallTimeLimitWarning) for item in observed)

    clock.advance(0.1)
    control._stage._time_limit_changed.set()
    warning_request = await asyncio.wait_for(agent.requests.get(), 1)
    assert isinstance(warning_request.stimulus, d.CallTimeLimitWarning)
    assert warning_request.stimulus.remaining_ms == 2000
    warning_plan = None
    while warning_plan is None:
        candidate, _, _ = await asyncio.wait_for(agent.executions.get(), 1)
        if candidate.actions and isinstance(candidate.actions[0], d.Say):
            warning_plan = candidate
    assert isinstance(warning_plan.actions[0], d.Say)
    assert warning_plan.actions[0].content == "通话时间快到了，我们很快就要结束啦。"
    await asyncio.sleep(0)
    assert agent.requests.empty()

    clock.advance(2.0)
    control._stage._time_limit_changed.set()
    snapshot = await asyncio.wait_for(control.wait_realtime_stopped(), 2)
    terminal = None
    while terminal is None:
        output = await asyncio.wait_for(adapter.next_output(connection), 2)
        if output.text is not None and json.loads(output.text)["type"] == "call.ended":
            terminal = json.loads(output.text)

    assert snapshot.terminal.end_reason is CallEndReason.TIME_LIMIT
    assert terminal["end_reason"] == CallEndReason.TIME_LIMIT.value
    assert repository.find_by_id(UUID(call_id)).end_reason is CallEndReason.TIME_LIMIT

    await adapter.close()
    await stages.close()
    assert not control._stage.tasks
    assert stages._lease_registry.current("user", "luotianyi") is None
    assert stages._call_ownerships == {}


@pytest.mark.asyncio
async def test_invalid_public_call_stage_config_fails_open_and_releases_claim():
    class ContextFactoryProbe:
        created = []

        async def create(self, *args, **kwargs):
            context = await ContextFactory(character_id="luotianyi", database=_ContextDatabase()).create(
                *args, **kwargs
            )
            self.created.append(context)
            return context

    contexts = ContextFactoryProbe()
    speech = FakeRealtimeSpeechSessionFactory()
    stages, repository = manager(
        speech_factory=speech,
        context_factory=contexts,
        config={"call_stage": {"time_limit_seconds": 10, "time_limit_warning_seconds": 10}},
    )
    adapter = call_adapter(stages)
    connection = await adapter.open(raw=start_message(), user_id="user", connection_id=object())
    first = json.loads((await adapter.next_output(connection)).text)
    call_id = first["call_id"]
    await adapter.next_output(connection)
    control = stages.current_call_control(call_id)

    await asyncio.wait_for(control.wait_realtime_stopped(), 2)

    record = repository.find_by_id(UUID(call_id))
    assert record.state is CallState.FAILED
    assert stages._lease_registry.current("user", "luotianyi") is None
    assert stages._call_ownerships == {}
    assert stages._call_stages == {}
    assert speech.sessions == {}
    assert contexts.created == [] or all(context._closed for context in contexts.created)
    assert stages._call_claims == {}
    assert (
        stages.current_call_control(call_id),
        "request-1" in stages._call_controls_by_request,
    ) == (None, False)
    await adapter.close()
    await stages.close()


@pytest.mark.asyncio
async def test_repeated_start_after_invalid_config_returns_durable_failed_identity_without_new_resources():
    class ContextFactoryProbe:
        calls = 0

        async def create(self, *args, **kwargs):
            self.calls += 1
            return await ContextFactory(character_id="luotianyi", database=_ContextDatabase()).create(*args, **kwargs)

    contexts = ContextFactoryProbe()
    speech = FakeRealtimeSpeechSessionFactory()
    stages, repository = manager(
        speech_factory=speech,
        context_factory=contexts,
        config={"call_stage": {"time_limit_seconds": 10, "time_limit_warning_seconds": 10}},
    )
    adapter = call_adapter(stages)
    first_connection = await adapter.open(raw=start_message(), user_id="user", connection_id=object())
    first = json.loads((await adapter.next_output(first_connection)).text)
    call_id = first["call_id"]
    await adapter.next_output(first_connection)
    control = stages.current_call_control(call_id)
    await asyncio.wait_for(control.wait_realtime_stopped(), 2)
    before_claims = dict(stages._call_claims)

    with pytest.raises(CallTransportError) as failed:
        await adapter.open(raw=start_message(), user_id="user", connection_id=object())

    assert "CALL_START_FAILED" in str(failed.value)
    assert repository.find_by_request("request-1").call_id == UUID(call_id)
    assert stages._call_claims == before_claims == {}
    assert speech.sessions == {}
    assert contexts.calls == 0
    await adapter.close()
    await stages.close()


def test_failed_control_retirement_is_identity_guarded():
    speech = FakeRealtimeSpeechSessionFactory()
    stages, _ = manager(speech_factory=speech)
    request = CallOpenRequest(user_id="user", character_id="luotianyi", client_request_id="request-1")
    transport = type("Transport", (), {})()
    old = CallControl(stages, request, transport)
    old._identity = CallIdentity("call-1", "request-1", "luotianyi", CallState.PREPARING)
    replacement = CallControl(stages, request, transport)
    replacement._identity = old._identity
    stages._call_controls["call-1"] = replacement
    stages._call_controls_by_request["request-1"] = replacement

    stages._retire_failed_call_control(old)

    assert stages._call_controls["call-1"] is replacement
    assert stages._call_controls_by_request["request-1"] is replacement


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_point", ["get_logger", "error"])
async def test_diagnostic_failure_cannot_block_invalid_config_control_retirement(monkeypatch, failure_point):
    speech = FakeRealtimeSpeechSessionFactory()
    stages, repository = manager(
        speech_factory=speech,
        config={"call_stage": {"time_limit_seconds": 10, "time_limit_warning_seconds": 10}},
    )

    class Logger:
        def error(self, *args, **kwargs):
            if failure_point == "error":
                raise RuntimeError("diagnostic error failed")

    original_get_logger = get_logger

    def failing_get_logger(name):
        if name == "src.stage.stage_manager":
            if failure_point == "get_logger":
                raise RuntimeError("diagnostic lookup failed")
            return Logger()
        return original_get_logger(name)

    monkeypatch.setattr("src.stage.stage_manager.get_logger", failing_get_logger)
    adapter = call_adapter(stages)
    connection = await adapter.open(raw=start_message(), user_id="user", connection_id=object())
    first = json.loads((await adapter.next_output(connection)).text)
    call_id = first["call_id"]
    await adapter.next_output(connection)
    control = stages.current_call_control(call_id)
    await asyncio.wait_for(control.wait_realtime_stopped(), 2)

    record = repository.find_by_id(UUID(call_id))
    assert record.state is CallState.FAILED
    assert stages._call_claims == {}
    assert stages._lease_registry.current("user", "luotianyi") is None
    assert stages._call_ownerships == {}
    assert stages._call_stages == {}
    assert stages.current_call_control(call_id) is None
    assert "request-1" not in stages._call_controls_by_request
    assert speech.sessions == {}

    with pytest.raises(CallTransportError, match="CALL_START_FAILED"):
        await adapter.open(raw=start_message(), user_id="user", connection_id=object())
    assert repository.find_by_request("request-1").call_id == UUID(call_id)
    await adapter.close()
    await stages.close()


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
        await adapter.open(raw=raw, user_id="user", connection_id=object())

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

    monkeypatch.setattr(stages, "open_call", reject_finalizing)
    with pytest.raises(CallTransportError) as rejected:
        await adapter.open(raw=start_message(), user_id="user", connection_id=object())

    assert rejected.value.code == "INTERACTION_FINALIZING"
    assert rejected.value.retryable is True
    assert rejected.value.request_id == "request-1"
    assert repository.find_by_request("request-1") is None
    assert adapter._hub._sessions == {}
    await adapter.close()
    await stages.close()


@pytest.mark.asyncio
async def test_open_orders_preparing_before_ack_and_repeated_start_keeps_identity_and_deadline():
    speech = BlockingSpeechFactory()
    stages, repository = manager(speech_factory=speech)
    adapter = call_adapter(stages)
    first = await asyncio.wait_for(adapter.open(raw=start_message(), user_id="user", connection_id=object()), 2)
    preparing = json.loads((await adapter.next_output(first)).text)
    ack = json.loads((await adapter.next_output(first)).text)
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

    second = await adapter.open(raw=start_message(), user_id="user", connection_id=object())
    second_ack = json.loads((await adapter.next_output(second)).text)
    assert second_ack["call_id"] == call_id
    assert stages._call_setup_deadlines["request-1"] == deadline
    assert repository.find_by_request("request-1").call_id == uuid4().__class__(call_id)
    speech.release.set()
    await asyncio.wait_for(adapter.close(), 2)
    await asyncio.wait_for(stages.close(), 2)


@pytest.mark.asyncio
async def test_initialization_hangup_uses_same_control_and_does_not_create_second_provider():
    speech = BlockingSpeechFactory()
    stages, _ = manager(speech_factory=speech)
    adapter = call_adapter(stages)
    connection = await adapter.open(raw=start_message(), user_id="user", connection_id=object())
    await adapter.next_output(connection)
    await adapter.next_output(connection)
    await asyncio.wait_for(speech.entered.wait(), 1)
    call_id = next(iter(stages._call_controls)).strip()
    hangup = json.dumps(
        {
            "protocol": "call.v1",
            "type": "call.hangup",
            "seq": 2,
            "call_id": call_id,
            "reason": "user_hangup",
        }
    )
    receiving = asyncio.create_task(adapter.receive_text(connection, hangup))
    await asyncio.sleep(0)
    assert not receiving.done()
    speech.release.set()
    await receiving
    assert speech.calls == 1
    await adapter.close()
    await stages.close()


@pytest.mark.asyncio
async def test_unknown_resume_and_active_connection_takeover_are_rejected_without_new_identity():
    speech = BlockingSpeechFactory()
    stages, repository = manager(speech_factory=speech)
    adapter = call_adapter(stages)
    with pytest.raises(CallTransportError, match="CALL_NOT_FOUND"):
        await adapter.open(raw=resume_message(str(uuid4())), user_id="user", connection_id=object())
    assert repository.find_by_request("missing") is None
    await adapter.open(raw=start_message(), user_id="user", connection_id=object())
    with pytest.raises(CallTransportError, match="CALL_CONNECTION_ACTIVE"):
        await adapter.open(raw=start_message(), user_id="user", connection_id=object())
    speech.release.set()
    await adapter.close()
    await stages.close()


@pytest.mark.asyncio
async def test_cancelled_open_after_prepare_has_no_session_lease_or_request_task():
    speech = BlockingSpeechFactory()
    stages, repository = manager(speech_factory=speech)
    adapter = call_adapter(stages)
    original = adapter._hub.register_and_attach_start
    registered = asyncio.Event()
    release = asyncio.Event()

    async def blocked_register(*args, **kwargs):
        binding = await original(*args, **kwargs)
        registered.set()
        await release.wait()
        return binding

    adapter._hub.register_and_attach_start = blocked_register
    opening = asyncio.create_task(adapter.open(raw=start_message(), user_id="user", connection_id=object()))
    await asyncio.wait_for(registered.wait(), 1)
    opening.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await opening
    await asyncio.sleep(0)

    assert adapter._hub._sessions == {}
    assert stages._call_open_tasks == {}
    assert stages._call_claims == {}
    assert stages._call_ownerships == {}
    assert stages._lease_registry.current("user", "luotianyi") is None
    record = repository.find_by_request("request-1")
    assert record is not None and record.state is CallState.FAILED
    with pytest.raises(CallTransportError) as duplicate:
        await adapter.open(raw=start_message(), user_id="user", connection_id=object())
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
        adapter.open(raw=start_message(), user_id="user", connection_id=object()),
        adapter.open(raw=start_message(), user_id="user", connection_id=object()),
        return_exceptions=True,
    )
    connections = [result for result in (first, second) if not isinstance(result, BaseException)]
    failures = [result for result in (first, second) if isinstance(result, BaseException)]
    assert len(connections) == 1
    assert len(failures) == 1 and "CALL_CONNECTION_ACTIVE" in str(failures[0])
    assert speech.calls == 0
    assert len(adapter._hub._sessions) == 1
    await adapter.next_output(connections[0])
    speech.release.set()
    await adapter.close()
    await stages.close()


@pytest.mark.asyncio
async def test_cross_identity_request_conflict_is_normalized_without_call_details():
    speech = BlockingSpeechFactory()
    stages, _ = manager(speech_factory=speech)
    adapter = call_adapter(stages)
    connection = await adapter.open(raw=start_message(), user_id="user-a", connection_id=object())
    await adapter.next_output(connection)
    await adapter.next_output(connection)
    with pytest.raises(CallTransportError) as rejected:
        await adapter.open(raw=start_message(), user_id="user-b", connection_id=object())
    assert rejected.value.code == "CALL_START_REJECTED"
    assert rejected.value.request_id == "request-1"
    assert rejected.value.request_seq == 1
    assert rejected.value.retryable is False
    assert rejected.value.close_code == 1013
    speech.release.set()
    await adapter.close()
    await stages.close()


@pytest.mark.asyncio
async def test_adapter_close_waits_for_cancelled_open_compensation_before_closing_transport():
    speech = BlockingSpeechFactory()
    stages, _ = manager(speech_factory=speech)
    adapter = call_adapter(stages)
    original = adapter._hub.register_and_attach_start
    registered = asyncio.Event()
    release = asyncio.Event()

    async def blocked_register(*args, **kwargs):
        binding = await original(*args, **kwargs)
        registered.set()
        await release.wait()
        return binding

    adapter._hub.register_and_attach_start = blocked_register
    opening = asyncio.create_task(adapter.open(raw=start_message(), user_id="user", connection_id=object()))
    await asyncio.wait_for(registered.wait(), 1)
    closing = asyncio.create_task(adapter.close())
    await asyncio.sleep(0)
    assert not closing.done()
    release.set()
    await asyncio.wait_for(closing, 1)
    with pytest.raises(asyncio.CancelledError):
        await opening
    assert adapter._hub._sessions == {}
    assert stages._call_claims == {}
    assert stages._call_ownerships == {}
    assert stages._lease_registry.current("user", "luotianyi") is None
    await stages.close()


@pytest.mark.asyncio
async def test_stage_created_after_disconnect_stays_ringing_until_resume():
    class Session:
        async def start(self, _config):
            pass

        async def close(self):
            pass

        async def events(self):
            if False:
                yield None

        async def wait_failure(self):
            await asyncio.Event().wait()

    class Speech:
        is_configured = True

        async def create(self, _call_id):
            return Session()

    stages, _ = manager(speech_factory=Speech())
    adapter = call_adapter(stages)
    connection = await adapter.open(raw=start_message(), user_id="user", connection_id=object())
    call_id = json.loads((await adapter.next_output(connection)).text)["call_id"]
    await adapter.next_output(connection)
    await adapter.disconnect(connection)
    control = stages.current_call_control(call_id)
    for _ in range(100):
        if control is not None and control._stage is not None:
            break
        await asyncio.sleep(0)
    assert control._stage.state is not CallState.ACTIVE
    resumed = await adapter.open(raw=resume_message(call_id), user_id="user", connection_id=object())
    assert json.loads((await adapter.next_output(resumed)).text)["type"] == "call.resumed"
    await adapter.close()
    await stages.close()


@pytest.mark.asyncio
async def test_failed_business_resume_keeps_cursor_and_allows_later_resume(monkeypatch):
    speech = BlockingSpeechFactory()
    stages, _ = manager(speech_factory=speech)
    adapter = call_adapter(stages)
    connection = await adapter.open(raw=start_message(), user_id="user", connection_id=object())
    call_id = json.loads((await adapter.next_output(connection)).text)["call_id"]
    await adapter.next_output(connection)
    await adapter.disconnect(connection)
    session = adapter._hub.session_for(call_id)
    before = session.server_ack_cursor

    async def fail_resume(*args, **kwargs):
        raise RuntimeError("CALL_RESUME_UNAVAILABLE")

    monkeypatch.setattr(stages, "resume_call", fail_resume)
    with pytest.raises(CallTransportError, match="CALL_RESUME_UNAVAILABLE"):
        await adapter.open(raw=resume_message(call_id), user_id="user", connection_id=object())
    assert session.server_ack_cursor == before
    monkeypatch.undo()
    valid = await adapter.open(raw=resume_message(call_id), user_id="user", connection_id=object())
    assert json.loads((await adapter.next_output(valid)).text)["type"] == "call.resumed"
    speech.release.set()
    await adapter.close()
    await stages.close()


@pytest.mark.asyncio
async def test_resume_buffers_stage_output_without_blocking_and_flushes_after_resumed(
    monkeypatch,
):
    speech = BlockingSpeechFactory()
    stages, _ = manager(speech_factory=speech)
    adapter = call_adapter(stages)
    connection = await adapter.open(raw=start_message(), user_id="user", connection_id=object())
    call_id = json.loads((await adapter.next_output(connection)).text)["call_id"]
    await adapter.next_output(connection)
    await adapter.disconnect(connection)
    session = adapter._hub.session_for(call_id)
    bridge = session.business_sink
    original_commit = stages.commit_call_resume

    async def emitting_commit(control):
        await bridge.send_state(CallStateChanged(call_id, CallState.RINGING, "request-1"))
        await original_commit(control)

    monkeypatch.setattr(stages, "commit_call_resume", emitting_commit)
    resumed = await asyncio.wait_for(
        adapter.open(raw=resume_message(call_id), user_id="user", connection_id=object()),
        1,
    )
    first = json.loads((await adapter.next_output(resumed)).text)
    second = json.loads((await adapter.next_output(resumed)).text)
    assert first["type"] == "call.resumed"
    assert second["type"] == "call.state"
    speech.release.set()
    await adapter.close()
    await stages.close()


@pytest.mark.asyncio
async def test_stage_none_resume_precheck_is_read_only():
    speech = BlockingSpeechFactory()
    stages, _ = manager(speech_factory=speech)
    adapter = call_adapter(stages)
    original_create = stages._create_call_stage
    create_entered, create_release = asyncio.Event(), asyncio.Event()

    async def delayed_create(*args, **kwargs):
        create_entered.set()
        await create_release.wait()
        return await original_create(*args, **kwargs)

    stages._create_call_stage = delayed_create
    connection = await adapter.open(raw=start_message(), user_id="user", connection_id=object())
    call_id = json.loads((await adapter.next_output(connection)).text)["call_id"]
    await adapter.next_output(connection)
    await create_entered.wait()
    control = stages.current_call_control(call_id)
    await adapter.disconnect(connection)
    assert control._stage is None and control._connected is False
    assert await control.resume() is True
    assert control._connected is False
    create_release.set()
    speech.release.set()
    await adapter.close()
    await stages.close()


@pytest.mark.asyncio
async def test_concurrent_resume_reservation_has_one_winner_without_cursor_side_effect():
    speech = BlockingSpeechFactory()
    stages, _ = manager(speech_factory=speech)
    adapter = call_adapter(stages)
    connection = await adapter.open(raw=start_message(), user_id="user", connection_id=object())
    call_id = json.loads((await adapter.next_output(connection)).text)["call_id"]
    await adapter.next_output(connection)
    await adapter.disconnect(connection)
    session = adapter._hub.session_for(call_id)
    before = session.server_ack_cursor

    first, second = await asyncio.gather(
        adapter.open(raw=resume_message(call_id), user_id="user", connection_id=object()),
        adapter.open(raw=resume_message(call_id), user_id="user", connection_id=object()),
        return_exceptions=True,
    )
    winners = [item for item in (first, second) if not isinstance(item, BaseException)]
    losers = [item for item in (first, second) if isinstance(item, BaseException)]
    assert len(winners) == len(losers) == 1
    assert "CALL_CONNECTION_ACTIVE" in str(losers[0])
    assert session.server_ack_cursor == before
    speech.release.set()
    await adapter.close()
    await stages.close()


@pytest.mark.asyncio
async def test_real_stage_resume_pending_overflow_terminates_after_business_commit(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'call.sqlite'}")
    Base.metadata.create_all(engine)
    repository = SqlCallSessionRepository(sessionmaker(bind=engine))
    speech = FakeRealtimeSpeechSessionFactory()
    clock = _IncrementingClock()
    stages, _ = manager(speech_factory=speech, repository=repository, wall_clock=clock)
    adapter = call_adapter(stages)
    connection = await adapter.open(raw=start_message(), user_id="user", connection_id=object())
    call_id = json.loads((await adapter.next_output(connection)).text)["call_id"]
    await adapter.next_output(connection)
    control = stages.current_call_control(call_id)
    await asyncio.wait_for(control._stage_available.wait(), 1)

    async def wait_for_ringing():
        while control._stage.state is not CallState.RINGING:
            await asyncio.sleep(0)

    await asyncio.wait_for(wait_for_ringing(), 2)
    await control._stage.apply_answer(
        d.AnswerCall(
            action_id="test-answer",
            call_id=control._stage._record.call_id,
            decision=CallAnswerDecision.ACCEPT,
        )
    )
    assert control._stage.state is CallState.ACTIVE
    await adapter.disconnect(connection)
    session = adapter._hub.session_for(call_id)
    bridge = session.business_sink
    bridge._MAX_RESUME_PENDING_FRAMES = 0
    with pytest.raises(CallTransportBackpressure, match="RESUME_OUTPUT_BUFFER_FULL"):
        await adapter.open(raw=resume_message(call_id), user_id="user", connection_id=object())
    await asyncio.wait_for(control.wait_realtime_stopped(), 2)
    record = repository.find_by_id(call_id)
    assert record.state is CallState.ENDED
    assert record.end_reason is CallEndReason.SYSTEM_FAILURE
    assert control._stage.state is CallState.ENDED
    assert speech.sessions[control._stage._record.call_id].closed is True
    assert control._stage.context is None
    assert bridge._resume_pending is None
    assert adapter._hub.session_for(call_id) is None
    assert adapter._hub._sessions == {}
    assert stages._lease_registry.current("user", "luotianyi") is None
    assert stages._call_ownerships == {}
    assert repository.find_by_request("request-1").call_id == control._stage._record.call_id
    await adapter.close()
    await stages.close()


@pytest.mark.asyncio
async def test_known_provider_failure_rejects_public_adapter_resume_before_resumed_output(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'call.sqlite'}")
    Base.metadata.create_all(engine)
    repository = SqlCallSessionRepository(sessionmaker(bind=engine))
    speech = FakeRealtimeSpeechSessionFactory()
    clock = _IncrementingClock()
    stages, _ = manager(speech_factory=speech, repository=repository, wall_clock=clock)
    adapter = call_adapter(stages)
    connection = await adapter.open(raw=start_message(), user_id="user", connection_id=object())
    call_id = json.loads((await adapter.next_output(connection)).text)["call_id"]
    await adapter.next_output(connection)
    control = stages.current_call_control(call_id)
    await asyncio.wait_for(control._stage_available.wait(), 1)

    async def wait_for_ringing():
        while control._stage.state is not CallState.RINGING:
            await asyncio.sleep(0)

    await asyncio.wait_for(wait_for_ringing(), 2)
    await control._stage.apply_answer(
        d.AnswerCall(
            action_id="test-answer",
            call_id=control._stage._record.call_id,
            decision=CallAnswerDecision.ACCEPT,
        )
    )
    await adapter.disconnect(connection)
    provider = speech.sessions[control._stage._record.call_id]
    termination_entered, release_termination = asyncio.Event(), asyncio.Event()
    original_terminate_owned = control._stage._terminate_owned

    async def delayed_terminate_owned(reason):
        termination_entered.set()
        await release_termination.wait()
        return await original_terminate_owned(reason)

    monkeypatch.setattr(control._stage, "_terminate_owned", delayed_terminate_owned)
    await provider.emit(ProviderFailed("provider_connection_closed", True))
    await asyncio.wait_for(termination_entered.wait(), 0.2)
    session = adapter._hub.session_for(call_id)
    before_cursor = session.server_ack_cursor
    before_queue_size = session.business_sink.outputs.qsize()

    try:
        with pytest.raises(CallTransportError, match="CALL_RESUME_UNAVAILABLE"):
            await asyncio.wait_for(
                adapter.open(raw=resume_message(call_id), user_id="user", connection_id=object()),
                1,
            )
    finally:
        release_termination.set()

    assert session.server_ack_cursor == before_cursor
    assert session.business_sink.outputs.qsize() == before_queue_size
    entry = adapter._hub._sessions.get(call_id)
    assert entry is not None and entry.connection_id is None and entry.resume_token is None
    await asyncio.wait_for(control.wait_realtime_stopped(), 2)
    record = repository.find_by_id(call_id)
    assert record.end_reason is CallEndReason.PROVIDER_FAILED
    await adapter.close()
    assert adapter._hub.session_for(call_id) is None
    assert stages._lease_registry.current("user", "luotianyi") is None
    await stages.close()


@pytest.mark.asyncio
async def test_resume_commit_failure_after_active_uses_sqlite_stage_termination(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'call.sqlite'}")
    Base.metadata.create_all(engine)
    repository = SqlCallSessionRepository(sessionmaker(bind=engine))
    speech = FakeRealtimeSpeechSessionFactory()
    clock = _IncrementingClock()
    stages, _ = manager(speech_factory=speech, repository=repository, wall_clock=clock)
    adapter = call_adapter(stages)

    connection = await adapter.open(raw=start_message(), user_id="user", connection_id=object())
    call_id = json.loads((await adapter.next_output(connection)).text)["call_id"]
    await adapter.next_output(connection)
    control = stages.current_call_control(call_id)
    await asyncio.wait_for(control._stage_available.wait(), 1)

    async def wait_for_ringing():
        while control._stage.state is not CallState.RINGING:
            await asyncio.sleep(0)

    await asyncio.wait_for(wait_for_ringing(), 2)
    await control._stage.apply_answer(
        d.AnswerCall(
            action_id="test-answer",
            call_id=control._stage._record.call_id,
            decision=CallAnswerDecision.ACCEPT,
        )
    )
    assert control._stage.state is CallState.ACTIVE
    await adapter.disconnect(connection)
    await asyncio.wait_for(control._stage_available.wait(), 1)

    session = adapter._hub.session_for(call_id)
    assert session is not None
    original_commit = session.commit_resume

    def fail_cursor_commit(_cursor):
        raise RuntimeError("cursor commit fault")

    monkeypatch.setattr(session, "commit_resume", fail_cursor_commit)
    with pytest.raises(RuntimeError, match="cursor commit fault"):
        await asyncio.wait_for(
            adapter.open(raw=resume_message(call_id), user_id="user", connection_id=object()),
            1,
        )

    await asyncio.wait_for(control.wait_realtime_stopped(), 2)
    record = repository.find_by_id(call_id)
    assert record.state is CallState.ENDED
    assert record.end_reason is CallEndReason.SYSTEM_FAILURE
    assert control._stage.state is CallState.ENDED
    assert speech.sessions[control._stage._record.call_id].closed is True
    assert control._stage.context is None
    assert stages._lease_registry.current("user", "luotianyi") is None
    assert adapter._hub.session_for(call_id) is None
    assert adapter._hub._sessions == {}
    assert stages._call_ownerships == {}
    assert repository.find_by_request("request-1").call_id == control._stage._record.call_id
    monkeypatch.setattr(session, "commit_resume", original_commit)
    await adapter.close()
    await stages.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["enqueue", "flush"])
async def test_resume_post_business_output_failure_terminates_real_sqlite_stage(monkeypatch, tmp_path, fault):
    engine = create_engine(f"sqlite:///{tmp_path / 'call.sqlite'}")
    Base.metadata.create_all(engine)
    repository = SqlCallSessionRepository(sessionmaker(bind=engine))
    speech = FakeRealtimeSpeechSessionFactory()
    clock = _IncrementingClock()
    stages, _ = manager(speech_factory=speech, repository=repository, wall_clock=clock)
    adapter = call_adapter(stages)
    connection = await adapter.open(raw=start_message(), user_id="user", connection_id=object())
    call_id = json.loads((await adapter.next_output(connection)).text)["call_id"]
    await adapter.next_output(connection)
    control = stages.current_call_control(call_id)
    await asyncio.wait_for(control._stage_available.wait(), 1)

    async def wait_for_ringing():
        while control._stage.state is not CallState.RINGING:
            await asyncio.sleep(0)

    await asyncio.wait_for(wait_for_ringing(), 2)
    await control._stage.apply_answer(
        d.AnswerCall(
            action_id="test-answer",
            call_id=control._stage._record.call_id,
            decision=CallAnswerDecision.ACCEPT,
        )
    )
    assert control._stage.state is CallState.ACTIVE
    await adapter.disconnect(connection)

    if fault == "enqueue":

        async def fail_enqueue(*args, **kwargs):
            raise RuntimeError("resume enqueue fault")

        monkeypatch.setattr(adapter, "_enqueue", fail_enqueue)
    else:
        bridge = adapter._hub.session_for(call_id).business_sink

        async def fail_flush(bridge):
            raise RuntimeError("resume flush fault")

        monkeypatch.setattr(type(bridge), "commit_resume_outputs", fail_flush)

    with pytest.raises(RuntimeError, match="resume (enqueue|flush) fault"):
        await asyncio.wait_for(
            adapter.open(raw=resume_message(call_id), user_id="user", connection_id=object()),
            1,
        )
    await asyncio.wait_for(control.wait_realtime_stopped(), 2)
    record = repository.find_by_id(call_id)
    assert record.state is CallState.ENDED
    assert record.end_reason is CallEndReason.SYSTEM_FAILURE
    assert control._stage.state is CallState.ENDED
    assert speech.sessions[control._stage._record.call_id].closed is True
    assert control._stage.context is None
    assert adapter._hub.session_for(call_id) is None
    assert adapter._hub._sessions == {}
    assert stages._lease_registry.current("user", "luotianyi") is None
    assert stages._call_ownerships == {}
    assert repository.find_by_request("request-1").call_id == control._stage._record.call_id
    await adapter.close()
    await stages.close()


@pytest.mark.asyncio
async def test_cancelled_resume_after_business_commit_terminates_and_releases_owned_state(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'call.sqlite'}")
    Base.metadata.create_all(engine)
    repository = SqlCallSessionRepository(sessionmaker(bind=engine))
    speech = FakeRealtimeSpeechSessionFactory()
    clock = _IncrementingClock()
    stages, _ = manager(speech_factory=speech, repository=repository, wall_clock=clock)
    adapter = call_adapter(stages)
    connection = await adapter.open(raw=start_message(), user_id="user", connection_id=object())
    call_id = json.loads((await adapter.next_output(connection)).text)["call_id"]
    await adapter.next_output(connection)
    control = stages.current_call_control(call_id)
    await asyncio.wait_for(control._stage_available.wait(), 1)

    async def wait_for_ringing():
        while control._stage.state is not CallState.RINGING:
            await asyncio.sleep(0)

    await asyncio.wait_for(wait_for_ringing(), 2)
    await control._stage.apply_answer(
        d.AnswerCall(
            action_id="test-answer",
            call_id=control._stage._record.call_id,
            decision=CallAnswerDecision.ACCEPT,
        )
    )
    await adapter.disconnect(connection)
    entered, release = asyncio.Event(), asyncio.Event()
    original_enqueue = adapter._enqueue

    async def blocked_enqueue(queue, outputs):
        entered.set()
        await release.wait()
        await original_enqueue(queue, outputs)

    monkeypatch.setattr(adapter, "_enqueue", blocked_enqueue)
    opening = asyncio.create_task(adapter.open(raw=resume_message(call_id), user_id="user", connection_id=object()))
    await asyncio.wait_for(entered.wait(), 1)
    assert control._stage.state is CallState.ACTIVE
    opening.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await opening
    await asyncio.wait_for(control.wait_realtime_stopped(), 2)
    record = repository.find_by_id(call_id)
    assert record.state is CallState.ENDED
    assert record.end_reason is CallEndReason.SYSTEM_FAILURE
    assert control._stage.state is CallState.ENDED
    assert speech.sessions[control._stage._record.call_id].closed is True
    assert control._stage.context is None
    assert adapter._hub.session_for(call_id) is None
    assert adapter._hub._sessions == {}
    assert stages._lease_registry.current("user", "luotianyi") is None
    assert stages._call_ownerships == {}
    assert stages.current_call_control(call_id) is None
    assert adapter._open_tasks == set()
    assert repository.find_by_request("request-1").call_id == control._stage._record.call_id
    await adapter.close()
    await stages.close()


@pytest.mark.asyncio
async def test_second_cancel_preserves_resume_error_and_logs_owned_termination_failure(
    monkeypatch,
):  # noqa: C901
    class Session:
        call_id = "call"

        @staticmethod
        def commit_resume(_cursor):
            raise RuntimeError("original cursor fault")

    class Candidate:
        def __init__(self, session):
            self.session = session

    class Binding:
        def __init__(self, session):
            self.session = session

    class Hub:
        def __init__(self, session):
            self.session = session
            self.unregistered = False

        async def commit_resume(self, _candidate):
            return Binding(self.session)

        async def unregister(self, *_args, **_kwargs):
            self.unregistered = True
            return True

    class Bridge:
        def __init__(self):
            self.outputs = asyncio.Queue()
            self.pending = False
            self.aborted = False

        def begin_resume_outputs(self):
            self.pending = True

        def abort_resume_outputs(self):
            self.pending = False
            self.aborted = True

        async def commit_resume_outputs(self):
            pass

    class Manager:
        @staticmethod
        async def commit_call_resume(_control):
            pass

    class Control:
        def __init__(self):
            self.entered = asyncio.Event()
            self.release = asyncio.Event()
            self.finished = False

        async def terminate(self, _reason):
            self.entered.set()
            await self.release.wait()
            self.finished = True
            raise RuntimeError("termination cleanup fault")

    session = Session()
    bridge = Bridge()
    control = Control()
    adapter = CallWebSocketAdapter(manager=Manager())
    adapter._hub = Hub(session)
    cleanup_logs = []
    monkeypatch.setattr(adapter, "_log_resume_cleanup_failure", lambda *args: cleanup_logs.append(args))
    operation = asyncio.create_task(adapter._commit_resume(Candidate(session), bridge, control, 0, [], asyncio.Event()))

    await asyncio.wait_for(control.entered.wait(), 1)
    operation.cancel()
    await asyncio.sleep(0)
    operation.cancel()
    control.release.set()

    with pytest.raises(RuntimeError, match="original cursor fault"):
        await operation
    assert control.finished is True
    assert bridge.aborted is True and bridge.pending is False
    assert adapter._hub.unregistered is True
    assert adapter._open_tasks == set()
    assert len(cleanup_logs) == 1
    kind, original_error, cleanup_error = cleanup_logs[0]
    assert kind == "termination"
    assert type(original_error) is RuntimeError
    assert type(cleanup_error) is RuntimeError


@pytest.mark.asyncio
@pytest.mark.parametrize("logger_fault", ["handler", "helper"])
async def test_logger_failure_cannot_replace_resume_error_or_skip_unregister(monkeypatch, logger_fault):  # noqa: C901
    class Session:
        call_id = "call"

        @staticmethod
        def commit_resume(_cursor):
            raise RuntimeError("original cursor fault")

    class Candidate:
        def __init__(self, session):
            self.session = session

    class Binding:
        def __init__(self, session):
            self.session = session

    class Hub:
        def __init__(self, session):
            self.session = session
            self.unregistered = False

        async def commit_resume(self, _candidate):
            return Binding(self.session)

        async def unregister(self, *_args, **_kwargs):
            self.unregistered = True
            return True

    class Bridge:
        def __init__(self):
            self.outputs = asyncio.Queue()
            self.pending = False
            self.aborted = False

        def begin_resume_outputs(self):
            self.pending = True

        def abort_resume_outputs(self):
            self.pending = False
            self.aborted = True

        async def commit_resume_outputs(self):
            pass

    class Manager:
        @staticmethod
        async def commit_call_resume(_control):
            pass

    class Control:
        def __init__(self):
            self.finished = False

        async def terminate(self, _reason):
            self.finished = True
            raise RuntimeError("termination cleanup fault")

    class FailingHandler(logging.Handler):
        def emit(self, _record):
            raise RuntimeError("logger failed")

    session = Session()
    bridge = Bridge()
    control = Control()
    adapter = CallWebSocketAdapter(manager=Manager())
    adapter._hub = Hub(session)
    handler = None
    if logger_fault == "handler":
        handler = FailingHandler()
        get_logger("src.adapter.websocket.call_v1.adapter").addHandler(handler)
    else:
        monkeypatch.setattr(
            adapter,
            "_log_resume_cleanup_failure",
            lambda *_args: (_ for _ in ()).throw(RuntimeError("logger failed")),
        )
    try:
        with pytest.raises(RuntimeError, match="original cursor fault"):
            await adapter._commit_resume(Candidate(session), bridge, control, 0, [], asyncio.Event())
    finally:
        if handler is not None:
            get_logger("src.adapter.websocket.call_v1.adapter").removeHandler(handler)

    assert control.finished is True
    assert bridge.aborted is True and bridge.pending is False
    assert adapter._hub.unregistered is True
    assert adapter._open_tasks == set()
