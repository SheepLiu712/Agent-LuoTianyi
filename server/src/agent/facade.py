"""按角色绑定的两接口门面及空处理器装配的入口校验。"""
from src.domain.agent import (
    ActionExecutionStatus, ActionPlan, ActionPlanSink, ActionResult, AgentOutputSink,
    ExecutionContext, ExecutionErrorCode, ExecutionReport, ExecutionStatus,
    HandleStimulusRequest, HandlingErrorCode, HandlingReport, HandlingRequestStatus,
)
from src.utils.logger import get_logger


class Agent:
    """角色的业务入口，通过请求处理和计划执行返回强类型报告。

    由 AgentRuntime 绑定角色并管理接受状态。当前生产装配没有业务处理器，
    合法且未取消的调用返回 UNSUPPORTED；不触发模型、能力或 sink。
    """

    __slots__ = ("_character_id", "_accepting", "_logger")

    def __init__(self, *, character_id: str) -> None:
        """由运行时创建指定角色的门面；角色 ID 必须为非空白字符串。"""
        if not isinstance(character_id, str) or not character_id.strip():
            raise ValueError("Agent requires a nonblank character_id")
        self._character_id = character_id
        self._accepting = True
        self._logger = get_logger(__name__)

    def _stop_accepting(self) -> None:
        self._accepting = False

    async def handle_stimulus(
        self, request: HandleStimulusRequest, plan_sink: ActionPlanSink,
    ) -> HandlingReport:
        """校验角色目标和取消状态，返回保留全部 pending 的入口报告。

        request 是当前交互请求，plan_sink 是此次调用的异步计划接收器。
        角色不匹配、已关闭或未注册刺激通过报告的稳定错误码表达；已取消
        返回 CANCELLED。参数类型错误抛出 TypeError，本版不向 sink 输出。
        """
        if not isinstance(request, HandleStimulusRequest):
            raise TypeError("request must be HandleStimulusRequest")
        self._check_sink(plan_sink)
        status = HandlingRequestStatus.FAILED
        stimuli = (request.stimulus, *request.interaction.pending_stimuli)
        if any(self._character_id not in item.target_character_ids for item in stimuli):
            error = HandlingErrorCode.CONTRACT_SNAPSHOT_MISMATCH
        elif not self._accepting:
            error = HandlingErrorCode.DEPENDENCY_UNAVAILABLE
        elif request.cancellation.is_cancelled:
            status, error = HandlingRequestStatus.CANCELLED, None
        else:
            error = HandlingErrorCode.UNSUPPORTED_STIMULUS
        pending = tuple(item.stimulus_id for item in request.interaction.pending_stimuli)
        report = HandlingReport(
            request_id=request.request_id, request_status=status,
            trigger_stimulus_id=request.stimulus.stimulus_id,
            basis_interaction_revision=request.interaction.interaction_revision,
            considered_pending_stimulus_ids=pending, consumed_pending_stimulus_ids=(),
            retained_pending_stimulus_ids=pending, emitted_plan_ids=(), reconsider_at=None,
            error_code=error, retryable=False,
        )
        self._record(request.request_id, request.interaction.interaction_id, status, error)
        return report

    async def realize_action_plan(
        self, plan: ActionPlan, execution_context: ExecutionContext, output_sink: AgentOutputSink,
    ) -> ExecutionReport:
        """校验计划角色、交互和修订，返回全部行动尚未开始的执行报告。

        execution_context 提供执行身份与共享取消令牌，output_sink 接收输出。
        不匹配、过时、关闭及未注册行动通过报告表达；取消使用 CANCELLED。
        参数类型错误抛出 TypeError，本版不执行行动或向 sink 输出。
        """
        if not isinstance(plan, ActionPlan) or not isinstance(execution_context, ExecutionContext):
            raise TypeError("plan and execution_context must be domain objects")
        self._check_sink(output_sink)
        status = ExecutionStatus.FAILED
        if (plan.target_character_id != self._character_id
                or plan.interaction_id != execution_context.interaction_id):
            error = ExecutionErrorCode.CONTRACT_MISMATCH
        elif plan.basis_interaction_revision != execution_context.current_interaction_revision:
            error = ExecutionErrorCode.STALE_INTERACTION
        elif not self._accepting:
            error = ExecutionErrorCode.DEPENDENCY_UNAVAILABLE
        elif execution_context.cancellation.is_cancelled:
            status, error = ExecutionStatus.CANCELLED, ExecutionErrorCode.CANCELLED
        else:
            error = ExecutionErrorCode.UNSUPPORTED_ACTION
        report = ExecutionReport(
            execution_id=execution_context.execution_id, plan_id=plan.plan_id, status=status,
            action_results=tuple(ActionResult(
                action_id=action.action_id, status=ActionExecutionStatus.NOT_STARTED,
                error_code=None, irreversible_effect_committed=False, effect_ref=None,
            ) for action in plan.actions),
            output_started=False, error_code=error, retryable=False,
        )
        self._record(execution_context.execution_id, execution_context.interaction_id, status, error)
        return report

    @staticmethod
    def _check_sink(sink: object) -> None:
        if not callable(getattr(sink, "emit", None)):
            raise TypeError("sink must provide emit")

    def _record(self, call_id, interaction_id, status, error) -> None:
        self._logger.info(
            "Agent settlement character_id=%s call_id=%s interaction_id=%s status=%s error_code=%s",
            self._character_id, call_id, interaction_id, status.value, error.value if error else None,
        )
