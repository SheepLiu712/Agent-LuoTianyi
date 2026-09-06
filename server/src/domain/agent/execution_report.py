"""逐行动执行结果及其不可变汇总。"""
from dataclasses import dataclass

from ._realization_contract import RealizationContractErrorCode as _Code, _Value
from .realization_enums import ActionExecutionStatus, EffectKind, ExecutionErrorCode, ExecutionStatus


def _status_error_valid(status, error):
    if status.value == "failed":
        return error is not None and error is not ExecutionErrorCode.CANCELLED
    if status.value == "cancelled":
        return error is ExecutionErrorCode.CANCELLED
    return error is None


@dataclass(frozen=True, slots=True, kw_only=True)
class EffectRef(_Value):
    """已提交动态、评论或学歌任务的稳定引用，仅保存类别和非空白身份。"""
    kind: EffectKind
    effect_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ActionResult(_Value):
    """单项行动的状态、错误和已提交效果；失败或取消可保留部分效果。

    NOT_STARTED 没有已提交效果；提供效果引用时必须标明已提交。
    """
    _code = _Code.CONTRACT_INVALID_EXECUTION_REPORT
    action_id: str
    status: ActionExecutionStatus
    error_code: ExecutionErrorCode | None
    irreversible_effect_committed: bool
    effect_ref: EffectRef | None

    def __post_init__(self):
        _Value.__post_init__(self)
        self._require(_status_error_valid(self.status, self.error_code), "Invalid action error")
        self._require(self.effect_ref is None or self.irreversible_effect_committed, "Uncommitted effect reference")
        if self.status is ActionExecutionStatus.NOT_STARTED:
            self._require(not self.irreversible_effect_committed, "Unstarted action has effect")


@dataclass(frozen=True, kw_only=True)
class ExecutionReport(_Value):
    """执行终态与按计划排列的非空逐项结果，验证报告内部的顺序和状态关系。

    output_started 与 retryable 是显式事实；构造不验证外部投递或效果真实提交。
    """
    _code = _Code.CONTRACT_INVALID_EXECUTION_REPORT
    execution_id: str
    plan_id: str
    status: ExecutionStatus
    action_results: tuple[ActionResult, ...]
    output_started: bool
    error_code: ExecutionErrorCode | None
    retryable: bool

    @property
    def irreversible_effect_committed(self) -> bool:
        """是否有任一行动已提交不可回滚效果，由逐项结果计算。"""
        return any(item.irreversible_effect_committed for item in self.action_results)

    def __post_init__(self):
        _Value.__post_init__(self)
        ids = tuple(item.action_id for item in self.action_results)
        self._require(bool(ids) and len(set(ids)) == len(ids), "Invalid result identities")
        self._require(_status_error_valid(self.status, self.error_code), "Invalid execution error")
        stopped = False
        for item in self.action_results:
            if stopped:
                self._require(item.status is ActionExecutionStatus.NOT_STARTED, "Action after stop")
            if item.status in (ActionExecutionStatus.FAILED, ActionExecutionStatus.CANCELLED):
                self._require(item.status.value == self.status.value and item.error_code is self.error_code,
                              "Action and execution disagree")
                stopped = True
            elif item.status is ActionExecutionStatus.NOT_STARTED:
                stopped = True
            if self.status is ExecutionStatus.COMPLETED:
                self._require(item.status in (ActionExecutionStatus.COMPLETED, ActionExecutionStatus.ALREADY_COMPLETED),
                              "Incomplete action in completed execution")
