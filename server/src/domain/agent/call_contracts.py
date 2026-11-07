"""Call-specific Agent stimuli and snapshot contracts without wire or provider types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar
from uuid import UUID

from src.domain.call import CallAudioSemantic, CallEndReason, CallFinalSnapshot, CallState

from ._handle_input_contract import _require
from ._stimulus_contract import _require_aware_datetime, _require_instance, _require_nonnegative_int
from .interaction_snapshot import (
    ConnectionState,
    InteractionKind,
    _InteractionFacts,
)
from .stimulus import Stimulus, StimulusKind


@dataclass(frozen=True, slots=True, kw_only=True)
class CallInteractionSnapshot(_InteractionFacts):
    kind: ClassVar[InteractionKind] = InteractionKind.CALL
    call_id: UUID
    state: CallState
    connection_state: ConnectionState

    def __post_init__(self) -> None:
        _InteractionFacts.__post_init__(self)
        _require(isinstance(self.call_id, UUID), "call_id")
        _require(isinstance(self.state, CallState), "state")
        _require(isinstance(self.connection_state, ConnectionState), "connection_state")


@dataclass(frozen=True, slots=True, kw_only=True)
class CallAnswerRequested(Stimulus):
    kind: ClassVar[StimulusKind] = StimulusKind.CALL_ANSWER_REQUESTED
    call_id: UUID
    requested_at: datetime

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_instance(self.call_id, UUID)
        _require_aware_datetime(self.requested_at)


@dataclass(frozen=True, slots=True, kw_only=True)
class CallStarted(Stimulus):
    kind: ClassVar[StimulusKind] = StimulusKind.CALL_STARTED
    call_id: UUID
    connected_at: datetime

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_instance(self.call_id, UUID)
        _require_aware_datetime(self.connected_at)


@dataclass(frozen=True, slots=True, kw_only=True)
class CallTranscriptUpdated(Stimulus):
    """未确认的临时转写，只能用于候选召回，不能写入对话。"""

    kind: ClassVar[StimulusKind] = StimulusKind.CALL_TRANSCRIPT_UPDATED
    call_id: UUID
    turn_seq: int
    text: str

    def __post_init__(self):
        Stimulus.__post_init__(self)
        _require_instance(self.call_id, UUID)
        _require(type(self.turn_seq) is int and self.turn_seq > 0, "turn_seq")
        _require(isinstance(self.text, str) and bool(self.text.strip()), "text")


@dataclass(frozen=True, slots=True, kw_only=True)
class CallTurnCompleted(Stimulus):
    kind: ClassVar[StimulusKind] = StimulusKind.CALL_TURN_COMPLETED
    call_id: UUID
    turn_seq: int
    audio_content: CallAudioSemantic

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_instance(self.call_id, UUID)
        if type(self.turn_seq) is not int or self.turn_seq <= 0:
            raise ValueError("turn_seq must be positive")
        _require_instance(self.audio_content, CallAudioSemantic)


@dataclass(frozen=True, slots=True, kw_only=True)
class CallReplyRequested(Stimulus):
    """A frozen pending-input batch; turn_seq anchors its maintenance range."""

    kind: ClassVar[StimulusKind] = StimulusKind.CALL_REPLY_REQUESTED
    call_id: UUID
    turn_seq: int
    audio_content: CallAudioSemantic
    interrupted: bool = False

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_instance(self.call_id, UUID)
        _require(type(self.turn_seq) is int and self.turn_seq > 0, "turn_seq")
        _require_instance(self.audio_content, CallAudioSemantic)
        _require(type(self.interrupted) is bool, "interrupted")


@dataclass(frozen=True, slots=True, kw_only=True)
class CallReplyConfirmed(Stimulus):
    """A complete formal response was played; bookkeeping only, never cognition."""

    kind: ClassVar[StimulusKind] = StimulusKind.CALL_REPLY_CONFIRMED
    call_id: UUID
    turn_seq: int | None
    response_id: str
    text: str

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_instance(self.call_id, UUID)
        _require(bool(self.response_id.strip()) and bool(self.text.strip()), "confirmed response")
        _require(self.turn_seq is None or type(self.turn_seq) is int and self.turn_seq > 0, "turn_seq")


@dataclass(frozen=True, slots=True, kw_only=True)
class CallSilenceElapsed(Stimulus):
    kind: ClassVar[StimulusKind] = StimulusKind.CALL_SILENCE_ELAPSED
    call_id: UUID
    silence_ms: int

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_instance(self.call_id, UUID)
        _require_nonnegative_int(self.silence_ms)


@dataclass(frozen=True, slots=True, kw_only=True)
class CallTimeLimitWarning(Stimulus):
    kind: ClassVar[StimulusKind] = StimulusKind.CALL_TIME_LIMIT_WARNING
    call_id: UUID
    remaining_ms: int

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_instance(self.call_id, UUID)
        _require_nonnegative_int(self.remaining_ms)


@dataclass(frozen=True, slots=True, kw_only=True)
class CallEnding(Stimulus):
    kind: ClassVar[StimulusKind] = StimulusKind.CALL_ENDING
    call_id: UUID
    reason: CallEndReason
    final_snapshot: CallFinalSnapshot

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_instance(self.call_id, UUID)
        _require_instance(self.reason, CallEndReason)
        _require_instance(self.final_snapshot, CallFinalSnapshot)
        if self.final_snapshot.terminal.call_id != self.call_id:
            raise ValueError("call ending identity mismatch")
        if self.final_snapshot.terminal.end_reason is not self.reason:
            raise ValueError("call ending reason mismatch")


@dataclass(frozen=True, slots=True, kw_only=True)
class CallReplySegmentReady(Stimulus):
    """实时模型已完成的短句；处理时不再调用回复模型。"""

    kind: ClassVar[StimulusKind] = StimulusKind.CALL_REPLY_SEGMENT_READY
    call_id: UUID
    response_id: str
    segment_index: int
    turn_seq: int | None
    text: str
    tone: str = "中性"


@dataclass(frozen=True, slots=True, kw_only=True)
class CallMemoryLookupRequested(Stimulus):
    kind: ClassVar[StimulusKind] = StimulusKind.CALL_MEMORY_LOOKUP_REQUESTED
    call_id: UUID
    response_id: str
    tool_call_id: str
    query: str
    turn_seq: int | None = None


CallStimulus = (
    CallTimeLimitWarning
    | CallAnswerRequested
    | CallStarted
    | CallTranscriptUpdated
    | CallTurnCompleted
    | CallReplyRequested
    | CallReplyConfirmed
    | CallSilenceElapsed
    | CallEnding
    | CallReplySegmentReady
    | CallMemoryLookupRequested
)
