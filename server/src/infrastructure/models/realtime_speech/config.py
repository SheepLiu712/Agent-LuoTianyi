"""Configuration for realtime speech providers."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


class RealtimeSpeechUnavailable(RuntimeError):
    """Raised when the realtime speech capability is disabled."""


class RealtimeSpeechConfigError(ValueError):
    """Raised when an enabled realtime speech provider is misconfigured."""


@dataclass(frozen=True, slots=True)
class AliyunRealtimeSpeechConfig:
    """Explicit connection settings for one Aliyun realtime speech session."""

    api_key: str = field(repr=False)
    model: str
    workspace_id: str | None = None
    endpoint: str | None = None
    connect_timeout_seconds: float = 10.0
    session_timeout_seconds: float = 10.0
    close_timeout_seconds: float = 5.0
    cleanup_timeout_seconds: float = 2.0
    write_queue_size: int = 32
    event_queue_size: int = 64
    max_audio_frame_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        _required_string(self.api_key, "api_key")
        if self.api_key.startswith("$"):
            raise RealtimeSpeechConfigError("realtime speech api_key is unresolved")
        _required_string(self.model, "model")
        _optional_typed_string(self.workspace_id, "workspace_id")
        _optional_typed_string(self.endpoint, "endpoint")
        if not self.endpoint and not self.workspace_id:
            raise RealtimeSpeechConfigError("realtime speech endpoint or workspace_id is required")
        for name in ("write_queue_size", "event_queue_size", "max_audio_frame_bytes"):
            _positive_int(getattr(self, name), name)
        for name in (
            "connect_timeout_seconds",
            "session_timeout_seconds",
            "close_timeout_seconds",
            "cleanup_timeout_seconds",
        ):
            _positive_finite_number(getattr(self, name), name)

    @property
    def websocket_url(self) -> str:
        base = self.endpoint or (f"wss://{self.workspace_id}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime")
        parsed = urlparse(base)
        if parsed.scheme != "wss" or not parsed.netloc:
            raise RealtimeSpeechConfigError("realtime speech endpoint must be a secure wss URL")
        query = parse_qs(parsed.query, keep_blank_values=True)
        query["model"] = [self.model]
        return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))

    @classmethod
    def from_mapping(cls, value: object) -> AliyunRealtimeSpeechConfig:
        if not isinstance(value, dict):
            raise RealtimeSpeechConfigError("realtime speech provider config must be an object")
        return cls(
            api_key=_mapping_string(value, "api_key", required=True),
            model=_mapping_string(value, "model", required=True),
            workspace_id=_mapping_string(value, "workspace_id", required=False),
            endpoint=_mapping_string(value, "endpoint", required=False),
            connect_timeout_seconds=_mapping_number(value, "connect_timeout_seconds", 10.0),
            session_timeout_seconds=_mapping_number(value, "session_timeout_seconds", 10.0),
            close_timeout_seconds=_mapping_number(value, "close_timeout_seconds", 5.0),
            cleanup_timeout_seconds=_mapping_number(value, "cleanup_timeout_seconds", 2.0),
            write_queue_size=_mapping_int(value, "write_queue_size", 32),
            event_queue_size=_mapping_int(value, "event_queue_size", 64),
            max_audio_frame_bytes=_mapping_int(value, "max_audio_frame_bytes", 64 * 1024),
        )


def _mapping_string(value: dict[object, object], name: str, *, required: bool) -> str | None:
    raw = value.get(name)
    if raw is None and not required:
        return None
    if not isinstance(raw, str):
        raise RealtimeSpeechConfigError(f"realtime speech {name} must be a string")
    cleaned = raw.strip()
    if required and not cleaned:
        raise RealtimeSpeechConfigError(f"realtime speech {name} is required")
    return cleaned or None


def _mapping_number(value: dict[object, object], name: str, default: float) -> float:
    raw = value.get(name, default)
    _positive_finite_number(raw, name)
    return float(raw)


def _mapping_int(value: dict[object, object], name: str, default: int) -> int:
    raw = value.get(name, default)
    _positive_int(raw, name)
    return raw


def _required_string(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise RealtimeSpeechConfigError(f"realtime speech {name} is required")


def _optional_typed_string(value: object, name: str) -> None:
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise RealtimeSpeechConfigError(f"realtime speech {name} must be a non-empty string")


def _positive_int(value: object, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise RealtimeSpeechConfigError(f"realtime speech {name} must be a positive integer")


def _positive_finite_number(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RealtimeSpeechConfigError(f"realtime speech {name} must be a finite positive number")
    if not math.isfinite(value) or value <= 0:
        raise RealtimeSpeechConfigError(f"realtime speech {name} must be a finite positive number")
