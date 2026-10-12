"""Factories for isolated realtime speech sessions."""

from __future__ import annotations

from uuid import UUID

from .aliyun import AliyunRealtimeSpeechSession, Connector
from .config import AliyunRealtimeSpeechConfig, RealtimeSpeechConfigError, RealtimeSpeechUnavailable
from .contracts import RealtimeSpeechSession


class AliyunRealtimeSpeechSessionFactory:
    def __init__(
        self,
        config: AliyunRealtimeSpeechConfig | None,
        *,
        connector: Connector | None = None,
        call_metrics=None,
    ) -> None:
        self._config = config
        self._connector = connector
        self._call_metrics = call_metrics

    @classmethod
    def from_mapping(
        cls, value: object, *, connector: Connector | None = None, call_metrics=None
    ) -> AliyunRealtimeSpeechSessionFactory:
        if not isinstance(value, dict):
            raise RealtimeSpeechConfigError("realtime speech provider config must be an object")
        enabled = value.get("enabled", False)
        if type(enabled) is not bool:
            raise RealtimeSpeechConfigError("realtime speech enabled must be a boolean")
        if not enabled:
            return cls(None, connector=connector, call_metrics=call_metrics)
        return cls(AliyunRealtimeSpeechConfig.from_mapping(value), connector=connector, call_metrics=call_metrics)

    async def create(self, call_id: UUID) -> RealtimeSpeechSession:
        if self._config is None:
            raise RealtimeSpeechUnavailable("realtime speech capability is unavailable")
        return AliyunRealtimeSpeechSession(
            self._config, connector=self._connector, call_id=call_id, call_metrics=self._call_metrics
        )

    @property
    def is_configured(self) -> bool:
        return self._config is not None
