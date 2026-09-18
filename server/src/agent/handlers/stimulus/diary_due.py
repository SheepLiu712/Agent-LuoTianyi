"""日记规划事实的生成决策。"""

from __future__ import annotations

from uuid import uuid4

import src.domain.agent as d
from src.agent.processing.plan_emitter import ActionPlanDraft, PlanEmitter
from src.agent.skills.expression.diary_writing import DiaryWritingSkill


class DiaryPlanningDueHandler:
    def __init__(self, writing: DiaryWritingSkill) -> None:
        self._writing = writing

    async def handle(
        self, request: d.HandleStimulusRequest, plans: PlanEmitter,
    ) -> d.HandlingReport:
        stimulus = request.stimulus
        if not isinstance(stimulus, d.DiaryPlanningDue):
            raise TypeError("DiaryPlanningDueHandler 只处理 DiaryPlanningDue")
        if not self._writing.available():
            return self._report(request, d.HandlingRequestStatus.FAILED,
                                d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE)
        body = (await self._writing.compose(
            stimulus.owner_user_id, stimulus.local_date,
        )).strip()
        if not body:
            return self._report(request, d.HandlingRequestStatus.FAILED,
                                d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE)
        receipt = await plans.emit(ActionPlanDraft(
            source_stimulus_ids=(stimulus.stimulus_id,),
            actions=(d.WriteDiary(
                action_id=str(uuid4()), owner_user_id=stimulus.owner_user_id,
                local_date=stimulus.local_date, body=body,
            ),),
        ))
        return self._report(
            request, d.HandlingRequestStatus.COMPLETED, None,
            consumed=(stimulus.stimulus_id,), plans=(receipt.plan_id,),
        )

    @staticmethod
    def _report(
        request: d.HandleStimulusRequest,
        status: d.HandlingRequestStatus,
        error_code: d.HandlingErrorCode | None,
        *,
        consumed: tuple[str, ...] = (),
        plans: tuple[str, ...] = (),
    ) -> d.HandlingReport:
        pending = tuple(item.stimulus_id for item in request.interaction.pending_stimuli)
        return d.HandlingReport(
            request_id=request.request_id,
            trigger_stimulus_id=request.stimulus.stimulus_id,
            basis_interaction_revision=request.interaction.interaction_revision,
            request_status=status,
            considered_pending_stimulus_ids=pending,
            consumed_pending_stimulus_ids=consumed,
            retained_pending_stimulus_ids=tuple(item for item in pending if item not in consumed),
            emitted_plan_ids=plans,
            error_code=error_code,
            retryable=False,
        )
