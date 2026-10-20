import asyncio
import hashlib
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from support.call_output import output_sink
from support.realtime_speech import FakeRealtimeSpeechSessionFactory
from support.stage_manager import start_call_stage

import src.domain.agent as d
from src.agent.context import ContextFactory
from src.agent.facade import Agent
from src.agent.handlers.action.router import ActionRouter
from src.agent.handlers.stimulus.call import CallReplyConfirmedHandler, CallTurnCompletedHandler
from src.agent.handlers.stimulus.router import StimulusRouter
from src.agent.processing.output_drafts import AudioChunkDraft, MessageEndDraft, TextFinalDraft
from src.agent.processing.plan_emitter import ActionPlanDraft
from src.agent.skills.expression.prepared_speech import PreparedSpeechCatalog
from src.domain.call import (
    CallAnswerDecision,
    CallAudioSemantic,
    CallEndReason,
    CallOutcome,
    CallReplyStatus,
    CallSpeechDelivery,
    CallState,
)
from src.infrastructure.models.realtime_speech import (
    ProviderFailed,
    SpeechStarted,
    SpeechStopped,
    TurnCompleted,
    TurnInvalid,
)
from src.infrastructure.observability.call_metrics import CallMetricName
from src.infrastructure.persistence.call_sessions import (
    BEIJING_TIMEZONE,
    CallSessionRecord,
    SqlCallSessionRepository,
)
from src.infrastructure.persistence.database.sql_database import Base
from src.stage.call_stage import CallIngressReceipt, CallStage, CallStageOwnership, CallStateChanged


class _ContextDatabase:
    def get_user_description(self, _user_id):
        return ""

    def get_user_preferences(self, _user_id):
        return {}

    def get_call_conversation_seed_state(self, _user_id, *, character_id, requested_at):
        assert character_id == "luotianyi"
        assert requested_at.tzinfo is None
        return {"summary": "", "conversations": []}


class _Clock:
    def __init__(self):
        self.wall = datetime(2026, 10, 11, 12, 0, tzinfo=BEIJING_TIMEZONE)
        self.monotonic = 100.0

    def now(self):
        self.wall += timedelta(milliseconds=1)
        return self.wall

    def tick(self):
        return self.monotonic

    def advance(self, seconds):
        self.monotonic += seconds


class _Transport:
    def __init__(self):
        self.items = []

    async def send_state(self, item):
        self.items.append(item)

    async def send_ended(self, snapshot):
        self.items.append(("ended", snapshot))

    async def send_failed(self, reason):
        self.items.append(("failed", reason))

    async def start_stream(self, response_id, stream_id, audio_format):
        self.items.append(("start", response_id, stream_id, audio_format))

    async def send_pcm(self, response_id, stream_id, payload, *, final):
        self.items.append(("pcm", response_id, stream_id, payload, final))

    async def stop_response(self, response_id, stream_ids):
        self.items.append(("stop", response_id, stream_ids))


class _FailingTransport(_Transport):
    def __init__(self, operation):
        super().__init__()
        self.operation = operation

    async def send_state(self, item):
        if self.operation == "state" and item.state is CallState.ACTIVE:
            raise RuntimeError("transport state failed")
        await super().send_state(item)

    async def send_ended(self, snapshot):
        if self.operation == "ended":
            raise RuntimeError("transport ended failed")
        await super().send_ended(snapshot)


class _BlockingTerminalTransport(_Transport):
    def __init__(self):
        super().__init__()
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def send_ended(self, snapshot):
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


class _BlockingProviderFactory:
    async def create(self, _call_id):
        await asyncio.Event().wait()


class _BlockingPushProviderFactory(FakeRealtimeSpeechSessionFactory):
    async def create(self, call_id):
        provider = await super().create(call_id)
        provider.push_started = asyncio.Event()
        provider.release_push = asyncio.Event()
        original_push = provider.push_audio

        async def push_audio(frame):
            provider.push_started.set()
            await provider.release_push.wait()
            await original_push(frame)

        provider.push_audio = push_audio
        return provider


def _report(request, plans):
    return d.HandlingReport(
        request_id=request.request_id,
        request_status=d.HandlingRequestStatus.COMPLETED,
        trigger_stimulus_id=request.stimulus.stimulus_id,
        basis_interaction_revision=request.interaction.interaction_revision,
        considered_pending_stimulus_ids=tuple(i.stimulus_id for i in request.interaction.pending_stimuli),
        consumed_pending_stimulus_ids=tuple(i.stimulus_id for i in request.interaction.pending_stimuli),
        retained_pending_stimulus_ids=(),
        emitted_plan_ids=tuple(plans.accepted_ids),
        error_code=None,
        retryable=False,
    )


class _AnswerHandler:
    async def handle(self, request, plans):
        return _report(request, plans)


class _TurnHandler:
    def __init__(self):
        self.gate = asyncio.Event()
        self.requests = []

    async def handle(self, request, plans):
        self.requests.append(request)
        await self.gate.wait()
        response_id = f"response-{request.stimulus.turn_seq}"
        await plans.emit(
            ActionPlanDraft(
                source_stimulus_ids=(request.stimulus.stimulus_id,),
                actions=(
                    d.Say(
                        action_id=f"{request.request_id}-say",
                        content="正式回答",
                        sound_content="正式回答",
                        prepared_audio_ref=None,
                        tone=d.Tone(value="normal"),
                        expression=None,
                        delivery=d.OutputDelivery.EPHEMERAL_REACTION,
                        call_delivery=CallSpeechDelivery(
                            audio_route=d.CallAudioRoute.CALL,
                            display_in_chat=False,
                            is_ephemeral=True,
                            response_id=response_id,
                        ),
                    ),
                ),
            )
        )
        return _report(request, plans)


class _NoPlanHandler:
    async def handle(self, request, plans):
        return _report(request, plans)


class _SilenceHandler:
    def __init__(self):
        self.requests = []

    async def handle(self, request, plans):
        self.requests.append(request)
        return _report(request, plans)


class _TimeLimitWarningHandler:
    def __init__(self):
        self.requests = []

    async def handle(self, request, plans):
        self.requests.append(request)
        return _report(request, plans)


class _NoOutputActionHandler:
    async def realize(self, action, execution_context, outputs):
        return d.ActionResult(
            action_id=action.action_id,
            status=d.ActionExecutionStatus.COMPLETED,
            error_code=None,
            irreversible_effect_committed=False,
            effect_ref=None,
        )


