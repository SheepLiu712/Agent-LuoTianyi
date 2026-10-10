"""Provider-neutral domain contracts consumed by the future CallStage and Agent lanes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID

from .types import CallEndReason, CallOutcome


def _nonblank(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be nonblank")


def _aware(value: datetime, field: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


class CallAnswerDecision(str, Enum):
    ACCEPT = "accept"
    DECLINE = "decline"


class CallAudioRoute(str, Enum):
    CHAT = "CHAT"
    CALL = "CALL"


class CallReplyStatus(str, Enum):
    NOT_STARTED = "not_started"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CallTerminalFacts:
    call_id: UUID
    outcome: CallOutcome
    end_reason: CallEndReason
    active_duration_ms: int
    ended_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.call_id, UUID):
            raise ValueError("call_id is required")
        if not isinstance(self.outcome, CallOutcome) or not isinstance(self.end_reason, CallEndReason):
            raise ValueError("outcome and end_reason are required")
        if type(self.active_duration_ms) is not int or self.active_duration_ms < 0:
            raise ValueError("active_duration_ms must be nonnegative")
        _aware(self.ended_at, "ended_at")
        if self.outcome is not CallOutcome.CONNECTED and self.active_duration_ms != 0:
            raise ValueError("calls that never connected must have zero duration")
        if self.outcome is CallOutcome.DECLINED and self.end_reason is not CallEndReason.DECLINED:
            raise ValueError("declined outcome requires declined reason")
        if self.outcome is CallOutcome.CANCELLED_BEFORE_ANSWER and self.end_reason is CallEndReason.DECLINED:
            raise ValueError("cancelled outcome cannot use declined reason")
        if self.outcome is CallOutcome.CONNECTED and self.end_reason is CallEndReason.DECLINED:
            raise ValueError("connected outcome cannot use declined reason")


@dataclass(frozen=True, slots=True)
class CallFinalTurn:
    turn_seq: int
    user_semantic: str
    reply_status: CallReplyStatus
    formal_agent_text: str | None

    def __post_init__(self) -> None:
        if type(self.turn_seq) is not int or self.turn_seq <= 0:
            raise ValueError("turn_seq must be positive")
        _nonblank(self.user_semantic, "user_semantic")
        if not isinstance(self.reply_status, CallReplyStatus):
            raise ValueError("reply_status is required")
        if self.formal_agent_text is not None:
            _nonblank(self.formal_agent_text, "formal_agent_text")
        if self.reply_status is CallReplyStatus.COMPLETED and self.formal_agent_text is None:
            raise ValueError("completed reply requires formal agent text")
        if self.reply_status in {CallReplyStatus.NOT_STARTED, CallReplyStatus.FAILED} and self.formal_agent_text is not None:
            raise ValueError("unanswered or failed reply cannot contain formal agent text")


@dataclass(frozen=True, slots=True)
class CallFinalSnapshot:
    terminal: CallTerminalFacts
    completed_turns: tuple[CallFinalTurn, ...]
    maintenance_turn_seq: int

    def __post_init__(self) -> None:
        if not isinstance(self.terminal, CallTerminalFacts):
            raise ValueError("terminal facts are required")
        if type(self.completed_turns) is not tuple or not all(
            isinstance(turn, CallFinalTurn) for turn in self.completed_turns
        ):
            raise ValueError("completed_turns must be a tuple of CallFinalTurn")
        seqs = tuple(turn.turn_seq for turn in self.completed_turns)
        if seqs != tuple(sorted(set(seqs))):
            raise ValueError("completed turn sequence must be unique and ordered")
        if type(self.maintenance_turn_seq) is not int or self.maintenance_turn_seq < 0:
            raise ValueError("maintenance_turn_seq must be nonnegative")
        if self.maintenance_turn_seq > (seqs[-1] if seqs else 0):
            raise ValueError("maintenance progress exceeds final turns")


@dataclass(frozen=True, slots=True)
class CallSpeechDelivery:
    audio_route: CallAudioRoute = CallAudioRoute.CHAT
    display_in_chat: bool = True
    is_ephemeral: bool = False
    provisional: bool = False
    response_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.audio_route, CallAudioRoute):
            raise ValueError("audio_route is required")
        if any(type(value) is not bool for value in (self.display_in_chat, self.is_ephemeral, self.provisional)):
            raise ValueError("delivery flags must be bool")
        if self.response_id is not None:
            _nonblank(self.response_id, "response_id")
        if self.audio_route is CallAudioRoute.CALL:
            if self.display_in_chat or not self.is_ephemeral or self.response_id is None:
                raise ValueError("CALL delivery must be ephemeral, hidden, and response-scoped")
        elif self.provisional or self.response_id is not None:
            raise ValueError("CHAT delivery cannot carry call response metadata")
