import asyncio
import hashlib
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from support.realtime_speech import FakeRealtimeSpeechSessionFactory

import src.domain.agent as d
from src.agent.context import ContextFactory
from src.agent.facade import Agent
from src.agent.handlers.action.router import ActionRouter
from src.agent.handlers.stimulus.router import StimulusRouter
from src.agent.processing.output_drafts import AudioChunkDraft, MessageEndDraft, TextFinalDraft
from src.agent.processing.plan_emitter import ActionPlanDraft
from src.domain.call import (
    CallAnswerDecision,
    CallAudioSemantic,
    CallEndReason,
    CallOutcome,
    CallReplyStatus,
    CallSpeechDelivery,
    CallState,
)
from src.infrastructure.models.realtime_speech import SpeechStarted, TurnCompleted, TurnInvalid
from src.infrastructure.persistence.call_sessions import (
    BEIJING_TIMEZONE,
    CallSessionRecord,
    SqlCallSessionRepository,
)
from src.infrastructure.persistence.database.sql_database import Base
from src.stage.call_stage import CallIngressReceipt, CallStage, CallStateChanged
from src.stage.stage_manager import CallStageOwnership


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


def _report(request, plans):
    return d.HandlingReport(
        request_id=request.request_id,
        request_status=d.HandlingRequestStatus.COMPLETED,
        trigger_stimulus_id=request.stimulus.stimulus_id,
        basis_interaction_revision=request.interaction.interaction_revision,
        considered_pending_stimulus_ids=(),
        consumed_pending_stimulus_ids=(),
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

    async def handle(self, request, plans):
        await self.gate.wait()
        response_id = f"response-{request.stimulus.turn_seq}"
        await plans.emit(
            ActionPlanDraft(
                source_stimulus_ids=(request.stimulus.stimulus_id,),
                actions=(
                    d.Say(
                        action_id=f"{request.request_id}-say",
                        content="正式回答",
                        sound_content=None,
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


def _agent(turn_handler):
    no_plan = _NoPlanHandler()
    return Agent(
        character_id="luotianyi",
        stimulus_router=StimulusRouter(
            (
                (d.StimulusKind.CALL_ANSWER_REQUESTED, _AnswerHandler()),
                (d.StimulusKind.CALL_STARTED, no_plan),
                (d.StimulusKind.CALL_TURN_COMPLETED, turn_handler),
                (d.StimulusKind.CALL_SILENCE_ELAPSED, no_plan),
                (d.StimulusKind.CALL_ENDING, no_plan),
            )
        ),
        action_router=ActionRouter(
            (
                (d.ActionKind.ANSWER_CALL, _NoOutputActionHandler()),
                (d.ActionKind.SAY, _SayHandler()),
            )
        ),
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


async def _create(call_setup, *, decision=CallAnswerDecision.ACCEPT, config=None, release=None):
    repository, record, ownership, clock = call_setup
    speech = FakeRealtimeSpeechSessionFactory()
    transport = _Transport()
    turn_handler = _TurnHandler()
    context_factory = ContextFactory(character_id="luotianyi", database=_ContextDatabase())
    stage = await CallStage.create(
        ownership=ownership,
        record=record,
        agent=_agent(turn_handler),
        context_factory=context_factory,
        call_sessions=repository,
        speech_factory=speech,
        transport=transport,
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
    await stage.wait_closed()

    assert stage.snapshot.terminal.outcome is CallOutcome.DECLINED
    assert stage.snapshot.terminal.active_duration_ms == 0

    repository, record, ownership, clock = call_setup
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
        await CallStage.create(
            ownership=expired,
            record=second,
            agent=_agent(_TurnHandler()),
            context_factory=ContextFactory(character_id="luotianyi", database=_ContextDatabase()),
            call_sessions=repository,
            speech_factory=FakeRealtimeSpeechSessionFactory(),
            transport=_Transport(),
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
async def test_failed_terminal_delivery_cannot_hold_realtime_resources_or_skip_settlement(call_setup):
    repository, record, ownership, clock = call_setup
    speech = FakeRealtimeSpeechSessionFactory()
    transport = _FailingTransport("ended")
    released = []
    settled = []

    class Settlement:
        async def emit(self, snapshot):
            settled.append(snapshot)

    stage = await CallStage.create(
        ownership=ownership,
        record=record,
        agent=_agent(_TurnHandler()),
        context_factory=ContextFactory(character_id="luotianyi", database=_ContextDatabase()),
        call_sessions=repository,
        speech_factory=speech,
        transport=transport,
        release_ownership=lambda value: not released.append(value),
        settlement_sink=Settlement(),
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
async def test_blocked_terminal_delivery_is_bounded_after_settlement_admission(call_setup):
    repository, record, ownership, clock = call_setup
    speech = FakeRealtimeSpeechSessionFactory()
    transport = _BlockingTerminalTransport()
    released = []
    settled = []

    class Settlement:
        async def emit(self, snapshot):
            settled.append(snapshot)

    stage = await CallStage.create(
        ownership=ownership,
        record=record,
        agent=_agent(_TurnHandler()),
        context_factory=ContextFactory(character_id="luotianyi", database=_ContextDatabase()),
        call_sessions=repository,
        speech_factory=speech,
        transport=transport,
        release_ownership=lambda value: not released.append(value),
        settlement_sink=Settlement(),
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
        await CallStage.create(
            ownership=ownership,
            record=record,
            agent=_agent(_TurnHandler()),
            context_factory=ContextFactory(character_id="luotianyi", database=_ContextDatabase()),
            call_sessions=repository,
            speech_factory=_BlockingProviderFactory(),
            transport=_Transport(),
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