class _SayHandler:
    async def realize(self, action, execution_context, outputs):
        await outputs.emit(TextFinalDraft(delivery=action.delivery, text=action.content))
        await outputs.emit(
            AudioChunkDraft(
                delivery=action.delivery,
                data=b"\x00\x00",
                framing=d.AudioFraming.RAW_PCM,
                audio_format=d.CALL_PCM_FORMAT,
                final=True,
            )
        )
        await outputs.emit(
            MessageEndDraft(delivery=action.delivery, status=d.MessageEndStatus.COMPLETED, error_code=None)
        )
        return d.ActionResult(
            action_id=action.action_id,
            status=d.ActionExecutionStatus.COMPLETED,
            error_code=None,
            irreversible_effect_committed=False,
            effect_ref=None,
        )


def _agent(turn_handler, *, silence_handler=None, time_limit_handler=None):
    no_plan = _NoPlanHandler()
    silence = silence_handler or no_plan
    return Agent(
        character_id="luotianyi",
        stimulus_router=StimulusRouter(
            (
                (d.StimulusKind.CALL_TURN_COMPLETED, CallTurnCompletedHandler()),
                (d.StimulusKind.CALL_REPLY_CONFIRMED, CallReplyConfirmedHandler()),
                (d.StimulusKind.CALL_ANSWER_REQUESTED, _AnswerHandler()),
                (d.StimulusKind.CALL_STARTED, no_plan),
                (d.StimulusKind.CALL_REPLY_REQUESTED, turn_handler),
                (d.StimulusKind.CALL_SILENCE_ELAPSED, silence),
                (d.StimulusKind.CALL_TIME_LIMIT_WARNING, time_limit_handler or no_plan),
                (d.StimulusKind.CALL_ENDING, no_plan),
            )
        ),
        action_router=ActionRouter(
            (
                (d.ActionKind.ANSWER_CALL, _NoOutputActionHandler()),
                (d.ActionKind.SAY, _SayHandler()),
                (d.ActionKind.COGNITIVE_MAINTENANCE, _NoOutputActionHandler()),
            )
        ),
    )


@pytest.mark.asyncio
async def test_time_limit_warning_and_hard_deadline_are_stage_owned_and_monotonic(call_setup):
    warning_handler = _TimeLimitWarningHandler()
    stage, _, _, _ = await _create(
        call_setup,
        config={"time_limit_seconds": 2.0, "time_limit_warning_seconds": 1.0},
        time_limit_handler=warning_handler,
    )
    _, _, _, clock = call_setup
    await _eventually(lambda: stage.state is CallState.ACTIVE)

    clock.advance(1.0)
    stage._time_limit_changed.set()
    await _eventually(lambda: len(warning_handler.requests) == 1)
    assert stage.state is CallState.ACTIVE

    clock.advance(1.0)
    stage._time_limit_changed.set()
    snapshot = await asyncio.wait_for(stage.wait_closed(), 1)

    assert snapshot.terminal.end_reason is CallEndReason.TIME_LIMIT
    assert len(warning_handler.requests) == 1
    assert not stage.tasks


@pytest.mark.asyncio
async def test_time_limit_resume_does_not_reset_warning_or_deadline(call_setup):
    warning_handler = _TimeLimitWarningHandler()
    stage, _, _, _ = await _create(
        call_setup,
        config={"time_limit_seconds": 3.0, "time_limit_warning_seconds": 1.0},
        time_limit_handler=warning_handler,
    )
    _, _, _, clock = call_setup
    await _eventually(lambda: stage.state is CallState.ACTIVE)
    clock.advance(1.5)
    await stage.disconnect()
    assert await stage.resume() is True

    clock.advance(0.5)
    stage._time_limit_changed.set()
    await _eventually(lambda: len(warning_handler.requests) == 1)
    assert await stage.resume() is False

    clock.advance(1.0)
    stage._time_limit_changed.set()
    snapshot = await asyncio.wait_for(stage.wait_closed(), 1)

    assert snapshot.terminal.end_reason is CallEndReason.TIME_LIMIT
    assert len(warning_handler.requests) == 1


@pytest.mark.asyncio
async def test_time_limit_during_unrecovered_disconnect_yields_recovery_timeout(call_setup):
    stage, _, _, _ = await _create(
        call_setup,
        config={"time_limit_seconds": 2.0, "time_limit_warning_seconds": 1.0},
    )
    _, _, _, clock = call_setup
    await _eventually(lambda: stage.state is CallState.ACTIVE)
    clock.advance(1.5)
    await stage.disconnect()
    clock.advance(0.5)
    stage._time_limit_changed.set()
    await asyncio.sleep(0)
    assert stage.state is CallState.RECONNECTING

    clock.advance(2.5)
    stage._time_limit_changed.set()
    assert await stage.resume() is False
    snapshot = await asyncio.wait_for(stage.wait_closed(), 1)

    assert snapshot.terminal.end_reason is CallEndReason.RECOVERY_TIMEOUT
    assert snapshot.terminal.active_duration_ms == 1500


@pytest.mark.asyncio
async def test_resume_after_deadline_counts_reconnect_and_immediately_time_limits(call_setup):
    warning_handler = _TimeLimitWarningHandler()
    stage, _, _, _ = await _create(
        call_setup,
        config={"time_limit_seconds": 2.0, "time_limit_warning_seconds": 1.0},
        time_limit_handler=warning_handler,
    )
    _, _, _, clock = call_setup
    await _eventually(lambda: stage.state is CallState.ACTIVE)
    clock.advance(1.5)
    await stage.disconnect()
    clock.advance(0.75)
    stage._time_limit_changed.set()
    await asyncio.sleep(0)

    assert await stage.resume() is True
    snapshot = await asyncio.wait_for(stage.wait_closed(), 1)

    assert snapshot.terminal.end_reason is CallEndReason.TIME_LIMIT
    assert snapshot.terminal.active_duration_ms == 2250
    assert warning_handler.requests == []


@pytest.mark.asyncio
async def test_warning_waits_for_resume_and_is_sent_once_before_deadline(call_setup):
    warning_handler = _TimeLimitWarningHandler()
    stage, _, _, _ = await _create(
        call_setup,
        config={"time_limit_seconds": 3.0, "time_limit_warning_seconds": 1.0},
        time_limit_handler=warning_handler,
    )
    _, _, _, clock = call_setup
    await _eventually(lambda: stage.state is CallState.ACTIVE)
    clock.advance(1.5)
    await stage.disconnect()
    clock.advance(0.6)
    stage._time_limit_changed.set()
    await asyncio.sleep(0)
    assert warning_handler.requests == []

    assert await stage.resume() is True
    await _eventually(lambda: len(warning_handler.requests) == 1)
    clock.advance(0.9)
    stage._time_limit_changed.set()
    snapshot = await asyncio.wait_for(stage.wait_closed(), 1)

    assert snapshot.terminal.end_reason is CallEndReason.TIME_LIMIT
    assert len(warning_handler.requests) == 1


