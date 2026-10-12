"""Content-free realtime call metrics over the existing observability store."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol
from uuid import UUID


class PipelineMetricSink(Protocol):
    def record_pipeline_span(self, **values) -> None: ...


class CallMetricName(str, Enum):
    STATE = "state"
    PROVIDER_ENDPOINT = "provider_endpoint"
    FIRST_AUDIO = "first_audio"
    FORMAL_REPLY = "formal_reply"
    TTS = "tts"
    PLAYBACK_BACKLOG = "playback_backlog"
    PLAYBACK_ACK_RETRY = "playback_ack_retry"
    INTERRUPT = "interrupt"
    STOP_CONFIRMATION = "stop_confirmation"
    RECONNECT = "reconnect"
    BUFFER = "buffer"
    SUMMARY = "summary"
    MAINTENANCE = "maintenance"
    PROVIDER_USAGE = "provider_usage"
    SETTLEMENT_ADMISSION = "settlement_admission"


class CallMetricStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    UNKNOWN = "unknown"


class CallMetricResult(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class CallCostStatus(str, Enum):
    KNOWN = "known"
    UNKNOWN = "unknown"


class CallProvider(str, Enum):
    ALIYUN = "aliyun"
    MOCK = "mock"
    UNKNOWN = "unknown"


_STATES = frozenset({"preparing", "ringing", "active", "reconnecting", "ending", "declined", "ended", "failed"})
_COUNT_FIELDS = frozenset({"seq", "buffered_bytes", "reconnect_count", "interrupt_count", "ack_retry_count"})
_NUMERIC_FIELDS = _COUNT_FIELDS | frozenset({"latency_ms", "state_duration_ms", "usage_units", "cost_microunits"})
_LABEL_FIELDS = frozenset({"state", "result", "error_code", "provider", "cost_status"})
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]{0,31}$")
_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


@dataclass(frozen=True, slots=True)
class CallMetric:
    call_id: UUID
    name: CallMetricName
    start_ts: str
    end_ts: str
    duration_ms: float
    status: CallMetricStatus = CallMetricStatus.SUCCESS
    numeric: dict[str, int | float | None] | None = None
    labels: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.call_id, UUID) or not isinstance(self.name, CallMetricName):
            raise ValueError("call metric requires fixed identity and name")
        if not isinstance(self.status, CallMetricStatus):
            raise ValueError("call metric status must use CallMetricStatus")
        self._validate_timestamp("start_ts", self.start_ts)
        self._validate_timestamp("end_ts", self.end_ts)
        self._validate_number("duration_ms", self.duration_ms, allow_none=False)
        numeric = self.numeric or {}
        labels = self.labels or {}
        if set(numeric) - _NUMERIC_FIELDS or set(labels) - _LABEL_FIELDS:
            raise ValueError("unsupported call metric field")
        for field, value in numeric.items():
            self._validate_number(field, value, allow_none=field == "cost_microunits")
            if field in _COUNT_FIELDS and value is not None and type(value) is not int:
                raise ValueError(f"{field} must be an integer")
        self._validate_labels(labels)
        if numeric.get("cost_microunits") is None and "cost_microunits" in numeric:
            if labels.get("cost_status") != CallCostStatus.UNKNOWN.value:
                raise ValueError("unknown cost requires cost_status=unknown")

    @staticmethod
    def _validate_number(field: str, value, *, allow_none: bool) -> None:
        if value is None and allow_none:
            return
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{field} must be finite and nonnegative")

    @staticmethod
    def _validate_labels(labels: dict[str, str]) -> None:
        if "state" in labels and labels["state"] not in _STATES:
            raise ValueError("invalid call state metric label")
        if "result" in labels and labels["result"] not in {item.value for item in CallMetricResult}:
            raise ValueError("invalid call result metric label")
        if "cost_status" in labels and labels["cost_status"] not in {item.value for item in CallCostStatus}:
            raise ValueError("invalid cost status metric label")
        if "provider" in labels and labels["provider"] not in {item.value for item in CallProvider}:
            raise ValueError("invalid provider metric identifier")
        if "error_code" in labels and not _ERROR_CODE.fullmatch(labels["error_code"]):
            raise ValueError("invalid stable error code")

    @staticmethod
    def _validate_timestamp(field: str, value: str) -> None:
        if not isinstance(value, str) or len(value) > 40:
            raise ValueError(f"{field} must be a bounded ISO timestamp")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"{field} must be a valid ISO timestamp") from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} must be timezone-aware")


class CallMetrics:
    def __init__(self, sink: PipelineMetricSink | None) -> None:
        self._sink = sink

    def record(self, metric: CallMetric) -> bool:
        if self._sink is None:
            return False
        try:
            self._sink.record_pipeline_span(
                trace_id=f"call:{metric.call_id}",
                span_name=f"call.{metric.name.value}",
                start_ts=metric.start_ts,
                end_ts=metric.end_ts,
                duration_ms=metric.duration_ms,
                status=metric.status.value,
                metadata={**(metric.numeric or {}), **(metric.labels or {})},
            )
            return True
        except Exception as error:
            from src.utils.logger import get_logger

            get_logger(__name__).warning(
                "Call metric sink failed call_id=%s metric=%s type=%s",
                metric.call_id,
                metric.name.value,
                type(error).__name__,
            )
            return False
