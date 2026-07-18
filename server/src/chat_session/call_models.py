from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, IntEnum
from typing import Any


class CallState(str, Enum):
    IDLE = "IDLE"
    REQUESTING = "REQUESTING"
    ACTIVE = "ACTIVE"
    RECONNECTING = "RECONNECTING"
    ENDING = "ENDING"
    ENDED = "ENDED"


class CallExitCode(IntEnum):
    NORMAL = 0
    HANGUP_BEFORE_CONNECTED = 1
    RECONNECT_TIMEOUT = -1
    REALTIME_PROVIDER_FAILED = -2
    TTS_FAILED = -3
    INTERNAL_ERROR = -4
    CONCURRENCY_REJECTED = -5


@dataclass(frozen=True)
class CallTurnDraft:
    call_id: str
    seq: int
    speaker: str
    text: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    raw_events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CallResponseState:
    response_id: str
    cancelled: bool = False
    completed: bool = False
    pending_audio_ids: list[str] = field(default_factory=list)
    completed_audio_ids: set[str] = field(default_factory=set)
    raw_events: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class CallTTSLine:
    call_id: str
    response_id: str
    seq: int
    content: str
    tone: str
    expression: str = ""
    audio_id: str = ""