@pytest.mark.asyncio
async def test_early_hangup_cancels_time_limit_task_without_warning(call_setup):
    warning_handler = _TimeLimitWarningHandler()
    stage, _, _, _ = await _create(
        call_setup,
        config={"time_limit_seconds": 10.0, "time_limit_warning_seconds": 2.0},
        time_limit_handler=warning_handler,
    )
    await _eventually(lambda: stage.state is CallState.ACTIVE)

    snapshot = await stage.terminate(CallEndReason.USER_HANGUP)

    assert snapshot.terminal.end_reason is CallEndReason.USER_HANGUP
    assert warning_handler.requests == []
    assert not stage.tasks


@pytest.mark.asyncio
async def test_blocked_warning_does_not_delay_hard_time_limit(call_setup):
    warning_handler = _TimeLimitWarningHandler()
    warning_handler.release = asyncio.Event()

    async def blocked_handle(request, plans):
        warning_handler.requests.append(request)
        await warning_handler.release.wait()
        return _report(request, plans)

    warning_handler.handle = blocked_handle
    stage, _, _, _ = await _create(
        call_setup,
        config={"time_limit_seconds": 2.0, "time_limit_warning_seconds": 1.0},
        time_limit_handler=warning_handler,
    )
    _, _, _, clock = call_setup
    await _eventually(lambda: stage.state is CallState.ACTIVE)
    clock.advance(1.0)
    stage._time_limit_changed.set()
    await _eventually(lambda: len(warning_handler.requests) == 1)

    clock.advance(1.0)
    stage._time_limit_changed.set()
    snapshot = await asyncio.wait_for(stage.wait_closed(), 1)

    assert snapshot.terminal.end_reason is CallEndReason.TIME_LIMIT
    assert not stage.tasks


@pytest.mark.asyncio
async def test_provider_failure_wins_when_requested_at_time_limit_boundary(call_setup):
    stage, provider, _, _ = await _create(
        call_setup,
        config={"time_limit_seconds": 2.0, "time_limit_warning_seconds": 1.0},
    )
    _, _, _, clock = call_setup
    await _eventually(lambda: stage.state is CallState.ACTIVE)
    clock.advance(2.0)
    await provider.emit(ProviderFailed("provider_connection_closed", True))
    await _eventually(lambda: stage.termination_requested)
    stage._time_limit_changed.set()

    snapshot = await asyncio.wait_for(stage.wait_closed(), 1)

    assert snapshot.terminal.end_reason is CallEndReason.PROVIDER_FAILED
    assert not stage.tasks


@pytest.mark.parametrize(
    "config",
    [
        {"time_limit_seconds": 0},
        {"time_limit_seconds": float("inf")},
        {"time_limit_seconds": 10, "time_limit_warning_seconds": -1},
        {"time_limit_seconds": 10, "time_limit_warning_seconds": 10},
    ],
)
def test_time_limit_configuration_requires_finite_ordered_values(call_setup, config):
    repository, record, ownership, clock = call_setup

    with pytest.raises(ValueError, match="time_limit"):
        CallStage(
            ownership=ownership,
            record=record,
            agent=_agent(_TurnHandler()),
            context_factory=ContextFactory(character_id="luotianyi", database=_ContextDatabase()),
            call_sessions=repository,
            speech_factory=FakeRealtimeSpeechSessionFactory(),
            output_sink=output_sink(_Transport()),
            monotonic=clock.tick,
            wall_clock=clock.now,
            config=config,
        )


async def _eventually(predicate, timeout=1.0):
    async def wait():
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(wait(), timeout)


def _receipt(call_id, seq, payload):
    return CallIngressReceipt(
        call_id=str(call_id),
        direction="client_to_server",
        seq=seq,
        fingerprint=hashlib.sha256(b"audio\0" + payload).digest(),
    )


@pytest.fixture
def call_setup(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'call.db'}")
    Base.metadata.create_all(engine)
    repository = SqlCallSessionRepository(sessionmaker(bind=engine))
    clock = _Clock()
    call_id = uuid4()
    record = CallSessionRecord(
        call_id=call_id,
        client_request_id="request-1",
        user_id="user",
        character_id="luotianyi",
        state=CallState.PREPARING,
        requested_at=clock.now(),
        created_at=clock.now(),
        updated_at=clock.now(),
    )
    repository.create_if_absent(record)
    ownership = CallStageOwnership(
        call_id=str(call_id),
        user_id="user",
        character_id="luotianyi",
        client_request_id="request-1",
        setup_deadline=110.0,
        generation=1,
    )
    return repository, record, ownership, clock


async def _create(
    call_setup,
    *,
    decision=CallAnswerDecision.ACCEPT,
    config=None,
    release=None,
    silence_handler=None,
    time_limit_handler=None,
):
    repository, record, ownership, clock = call_setup
    speech = FakeRealtimeSpeechSessionFactory()
    transport = _Transport()
    turn_handler = _TurnHandler()
    context_factory = ContextFactory(character_id="luotianyi", database=_ContextDatabase())
    stage = await start_call_stage(
        ownership=ownership,
        record=record,
        agent=_agent(
            turn_handler,
            silence_handler=silence_handler,
            time_limit_handler=time_limit_handler,
        ),
        context_factory=context_factory,
        call_sessions=repository,
        speech_factory=speech,
        output_sink=output_sink(transport),
        release_ownership=release,
        monotonic=clock.tick,
        wall_clock=clock.now,
        config=config,
    )
    await stage.apply_answer(d.AnswerCall(action_id="answer", call_id=record.call_id, decision=decision))
    return stage, speech.sessions[record.call_id], transport, turn_handler


@pytest.mark.asyncio
async def test_real_stage_agent_context_and_sqlite_connect_then_cleanup(call_setup):
    released = []
    stage, provider, transport, _ = await _create(call_setup, release=lambda ownership: not released.append(ownership))
    repository, record, _, _ = call_setup

    await _eventually(lambda: stage.state is CallState.ACTIVE)
    assert provider.started_with is not None
    assert repository.find_by_id(record.call_id).state is CallState.ACTIVE
    assert [item.state for item in transport.items if isinstance(item, CallStateChanged)][:2] == [
        CallState.RINGING,
        CallState.ACTIVE,
    ]

    snapshot = await stage.terminate(CallEndReason.USER_HANGUP)

    assert snapshot.terminal.outcome is CallOutcome.CONNECTED
    assert stage.context is None
    assert provider.closed is True
    assert not stage.tasks
    assert released
    assert repository.find_by_id(record.call_id).state is CallState.ENDED


