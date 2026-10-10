"""Factories for isolated realtime speech sessions."""

from __future__ import annotations

from uuid import UUID

from .aliyun import AliyunRealtimeSpeechSession, Connector
from .config import AliyunRealtimeSpeechConfig, RealtimeSpeechConfigError, RealtimeSpeechUnavailable
from .contracts import RealtimeSpeechSession


class AliyunRealtimeSpeechSessionFactory:
    def __init__(self, config: AliyunRealtimeSpeechConfig | None, *, connector: Connector | None = None) -> None:
        self._config = config
        self._connector = connector

    @classmethod
    def from_mapping(cls, value: object, *, connector: Connector | None = None) -> AliyunRealtimeSpeechSessionFactory:
        if not isinstance(value, dict):
            raise RealtimeSpeechConfigError("realtime speech provider config must be an object")
        enabled = value.get("enabled", False)
        if type(enabled) is not bool:
            raise RealtimeSpeechConfigError("realtime speech enabled must be a boolean")
        if not enabled:
            return cls(None, connector=connector)
        return cls(AliyunRealtimeSpeechConfig.from_mapping(value), connector=connector)

    async def create(self, call_id: UUID) -> RealtimeSpeechSession:
        del call_id
        if self._config is None:
            raise RealtimeSpeechUnavailable("realtime speech capability is unavailable")
        return AliyunRealtimeSpeechSession(self._config, connector=self._connector)
