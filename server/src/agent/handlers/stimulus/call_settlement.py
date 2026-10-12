"""Plan call settlement actions through the real Agent handle entry."""

import src.domain.agent as d
from src.agent.processing.plan_emitter import ActionPlanDraft, PlanEmitter


class CallSettlementRequestedHandler:
    async def handle(self, request: d.HandleStimulusRequest, plans: PlanEmitter) -> d.HandlingReport:
        stimulus = request.stimulus
        if not isinstance(stimulus, d.CallSettlementRequested):
            raise TypeError("CallSettlementRequestedHandler requires CallSettlementRequested")
        user_id = stimulus.user_id
        if user_id is None:
            raise ValueError("call settlement requires user identity")
        await plans.emit(
            ActionPlanDraft(
                source_stimulus_ids=(stimulus.stimulus_id,),
                actions=(
                    d.SummarizeCall(
                        action_id=f"{request.request_id}-summary",
                        user_id=user_id,
                        final_snapshot=stimulus.final_snapshot,
                    ),
                    d.MaintainCall(
                        action_id=f"{request.request_id}-maintenance",
                        user_id=user_id,
                        final_snapshot=stimulus.final_snapshot,
                        settlement_input_digest=stimulus.settlement_input_digest,
                    ),
                ),
            )
        )
        return d.HandlingReport(
            request_id=request.request_id,
            request_status=d.HandlingRequestStatus.COMPLETED,
            trigger_stimulus_id=stimulus.stimulus_id,
            basis_interaction_revision=request.interaction.interaction_revision,
            considered_pending_stimulus_ids=(),
            consumed_pending_stimulus_ids=(),
            retained_pending_stimulus_ids=(),
            emitted_plan_ids=tuple(plans.accepted_ids),
            error_code=None,
            retryable=False,
        )