@pytest.mark.asyncio
async def test_decline_and_setup_deadline_are_terminal_without_active_duration(call_setup):
    stage, _, _, _ = await _create(call_setup, decision=CallAnswerDecision.DECLINE)
    snapshot = await stage.wait_closed()
    repeated = await stage.terminate(CallEndReason.USER_HANGUP)
    repository, record, ownership, clock = call_setup
    persisted = repository.find_by_id(record.call_id)

    assert stage.snapshot.terminal.outcome is CallOutcome.DECLINED
    assert stage.snapshot.terminal.active_duration_ms == 0
    assert snapshot is repeated
    assert persisted.state is CallState.ENDED
    assert persisted.outcome is CallOutcome.DECLINED
    assert persisted.end_reason is CallEndReason.DECLINED

    second = record.with_update(
        call_id=uuid4(),
        client_request_id="request-2",
        requested_at=clock.now(),
        created_at=clock.now(),
        updated_at=clock.now(),
        state=CallState.PREPARING,
    )
    repository.create_if_absent(second)
    expired = CallStageOwnership(
        str(second.call_id), "user", "luotianyi", "request-2", clock.monotonic, ownership.generation + 1
    )
    with pytest.raises(TimeoutError):
        await start_call_stage(
            ownership=expired,
            record=second,
            agent=_agent(_TurnHandler()),
            context_factory=ContextFactory(character_id="luotianyi", database=_ContextDatabase()),
            call_sessions=repository,
            speech_factory=FakeRealtimeSpeechSessionFactory(),
            output_sink=output_sink(_Transport()),
            monotonic=clock.tick,
            wall_clock=clock.now,
        )


@pytest.mark.asyncio
async def test_pcm_receipts_are_bounded_idempotent_and_turns_require_completed_event(call_setup):
    stage, provider, _, turn_handler = await _create(call_setup, config={"pcm_queue_capacity": 1})
    await _eventually(lambda: stage.state is CallState.ACTIVE)

    assert stage.accept_pcm(_receipt(stage._record.call_id, 7, b"\x00\x00"), b"\x00\x00") is True
    assert stage.accept_pcm(_receipt(stage._record.call_id, 7, b"\x00\x00"), b"\x00\x00") is True
    assert stage.accept_pcm(_receipt(stage._record.call_id, 9, b"\x00"), b"\x00") is False
    await _eventually(lambda: len(provider.pushed_frames) == 1)

    await provider.emit(TurnInvalid("ambient_only"))
    await asyncio.sleep(0)
    assert stage._turns == {}
    await provider.emit(TurnCompleted(CallAudioSemantic(transcript="你好")))
    await _eventually(lambda: 1 in stage._turns)
    turn_handler.gate.set()
    await _eventually(lambda: bool(stage._playback.pending_streams))
    response_id, stream_id = stage._playback.pending_streams[0]
    stage.playback_completed(response_id, stream_id)
    await _eventually(lambda: stage._turns[1].status is CallReplyStatus.COMPLETED)
    await stage.terminate()


@pytest.mark.asyncio
async def test_reconnect_preserves_accepted_pcm_and_completed_turn_exactly_once(call_setup):
    repository, record, ownership, clock = call_setup
    speech = _BlockingPushProviderFactory()
    transport = _Transport()
    turn_handler = _TurnHandler()
    turn_handler.gate.set()
    captured_metrics = []

    class Metrics:
        def record(self, metric):
            captured_metrics.append(metric)
            return True

    stage = await start_call_stage(
        ownership=ownership,
        record=record,
        agent=_agent(turn_handler),
        context_factory=ContextFactory(character_id="luotianyi", database=_ContextDatabase()),
        call_sessions=repository,
        speech_factory=speech,
        output_sink=output_sink(transport),
        call_metrics=Metrics(),
        monotonic=clock.tick,
        wall_clock=clock.now,
    )
    await stage.apply_answer(
        d.AnswerCall(action_id="answer", call_id=record.call_id, decision=CallAnswerDecision.ACCEPT)
    )
    provider = speech.sessions[record.call_id]
    try:
        await _eventually(lambda: stage.state is CallState.ACTIVE)
        assert stage.accept_pcm(_receipt(record.call_id, 1, b"\x01\x00"), b"\x01\x00")
        assert stage.accept_pcm(_receipt(record.call_id, 2, b"\x02\x00"), b"\x02\x00")
        await provider.push_started.wait()

        await stage.disconnect()
        provider.release_push.set()
        await provider.emit(TurnCompleted(CallAudioSemantic(transcript="断线期已完成轮次")))
        assert await stage.resume() is True

        await asyncio.wait_for(stage._pcm.join(), 1)
        assert [frame.sequence for frame in provider.pushed_frames] == [1, 2]
        await _eventually(lambda: len(turn_handler.requests) == 1)
        await _eventually(lambda: stage._realize_task is not None and stage._realize_task.done())
        assert [frame.payload for frame in provider.pushed_frames] == [b"\x01\x00", b"\x02\x00"]
        assert len(turn_handler.requests[0].interaction.pending_stimuli) == 1
        assert list(stage._turns) == [1]
        assert CallMetricName.FIRST_AUDIO not in [metric.name for metric in captured_metrics]

        response_id, stream_id = stage._playback.pending_streams[0]
        stage.playback_completed(response_id, stream_id)
        await _eventually(lambda: not stage._inputs.pending)
        await provider.emit(TurnCompleted(CallAudioSemantic(transcript="恢复后新轮次")))
        await _eventually(lambda: len(turn_handler.requests) == 2)
        await _eventually(lambda: stage._realize_task is not None and stage._realize_task.done())
        response_id, _ = stage._playback.pending_streams[0]
        stage.audio_sent(response_id)
        assert [metric.name for metric in captured_metrics].count(CallMetricName.FIRST_AUDIO) == 1
    finally:
        provider.release_push.set()
        await stage.terminate(CallEndReason.USER_HANGUP)


@pytest.mark.asyncio
async def test_reconnect_timeout_discards_paused_pcm_and_provider_events(call_setup):
    repository, record, ownership, clock = call_setup
    speech = _BlockingPushProviderFactory()
    turn_handler = _TurnHandler()
    stage = await start_call_stage(
        ownership=ownership,
        record=record,
        agent=_agent(turn_handler),
        context_factory=ContextFactory(character_id="luotianyi", database=_ContextDatabase()),
        call_sessions=repository,
        speech_factory=speech,
        output_sink=output_sink(_Transport()),
        monotonic=clock.tick,
        wall_clock=clock.now,
    )
    await stage.apply_answer(
        d.AnswerCall(action_id="answer", call_id=record.call_id, decision=CallAnswerDecision.ACCEPT)
    )
    provider = speech.sessions[record.call_id]
    try:
        await _eventually(lambda: stage.state is CallState.ACTIVE)
        assert stage.accept_pcm(_receipt(record.call_id, 2, b"\x01\x00"), b"\x01\x00")
        assert stage.accept_pcm(_receipt(record.call_id, 3, b"\x02\x00"), b"\x02\x00")
        await provider.push_started.wait()
        await stage.disconnect()
        await provider.emit(TurnCompleted(CallAudioSemantic(transcript="不得兑现")))
        clock.advance(3.0)

        assert await stage.resume() is False
        await stage.wait_closed()

        assert stage.context is None
        assert stage._pcm.empty()
        assert stage._pcm_buffered_bytes == 0
        assert turn_handler.requests == []
        assert not stage.tasks
    finally:
        provider.release_push.set()
        await stage.terminate(CallEndReason.USER_HANGUP)


