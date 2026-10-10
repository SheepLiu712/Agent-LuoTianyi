"""Realtime call interaction coordinator.

The stage deliberately speaks only in Agent, ledger, provider, and transport
contracts.  Wire sequencing and provider SDK details belong to the adapter
and realtime-speech implementations respectively.
"""

from __future__ import annotations

import asyncio
import inspect
import math
import time
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo

import src.domain.agent as d
from src.agent.context import ContextFactory, InteractionContext
from src.domain.call import (
    CallEndReason,
    CallFinalSnapshot,
    CallFinalTurn,
    CallOutcome,
    CallReplyStatus,
    CallState,
    CallTerminalFacts,
)
from src.infrastructure.models.realtime_speech import (
    AmbientAudio,
    AudioFrame,
    ProviderFailed,
    RealtimeSpeechConfig,
    RealtimeSpeechSession,
    RealtimeSpeechSessionFactory,
    SpeechStarted,
    SpeechStopped,
    TurnCompleted,
)
from src.infrastructure.persistence.call_sessions.repository import CallSessionRecord, CallSessionRepository
from src.utils.owned_operation import complete_owned

from ._call_playback import CallPlaybackCoordinator, PlaybackCompletion, PlaybackSettlementError
from .call_lifecycle import CallLifecycle

if TYPE_CHECKING:
    from .stage_manager import CallStageOwnership


class CallTransportSink(Protocol):
    """Awaitable response-stream transport owned by the call adapter."""

    async def send_state(self, item: object) -> None: ...

    async def send_ended(self, snapshot: CallFinalSnapshot) -> None: ...

    async def send_failed(self, reason: CallEndReason) -> None: ...

    async def start_stream(self, response_id: str, stream_id: int, audio_format: d.AudioFormat) -> None: ...

    async def send_pcm(self, response_id: str, stream_id: int, payload: bytes, *, final: bool) -> None: ...

    async def stop_response(self, response_id: str, stream_ids: tuple[int, ...]) -> None: ...


class CallSettlementSink(Protocol):
    """Observes the immutable terminal snapshot for the later settlement lane."""

    async def emit(self, snapshot: CallFinalSnapshot) -> object: ...


@dataclass(frozen=True, slots=True)
class CallStateChanged:
    call_id: str
    state: CallState


@dataclass(frozen=True, slots=True)
class CallOutput:
    output: d.AgentOutput


@dataclass(frozen=True, slots=True)
class CallPlaybackStop:
    response_id: str
    stream_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class CallIngressReceipt:
    call_id: str
    direction: str
    seq: int
    fingerprint: bytes


@dataclass(slots=True)
class _Response:
    turn_seq: int | None
    provisional: bool
    generation: int
    stream_id: int | None = None
    message_completed: bool = False
    playback_completed: bool = False
    failed: bool = False
    settled: asyncio.Event | None = None


@dataclass(frozen=True, slots=True)
class _QueuedPlan:
    plan: d.ActionPlan
    token: d.CancellationToken
    turn_seq: int | None
    barriers: tuple[str, ...]


class _CallOutputPermit:
    def __init__(self, stage: "CallStage", response_ids: frozenset[str], generation: int) -> None:
        self._stage = stage
        self._response_ids = response_ids
        self._generation = generation

    def allows(self, response_id: str) -> bool:
        return (
            response_id in self._response_ids
            and self._generation == self._stage._generation
            and response_id not in self._stage._tombstones
            and self._stage.state not in {CallState.ENDING, CallState.ENDED, CallState.FAILED, CallState.DECLINED}
        )


@dataclass(slots=True)
class _Turn:
    semantic: str
    status: CallReplyStatus = CallReplyStatus.NOT_STARTED
    formal_text: str | None = None


