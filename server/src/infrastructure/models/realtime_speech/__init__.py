"""Provider-neutral realtime speech session contracts."""

from .aliyun import AliyunRealtimeSpeechSession
from .config import AliyunRealtimeSpeechConfig, RealtimeSpeechConfigError, RealtimeSpeechUnavailable
from .contracts import (
    AmbientAudio,
    AudioFrame,
    ProviderFailed,
    RealtimeSpeechConfig,
    RealtimeSpeechEvent,
    RealtimeSpeechSession,
    RealtimeSpeechSessionFactory,
    SpeechStarted,
    SpeechStopped,
    TranscriptUpdated,
    TurnCompleted,
    TurnInvalid,
)
from .factory import AliyunRealtimeSpeechSessionFactory

__all__ = [
    "AmbientAudio",
    "AliyunRealtimeSpeechConfig",
    "RealtimeSpeechConfigError",
    "AliyunRealtimeSpeechSession",
    "AliyunRealtimeSpeechSessionFactory",
    "AudioFrame",
    "ProviderFailed",
    "RealtimeSpeechConfig",
    "RealtimeSpeechEvent",
    "RealtimeSpeechSession",
    "RealtimeSpeechSessionFactory",
    "RealtimeSpeechUnavailable",
    "SpeechStarted",
    "SpeechStopped",
    "TranscriptUpdated",
    "TurnCompleted",
    "TurnInvalid",
]