@pytest.mark.asyncio
async def test_provider_failure_bypasses_paused_reconnect_events_and_cleans_owned_work(call_setup):
    stage, provider, _, turn_handler = await _create(call_setup)
    await _eventually(lambda: stage.state is CallState.ACTIVE)
    await stage.disconnect()
    await provider.emit(TurnCompleted(CallAudioSemantic(transcript="恢复后才可兑现")))
    await _eventually(
        lambda: provider._events.empty() and stage._events_task is not None and not stage._events_task.done()
    )

    await provider.emit(ProviderFailed("provider_connection_closed", True))
    snapshot = await asyncio.wait_for(stage.wait_closed(), 0.2)

    assert snapshot.terminal.end_reason is CallEndReason.PROVIDER_FAILED
    assert turn_handler.requests == []
    assert stage.context is None
    assert stage._pcm.empty()
    assert stage._pcm_buffered_bytes == 0
    assert not stage.tasks
    assert provider.closed is True


@pytest.mark.asyncio
async def test_provider_failure_requested_before_resume_rejects_resume_and_cleans_paused_work(call_setup):
    repository, record, ownership, clock = call_setup
    speech = _BlockingPushProviderFactory()
    turn_handler = _TurnHandler()
    released = []
    stage = await start_call_stage(
        ownership=ownership,
        record=record,
        agent=_agent(turn_handler),
        context_factory=ContextFactory(character_id="luotianyi", database=_ContextDatabase()),
        call_sessions=repository,
        speech_factory=speech,
        output_sink=output_sink(_Transport()),
        release_ownership=lambda value: not released.append(value),
        monotonic=clock.tick,
        wall_clock=clock.now,
    )
    await stage.apply_answer(
        d.AnswerCall(action_id="answer", call_id=record.call_id, decision=CallAnswerDecision.ACCEPT)
    )
    provider = speech.sessions[record.call_id]
    await _eventually(lambda: stage.state is CallState.ACTIVE)
    assert stage.accept_pcm(_receipt(record.call_id, 2, b"\x01\x00"), b"\x01\x00")
    assert stage.accept_pcm(_receipt(record.call_id, 3, b"\x02\x00"), b"\x02\x00")
    await provider.push_started.wait()
    await stage.disconnect()
    await provider.emit(TurnCompleted(CallAudioSemantic(transcript="竞态中不得兑现")))
    await _eventually(lambda: provider._events.empty())

    termination_entered = asyncio.Event()
    release_termination = asyncio.Event()
    original_terminate_owned = stage._terminate_owned

    async def delayed_terminate_owned(reason):
        termination_entered.set()
        await release_termination.wait()
        return await original_terminate_owned(reason)

    stage._terminate_owned = delayed_terminate_owned
    await provider.emit(ProviderFailed("provider_connection_closed", True))
    await asyncio.wait_for(termination_entered.wait(), 0.2)
    assert stage.termination_requested is True

    assert await stage.resume() is False
    assert stage.state is CallState.RECONNECTING
    assert turn_handler.requests == []
    assert [frame.sequence for frame in provider.pushed_frames] == []

    release_termination.set()
    provider.release_push.set()
    snapshot = await asyncio.wait_for(stage.wait_closed(), 1)
    assert snapshot.terminal.end_reason is CallEndReason.PROVIDER_FAILED
    assert turn_handler.requests == []
    assert stage.context is None
    assert stage._pcm.empty()
    assert stage._pcm_buffered_bytes == 0
    await _eventually(lambda: released == [ownership])
    assert released == [ownership]
    assert provider.closed is True
    assert not stage.tasks


@pytest.mark.asyncio
async def test_invalid_turn_releases_matching_speech_and_preserves_newer_speech(call_setup):
    silence_handler = _SilenceHandler()
    stage, provider, _, _ = await _create(call_setup, silence_handler=silence_handler)
    repository, record, _, clock = call_setup
    maintenance_turn_seq = repository.find_by_id(record.call_id).maintenance_turn_seq
    await _eventually(lambda: stage.state is CallState.ACTIVE)

    await provider.emit(SpeechStarted("invalid-turn"))
    await _eventually(lambda: stage._playback._user_speaking)
    stage.register_playback("response", 1)
    stage.playback_final("response", 1)
    stage.playback_completed("response", 1)
    assert stage._playback.silence_started_at is None

    await provider.emit(TurnInvalid("turn_invalid", "invalid-turn"))
    await _eventually(lambda: stage._playback.silence_started_at == clock.monotonic)
    assert stage._turns == {}
    assert stage._unfinished_turns == set()
    clock.advance(5)
    await _eventually(lambda: len(silence_handler.requests) == 1, timeout=6.0)
    assert silence_handler.requests[0].stimulus.kind is d.StimulusKind.CALL_SILENCE_ELAPSED

    await provider.emit(SpeechStarted("new-turn"))
    await _eventually(lambda: stage._playback._user_speaking)
    new_turn_generation = stage._generation
    await provider.emit(TurnInvalid("turn_invalid", "invalid-turn"))
    await asyncio.sleep(0)
    assert stage._playback._user_speaking is True
    assert stage._generation == new_turn_generation
    assert stage._turns == {}
    assert stage._unfinished_turns == set()
    assert repository.find_by_id(record.call_id).maintenance_turn_seq == maintenance_turn_seq
    await stage.terminate()


