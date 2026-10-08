"""用户提出建立新关系后的当前交互上下文更新。"""

import src.domain.agent as d
from src.agent.processing.plan_emitter import PlanEmitter


class NewRelationshipProposeHandler:
    """默认接受关系提议，并从数据库同步已经保存的偏好。"""

    async def handle(self, request: d.HandleStimulusRequest, plans: PlanEmitter) -> d.HandlingReport:
        if not isinstance(request.stimulus, d.NewRelationshipPropose):
            raise TypeError("NewRelationshipProposeHandler 只处理 NewRelationshipPropose")
        if request.stimulus.user_id is None:
            raise ValueError("关系提议需要用户身份")
        # HTTP 已保存偏好；读取最新值可避免并发提议以旧值覆盖新值。
        await plans.context.user.refresh_preferences()
        pending = tuple(item.stimulus_id for item in request.interaction.pending_stimuli)
        return d.HandlingReport(
            request_id=request.request_id,
            trigger_stimulus_id=request.stimulus.stimulus_id,
            basis_interaction_revision=request.interaction.interaction_revision,
            request_status=d.HandlingRequestStatus.COMPLETED,
            considered_pending_stimulus_ids=pending,
            consumed_pending_stimulus_ids=(),
            retained_pending_stimulus_ids=pending,
            emitted_plan_ids=(),
            error_code=None,
            retryable=False,
        )
