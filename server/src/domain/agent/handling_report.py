"""不可变的 handle 处理结果及逐刺激 ID 的结算约束。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from inspect import Signature, signature

from ._handle_input_contract import _aware, _nonblank, _revision


class HandlingRequestStatus(str, Enum):
    """请求的结束状态：正常完成、已取消或失败；与逐条内容的消费结果分别表达。"""

    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class HandlingErrorCode(str, Enum):
    """合法报告记录的处理失败原因，覆盖输入契约、处理能力、接收端和依赖错误。"""

    CONTRACT_INVALID_STIMULUS = "CONTRACT_INVALID_STIMULUS"
    CONTRACT_UNSUPPORTED_SCHEMA = "CONTRACT_UNSUPPORTED_SCHEMA"
    CONTRACT_SNAPSHOT_MISMATCH = "CONTRACT_SNAPSHOT_MISMATCH"
    UNSUPPORTED_STIMULUS = "UNSUPPORTED_STIMULUS"
    UNSUPPORTED_INTERACTION = "UNSUPPORTED_INTERACTION"
    STALE_INTERACTION = "STALE_INTERACTION"
    SINK_CLOSED = "SINK_CLOSED"
    BACKPRESSURE_TIMEOUT = "BACKPRESSURE_TIMEOUT"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class HandlingReportErrorCode(str, Enum):
    """报告自身构造失败的稳定错误码。"""

    CONTRACT_INVALID_HANDLING_REPORT = "CONTRACT_INVALID_HANDLING_REPORT"


class InvalidHandlingReportError(ValueError):
    """报告字段或结算关系非法时抛出的构造错误，提供稳定且只读的 code。"""

    @property
    def code(self) -> HandlingReportErrorCode:
        """返回固定的 CONTRACT_INVALID_HANDLING_REPORT 构造错误码。"""
        return HandlingReportErrorCode.CONTRACT_INVALID_HANDLING_REPORT


class _ReportMeta(type):
    @property
    def __signature__(cls) -> Signature:
        constructor = signature(cls.__init__)
        return constructor.replace(parameters=tuple(constructor.parameters.values())[1:])

    def __call__(cls, *args, **kwargs):
        try:
            signature(cls).bind(*args, **kwargs)
        except TypeError as error:
            raise InvalidHandlingReportError("Invalid or missing report arguments") from error
        return super().__call__(*args, **kwargs)


def _require(condition: bool, field: str) -> None:
    if not condition:
        raise InvalidHandlingReportError(f"Invalid {field}")


def _identity_tuple(value: object, field: str) -> None:
    _require(isinstance(value, tuple), field)
    _require(all(_nonblank(item) for item in value), field)
    _require(len(set(value)) == len(value), field)


_INPUT_CONTRACT_ERRORS = frozenset({
    HandlingErrorCode.CONTRACT_INVALID_STIMULUS,
    HandlingErrorCode.CONTRACT_UNSUPPORTED_SCHEMA,
    HandlingErrorCode.CONTRACT_SNAPSHOT_MISMATCH,
})


@dataclass(frozen=True, slots=True, kw_only=True)
class HandlingReport(metaclass=_ReportMeta):
    """单次请求的不可变处理报告，以显式关键字记录状态、结算和已接收计划 ID。

    request_id 和 trigger_stimulus_id 标识请求与触发刺激，basis_interaction_revision
    记录处理依据的交互修订。considered_pending_stimulus_ids 是本次考虑的内容，
    consumed_pending_stimulus_ids 与 retained_pending_stimulus_ids 必须互斥、
    合起来覆盖 considered，且各自保持其中的相对顺序；所有 ID 元组内部唯一。

    emitted_plan_ids 保留计划被接收的顺序。reconsider_at 为 None 或带时区的
    重评时间，提供时间时 retained 必须非空。FAILED 必须附 HandlingErrorCode，
    其他状态的 error_code 为 None；输入契约错误要求 consumed 为空。
    retryable 是调用方显式提供的布尔值。

    构造器校验报告字段和内部关系，非法组合抛出 InvalidHandlingReportError。
    """

    request_id: str
    request_status: HandlingRequestStatus
    trigger_stimulus_id: str
    basis_interaction_revision: int
    considered_pending_stimulus_ids: tuple[str, ...]
    consumed_pending_stimulus_ids: tuple[str, ...]
    retained_pending_stimulus_ids: tuple[str, ...]
    emitted_plan_ids: tuple[str, ...]
    reconsider_at: datetime | None
    error_code: HandlingErrorCode | None
    retryable: bool

    def __post_init__(self) -> None:
        _require(_nonblank(self.request_id), "request_id")
        _require(isinstance(self.request_status, HandlingRequestStatus), "request_status")
        _require(_nonblank(self.trigger_stimulus_id), "trigger_stimulus_id")
        _require(_revision(self.basis_interaction_revision), "basis_interaction_revision")
        _require(type(self.retryable) is bool, "retryable")
        for field in (
            "considered_pending_stimulus_ids", "consumed_pending_stimulus_ids",
            "retained_pending_stimulus_ids", "emitted_plan_ids",
        ):
            _identity_tuple(getattr(self, field), field)

        considered = set(self.considered_pending_stimulus_ids)
        consumed = set(self.consumed_pending_stimulus_ids)
        retained = set(self.retained_pending_stimulus_ids)
        _require(not consumed.intersection(retained), "overlapping settlement")
        _require(considered == consumed.union(retained), "incomplete settlement")
        for members, ordered in (
            (consumed, self.consumed_pending_stimulus_ids),
            (retained, self.retained_pending_stimulus_ids),
        ):
            _require(
                tuple(item for item in self.considered_pending_stimulus_ids if item in members) == ordered,
                "settlement order",
            )

        if self.reconsider_at is not None:
            _require(bool(retained) and _aware(self.reconsider_at), "reconsider_at")
        if self.request_status is HandlingRequestStatus.FAILED:
            _require(isinstance(self.error_code, HandlingErrorCode), "error_code")
        else:
            _require(self.error_code is None, "error_code")
        if self.error_code in _INPUT_CONTRACT_ERRORS:
            _require(not consumed, "input contract failure consumed content")