@pytest.mark.asyncio
@pytest.mark.parametrize("stopped_first", [False, True])
async def test_invalid_speech_after_completed_playback_restarts_silence_without_formal_input(call_setup, stopped_first):
    silence_handler = _SilenceHandler()
    stage, provider, _, turn_handler = await _create(call_setup, silence_handler=silence_handler)
    repository, record, _, clock = call_setup
    progress = repository.find_by_id(record.call_id).maintenance_turn_seq
    try:
        await _eventually(lambda: stage.state is CallState.ACTIVE)
        stage.register_playback("previous-reply", 1)
        stage.playback_final("previous-reply", 1)
        stage.playback_completed("previous-reply", 1)
        assert stage._playback.silence_started_at == clock.monotonic
        clock.advance(3)
        await provider.emit(SpeechStarted("noise"))
        await _eventually(lambda: stage._playback._user_speaking)
        assert stage._playback.silence_started_at is None
        if stopped_first:
            await provider.emit(SpeechStopped("noise"))
            await _eventually(lambda: not stage._playback._user_speaking)
            assert stage._playback.silence_started_at is None
        clock.advance(4)
        await provider.emit(TurnInvalid("empty_transcript" if stopped_first else "turn_invalid", "noise"))
        await _eventually(lambda: stage._playback.silence_started_at == clock.monotonic)
        restored_at = clock.monotonic
        silence_task = stage._silence_task
        clock.advance(2)
        await provider.emit(TurnInvalid("turn_invalid", "noise"))
        await provider.emit(SpeechStopped("noise"))
        for _ in range(10):
            await asyncio.sleep(0)
        assert stage._playback.silence_started_at == restored_at
        assert stage._silence_task is silence_task
        assert not silence_handler.requests
        assert not stage._playback.silence_elapsed()
        clock.advance(3)
        await _eventually(lambda: len(silence_handler.requests) == 1, timeout=6)
        assert silence_handler.requests[0].stimulus.kind is d.StimulusKind.CALL_SILENCE_ELAPSED
        assert not stage._turns and not stage._unfinished_turns
        assert not turn_handler.requests and not stage._plans
        assert repository.find_by_id(record.call_id).maintenance_turn_seq == progress
    finally:
        await stage.terminate()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stale", [SpeechStopped("old"), TurnInvalid("turn_invalid", "old"), TurnInvalid("turn_invalid")]
)
async def test_stale_speech_end_cannot_release_new_speech_or_restore_silence(call_setup, stale):
    stage, provider, _, _ = await _create(call_setup)
    try:
        await _eventually(lambda: stage.state is CallState.ACTIVE)
        stage.register_playback("previous-reply", 1)
        stage.playback_final("previous-reply", 1)
        stage.playback_completed("previous-reply", 1)
        await provider.emit(SpeechStarted("old"))
        await _eventually(lambda: stage._active_speech_item_id == "old")
        await provider.emit(SpeechStarted("new"))
        await _eventually(lambda: stage._active_speech_item_id == "new")
        await provider.emit(stale)
        for _ in range(10):
            await asyncio.sleep(0)
        assert stage._playback._user_speaking
        assert stage._playback.silence_started_at is None
        assert stage._active_speech_item_id == "new"
    finally:
        await stage.terminate()


@pytest.mark.asyncio
async def test_invalid_turn_without_identity_releases_speaking_without_formal_turn_or_reply(call_setup):
    stage, provider, _, turn_handler = await _create(call_setup)
    repository, record, _, _ = call_setup
    maintenance_turn_seq = repository.find_by_id(record.call_id).maintenance_turn_seq
    await _eventually(lambda: stage.state is CallState.ACTIVE)

    await provider.emit(SpeechStarted())
    await _eventually(lambda: stage._playback._user_speaking)
    generation = stage._generation

    await provider.emit(TurnInvalid("turn_invalid"))
    await _eventually(lambda: not stage._playback._user_speaking)

    assert stage._generation == generation
    assert stage._turns == {}
    assert stage._unfinished_turns == set()
    assert turn_handler.requests == []
    assert not stage._plans
    assert repository.find_by_id(record.call_id).maintenance_turn_seq == maintenance_turn_seq
    await stage.terminate()
    assert not stage.tasks


@pytest.mark.asyncio
async def test_speech_started_interrupts_handle_and_terminal_snapshot_keeps_user_fact(call_setup):
    stage, provider, _, turn_handler = await _create(call_setup)
    await _eventually(lambda: stage.state is CallState.ACTIVE)
    await provider.emit(TurnCompleted(CallAudioSemantic(sound_description="敲桌声")))
    await _eventually(lambda: bool(stage._handle_tasks))

    await provider.emit(SpeechStarted())
    await _eventually(lambda: not stage._handle_tasks)
    turn_handler.gate.set()
    snapshot = await stage.terminate()

    assert len(snapshot.completed_turns) == 1
    assert snapshot.completed_turns[0].user_semantic == "敲桌声"
    assert snapshot.completed_turns[0].reply_status is CallReplyStatus.NOT_STARTED


@pytest.mark.asyncio
async def test_playback_completion_is_idempotent_and_resume_restarts_full_silence(call_setup):
    stage, _, _, _ = await _create(call_setup)
    await _eventually(lambda: stage.state is CallState.ACTIVE)
    stage.register_playback("response", 1)
    stage.playback_final("response", 1)
    first = stage.playback_completed("response", 1)
    duplicate = stage.playback_completed("response", 1)
    assert first.duplicate is False
    assert duplicate.duplicate is True
    assert duplicate.silence_started_at == first.silence_started_at

    await stage.disconnect()
    assert stage.state is CallState.RECONNECTING
    assert await stage.resume() is True
    assert stage.state is CallState.ACTIVE
    assert stage._playback.silence_started_at == call_setup[3].monotonic
    await stage.terminate()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("elapsed", "expected"),
    [(2.999, True), (3.0, False), (3.1, False)],
)
async def test_resume_uses_fixed_disconnect_deadline_even_when_timer_is_delayed(call_setup, elapsed, expected):
    stage, provider, _, _ = await _create(call_setup)
    repository, record, _, clock = call_setup
    await _eventually(lambda: stage.state is CallState.ACTIVE)
    await stage.disconnect()
    clock.monotonic += elapsed

    assert await stage.resume() is expected
    if expected:
        assert stage.state is CallState.ACTIVE
        assert provider.closed is False
        await stage.terminate()
    else:
        snapshot = await stage.wait_closed()
        assert snapshot.terminal.end_reason is CallEndReason.RECOVERY_TIMEOUT
        assert repository.find_by_id(record.call_id).state is CallState.ENDED
        assert provider.closed is True


@pytest.mark.asyncio
async def test_resume_keeps_context_and_does_not_emit_another_call_started(call_setup):
    stage, _, _, _ = await _create(call_setup)
    await _eventually(lambda: stage.state is CallState.ACTIVE)
    original_context = stage.context
    original_revision = stage._revision
    await stage.disconnect()

    assert await stage.resume() is True

    assert stage.context is original_context
    assert stage._revision == original_revision
    await stage.terminate()


@pytest.mark.asyncio
async def test_user_hangup_reason_wins_recovery_deadline_race(call_setup):
    stage, _, _, _ = await _create(call_setup)
    await stage.disconnect()
    stage._recovery_deadline = stage._monotonic()
    original = stage._terminate_owned
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(reason):
        entered.set()
        await release.wait()
        return await original(reason)

    stage._terminate_owned = delayed
    hangup = asyncio.create_task(stage.terminate(CallEndReason.USER_HANGUP))
    await asyncio.wait_for(entered.wait(), 1)
    deadline = asyncio.create_task(stage.expire_retention(stage._recovery_deadline))
    await asyncio.sleep(0)
    release.set()
    snapshot = await hangup
    await deadline
    assert snapshot.terminal.end_reason is CallEndReason.USER_HANGUP
    assert stage.snapshot is snapshot


