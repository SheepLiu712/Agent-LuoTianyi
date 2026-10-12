"""Provider-neutral realtime speech session contracts."""

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
    TurnCompleted,
    TurnInvalid,
)

__all__ = [
    "AmbientAudio",
    "AudioFrame",
    "ProviderFailed",
    "RealtimeSpeechConfig",
    "RealtimeSpeechEvent",
    "RealtimeSpeechSession",
    "RealtimeSpeechSessionFactory",
    "SpeechStarted",
    "SpeechStopped",
    "TurnCompleted",
    "TurnInvalid",
]