class CallStage:
    """Owns one call's lifecycle, serial Agent plans, and temporary resources."""

    def __init__(
        self,
        *,
        ownership: CallStageOwnership,
        record: CallSessionRecord,
        agent: Any,
        context_factory: ContextFactory,
        call_sessions: CallSessionRepository,
        speech_factory: RealtimeSpeechSessionFactory,
        transport: CallTransportSink,
        release_ownership: Callable[[CallStageOwnership], bool] | None = None,
        settlement_sink: CallSettlementSink | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] | None = None,
        config: dict[str, object] | None = None,
    ) -> None:
        if str(record.call_id) != ownership.call_id:
            raise ValueError("call ownership does not match record")
        if record.user_id != ownership.user_id or record.character_id != ownership.character_id:
            raise ValueError("call ownership identity does not match record")
        self._ownership, self._record = ownership, record
        self._agent, self._context_factory, self._repository = agent, context_factory, call_sessions
        self._speech_factory, self._transport = speech_factory, transport
        self._release_ownership = release_ownership
        self._settlement_sink = settlement_sink
        self._monotonic = monotonic
        self._wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        settings = {} if config is None else config
        self._pcm_capacity = int(settings.get("pcm_queue_capacity", 64))
        self._receipt_capacity = int(settings.get("receipt_capacity", 4096))
        self._terminal_delivery_timeout = float(settings.get("terminal_delivery_timeout", 1.0))
        if self._pcm_capacity <= 0:
            raise ValueError("pcm_queue_capacity must be positive")
        if self._receipt_capacity <= 0:
            raise ValueError("receipt_capacity must be positive")
        if not math.isfinite(self._terminal_delivery_timeout) or self._terminal_delivery_timeout <= 0:
            raise ValueError("terminal_delivery_timeout must be positive and finite")
        self._lifecycle = CallLifecycle()
        self._context: InteractionContext | None = None
        self._provider: RealtimeSpeechSession | None = None
        self._pcm: asyncio.Queue[AudioFrame] = asyncio.Queue(self._pcm_capacity)
        self._receipts: OrderedDict[tuple[str, str, int], bytes] = OrderedDict()
        self._provider_audio_sequence = 0
        self._plans: deque[_QueuedPlan] = deque()
        self._request_tokens: set[d.CancellationToken] = set()
        self._handle_tasks: set[asyncio.Task[Any]] = set()
        self._execution_tokens: set[d.CancellationToken] = set()
        self._tasks: set[asyncio.Task[Any]] = set()
        self._pcm_task: asyncio.Task[Any] | None = None
        self._events_task: asyncio.Task[Any] | None = None
        self._realize_task: asyncio.Task[Any] | None = None
        self._recovery_task: asyncio.Task[Any] | None = None
        self._silence_task: asyncio.Task[Any] | None = None
        self._playback = CallPlaybackCoordinator(monotonic=monotonic)
        self._revision = 0
        self._turns: dict[int, _Turn] = {}
        self._unfinished_turns: set[int] = set()
        self._request_turn: dict[str, int | None] = {}
        self._started = False
        self._closed = asyncio.Event()
        self._final: CallFinalSnapshot | None = None
        self._active_response_id: str | None = None
        self._responses: dict[str, _Response] = {}
        self._tombstones: set[str] = set()
        self._generation = 0
        self._next_stream_id = 1
        self._pending_send = 0
        self._connected_monotonic: float | None = None
        self._first_disconnect_monotonic: float | None = None
        self._recovery_deadline: float | None = None
        self._pending_end_reason: CallEndReason | None = None
        self._ending_delivery = False
        self._ownership_released = False
        self._transition_lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()
        self._transport_abort_task: asyncio.Task[Any] | None = None
        self._aborting_transport = False

    @classmethod
    async def create(cls, **kwargs: object) -> "CallStage":
        stage = cls(**kwargs)
        await stage.start()
        return stage

    @property
    def state(self) -> CallState:
        return self._lifecycle.snapshot.state

    @property
    def context(self) -> InteractionContext | None:
        return self._context

    @property
    def snapshot(self) -> CallFinalSnapshot | None:
        return self._final

    @property
    def tasks(self) -> tuple[asyncio.Task[Any], ...]:
        return tuple(task for task in self._tasks if not task.done())

    async def start(self) -> None:
        """Create the ephemeral context and provider before publishing RINGING."""
        if self._started:
            return
        self._require_setup_time()
        try:
            requested_at = self._record.requested_at.replace(tzinfo=None)
            self._context = await self._await_setup(
                self._context_factory.create_call(
                    self._ownership.call_id,
                    user_id=self._record.user_id,
                    requested_at=requested_at,
                )
            )
            self._provider = await self._await_setup(self._speech_factory.create(self._record.call_id))
            await self._await_setup(self._provider.start(RealtimeSpeechConfig()))
            await self._transition(CallState.RINGING)
            self._started = True
            self._pcm_task = self._track(asyncio.create_task(self._drain_pcm(), name="call-pcm"))
            self._events_task = self._track(asyncio.create_task(self._consume_events(), name="call-speech-events"))
            await self._submit_stimulus(self._answer_requested())
        except BaseException:
            if self.state not in {CallState.ENDED, CallState.FAILED}:
                await self._fail_setup(
                    CallEndReason.SETUP_TIMEOUT if self._setup_expired() else CallEndReason.SYSTEM_FAILURE
                )
            raise

    def accept_pcm(self, receipt: CallIngressReceipt, payload: bytes) -> bool:
        """Accept one transport-ordered PCM frame without retaining its payload in receipts."""
        if not self._valid_pcm(receipt, payload):
            return False
        key = (receipt.call_id, receipt.direction, receipt.seq)
        prior = self._receipts.get(key)
        if prior is not None:
            self._receipts.move_to_end(key)
            return prior == receipt.fingerprint
        if self.state is not CallState.ACTIVE:
            return False
        self._provider_audio_sequence += 1
        try:
            self._pcm.put_nowait(AudioFrame(payload, "pcm_s16le", 16000, 1, self._provider_audio_sequence))
        except asyncio.QueueFull:
            self._provider_audio_sequence -= 1
            return False
        self._receipts[key] = receipt.fingerprint
        if len(self._receipts) > self._receipt_capacity:
            self._receipts.popitem(last=False)
        return True

    async def apply_answer(self, action: d.AnswerCall) -> bool:
        """Consume the Stage-owned answer action once it has been produced by Agent integration."""
        if not isinstance(action, d.AnswerCall) or action.call_id != self._record.call_id:
            return False
        if self.state is not CallState.RINGING:
            return False
        await self._apply_answer(action)
        return True

    def register_playback(self, response_id: str, stream_id: int) -> None:
        if response_id in self._tombstones:
            raise PlaybackSettlementError("interrupted response cannot register playback")
        self._playback.register_stream(response_id, stream_id)
        self._refresh_silence_task()

    def playback_final(self, response_id: str, stream_id: int) -> None:
        self._playback.mark_final_sent(response_id, stream_id)

    def playback_completed(self, response_id: str, stream_id: int) -> PlaybackCompletion:
        result = self._playback.complete_playback(response_id, stream_id)
        response = self._responses.get(response_id)
        if response is not None:
            response.playback_completed = True
        self._settle_response_if_complete(response_id)
        self._refresh_silence_task()
        self._finish_pending_end_if_ready()
        return result

    def playback_stopped(self, response_id: str, stream_id: int) -> bool:
        result = self._playback.settle_stopped_stream(response_id, stream_id)
        self._settle_response_if_complete(response_id)
        self._refresh_silence_task()
        self._finish_pending_end_if_ready()
        return result

    async def disconnect(self) -> None:
        async with self._lifecycle_lock:
            if self.state is not CallState.ACTIVE:
                return
            disconnected_at = self._now()
            disconnected_monotonic = self._monotonic()
            await self._transition_or_close(CallState.RECONNECTING, ledger_facts={"disconnected_at": disconnected_at})
            if self._first_disconnect_monotonic is None:
                self._first_disconnect_monotonic = disconnected_monotonic
            self._recovery_deadline = disconnected_monotonic + 3.0
            self._cancel_task(self._silence_task)
            self._recovery_task = self._track(asyncio.create_task(self._recover_deadline(), name="call-recovery"))

    async def resume(self) -> bool:
        async with self._lifecycle_lock:
            if self.state is not CallState.RECONNECTING:
                return False
            if self._recovery_deadline is None or self._monotonic() >= self._recovery_deadline:
                await self._terminate_locked(CallEndReason.RECOVERY_TIMEOUT)
                return False
            self._cancel_task(self._recovery_task)
            await self._transition_or_close(CallState.ACTIVE)
            self._first_disconnect_monotonic = None
            self._recovery_deadline = None
            # Product policy: a successful resume always starts a fresh full silence period.
            if self._playback.silence_started_at is None:
                try:
                    self._playback.restore_silence_after_reconnect(started_at=self._monotonic())
                except ValueError:
                    pass
            self._refresh_silence_task()
            return True

    async def terminate(self, reason: CallEndReason = CallEndReason.USER_HANGUP) -> CallFinalSnapshot | None:
        async with self._lifecycle_lock:
            return await self._terminate_locked(reason)

    async def _terminate_locked(self, reason: CallEndReason) -> CallFinalSnapshot | None:
        if self._final is not None:
            return self._final
        if self.state in {CallState.ENDED, CallState.FAILED}:
            return self._final
        self._interrupt()
        if self.state is CallState.RINGING and reason is CallEndReason.DECLINED:
            await self._transition_or_close(
                CallState.DECLINED,
                outcome=CallOutcome.DECLINED,
                end_reason=reason,
            )
            return await self._finish(CallOutcome.DECLINED, reason)
        if self.state is not CallState.ENDING and self.state is not CallState.DECLINED:
            await self._transition_or_close(CallState.ENDING)
        outcome = (
            CallOutcome.CONNECTED if self._lifecycle.snapshot.has_connected else CallOutcome.CANCELLED_BEFORE_ANSWER
        )
        return await self._finish(outcome, reason)

    async def wait_closed(self) -> CallFinalSnapshot | None:
        await self._closed.wait()
        return self._final

    async def close(self) -> CallFinalSnapshot | None:
        """Idempotently release a call whose owner is going away."""
        return await self.terminate(CallEndReason.SYSTEM_FAILURE)

    async def _consume_events(self) -> None:
        assert self._provider is not None
        async for event in self._provider.events():
            if self.state in {CallState.ENDED, CallState.FAILED}:
                return
            if isinstance(event, SpeechStarted):
                self._playback.set_user_speaking(True)
                self._interrupt()
            elif isinstance(event, SpeechStopped):
                self._playback.set_user_speaking(False)
                self._refresh_silence_task()
            elif isinstance(event, TurnCompleted):
                self._spawn_handle(self._on_turn(event), name="call-turn-handle")
            elif isinstance(event, ProviderFailed):
                await self.terminate(CallEndReason.PROVIDER_FAILED)
                return
            elif isinstance(event, AmbientAudio):
                continue

    async def _on_turn(self, event: TurnCompleted) -> None:
        if self.state is not CallState.ACTIVE:
            return
        sequence = len(self._turns) + 1
        self._turns[sequence] = _Turn(event.semantic.render())
        self._unfinished_turns.add(sequence)
        self._playback.set_unfinished_user_turn_count(len(self._unfinished_turns))
        stimulus = d.CallTurnCompleted(
            **self._stimulus_fields(), call_id=self._record.call_id, turn_seq=sequence, audio_content=event.semantic
        )
        await self._submit_stimulus(stimulus, turn_seq=sequence)

    async def _submit_stimulus(
        self,
        stimulus: d.Stimulus,
        turn_seq: int | None = None,
        *,
        allow_terminal: bool = False,
    ) -> None:
        if not allow_terminal and self.state in {
            CallState.ENDING,
            CallState.ENDED,
            CallState.FAILED,
            CallState.DECLINED,
        }:
            return
        token = d.CancellationToken()
        request_id = str(uuid4())
        self._request_tokens.add(token)
        self._request_turn[request_id] = turn_seq
        request = d.HandleStimulusRequest(
            request_id=request_id, stimulus=stimulus, interaction=self._agent_snapshot(), cancellation=token
        )
        sink = _PlanSink(self, request_id, token, turn_seq)
        try:
            await self._agent.handle_stimulus(request, sink, context=self._context)
        finally:
            self._request_tokens.discard(token)
            if turn_seq is not None and not sink.ids:
                self._finish_user_turn(turn_seq)

    def _enqueue_plan(self, plan: d.ActionPlan, token: d.CancellationToken, turn_seq: int | None) -> None:
        barriers = tuple(
            response_id
            for response_id, response in self._responses.items()
            if response.turn_seq == turn_seq and response.provisional and not response.playback_completed
        )
        for action in plan.actions:
            if isinstance(action, d.Say) and action.call_delivery.response_id is not None:
                self._responses[action.call_delivery.response_id] = _Response(
                    turn_seq=turn_seq,
                    provisional=action.call_delivery.provisional,
                    generation=self._generation,
                    settled=asyncio.Event(),
                )
        self._plans.append(_QueuedPlan(plan, token, turn_seq, barriers))
        if self._realize_task is None or self._realize_task.done():
            self._realize_task = self._track(asyncio.create_task(self._realize(), name="call-realize"))

    async def _realize(self) -> None:
        while self._plans and (
            self.state not in {CallState.ENDING, CallState.ENDED, CallState.FAILED} or self._ending_delivery
        ):
            queued = self._plans.popleft()
            if queued.token.is_cancelled:
                continue
            if queued.barriers and not await self._wait_response_barriers(queued.barriers, queued.token):
                continue
            await self._realize_plan(queued.plan, queued.turn_seq)

    async def _realize_plan(self, plan: d.ActionPlan, turn_seq: int | None) -> None:
        answer = next((action for action in plan.actions if isinstance(action, d.AnswerCall)), None)
        if answer is not None:
            await self._apply_answer(answer)
        ending = next((action for action in plan.actions if isinstance(action, d.EndCall)), None)
        if ending is not None:
            self._pending_end_reason = ending.reason
        execution_token = d.CancellationToken()
        self._execution_tokens.add(execution_token)
        self._playback.set_generation_count(1)
        response_ids = frozenset(
            action.call_delivery.response_id
            for action in plan.actions
            if isinstance(action, d.Say) and action.call_delivery.response_id is not None
        )
        context = d.ExecutionContext(
            execution_id=str(uuid4()),
            interaction_id=self._ownership.call_id,
            current_interaction_revision=self._revision,
            cancellation=execution_token,
            interaction_context=self._context,
            call_output_permit=_CallOutputPermit(self, response_ids, self._generation),
        )
        if turn_seq is not None and turn_seq in self._turns:
            self._turns[turn_seq].status = CallReplyStatus.NOT_STARTED
        try:
            report = await self._agent.realize_action_plan(plan, context, _OutputSink(self, context, turn_seq))
            if turn_seq is not None and report.status is not d.ExecutionStatus.COMPLETED:
                self._turns[turn_seq].status = CallReplyStatus.FAILED
        except asyncio.CancelledError:
            if turn_seq is not None:
                self._turns[turn_seq].status = CallReplyStatus.INTERRUPTED
            raise
        except Exception:
            if turn_seq is not None:
                self._turns[turn_seq].status = CallReplyStatus.FAILED
        finally:
            self._execution_tokens.discard(execution_token)
            self._playback.set_generation_count(0)
            if turn_seq is not None and not self._turn_has_unsettled_response(turn_seq):
                self._finish_user_turn(turn_seq)
            self._refresh_silence_task()
            self._finish_pending_end_if_ready()

    async def _apply_answer(self, action: d.AnswerCall) -> None:
        if action.call_id != self._record.call_id or self.state is not CallState.RINGING:
            return
        if action.decision.value == "decline":
            await self.terminate(CallEndReason.DECLINED)
            return
        connected_at = self._now()
        await self._transition_or_close(CallState.ACTIVE, ledger_facts={"connected_at": connected_at})
        self._connected_monotonic = self._monotonic()
        if not self._started:
            return
        await self._submit_stimulus(
            d.CallStarted(**self._stimulus_fields(), call_id=self._record.call_id, connected_at=connected_at)
        )

    async def _drain_pcm(self) -> None:
        while True:
            frame = await self._pcm.get()
            try:
                if self.state is CallState.ACTIVE and self._provider is not None:
                    await self._provider.push_audio(frame)
            finally:
                self._pcm.task_done()

    async def _recover_deadline(self) -> None:
        deadline = self._recovery_deadline
        if deadline is None:
            return
        await asyncio.sleep(max(0.0, deadline - self._monotonic()))
        async with self._lifecycle_lock:
            if (
                self.state is CallState.RECONNECTING
                and self._recovery_deadline == deadline
                and self._monotonic() >= deadline
            ):
                await self._terminate_locked(CallEndReason.RECOVERY_TIMEOUT)

    def _refresh_silence_task(self) -> None:
        self._cancel_task(self._silence_task)
        if self.state is CallState.ACTIVE and self._playback.silence_started_at is not None:
            self._silence_task = self._track(asyncio.create_task(self._await_silence(), name="call-silence"))

    async def _await_silence(self) -> None:
        await asyncio.sleep(5.0)
        if self.state is CallState.ACTIVE and self._playback.silence_elapsed():
            await self._submit_stimulus(
                d.CallSilenceElapsed(**self._stimulus_fields(), call_id=self._record.call_id, silence_ms=5000)
            )

    async def _transition(
        self,
        state: CallState,
        *,
        outcome: CallOutcome | None = None,
        end_reason: CallEndReason | None = None,
        ledger_facts: dict[str, object] | None = None,
        publish: bool = True,
    ) -> None:
        async with self._transition_lock:
            lifecycle = CallLifecycle()
            lifecycle._snapshot = self._lifecycle.snapshot
            snapshot = lifecycle.transition(state, outcome=outcome, end_reason=end_reason)
            changes: dict[str, object] = {"state": state, "updated_at": self._now()}
            if outcome is not None:
                changes["outcome"] = outcome
            if end_reason is not None:
                changes["end_reason"] = end_reason
            if ledger_facts:
                changes.update(ledger_facts)
            if state is CallState.ENDED:
                changes["ended_at"] = self._now()
            updated = self._record.with_update(**changes)
            changed = await complete_owned(
                asyncio.to_thread(
                    self._repository.update_if_state,
                    self._record.call_id,
                    expected_state=self._record.state,
                    record=updated,
                )
            )
        if not changed:
            persisted = await complete_owned(asyncio.to_thread(self._repository.find_by_id, self._record.call_id))
            if persisted is None or self._record_identity(persisted) != self._record_identity(self._record):
                raise RuntimeError("call ledger identity changed during CAS failure")
            raise RuntimeError("call ledger CAS failed")
        self._record = updated
        self._lifecycle._snapshot = snapshot
        self._playback.set_call_state(snapshot.state)
        if publish:
            try:
                await self._transport.send_state(CallStateChanged(self._ownership.call_id, state))
            except BaseException:
                if snapshot.has_connected and self._final is None:
                    self._request_transport_abort()
                raise

    async def _transition_or_close(self, state: CallState, **facts: object) -> None:
        await self._transition(state, **facts)

    async def _finish(self, outcome: CallOutcome, reason: CallEndReason) -> CallFinalSnapshot:
        try:
            ended = self._now()
            duration = self._active_duration_ms(ended)
            terminal_facts = {"ended_at": ended, "active_duration_ms": duration}
            if self.state is CallState.DECLINED:
                await self._transition(CallState.ENDED, outcome=outcome, end_reason=reason, ledger_facts=terminal_facts)
            elif self.state is CallState.ENDING:
                await self._transition(CallState.ENDED, outcome=outcome, end_reason=reason, ledger_facts=terminal_facts)
            terminal = CallTerminalFacts(self._record.call_id, outcome, reason, duration, ended)
            completed = tuple(
                CallFinalTurn(seq, turn.semantic, turn.status, turn.formal_text)
                for seq, turn in sorted(self._turns.items())
            )
            self._final = CallFinalSnapshot(terminal, completed, self._record.maintenance_turn_seq)
        except BaseException:
            await self._cleanup()
            raise
        self._ending_delivery = True
        ending_error: BaseException | None = None
        try:
            await self._submit_stimulus(
                d.CallEnding(
                    **self._stimulus_fields(),
                    call_id=self._record.call_id,
                    reason=reason,
                    final_snapshot=self._final,
                ),
                allow_terminal=True,
            )
            if self._realize_task is not None:
                await asyncio.gather(self._realize_task, return_exceptions=True)
        except BaseException as error:
            ending_error = error
        finally:
            self._ending_delivery = False
        cleanup_error = await self._cleanup()
        if self._settlement_sink is not None:
            try:
                await self._settlement_sink.emit(self._final)
            except BaseException as error:
                ending_error = ending_error or error
        await self._send_terminal_best_effort(self._final)
        ending_error = ending_error or cleanup_error
        if ending_error is not None:
            raise ending_error
        return self._final

    async def _send_terminal_best_effort(self, snapshot: CallFinalSnapshot) -> None:
        """Bound terminal delivery after realtime cleanup and settlement admission.

        Cancellation cannot retract bytes already written by a transport, so the
        binding remains responsible for terminal idempotency.
        """
        task = asyncio.create_task(self._transport.send_ended(snapshot), name="call-terminal-delivery")
        try:
            await asyncio.wait_for(task, timeout=self._terminal_delivery_timeout)
        except TimeoutError:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        except Exception:
            await asyncio.gather(task, return_exceptions=True)
        except asyncio.CancelledError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise

    async def _fail_setup(self, reason: CallEndReason) -> None:
        """Persist a non-recordable setup failure and release all runtime resources."""
        self._interrupt()
        await self._transition(CallState.FAILED, end_reason=reason, publish=False)
        cleanup_error = await self._cleanup()
        try:
            await self._transport.send_failed(reason)
        except BaseException:
            pass
        if cleanup_error is not None:
            raise cleanup_error

    def _interrupt(self) -> None:
        self._generation += 1
        for token in self._request_tokens:
            token.cancel(d.CancellationReason.SUPERSEDED)
        for token in self._execution_tokens:
            token.cancel(d.CancellationReason.SUPERSEDED)
        affected = {
            response_id
            for response_id, response in self._responses.items()
            if not response.playback_completed and not response.failed
        }
        if self._active_response_id is not None:
            affected.add(self._active_response_id)
        for affected_response in affected:
            self._tombstones.add(affected_response)
            response = self._responses.get(affected_response)
            turn_seq = response.turn_seq if response is not None else None
            if turn_seq is not None and turn_seq in self._turns:
                self._turns[turn_seq].status = CallReplyStatus.INTERRUPTED
            stream_ids = tuple(
                stream_id
                for response_id, stream_id in self._playback.pending_streams
                if response_id == affected_response
            )
            if response is not None:
                response.failed = True
                if not stream_ids and response.settled is not None:
                    response.settled.set()
            task = self._track(
                asyncio.create_task(self._stop_response(affected_response, stream_ids), name="call-playback-stop")
            )
            task.add_done_callback(self._observe_task)
        self._plans.clear()
        for task in tuple(self._handle_tasks):
            self._cancel_task(task)
        self._cancel_task(self._realize_task)

    async def _cleanup(self) -> BaseException | None:
        current = asyncio.current_task()
        pending = tuple(task for task in self._tasks if task is not current and not task.done())
        for task in pending:
            self._cancel_task(task)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        cleanup_error = await self._close_resources()
        while not self._pcm.empty():
            try:
                self._pcm.get_nowait()
                self._pcm.task_done()
            except asyncio.QueueEmpty:
                break
        self._playback.close()
        self._receipts.clear()
        self._turns.clear()
        self._unfinished_turns.clear()
        self._responses.clear()
        if self._release_ownership is not None and not self._ownership_released:
            try:
                self._ownership_released = self._release_ownership(self._ownership)
            except BaseException as error:
                cleanup_error = cleanup_error or error
        self._closed.set()
        return cleanup_error

    async def _close_resources(self) -> BaseException | None:
        cleanup_error: BaseException | None = None
        if self._provider is not None:
            try:
                await self._provider.close()
            except BaseException as error:
                cleanup_error = error
            finally:
                self._provider = None
        if self._context is not None:
            try:
                await self._context.close()
            except BaseException as error:
                cleanup_error = cleanup_error or error
            finally:
                self._context = None
        return cleanup_error

    def _answer_requested(self) -> d.CallAnswerRequested:
        return d.CallAnswerRequested(
            **self._stimulus_fields(), call_id=self._record.call_id, requested_at=self._record.requested_at
        )

    def _agent_snapshot(self) -> d.CallInteractionSnapshot:
        return d.CallInteractionSnapshot(
            interaction_id=self._ownership.call_id,
            interaction_revision=self._revision,
            user_id=self._record.user_id,
            pending_stimuli=(),
            now=self._now(),
            timezone=ZoneInfo("Asia/Shanghai"),
            supported_outputs=frozenset(d.AgentOutputKind),
            call_id=self._record.call_id,
            state=self.state,
            connection_state=(
                d.ConnectionState.CONNECTED if self.state is CallState.ACTIVE else d.ConnectionState.DISCONNECTED
            ),
        )

    def _stimulus_fields(self) -> dict[str, object]:
        return {
            "stimulus_id": str(uuid4()),
            "schema_version": 1,
            "occurred_at": self._now(),
            "source": d.StimulusSource.STAGE,
            "target_character_ids": (self._record.character_id,),
            "user_id": self._record.user_id,
            "ephemeral": True,
        }

    def _require_setup_time(self) -> None:
        if self._setup_expired():
            raise TimeoutError("call setup deadline elapsed")

    async def _await_setup(self, awaitable: Awaitable[Any]) -> Any:
        remaining = self._ownership.setup_deadline - self._monotonic()
        if remaining <= 0:
            if inspect.iscoroutine(awaitable):
                awaitable.close()
            raise TimeoutError("call setup deadline elapsed")
        try:
            return await asyncio.wait_for(awaitable, timeout=remaining)
        except asyncio.TimeoutError:
            raise TimeoutError("call setup deadline elapsed") from None

    def _setup_expired(self) -> bool:
        return self._monotonic() >= self._ownership.setup_deadline

    def _now(self) -> datetime:
        value = self._wall_clock()
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

    def _active_duration_ms(self, ended: datetime) -> int:
        _ = ended
        if self._connected_monotonic is None:
            return 0
        stop = self._first_disconnect_monotonic or self._monotonic()
        return max(0, int((stop - self._connected_monotonic) * 1000))

    @staticmethod
    def _valid_pcm(receipt: CallIngressReceipt, payload: bytes) -> bool:
        return (
            isinstance(receipt, CallIngressReceipt)
            and bool(receipt.call_id)
            and receipt.direction == "client_to_server"
            and type(receipt.seq) is int
            and receipt.seq > 0
            and isinstance(receipt.fingerprint, bytes)
            and len(receipt.fingerprint) == 32
            and isinstance(payload, bytes)
            and bool(payload)
            and len(payload) % 2 == 0
        )

    async def _stop_response(self, response_id: str, stream_ids: tuple[int, ...]) -> None:
        if stream_ids:
            await self._transport_send(self._transport.stop_response(response_id, stream_ids))
            return
        self._settle_response_if_complete(response_id)

    async def _transport_send(self, operation: Awaitable[None]) -> None:
        try:
            await operation
        except BaseException:
            if self._lifecycle.snapshot.has_connected and self._final is None:
                self._request_transport_abort()
            raise

    def _request_transport_abort(self) -> None:
        if self._aborting_transport or self._final is not None:
            return
        self._aborting_transport = True
        task = self._track(asyncio.create_task(self._abort_transport(), name="call-transport-abort"))
        self._transport_abort_task = task
        task.add_done_callback(self._observe_task)

    async def _abort_transport(self) -> None:
        try:
            await self.terminate(CallEndReason.SYSTEM_FAILURE)
        finally:
            self._aborting_transport = False

    @staticmethod
    def _observe_task(task: asyncio.Task[Any]) -> None:
        if task.cancelled():
            return
        task.exception()

    def _track(self, task: asyncio.Task[Any]) -> asyncio.Task[Any]:
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _spawn_handle(self, awaitable: Awaitable[None], *, name: str) -> None:
        task = self._track(asyncio.create_task(awaitable, name=name))
        self._handle_tasks.add(task)
        task.add_done_callback(self._handle_tasks.discard)

    def _finish_pending_end_if_ready(self) -> None:
        if (
            self._pending_end_reason is None
            or self._playback.pending_streams
            or self._execution_tokens
            or any(not response.playback_completed and not response.failed for response in self._responses.values())
        ):
            return
        reason = self._pending_end_reason
        self._pending_end_reason = None
        task = self._track(asyncio.create_task(self.terminate(reason), name="call-agent-end"))
        task.add_done_callback(self._observe_task)

    def _settle_response_if_complete(self, response_id: str) -> None:
        if any(item_response == response_id for item_response, _ in self._playback.pending_streams):
            return
        response = self._responses.get(response_id)
        if response is not None:
            response.playback_completed = True
            if response.settled is not None:
                response.settled.set()
            if response.turn_seq is not None and not response.provisional:
                turn = self._turns[response.turn_seq]
                turn.status = CallReplyStatus.COMPLETED if turn.formal_text else CallReplyStatus.FAILED
                if not self._turn_has_unsettled_response(response.turn_seq):
                    self._finish_user_turn(response.turn_seq)
        if self._active_response_id == response_id:
            self._active_response_id = None

    def _finish_user_turn(self, turn_seq: int) -> None:
        self._unfinished_turns.discard(turn_seq)
        self._playback.set_unfinished_user_turn_count(len(self._unfinished_turns))

    def _turn_has_unsettled_response(self, turn_seq: int) -> bool:
        return any(
            response.turn_seq == turn_seq and not response.playback_completed and not response.failed
            for response in self._responses.values()
        )

    async def _wait_response_barriers(self, response_ids: tuple[str, ...], token: d.CancellationToken) -> bool:
        for response_id in response_ids:
            response = self._responses.get(response_id)
            if response is None or response.settled is None:
                continue
            while not response.settled.is_set():
                if token.is_cancelled or response.generation != self._generation:
                    return False
                try:
                    await asyncio.wait_for(response.settled.wait(), timeout=0.05)
                except asyncio.TimeoutError:
                    continue
        return not token.is_cancelled

    @staticmethod
    def _record_identity(record: CallSessionRecord) -> tuple[object, ...]:
        return (
            record.call_id,
            record.client_request_id,
            record.user_id,
            record.character_id,
            record.requested_at,
            record.created_at,
        )

    @staticmethod
    def _cancel_task(task: asyncio.Task[Any] | None) -> None:
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()