@pytest.mark.asyncio
async def test_expired_resume_uses_owned_termination_without_recovery_self_wait(call_setup):
    stage, _, _, _ = await _create(call_setup)
    await stage.disconnect()
    stage._recovery_deadline = stage._monotonic()

    assert await asyncio.wait_for(stage.resume(), 1) is False
    assert stage.snapshot.terminal.end_reason is CallEndReason.RECOVERY_TIMEOUT
    assert not stage.tasks


@pytest.mark.asyncio
async def test_failed_terminal_delivery_cannot_hold_realtime_resources_or_skip_settlement(call_setup):
    repository, record, ownership, clock = call_setup
    speech = FakeRealtimeSpeechSessionFactory()
    transport = _FailingTransport("ended")
    released = []
    settled = []

    class Settlement:
        async def emit(self, snapshot, *, result):
            settled.append(snapshot)

    stage = await start_call_stage(
        ownership=ownership,
        record=record,
        agent=_agent(_TurnHandler()),
        context_factory=ContextFactory(character_id="luotianyi", database=_ContextDatabase()),
        call_sessions=repository,
        speech_factory=speech,
        output_sink=output_sink(transport),
        release_ownership=lambda value: not released.append(value),
        save_history=Settlement().emit,
        monotonic=clock.tick,
        wall_clock=clock.now,
    )
    await stage.apply_answer(
        d.AnswerCall(action_id="answer", call_id=record.call_id, decision=CallAnswerDecision.ACCEPT)
    )

    await stage.terminate()

    assert stage._closed.is_set()
    assert stage.context is None
    assert speech.sessions[record.call_id].closed is True
    assert released == [ownership]
    assert settled == [stage.snapshot]
    assert repository.find_by_id(record.call_id).state is CallState.ENDED
    assert not stage.tasks


@pytest.mark.asyncio
async def test_blocked_terminal_delivery_is_bounded_before_history_write(call_setup):
    repository, record, ownership, clock = call_setup
    speech = FakeRealtimeSpeechSessionFactory()
    transport = _BlockingTerminalTransport()
    released = []
    settled = []

    class Settlement:
        async def emit(self, snapshot, *, result):
            settled.append(snapshot)

    stage = await start_call_stage(
        ownership=ownership,
        record=record,
        agent=_agent(_TurnHandler()),
        context_factory=ContextFactory(character_id="luotianyi", database=_ContextDatabase()),
        call_sessions=repository,
        speech_factory=speech,
        output_sink=output_sink(transport),
        release_ownership=lambda value: not released.append(value),
        save_history=Settlement().emit,
        monotonic=clock.tick,
        wall_clock=clock.now,
        config={"terminal_delivery_timeout": 0.01},
    )
    await stage.apply_answer(
        d.AnswerCall(action_id="answer", call_id=record.call_id, decision=CallAnswerDecision.ACCEPT)
    )

    snapshot = await asyncio.wait_for(stage.terminate(), 1)

    assert transport.started.is_set()
    assert transport.cancelled.is_set()
    assert settled == [snapshot]
    assert stage._closed.is_set()
    assert stage.context is None
    assert speech.sessions[record.call_id].closed is True
    assert released == [ownership]
    assert repository.find_by_id(record.call_id).state is CallState.ENDED
    assert not stage.tasks


@pytest.mark.asyncio
async def test_terminal_ledger_uses_monotonic_duration_and_first_disconnect_cutoff(call_setup):
    stage, _, _, _ = await _create(call_setup)
    repository, record, _, clock = call_setup
    await _eventually(lambda: stage.state is CallState.ACTIVE)
    clock.monotonic += 2.0
    await stage.disconnect()
    clock.monotonic += 10.0
    await stage.terminate(CallEndReason.RECOVERY_TIMEOUT)
    snapshot = await stage.wait_closed()

    persisted = repository.find_by_id(record.call_id)
    assert snapshot.terminal.active_duration_ms == 2000
    assert persisted.active_duration_ms == 2000
    assert persisted.disconnected_at is not None
    assert persisted.ended_at is not None


@pytest.mark.asyncio
async def test_setup_await_is_bounded_by_original_deadline(call_setup):
    repository, record, ownership, clock = call_setup
    ownership = CallStageOwnership(
        ownership.call_id,
        ownership.user_id,
        ownership.character_id,
        ownership.client_request_id,
        clock.monotonic + 0.01,
        ownership.generation,
    )
    with pytest.raises(TimeoutError):
        await start_call_stage(
            ownership=ownership,
            record=record,
            agent=_agent(_TurnHandler()),
            context_factory=ContextFactory(character_id="luotianyi", database=_ContextDatabase()),
            call_sessions=repository,
            speech_factory=_BlockingProviderFactory(),
            output_sink=output_sink(_Transport()),
            monotonic=clock.tick,
            wall_clock=clock.now,
        )
    assert repository.find_by_id(record.call_id).state is CallState.FAILED


@pytest.mark.asyncio
async def test_pcm_rejects_sequence_duplicates_conflicts_and_gaps(call_setup):
    stage, provider, _, _ = await _create(call_setup, config={"pcm_queue_capacity": 4})
    await _eventually(lambda: stage.state is CallState.ACTIVE)

    call_id = stage._record.call_id
    assert stage.accept_pcm(_receipt(call_id, 2, b"\x00\x00"), b"\x00\x00")
    assert stage.accept_pcm(_receipt(call_id, 4, b"\x01\x00"), b"\x01\x00")
    assert not stage.accept_pcm(_receipt(call_id, 2, b"\x01\x00"), b"\x01\x00")
    await _eventually(lambda: [frame.sequence for frame in provider.pushed_frames] == [1, 2])
    await stage.terminate()


@pytest.mark.asyncio
async def test_pcm_does_not_require_audio_wire_sequence_to_start_at_one(call_setup):
    stage, _, _, _ = await _create(call_setup)
    await _eventually(lambda: stage.state is CallState.ACTIVE)

    assert stage.accept_pcm(_receipt(stage._record.call_id, 42, b"\x00\x00"), b"\x00\x00")
    await stage.terminate()


@pytest.mark.asyncio
async def test_pcm_receipts_roll_over_without_retaining_payload_or_refusing_long_calls(call_setup):
    stage, provider, _, _ = await _create(call_setup, config={"pcm_queue_capacity": 8, "receipt_capacity": 4})
    await _eventually(lambda: stage.state is CallState.ACTIVE)

    for seq in range(10, 16):
        payload = seq.to_bytes(2, "little")
        assert stage.accept_pcm(_receipt(stage._record.call_id, seq, payload), payload)
        await _eventually(lambda expected=seq - 9: len(provider.pushed_frames) == expected)

    assert len(stage._receipts) == 4
    assert all(len(fingerprint) == 32 for fingerprint in stage._receipts.values())
    assert [frame.sequence for frame in provider.pushed_frames] == list(range(1, 7))
    await stage.terminate()


