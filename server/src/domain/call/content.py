"""Privacy-bounded persisted call content and its logical identity."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid5

from .types import CallEndReason, CallOutcome


@dataclass(frozen=True, slots=True)
class CallContent:
    """The complete allowlist of call content permitted in Conversation storage."""

    call_id: UUID
    outcome: CallOutcome
    active_duration_ms: int
    summary: str | None
    end_reason: CallEndReason
    text: str = field(init=False)

    def __post_init__(self) -> None:
        if self.active_duration_ms < 0:
            raise ValueError("active_duration_ms cannot be negative")
        summary = self.summary.strip() if self.summary is not None else None
        summary = summary or None
        if self.outcome is CallOutcome.CONNECTED and summary is None:
            raise ValueError("connected calls require a summary")
        if self.outcome is not CallOutcome.CONNECTED and self.active_duration_ms != 0:
            raise ValueError("calls that never connected must have zero active duration")
        if self.outcome is not CallOutcome.CONNECTED and summary is not None:
            raise ValueError("calls that never connected cannot have a summary")
        object.__setattr__(self, "summary", summary)
        object.__setattr__(self, "text", self.render_for_agent())

    def render_for_agent(self) -> str:
        if self.outcome is CallOutcome.CONNECTED:
            return f"[语音通话]{self.summary}"
        if self.outcome is CallOutcome.CANCELLED_BEFORE_ANSWER:
            return "[语音通话] 已取消"
        return "[语音通话] 未接听"

    def render_for_history(self) -> str:
        """Render client-safe history text without exposing the summary."""
        if self.outcome is CallOutcome.CANCELLED_BEFORE_ANSWER:
            return "[语音通话] 已取消"
        if self.outcome is CallOutcome.DECLINED:
            return "[语音通话] 未接听"
        total_seconds = self.active_duration_ms // 1000
        minutes, seconds = divmod(total_seconds, 60)
        return f"[语音通话] {minutes:02d}:{seconds:02d}"


def derive_call_conversation_id(
    namespace: UUID,
    *,
    user_id: str,
    character_id: str,
    call_id: UUID,
) -> UUID:
    """Derive UUIDv5 while leaving the project namespace an explicit policy choice."""
    if not user_id or not character_id:
        raise ValueError("user_id and character_id are required")
    logical_name = "\x1f".join((user_id, character_id, str(call_id)))
    return uuid5(namespace, logical_name)
