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
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import src.domain.agent as d
from src.agent.context import ContextFactory, ConversationMode, InteractionContext
from src.domain.call import (
    CallEndingResult,
    CallEndReason,
    CallFinalSnapshot,
    CallFinalTurn,
    CallOutcome,
    CallReplyStatus,
    CallState,
    CallTerminalFacts,
    fallback_call_summary,
)
from src.domain.call.contracts import CallMaintenanceSnapshot
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
    TurnInvalid,
)
from src.infrastructure.observability.call_metrics import (
    CallMetric,
    CallMetricName,
    CallMetricResult,
    CallMetricStatus,
    CallProvider,
)
from src.infrastructure.persistence.call_sessions.repository import CallSessionRecord, CallSessionRepository
from src.utils.logger import get_logger
from src.utils.owned_operation import complete_owned

from ._call_history import CallHistory
from ._call_playback import CallPlaybackCoordinator, PlaybackCompletion, PlaybackSettlementError
from ._call_records import PreparedCall
from .call_lifecycle import CallLifecycle


def bind_call_stage_creator(
    *,
    get_agent,
    get_context_factory,
    call_sessions,
    conversation_service,
    call_maintenance_batches,
    speech_factory,
    output_sink,
    call_metrics=None,
    monotonic=time.monotonic,
    wall_clock=None,
) -> Callable[..., Awaitable[CallStage]] | None:
    """预绑定固定资源；缺少创建或结算依赖时返回 None，禁止通话接入。"""
    required = (
        get_agent,
        get_context_factory,
        call_sessions,
        conversation_service,
        call_maintenance_batches,
        speech_factory,
        output_sink,
    )
    if any(resource is None for resource in required):
        return None

    async def _create(prepared: PreparedCall, **lifecycle) -> CallStage:
        return await CallStage.create(
            record=prepared._record,
            agent=get_agent(prepared.character_id),
            context_factory=get_context_factory(prepared.character_id),
            call_sessions=call_sessions,
            conversation_service=conversation_service,
            call_maintenance_batches=call_maintenance_batches,
            speech_factory=speech_factory,
            output_sink=output_sink,
            call_metrics=call_metrics,
            monotonic=monotonic,
            wall_clock=wall_clock,
            **lifecycle,
        )

    return _create


@dataclass(frozen=True, slots=True)
class CallStageOwnership:
    """一次通话的交互身份、原建立期限和所有权代次。"""

    call_id: str
    user_id: str
    character_id: str
    client_request_id: str
    setup_deadline: float
    generation: int


@dataclass(frozen=True, slots=True)
class CallStateChanged:
    call_id: str
    state: CallState
    client_request_id: str
    connected_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CallReplyFailed:
    call_id: str


@dataclass(frozen=True, slots=True)
class CallOutput:
    output: d.AgentOutput


@dataclass(frozen=True, slots=True)
class CallPlaybackStop:
    response_id: str
    stream_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class CallStreamStarted:
    """声明业务音频流及其格式，不包含传输序号。"""

    response_id: str
    stream_id: int
    audio_format: d.AudioFormat


@dataclass(frozen=True, slots=True)
class CallPCM:
    """一段待交付的音频内容及业务流身份。"""

    response_id: str
    stream_id: int
    payload: bytes
    final: bool


@dataclass(frozen=True, slots=True)
class CallSetupFailed:
    """建立失败的稳定业务原因。"""

    reason: CallEndReason