@pytest.mark.asyncio
async def test_cleanup_releases_ownership_even_when_provider_close_fails(call_setup):
    released = []
    stage, provider, _, _ = await _create(call_setup, release=lambda ownership: not released.append(ownership))
    await _eventually(lambda: stage.state is CallState.ACTIVE)

    async def fail_close():
        provider.closed = True
        raise RuntimeError("close failed")

    provider.close = fail_close
    with pytest.raises(RuntimeError, match="close failed"):
        await stage.terminate()

    assert released
    assert stage.context is None
    assert not stage.tasks
    assert stage._closed.is_set()


@pytest.mark.asyncio
async def test_next_turn_runs_after_cancelled_owned_maintenance_drains(call_setup):
    from src.utils.owned_operation import complete_owned

    stage, provider, transport, handler = await _create(call_setup)
    entered, release = asyncio.Event(), asyncio.Event()
    original = stage._realize_plan

    async def blocked_first(plan, turn_seq):
        if turn_seq == 1:
            entered.set()
            await complete_owned(release.wait())
        else:
            await original(plan, turn_seq)

    stage._realize_plan = blocked_first
    handler.gate.set()
    try:
        await provider.emit(TurnCompleted(CallAudioSemantic(transcript="first")))
        await asyncio.wait_for(entered.wait(), 1)
        generation = stage._generation
        await provider.emit(SpeechStarted())
        await _eventually(lambda: stage._generation > generation)
        await provider.emit(TurnCompleted(CallAudioSemantic(transcript="next")))
        await _eventually(lambda: stage._inputs.ready == {1, 2})
        assert len(handler.requests) == 1, "owned maintenance must drain before selecting new output"
        release.set()
        await _eventually(
            lambda: any(
                isinstance(item, tuple) and item[0] == "start" and item[1] == "response-2" for item in transport.items
            )
        )
    finally:
        release.set()
        await stage.terminate(CallEndReason.USER_HANGUP)


@pytest.mark.asyncio
async def test_32_real_call_turns_emit_and_execute_threshold_maintenance(call_setup):
    from types import SimpleNamespace

    from src.agent.handlers.action.cognitive_maintenance import CognitiveMaintenanceActionHandler
    from src.agent.handlers.stimulus.call import CallReplyRequestedHandler
    from src.agent.skills.cognitive.call_recall import CallRecallDecisionSkill, CallReplySkill
    from src.agent.skills.cognitive.call_settlement import CallMaintenanceSkill
    from src.agent.skills.cognitive_maintenance import CognitiveMaintenanceSkill
    from src.agent.skills.contracts import ReplyDraft
    from src.agent.skills.conversation.compaction import ConversationCompactionSkill
    from src.domain.call import AckStyle, CallRecallDecision, RecallMode

    class Memory:
        inputs = []

        async def extract_maintenance_candidates(self, **kwargs):
            self.inputs.append(kwargs)
            return ()

        async def propose_user_profile(self, **kwargs):
            return None

        async def write_maintenance_candidates(self, **kwargs):
            pass

    class Model:
        async def generate_response(self, **kwargs):
            return "compressed call prefix"

    class Generator:
        async def generate(self, **kwargs):
            return (ReplyDraft("正式回答", "正式回答", "normal", None),)

    async def decide(*args, **kwargs):
        return CallRecallDecision(RecallMode.DIRECT, (), AckStyle.NONE)

    stage, provider, transport, _ = await _create(call_setup)
    repository, record, _, _ = call_setup
    memory = Memory()
    call_skill = CallMaintenanceSkill({"luotianyi": memory})
    compaction = ConversationCompactionSkill(
        {"llm_module": {}}, SimpleNamespace(register_llm_module=lambda *args: Model())
    )
    skill = CognitiveMaintenanceSkill(
        memories={"luotianyi": memory}, compaction=compaction, call_maintenance=call_skill
    )
    recall = CallRecallDecisionSkill(memories={"luotianyi": memory})
    recall.decide = decide
    stage._agent = Agent(
        character_id="luotianyi",
        stimulus_router=StimulusRouter(
            (
                (d.StimulusKind.CALL_TURN_COMPLETED, CallTurnCompletedHandler()),
                (d.StimulusKind.CALL_REPLY_CONFIRMED, CallReplyConfirmedHandler()),
                (
                    d.StimulusKind.CALL_REPLY_REQUESTED,
                    CallReplyRequestedHandler(
                        recall, CallReplySkill({"luotianyi": Generator()}), PreparedSpeechCatalog({})
                    ),
                ),
                (d.StimulusKind.CALL_ENDING, _NoPlanHandler()),
            )
        ),
        action_router=ActionRouter(
            (
                (d.ActionKind.SAY, _SayHandler()),
                (d.ActionKind.COGNITIVE_MAINTENANCE, CognitiveMaintenanceActionHandler("luotianyi", skill)),
            )
        ),
    )
    try:
        for seq in range(1, 33):
            await provider.emit(TurnCompleted(CallAudioSemantic(transcript=f"user turn {seq}")))
            await _eventually(
                lambda: len([item for item in transport.items if isinstance(item, tuple) and item[0] == "start"]) == seq
            )
            await _eventually(lambda: stage._realize_task.done())
            stream = [item for item in transport.items if isinstance(item, tuple) and item[0] == "start"][-1]
            stage.playback_completed(stream[1], stream[2])
            await _eventually(lambda: not stage._inputs.pending and not stage._fact_tasks)
            await _eventually(lambda: stage._realize_task.done())
        assert stage.context.conversation.read().summary.text == "compressed call prefix"
        assert len(stage.context.conversation.read().entries) == 32
        assert stage.context.conversation.read_call_maintenance_progress() == 16
        assert len(memory.inputs) == 1
        snapshot = await stage.terminate(CallEndReason.USER_HANGUP)
        assert snapshot.maintenance_turn_seq == 16
        assert all(turn.reply_status is CallReplyStatus.COMPLETED for turn in snapshot.completed_turns)
    finally:
        if stage.snapshot is None:
            await stage.terminate(CallEndReason.USER_HANGUP)


@pytest.mark.asyncio
async def test_interrupted_unanswered_input_is_protected_from_maintenance(call_setup):
    stage, provider, _, handler = await _create(call_setup)
    try:
        # This turn has a completed provider semantic but is still waiting in
        # Agent handling when the next user speech interrupts it.
        await provider.emit(TurnCompleted(CallAudioSemantic(transcript="settled user fact")))
        await _eventually(lambda: 1 in stage._unfinished_turns)
        generation = stage._generation
        await provider.emit(SpeechStarted())
        await _eventually(lambda: stage._generation > generation)
        snapshot = stage._maintenance_snapshot()
        assert snapshot.completed_turns == ()
        assert 1 in stage._inputs.pending
    finally:
        await stage.terminate(CallEndReason.USER_HANGUP)