class _PlanSink:
    def __init__(self, stage: CallStage, request_id: str, token: d.CancellationToken, turn_seq: int | None) -> None:
        self._stage, self._request_id, self._token, self._turn_seq, self._ids = stage, request_id, token, turn_seq, []

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(self._ids)

    async def emit(self, plan: d.ActionPlan) -> d.PlanReceipt:
        if (
            self._token.is_cancelled
            or plan.origin_request_id != self._request_id
            or plan.interaction_id != self._stage._ownership.call_id
            or plan.plan_ordinal != len(self._ids)
        ):
            raise d.SinkRejectedError("stale or invalid call plan", code=d.SinkRejectionCode.IDENTITY_MISMATCH)
        self._ids.append(plan.plan_id)
        self._stage._enqueue_plan(plan, self._token, self._turn_seq)
        return d.PlanReceipt(plan_id=plan.plan_id, status=d.PlanAcceptanceStatus.ACCEPTED)


class _OutputSink:
    def __init__(self, stage: CallStage, context: d.ExecutionContext, turn_seq: int | None) -> None:
        self._stage, self._context, self._turn_seq = stage, context, turn_seq

    async def emit(self, output: d.AgentOutput) -> d.OutputReceipt:
        response_id = self._validate(output)
        self._capture_text(output)
        await self._deliver(output, response_id)
        return d.OutputReceipt(
            execution_id=output.execution_id, sequence_no=output.sequence_no, status=d.OutputAcceptanceStatus.ACCEPTED
        )

    def _validate(self, output: d.AgentOutput) -> str | None:
        if (
            self._stage.state in {CallState.ENDING, CallState.ENDED, CallState.FAILED, CallState.DECLINED}
            or output.execution_id != self._context.execution_id
            or self._context.cancellation.is_cancelled
        ):
            raise d.SinkRejectedError("stale call output", code=d.SinkRejectionCode.STALE_INTERACTION)
        response_id = output.call_delivery.response_id
        if response_id is not None and response_id in self._stage._tombstones:
            raise d.SinkRejectedError("response was interrupted", code=d.SinkRejectionCode.STALE_INTERACTION)
        if response_id is not None:
            self._stage._active_response_id = response_id
            response = self._stage._responses.get(response_id)
            if response is None or response.generation != self._stage._generation:
                raise d.SinkRejectedError("response permit is stale", code=d.SinkRejectionCode.STALE_INTERACTION)

        return response_id

    def _capture_text(self, output: d.AgentOutput) -> None:
        if (
            self._turn_seq is not None
            and isinstance(output, d.TextFinalOutput)
            and not output.call_delivery.provisional
        ):
            turn = self._stage._turns[self._turn_seq]
            turn.formal_text = output.text

    async def _deliver(self, output: d.AgentOutput, response_id: str | None) -> None:
        if isinstance(output, d.AudioChunkOutput):
            if output.framing is not d.AudioFraming.RAW_PCM or output.audio_format != d.CALL_PCM_FORMAT:
                raise d.SinkRejectedError(
                    "CALL audio must be canonical PCM", code=d.SinkRejectionCode.UNSUPPORTED_OUTPUT
                )
            assert response_id is not None
            await self._send_audio(response_id, output)
        elif isinstance(output, d.MessageEndOutput):
            if response_id is not None:
                response = self._stage._responses[response_id]
                response.message_completed = output.status is d.MessageEndStatus.COMPLETED
                if not response.message_completed:
                    self._stage._tombstones.add(response_id)
                    response.failed = True
                    stream_ids = (response.stream_id,) if response.stream_id is not None else ()
                    if stream_ids:
                        await self._stage._transport_send(self._stage._transport.stop_response(response_id, stream_ids))
                    elif response.settled is not None:
                        response.settled.set()
        elif isinstance(output, d.ExpressionOutput):
            await self._stage._transport_send(self._stage._transport.send_state(CallOutput(output)))

    async def _send_audio(self, response_id: str, output: d.AudioChunkOutput) -> None:
        response = self._stage._responses[response_id]
        if response.stream_id is None:
            response.stream_id = self._stage._next_stream_id
            self._stage._next_stream_id += 1
            self._stage.register_playback(response_id, response.stream_id)
            await self._stage._transport_send(
                self._stage._transport.start_stream(response_id, response.stream_id, output.audio_format)
            )
        self._stage._pending_send += 1
        self._stage._playback.set_pending_send_count(self._stage._pending_send)
        try:
            await self._stage._transport_send(
                self._stage._transport.send_pcm(response_id, response.stream_id, output.data, final=output.final)
            )
        finally:
            self._stage._pending_send -= 1
            self._stage._playback.set_pending_send_count(self._stage._pending_send)
        if output.final:
            self._stage.playback_final(response_id, response.stream_id)
