"""One call-wide reminder; interrupted attempts never count as delivery."""

from dataclasses import dataclass
from enum import Enum

import src.domain.agent as d


class WarningState(str, Enum):
    """同一次通话提示的交付状态，独立于用户待回复批次。"""

    NOT_DUE = "not_due"
    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    DELIVERED = "delivered"
    FAILED = "failed"


@dataclass
class CallWarning:
    """保存当前提示尝试；打断后可重试，成功或生成失败后不再调度。"""

    state: WarningState = WarningState.NOT_DUE
    request_id: str | None = None
    report: d.HandlingReport | None = None

    def due(self) -> None:
        if self.state is WarningState.NOT_DUE:
            self.state = WarningState.PENDING

    def begin(self, request_id: str) -> None:
        if self.state is not WarningState.PENDING:
            raise RuntimeError("warning is not pending")
        self.state = WarningState.IN_FLIGHT
        self.request_id, self.report = request_id, None

    def interrupt(self, *, playback_succeeded: bool) -> None:
        if self.state is WarningState.IN_FLIGHT and not playback_succeeded:
            self.state = WarningState.PENDING
            self.request_id, self.report = None, None

    def finish(self, *, success: bool) -> None:
        self.state = WarningState.DELIVERED if success else WarningState.FAILED