CallStageOutput = (
    CallStateChanged
    | CallReplyFailed
    | CallOutput
    | CallFinalSnapshot
    | CallStreamStarted
    | CallPCM
    | CallPlaybackStop
    | CallSetupFailed
)


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
    audio_started_at: float | None = None
    formal_text: str | None = None
    request_id: str | None = None


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
    started_at: float = 0.0
    started_at_timestamp: str = ""
    first_audio_recorded: bool = False
    first_audio_disqualified: bool = False


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
        output_sink: Callable[[str, CallStageOutput], Awaitable[None]],
        release_ownership: Callable[[CallStageOwnership], bool] | None = None,
        save_history: Callable[..., Awaitable[object]] | None = None,
        own_termination: Callable[..., asyncio.Task] | None = None,
        retention_changed: Callable[[float | None], None] | None = None,
        call_metrics: Any | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] | None = None,
        config: dict[str, object] | None = None,
        connection_available: bool = True,
    ) -> None:
        if str(record.call_id) != ownership.call_id:
            raise ValueError("call ownership does not match record")
        if record.user_id != ownership.user_id or record.character_id != ownership.character_id:
            raise ValueError("call ownership identity does not match record")
        self._ownership, self._record = ownership, record
        self._agent, self._context_factory, self._repository = agent, context_factory, call_sessions
        self._speech_factory, self._output_sink = speech_factory, output_sink
        self._release_ownership = release_ownership
        self._save_history = save_history
        self._own_termination = own_termination
        self._retention_changed = retention_changed
        self._realtime_ended = asyncio.Event()
        self._call_metrics = call_metrics
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
        self._pcm_buffered_bytes = 0
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
        self._silence_task: asyncio.Task[Any] | None = None
        self._playback = CallPlaybackCoordinator(monotonic=monotonic)
        self._revision = 0
        self._turns: dict[int, _Turn] = {}
        self._reply_failures = 0
        self._failed_reply_requests: set[str] = set()
        self._unfinished_turns: set[int] = set()
        self._request_turn: dict[str, int | None] = {}
        self._started = False
        self._initialization: asyncio.Task[None] | None = None
        self._termination: asyncio.Task[CallFinalSnapshot | None] | None = None
        self._termination_reason: CallEndReason | None = None
        self._closed = asyncio.Event()
        self._final: CallFinalSnapshot | None = None
        self._active_response_id: str | None = None
        self._responses: dict[str, _Response] = {}
        self._tombstones: set[str] = set()
        self._generation = 0
        self._active_speech_item_id: str | None = None
        self._next_stream_id = 1
        self._pending_send = 0
        self._connected_monotonic: float | None = None
        self._first_disconnect_monotonic: float | None = None
        self._recovery_deadline: float | None = None
        self._pending_end_reason: CallEndReason | None = None
        self._ownership_released = False
        self._transition_lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()
        self._transport_abort_task: asyncio.Task[Any] | None = None
        self._aborting_transport = False
        self._reconnect_count = 0
        self._connection_available = connection_available
        self._pending_answer: d.AnswerCall | None = None

    @classmethod
    async def create(cls, *, conversation_service, call_maintenance_batches, **kwargs: object) -> "CallStage":
        """装配本次结算并返回 PREPARING Stage；握手排队后才启动耗时初始化。"""
        stage = cls(**kwargs)
        history = CallHistory(
            call_sessions=stage._repository,
            conversation_service=conversation_service,
            call_metrics=stage._call_metrics,
        )
        stage._save_history = history.save
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

    @property
    def termination_requested(self) -> bool:
        return self._termination_reason is not None

    @property
    def call_id(self) -> str:
        """返回本次呼叫稳定的身份。"""
        return str(self._record.call_id)

    @property
    def user_id(self) -> str:
        """返回呼叫所属用户。"""
        return self._record.user_id

    @property
    def character_id(self) -> str:
        """返回呼叫所属角色。"""
        return self._record.character_id

    @property
    def client_request_id(self) -> str:
        """返回原始建立请求身份，重连不产生新请求。"""
        return self._ownership.client_request_id

    def begin_initialization(self) -> None:
        """握手排队后启动自有初始化任务；不阻塞挂断或断线处理。"""
        if self._initialization is None and not self.termination_requested and not self._closed.is_set():
            self._initialization = asyncio.create_task(self._start(), name=f"call-initialize-{self.call_id}")
            self._initialization.add_done_callback(self._observe_task)

    async def start(self) -> None:
        """启动并等待资源准备；生产接入使用异步初始化入口。"""
        self.begin_initialization()
        if self._initialization is not None:
            await asyncio.shield(self._initialization)

    def can_reconnect(self) -> bool:
        """检查准备期原期限或接通后恢复期限，不改变交互状态。"""
        if self.termination_requested or self._closed.is_set():
            return False
        if self.state in {CallState.PREPARING, CallState.RINGING}:
            return not self._setup_expired()
        return self.can_resume()

    async def reconnect(self) -> bool:
        """实际绑定时重新校验业务期限，恢复连接而不重新初始化。"""
        if not self.can_reconnect():
            return False
        if self.state in {CallState.PREPARING, CallState.RINGING}:
            await self.set_connection_available(True)
            return True
        return await self.resume()

    async def _start(self) -> None:
        try:
            self._require_setup_time()
            requested_at = self._record.requested_at.replace(tzinfo=None)
            self._context = await self._await_setup(
                self._context_factory.create(
                    self._ownership.call_id,
                    mode=ConversationMode.CALL,
                    user_id=self._record.user_id,
                    requested_at=requested_at,
                ),
                cleanup=lambda context: context.close(),
            )
            self._provider = await self._await_setup(
                self._speech_factory.create(self._record.call_id), cleanup=lambda provider: provider.close()
            )
            await self._await_setup(self._provider.start(RealtimeSpeechConfig()))
            await self._transition(CallState.RINGING)
            self._started = True
            self._pcm_task = self._track(asyncio.create_task(self._drain_pcm(), name="call-pcm"))
            self._events_task = self._track(asyncio.create_task(self._consume_events(), name="call-speech-events"))
            await self._submit_stimulus(self._answer_requested())
        except asyncio.CancelledError:
            raise
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
        self._pcm_buffered_bytes += len(payload)
        self._receipts[key] = receipt.fingerprint
        if len(self._receipts) > self._receipt_capacity:
            self._receipts.popitem(last=False)
        self._record_metric(
            CallMetricName.BUFFER,
            duration_ms=0,
            numeric={"buffered_bytes": self._pcm_buffered_bytes},
            labels={"result": CallMetricResult.SUCCEEDED.value},
        )
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

    def audio_sent(self, response_id: str) -> None:
        """接纳非空 PCM 的网络发送成功通知，按正式轮次记录一次首音频耗时。"""
        response = self._responses.get(response_id)
        if (
            response is None
            or response.generation != self._generation
            or response_id in self._tombstones
            or self.state is not CallState.ACTIVE
        ):
            return
        turn = self._turns.get(response.turn_seq)
        if turn is None or turn.first_audio_recorded or turn.first_audio_disqualified:
            return
        turn.first_audio_recorded = True
        self._record_metric(
            CallMetricName.FIRST_AUDIO,
            duration_ms=max(0, (self._monotonic() - turn.started_at) * 1000),
            labels={"result": CallMetricResult.SUCCEEDED.value},
            start_ts=turn.started_at_timestamp,
        )

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
        self._record_metric(
            CallMetricName.STOP_CONFIRMATION,
            duration_ms=0,
            status=CallMetricStatus.SUCCESS if result else CallMetricStatus.ERROR,
            labels={
                "result": CallMetricResult.SUCCEEDED.value if result else CallMetricResult.FAILED.value,
                **({} if result else {"error_code": "STOP_CONFIRMATION_REJECTED"}),
            },
        )
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
            # A turn whose reply crosses a transport disconnect cannot prove a
            # continuous first-audio delivery path. Do not turn its later
            # buffered or replayed output into a successful latency sample.
            for turn in self._turns.values():
                if not turn.first_audio_recorded:
                    turn.first_audio_disqualified = True
            await self._transition_or_close(CallState.RECONNECTING, ledger_facts={"disconnected_at": disconnected_at})
            if self._first_disconnect_monotonic is None:
                self._first_disconnect_monotonic = disconnected_monotonic
            self._reconnect_count += 1
            self._recovery_deadline = disconnected_monotonic + 3.0
            self._cancel_task(self._silence_task)
            if self._retention_changed is not None:
                self._retention_changed(self._recovery_deadline)

    async def set_connection_available(self, available: bool) -> None:
        self._connection_available = available
        if not available and self.state is CallState.ACTIVE:
            await self.disconnect()
            return
        if available and self.state is CallState.RINGING and self._pending_answer is not None:
            answer = self._pending_answer
            self._pending_answer = None
            await self._apply_answer(answer)

    async def resume(self) -> bool:
        timed_out = False
        async with self._lifecycle_lock:
            if self.state is not CallState.RECONNECTING:
                return False
            if self._recovery_deadline is None or self._monotonic() >= self._recovery_deadline:
                self._record_metric(
                    CallMetricName.RECONNECT,
                    duration_ms=0,
                    status=CallMetricStatus.ERROR,
                    numeric={"reconnect_count": self._reconnect_count},
                    labels={"result": CallMetricResult.TIMEOUT.value, "error_code": "RECONNECT_TIMEOUT"},
                )
                timed_out = True
            else:
                if self._retention_changed is not None:
                    self._retention_changed(None)
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
                self._record_metric(
                    CallMetricName.RECONNECT,
                    duration_ms=0,
                    numeric={"reconnect_count": self._reconnect_count},
                    labels={"result": CallMetricResult.SUCCEEDED.value},
                )
                return True
        if timed_out:
            self.begin_termination(CallEndReason.RECOVERY_TIMEOUT)
            await self.wait_realtime_stopped()
        return False

    def can_resume(self) -> bool:
        return (
            self.state is CallState.RECONNECTING
            and self._recovery_deadline is not None
            and self._monotonic() < self._recovery_deadline
        )

    def begin_termination(self, reason: CallEndReason = CallEndReason.USER_HANGUP) -> asyncio.Task:
        """登记唯一完整终止任务；调用者可继续处理其他交互。"""
        if self._termination_reason is None:
            self._termination_reason = reason
        if self._termination is None:
            if self._own_termination is not None:
                self._termination = self._own_termination(lambda: self._terminate_owned(self._termination_reason))
            else:
                self._termination = asyncio.create_task(
                    self._terminate_owned(self._termination_reason), name=f"call-terminate-{self.call_id}"
                )
                self._termination.add_done_callback(self._observe_task)
        return self._termination

    async def terminate(self, reason: CallEndReason = CallEndReason.USER_HANGUP) -> CallFinalSnapshot | None:
        """等待实时停止、全部收尾和 Context 关闭；取消等待者不取消实际操作。"""
        return await asyncio.shield(self.begin_termination(reason))

    async def wait_realtime_stopped(self) -> CallFinalSnapshot | None:
        """等待终态输出处理和实时资源释放，不等待认知结算。"""
        await self._realtime_ended.wait()
        return self._final

    async def _terminate_owned(self, reason: CallEndReason) -> CallFinalSnapshot | None:
        try:
            initialization = self._initialization
            if (
                initialization is not None
                and initialization is not asyncio.current_task()
                and not initialization.done()
            ):
                initialization.cancel()
                await asyncio.gather(initialization, return_exceptions=True)
            async with self._lifecycle_lock:
                return await self._terminate_locked(reason)
        except BaseException:
            # A ledger transition can fail before _finish takes ownership of
            # cleanup. Never report completion with live resources or a lease.
            if not self._closed.is_set():
                await complete_owned(self._cleanup())
            raise
        finally:
            self._realtime_ended.set()
            self._closed.set()

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

    async def abort_failed_start(self) -> None:
        """终止未交付的建立操作，持久化失败并释放初始化资源。"""
        initialization = self._initialization
        if initialization is not None and initialization is not asyncio.current_task() and not initialization.done():
            initialization.cancel()
            await asyncio.gather(initialization, return_exceptions=True)
        if self._closed.is_set():
            return
        await self._fail_setup(CallEndReason.SETUP_TIMEOUT if self._setup_expired() else CallEndReason.SYSTEM_FAILURE)

    async def _consume_events(self) -> None:
        assert self._provider is not None
        async for event in self._provider.events():
            if self.state in {CallState.ENDED, CallState.FAILED}:
                return
            if isinstance(event, SpeechStarted):
                self._active_speech_item_id = event.item_id
                self._playback.set_user_speaking(True)
                self._interrupt()
            elif isinstance(event, SpeechStopped):
                self._release_user_speaking(event.item_id)
            elif isinstance(event, TurnCompleted):
                self._spawn_handle(self._on_turn(event), name="call-turn-handle")
            elif isinstance(event, TurnInvalid):
                self._release_user_speaking(event.item_id, invalid=True)
            elif isinstance(event, ProviderFailed):
                self._record_metric(
                    CallMetricName.PROVIDER_ENDPOINT,
                    duration_ms=0,
                    status=CallMetricStatus.ERROR,
                    labels={
                        "provider": CallProvider.UNKNOWN.value,
                        "result": CallMetricResult.FAILED.value,
                        "error_code": "PROVIDER_EVENT_FAILED",
                    },
                )
                await self.terminate(CallEndReason.PROVIDER_FAILED)
                return
            elif isinstance(event, AmbientAudio):
                continue

    def _release_user_speaking(self, item_id: str | None, *, invalid: bool = False) -> None:
        """Release only the provider turn that currently owns speaking state."""
        if item_id is not None and item_id != self._active_speech_item_id:
            return
        if item_id is None and self._active_speech_item_id is not None:
            return
        previous_silence = self._playback.silence_started_at
        if invalid:
            self._active_speech_item_id = None
            self._playback.finish_invalid_user_speech()
        else:
            # Keep this identity until the final transcript or next speech:
            # an empty transcript can invalidate an already stopped item.
            self._playback.set_user_speaking(False)
        if self._playback.silence_started_at != previous_silence:
            self._refresh_silence_task()

    async def _on_turn(self, event: TurnCompleted) -> None:
        if self.state is not CallState.ACTIVE:
            return
        sequence = len(self._turns) + 1
        self._turns[sequence] = _Turn(
            event.semantic.render(),
            started_at=self._monotonic(),
            started_at_timestamp=self._now().astimezone(timezone.utc).isoformat(timespec="milliseconds"),
        )
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
    ) -> None:
        if self.state in {
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
            report = await self._agent.handle_stimulus(request, sink, context=self._context)
            if (
                isinstance(stimulus, (d.CallTurnCompleted, d.CallStarted, d.CallSilenceElapsed))
                and report.request_status is d.HandlingRequestStatus.FAILED
                and not token.is_cancelled
            ):
                if turn_seq is not None:
                    self._turns[turn_seq].status = CallReplyStatus.FAILED
                self._record_reply_failure(request_id)
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
                    request_id=plan.origin_request_id,
                )
        self._plans.append(_QueuedPlan(plan, token, turn_seq, barriers))
        if self._realize_task is None or self._realize_task.done():
            self._realize_task = self._track(asyncio.create_task(self._realize(), name="call-realize"))
            self._realize_task.add_done_callback(self._resume_queued_plans)

    def _resume_queued_plans(self, completed) -> None:
        if (
            self._realize_task is completed
            and self._plans
            and self.state in {CallState.RINGING, CallState.ACTIVE, CallState.RECONNECTING}
        ):
            self._realize_task = self._track(asyncio.create_task(self._realize(), name="call-realize"))
            self._realize_task.add_done_callback(self._resume_queued_plans)

    async def _realize(self) -> None:
        while self._plans and self.state not in {CallState.ENDING, CallState.ENDED, CallState.FAILED}:
            queued = self._plans.popleft()
            if queued.token.is_cancelled:
                continue
            if queued.barriers and not await self._wait_response_barriers(queued.barriers, queued.token):
                continue
            # Maintenance must not reset an already settled reply's status.
            turn_seq = (
                None
                if all(isinstance(action, d.CognitiveMaintenance) for action in queued.plan.actions)
                else queued.turn_seq
            )
            await self._realize_plan(queued.plan, turn_seq)

    async def _realize_plan(
        self, plan: d.ActionPlan, turn_seq: int | None, *, retried: frozenset[str] = frozenset()
    ) -> None:
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
            call_maintenance_snapshot=self._maintenance_snapshot(),
        )
        if (
            turn_seq is not None
            and turn_seq in self._turns
            and any(isinstance(action, d.Say) and not action.call_delivery.provisional for action in plan.actions)
        ):
            self._turns[turn_seq].status = CallReplyStatus.NOT_STARTED
        try:
            report = await self._agent.realize_action_plan(plan, context, _OutputSink(self, context, turn_seq))
            await self._handle_plan_result(plan, report, turn_seq, execution_token, retried, response_ids)
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

    async def _handle_plan_result(self, plan, report, turn_seq, token, retried, response_ids):
        if report.status is d.ExecutionStatus.FAILED and not token.is_cancelled:
            retry = self._retry_say_plan(plan, report, turn_seq, retried)
            if retry is not None:
                await self._realize_plan(retry, turn_seq, retried=retried | {retry.actions[0].action_id})
                return
            if any(isinstance(action, d.Say) for action in plan.actions):
                await self._transport_send(self._emit(CallReplyFailed(self._ownership.call_id)))
                self._record_reply_failure(plan.origin_request_id)
                self._retire_unrealized_responses(response_ids)
            if turn_seq is not None:
                self._turns[turn_seq].status = CallReplyStatus.FAILED

    def _record_reply_failure(self, request_id: str) -> None:
        if request_id in self._failed_reply_requests:
            return
        self._failed_reply_requests.add(request_id)
        self._reply_failures += 1
        if self._reply_failures >= 2:
            task = self._track(
                asyncio.create_task(self.terminate(CallEndReason.SYSTEM_FAILURE), name="call-reply-failed")
            )
            task.add_done_callback(self._observe_task)

    def _retire_unrealized_responses(self, response_ids) -> None:
        for response_id in response_ids:
            response = self._responses[response_id]
            if response.stream_id is None and not response.message_completed:
                response.failed = True
                self._tombstones.add(response_id)
                response.settled.set()

    def _retry_say_plan(self, plan, report, turn_seq, retried):
        failed = next(
            (result for result in report.action_results if result.status is d.ActionExecutionStatus.FAILED), None
        )
        if (
            failed is None
            or failed.action_id in retried
            or failed.error_code
            not in {
                d.ExecutionErrorCode.AUDIO_EMPTY,
                d.ExecutionErrorCode.AUDIO_GENERATION_FAILED,
                d.ExecutionErrorCode.PROVIDER_TIMEOUT,
            }
        ):
            return None
        index = next(i for i, action in enumerate(plan.actions) if action.action_id == failed.action_id)
        action = plan.actions[index]
        if not isinstance(action, d.Say) or action.prepared_audio_ref is not None:
            return None
        old_id = action.call_delivery.response_id
        old = self._responses[old_id]
        new_id = f"{old_id}-retry"
        retry = replace(
            action,
            action_id=action.action_id,
            call_delivery=replace(action.call_delivery, response_id=new_id),
        )
        replacement = _Response(
            turn_seq=turn_seq,
            provisional=old.provisional,
            generation=self._generation,
            settled=asyncio.Event(),
            request_id=old.request_id,
        )
        # Preserve utterance ordering while retaining the failed response's tombstone.
        self._responses = {
            new_id if key == old_id else key: replacement if key == old_id else value
            for key, value in self._responses.items()
        }
        self._plans = deque(
            replace(queued, barriers=tuple(new_id if item == old_id else item for item in queued.barriers))
            for queued in self._plans
        )
        old.turn_seq = None
        old.request_id = None
        old.formal_text = None
        self._responses[old_id] = old
        return replace(plan, plan_id=f"{plan.plan_id}-retry", actions=(retry, *plan.actions[index + 1 :]))

    def _maintenance_snapshot(self) -> CallMaintenanceSnapshot:
        turns = []
        for seq, turn in sorted(self._turns.items()):
            if seq in self._unfinished_turns or self._turn_has_unsettled_response(seq):
                break
            text = turn.formal_text if turn.status in {CallReplyStatus.COMPLETED, CallReplyStatus.INTERRUPTED} else None
            turns.append(CallFinalTurn(seq, turn.semantic, turn.status, text))
        return CallMaintenanceSnapshot(self._record.call_id, tuple(turns))

    async def _apply_answer(self, action: d.AnswerCall) -> None:
        if action.call_id != self._record.call_id or self.state is not CallState.RINGING:
            return
        if action.decision.value == "decline":
            await self.terminate(CallEndReason.DECLINED)
            return
        if not self._connection_available:
            self._pending_answer = action
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
                self._pcm_buffered_bytes = max(0, self._pcm_buffered_bytes - len(frame.payload))
                self._pcm.task_done()

    async def expire_retention(self, deadline: float) -> None:
        """应用 Manager 的离线到期通知，重新校验期限避免旧计时终止新连接。"""
        should_terminate = False
        async with self._lifecycle_lock:
            should_terminate = (
                self.state is CallState.RECONNECTING
                and self._recovery_deadline == deadline
                and self._monotonic() >= deadline
            )
        if should_terminate:
            await self.terminate(CallEndReason.RECOVERY_TIMEOUT)

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
            # 墙钟可能在相邻状态更新间不变，账本版本仍必须严格递增。
            updated_at = max(self._now(), self._record.updated_at + timedelta(microseconds=1))
            changes: dict[str, object] = {"state": state, "updated_at": updated_at}
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
        self._record_metric(
            CallMetricName.STATE,
            duration_ms=0,
            labels={"state": state.value, "result": CallMetricResult.SUCCEEDED.value},
        )
        if publish:
            await self._publish_state(snapshot)

    async def _publish_state(self, snapshot) -> None:
        try:
            await self._emit(
                CallStateChanged(
                    self._ownership.call_id,
                    snapshot.state,
                    self._ownership.client_request_id,
                    self._record.connected_at,
                )
            )
        except BaseException as error:
            if isinstance(error, Exception) and snapshot.state in {
                CallState.ENDING,
                CallState.DECLINED,
                CallState.ENDED,
            }:
                get_logger(__name__).warning("Call terminal state delivery failed state=%s", snapshot.state.value)
                return
            if snapshot.has_connected and self._final is None:
                self._request_transport_abort()
            raise

    async def _transition_or_close(self, state: CallState, **facts: object) -> None:
        await self._transition(state, **facts)

    async def _finish(self, outcome: CallOutcome, reason: CallEndReason) -> CallFinalSnapshot:  # noqa: C901
        try:
            # Admission is already closed (ENDING/DECLINED). Drain any owned
            # maintenance write before freezing the final progress boundary.
            if self._realize_task is not None and self._realize_task is not asyncio.current_task():
                await asyncio.gather(self._realize_task, return_exceptions=True)
            ended = self._now()
            duration = self._active_duration_ms(ended)
            terminal_facts = {"ended_at": ended, "active_duration_ms": duration}
            if self.state is CallState.DECLINED:
                await self._transition(CallState.ENDED, outcome=outcome, end_reason=reason, ledger_facts=terminal_facts)
            elif self.state is CallState.ENDING:
                await self._transition(CallState.ENDED, outcome=outcome, end_reason=reason, ledger_facts=terminal_facts)
            terminal = CallTerminalFacts(self._record.call_id, outcome, reason, duration, ended)
            completed = tuple(
                CallFinalTurn(
                    seq,
                    turn.semantic,
                    turn.status,
                    (
                        turn.formal_text
                        if turn.status in {CallReplyStatus.COMPLETED, CallReplyStatus.INTERRUPTED}
                        else None
                    ),
                )
                for seq, turn in sorted(self._turns.items())
            )
            persisted = await complete_owned(asyncio.to_thread(self._repository.find_by_id, self._record.call_id))
            progress = persisted.maintenance_turn_seq if persisted is not None else self._record.maintenance_turn_seq
            if self._context is not None:
                progress = self._context.conversation.read_call_maintenance_progress()
            self._final = CallFinalSnapshot(terminal, completed, progress)
        except BaseException:
            await complete_owned(self._cleanup())
            raise
        cleanup_error = await complete_owned(self._cleanup(release_ownership=False, close_context=False))
        try:
            await self._send_terminal_best_effort(self._final)
            self._realtime_ended.set()
            result = await self._complete_ending(self._final)
            if self._save_history is not None:
                await complete_owned(self._save_history(self._final, result=result))
            if cleanup_error is not None:
                raise cleanup_error
        finally:
            try:
                if self._context is not None:
                    await complete_owned(self._context.close())
            finally:
                self._context = None
                self._release_call_ownership()
                self._closed.set()
        return self._final

    async def _complete_ending(self, snapshot) -> CallEndingResult | None:
        """Deliver the sole settlement stimulus using this call's original context."""
        try:
            token = d.CancellationToken()
            request = d.HandleStimulusRequest(
                request_id=str(uuid4()),
                stimulus=d.CallEnding(
                    **self._stimulus_fields(),
                    call_id=self._record.call_id,
                    reason=snapshot.terminal.end_reason,
                    final_snapshot=snapshot,
                ),
                interaction=self._agent_snapshot(),
                cancellation=token,
            )
            sink = _EndingPlanSink()
            report = await self._agent.handle_stimulus(request, sink, context=self._context)
            if report.request_status is not d.HandlingRequestStatus.COMPLETED:
                raise RuntimeError("Agent failed to handle CallEnding")
            if snapshot.terminal.outcome is not CallOutcome.CONNECTED:
                if sink.plans:
                    raise RuntimeError("nonconnected CallEnding must not run cognition")
                return None
            if (
                len(sink.plans) != 1
                or len(sink.plans[0].actions) != 1
                or not isinstance(sink.plans[0].actions[0], d.FinalizeCall)
            ):
                raise RuntimeError("CallEnding must produce exactly one FinalizeCall")
            execution = d.ExecutionContext(
                execution_id=str(uuid4()),
                interaction_id=self.call_id,
                current_interaction_revision=self._revision,
                cancellation=token,
                interaction_context=self._context,
            )
            realized = await self._agent.realize_action_plan(sink.plans[0], execution, _EndingOutputSink())
            if realized.status is not d.ExecutionStatus.COMPLETED or len(realized.action_results) != 1:
                raise RuntimeError("FinalizeCall failed")
            result = realized.action_results[0].call_ending
            if result is None:
                raise RuntimeError("FinalizeCall returned no result")
            return result
        except Exception:
            get_logger(__name__).exception("CallEnding failed call=%s", self.call_id)
            if snapshot.terminal.outcome is not CallOutcome.CONNECTED:
                return None
            working = self._context.conversation.read_working().summary.text if self._context is not None else ""
            progress = (
                self._context.conversation.read_call_maintenance_progress()
                if self._context is not None
                else snapshot.maintenance_turn_seq
            )
            summary, source = fallback_call_summary(working)
            return CallEndingResult(summary, source, False, progress)

    async def _emit(self, output: CallStageOutput) -> None:
        await self._output_sink(self.call_id, output)

    @property
    def is_finalizing(self) -> bool:
        """实时退出已开始，不能接受新的交互接入。"""
        return self.state in {CallState.ENDING, CallState.ENDED, CallState.DECLINED}

    def can_attach(self) -> bool:
        """检查能否申请连接；实际接入仍须重验恢复期限和连接状态。"""
        return not self.termination_requested and (self.state is CallState.ACTIVE or self.can_reconnect())

    async def _send_terminal_best_effort(self, snapshot: CallFinalSnapshot) -> None:
        """Bound terminal delivery after realtime cleanup, before cognition.

        Cancellation cannot retract bytes already written by a transport, so the
        binding remains responsible for terminal idempotency.
        """
        task = asyncio.create_task(self._emit(snapshot), name="call-terminal-delivery")
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
            await self._emit(CallSetupFailed(reason))
        except BaseException:
            pass
        finally:
            self._realtime_ended.set()
        if cleanup_error is not None:
            raise cleanup_error

    def _interrupt(self) -> None:
        self._record_metric(
            CallMetricName.INTERRUPT,
            duration_ms=0,
            numeric={"interrupt_count": 1},
            labels={"result": CallMetricResult.SUCCEEDED.value},
        )
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
            if (
                turn_seq is not None
                and turn_seq in self._turns
                and self._turns[turn_seq].status is not CallReplyStatus.FAILED
            ):
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
        # All pending work belongs to the interrupted generation, including
        # plans which never reached realization. Their user facts are settled.
        self._unfinished_turns.clear()
        self._playback.set_unfinished_user_turn_count(0)
        for task in tuple(self._handle_tasks):
            self._cancel_task(task)
        self._cancel_task(self._realize_task)

    async def _cleanup(self, *, release_ownership: bool = True, close_context: bool = True) -> BaseException | None:
        if self._retention_changed is not None:
            self._retention_changed(None)
        self._plans.clear()
        current = asyncio.current_task()
        pending = tuple(task for task in self._tasks if task is not current and not task.done())
        for task in pending:
            self._cancel_task(task)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        cleanup_error = await self._close_resources(close_context=close_context)
        while not self._pcm.empty():
            try:
                frame = self._pcm.get_nowait()
                self._pcm_buffered_bytes = max(0, self._pcm_buffered_bytes - len(frame.payload))
                self._pcm.task_done()
            except asyncio.QueueEmpty:
                break
        self._playback.close()
        self._receipts.clear()
        self._turns.clear()
        self._unfinished_turns.clear()
        self._responses.clear()
        if release_ownership:
            try:
                self._release_call_ownership()
            except BaseException as error:
                cleanup_error = cleanup_error or error
        if close_context:
            self._closed.set()
        return cleanup_error

    def _release_call_ownership(self) -> None:
        if self._release_ownership is not None and not self._ownership_released:
            self._ownership_released = self._release_ownership(self._ownership)

    async def _close_resources(self, *, close_context: bool = True) -> BaseException | None:
        cleanup_error: BaseException | None = None
        if self._provider is not None:
            try:
                await self._provider.close()
            except BaseException as error:
                cleanup_error = error
            finally:
                self._provider = None
        if close_context and self._context is not None:
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

    async def _await_setup(
        self,
        awaitable: Awaitable[Any],
        *,
        cleanup: Callable[[Any], Awaitable[None]] | None = None,
    ) -> Any:
        remaining = self._ownership.setup_deadline - self._monotonic()
        if remaining <= 0:
            if inspect.iscoroutine(awaitable):
                awaitable.close()
            raise TimeoutError("call setup deadline elapsed")
        task = asyncio.create_task(awaitable)
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=remaining)
        except (asyncio.CancelledError, asyncio.TimeoutError) as error:
            task.cancel()
            result = await asyncio.gather(task, return_exceptions=True)
            value = result[0]
            if cleanup is not None and not isinstance(value, BaseException):
                await cleanup(value)
            if isinstance(error, asyncio.TimeoutError):
                raise TimeoutError("call setup deadline elapsed") from None
            raise

    def _setup_expired(self) -> bool:
        return self._monotonic() >= self._ownership.setup_deadline

    def _now(self) -> datetime:
        value = self._wall_clock()
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

    def _record_metric(
        self,
        name,
        *,
        duration_ms,
        status=CallMetricStatus.SUCCESS,
        numeric=None,
        labels=None,
        start_ts: str | None = None,
    ) -> None:
        if self._call_metrics is None:
            return
        end_timestamp = self._now().astimezone(timezone.utc).isoformat(timespec="milliseconds")
        try:
            self._call_metrics.record(
                CallMetric(
                    call_id=self._record.call_id,
                    name=name,
                    start_ts=start_ts or end_timestamp,
                    end_ts=end_timestamp,
                    duration_ms=duration_ms,
                    status=status,
                    numeric=numeric,
                    labels=labels,
                )
            )
        except Exception:
            pass

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
            await self._transport_send(self._emit(CallPlaybackStop(response_id, stream_ids)))
            return
        self._settle_response_if_complete(response_id)

    async def _transport_send(self, operation: Awaitable[None]) -> None:
        try:
            await operation
        except asyncio.CancelledError:
            # Interruption and shutdown cancel owned output; neither is a wire failure.
            raise
        except Exception:
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
            self._reset_failures_after_playback(response)
            if response.turn_seq is not None and not response.provisional:
                turn = self._turns[response.turn_seq]
                formal = [
                    item
                    for item in self._responses.values()
                    if item.turn_seq == response.turn_seq and not item.provisional
                ]
                if turn.status not in {CallReplyStatus.FAILED, CallReplyStatus.INTERRUPTED} and all(
                    item.playback_completed and item.message_completed and not item.failed for item in formal
                ):
                    turn.status = CallReplyStatus.COMPLETED if turn.formal_text else CallReplyStatus.FAILED
                    if turn.status is CallReplyStatus.COMPLETED:
                        self._reply_failures = 0
                if not self._turn_has_unsettled_response(response.turn_seq):
                    self._finish_user_turn(response.turn_seq)
        if self._active_response_id == response_id:
            self._active_response_id = None

    def _reset_failures_after_playback(self, response) -> None:
        if not response.provisional and response.request_id is not None:
            request_responses = [
                item
                for item in self._responses.values()
                if item.request_id == response.request_id and not item.provisional
            ]
            if all(
                item.playback_completed and item.message_completed and not item.failed for item in request_responses
            ):
                self._reply_failures = 0

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
            response = self._stage._responses[output.call_delivery.response_id]
            response.formal_text = output.text
            turn.formal_text = "\n".join(
                item.formal_text
                for item in self._stage._responses.values()
                if item.turn_seq == self._turn_seq and not item.provisional and item.formal_text is not None
            )
            self._stage._record_metric(
                CallMetricName.FORMAL_REPLY,
                duration_ms=max(0, (self._stage._monotonic() - turn.started_at) * 1000),
                labels={"result": CallMetricResult.SUCCEEDED.value},
            )

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
                if response.message_completed and response.playback_completed and response.stream_id is not None:
                    self._stage._settle_response_if_complete(response_id)
                if not response.message_completed:
                    self._stage._tombstones.add(response_id)
                    response.failed = True
                    stream_ids = (response.stream_id,) if response.stream_id is not None else ()
                    if stream_ids:
                        await self._stage._transport_send(self._stage._emit(CallPlaybackStop(response_id, stream_ids)))
                    elif response.settled is not None:
                        response.settled.set()
        elif isinstance(output, d.ExpressionOutput):
            await self._stage._transport_send(self._stage._emit(CallOutput(output)))

    async def _send_audio(self, response_id: str, output: d.AudioChunkOutput) -> None:
        response = self._stage._responses[response_id]
        now = self._stage._monotonic()
        if response.audio_started_at is None:
            response.audio_started_at = now
        if response.stream_id is None:
            response.stream_id = self._stage._next_stream_id
            self._stage._next_stream_id += 1
            self._stage.register_playback(response_id, response.stream_id)
            await self._stage._transport_send(
                self._stage._emit(CallStreamStarted(response_id, response.stream_id, output.audio_format))
            )
        self._stage._pending_send += 1
        self._stage._playback.set_pending_send_count(self._stage._pending_send)
        try:
            await self._stage._transport_send(
                self._stage._emit(CallPCM(response_id, response.stream_id, output.data, output.final))
            )
        finally:
            self._stage._pending_send -= 1
            self._stage._playback.set_pending_send_count(self._stage._pending_send)
        if output.final:
            self._stage.playback_final(response_id, response.stream_id)
            self._stage._record_metric(
                CallMetricName.TTS,
                duration_ms=max(0, (self._stage._monotonic() - response.audio_started_at) * 1000),
                labels={"result": CallMetricResult.SUCCEEDED.value},
            )


class _EndingPlanSink:
    def __init__(self):
        self.plans = []

    async def emit(self, plan):
        self.plans.append(plan)
        return d.PlanReceipt(plan_id=plan.plan_id, status=d.PlanAcceptanceStatus.ACCEPTED)


class _EndingOutputSink:
    async def emit(self, output):
        raise d.SinkRejectedError("CallEnding cannot emit output", code=d.SinkRejectionCode.UNSUPPORTED_OUTPUT)
