"""通话交互的不可恢复终态；不包含认知、转录或历史快照。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from .contracts import CallEndReason, CallOutcome


@dataclass(frozen=True, slots=True)
class CallTerminated:
    call_id: str
    client_request_id: str
    kind: Literal["ENDED", "FAILED"]
    outcome: CallOutcome | None
    end_reason: CallEndReason
    active_duration_ms: int
    ended_at: datetime
