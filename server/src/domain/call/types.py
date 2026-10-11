"""Core realtime-call value objects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CallState(str, Enum):
    PREPARING = "preparing"
    RINGING = "ringing"
    ACTIVE = "active"
    RECONNECTING = "reconnecting"
    ENDING = "ending"
    DECLINED = "declined"
    ENDED = "ended"
    FAILED = "failed"


class CallOutcome(str, Enum):
    CONNECTED = "connected"
    CANCELLED_BEFORE_ANSWER = "cancelled_before_answer"
    DECLINED = "declined"


class CallEndReason(str, Enum):
    USER_HANGUP = "user_hangup"
    AGENT_HANGUP = "agent_hangup"
    DECLINED = "declined"
    SETUP_TIMEOUT = "setup_timeout"
    TIME_LIMIT = "time_limit"
    PROVIDER_FAILED = "provider_failed"
    RECOVERY_TIMEOUT = "recovery_timeout"
    SYSTEM_FAILURE = "system_failure"


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


@dataclass(frozen=True, slots=True)
class CallAudioSemantic:
    """Normalized meaning of one completed user call turn."""

    transcript: str | None = None
    emotion: str | None = None
    sound_description: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "transcript", _clean_optional(self.transcript))
        object.__setattr__(self, "emotion", _clean_optional(self.emotion))
        object.__setattr__(self, "sound_description", _clean_optional(self.sound_description))
        if self.transcript is None and self.emotion is None and self.sound_description is None:
            raise ValueError("a call audio semantic requires transcript, emotion, or sound_description")

    def render(self) -> str:
        """Render the exact Agent-facing text specified for call audio."""
        if self.transcript is not None:
            if self.emotion is not None:
                text = f"用户带着{self.emotion}的情绪说：“{self.transcript}”"
            else:
                text = f"用户说：“{self.transcript}”"
            if self.sound_description is not None:
                text += f"；{self.sound_description}"
            return text

        text = self.sound_description or ""
        if self.emotion is not None:
            text = f"{text}；情绪：{self.emotion}" if text else f"情绪：{self.emotion}"
        return text
