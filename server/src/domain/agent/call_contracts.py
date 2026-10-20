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
class CallSilenceElapsed(Stimulus):
    kind: ClassVar[StimulusKind] = StimulusKind.CALL_SILENCE_ELAPSED
    call_id: UUID
    silence_ms: int

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_instance(self.call_id, UUID)
        _require_nonnegative_int(self.silence_ms)


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


CallStimulus = CallAnswerRequested | CallStarted | CallTurnCompleted | CallSilenceElapsed | CallEnding
