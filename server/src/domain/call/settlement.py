"""本次通话结束处理的值结果，不包含跨进程恢复或执行认领。"""

from dataclasses import dataclass
from enum import Enum

DEFAULT_CALL_SUMMARY = "[和用户打了一通电话]"


class CallSummarySource(str, Enum):
    GENERATED = "generated"
    CONTEXT = "context"
    DEFAULT = "default"


@dataclass(frozen=True, slots=True)
class CallEndingResult:
    """概要来源与真实维护结果；概要降级不会把维护失败改成成功。"""

    summary: str
    summary_source: CallSummarySource
    maintenance_succeeded: bool
    maintenance_turn_seq: int

    def __post_init__(self):
        if not isinstance(self.summary, str) or not self.summary.strip():
            raise ValueError("call ending summary must be nonblank")
        if not isinstance(self.summary_source, CallSummarySource):
            raise TypeError("call summary source must be CallSummarySource")
        if type(self.maintenance_succeeded) is not bool:
            raise TypeError("maintenance_succeeded must be bool")
        if type(self.maintenance_turn_seq) is not int or self.maintenance_turn_seq < 0:
            raise ValueError("invalid maintenance progress")


def fallback_call_summary(working_summary: str) -> tuple[str, CallSummarySource]:
    """只接收本次通话的工作概要；禁止调用者传入聊天种子概要。"""
    if working_summary.strip():
        return working_summary, CallSummarySource.CONTEXT
    return DEFAULT_CALL_SUMMARY, CallSummarySource.DEFAULT
