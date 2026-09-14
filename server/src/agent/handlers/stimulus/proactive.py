"""主动刺激处理器。"""

from datetime import datetime
from uuid import uuid4

import src.domain.agent as d
from src.agent.context import ConversationEntry, TextContent
from src.agent.processing.plan_emitter import ActionPlanDraft, PlanEmitter
from src.resources.prepared_speech import PreparedSpeechResources
from src.utils.logger import get_logger


class FirstLoginHandler:
    """按配置顺序持久化并交付首次登录预制欢迎。"""

    def __init__(
        self,
        *,
        prepared_names: tuple[str, ...],
        prepared_speech: PreparedSpeechResources,
    ) -> None:
        self._prepared_names = prepared_names
        self._prepared_speech = prepared_speech
        self._logger = get_logger(__name__)

    async def handle(
        self,
        request: d.HandleStimulusRequest,
        plans: PlanEmitter,
    ) -> d.HandlingReport:
        """处理 first_login；其他主动原因保持未实现。"""
        stimulus = request.stimulus
        if not isinstance(stimulus, d.ProactivePromptDue):
            raise TypeError("FirstLoginHandler requires ProactivePromptDue")
        if stimulus.reason.value != "first_login":
            return self._report(
                request,
                plans,
                status=d.HandlingRequestStatus.FAILED,
                error_code=d.HandlingErrorCode.UNSUPPORTED_INTERACTION,
            )

        for name in self._prepared_names:
            try:
                prepared = self._prepared_speech.get(name)
            except KeyError:
                self._logger.error(
                    "First-login prepared speech missing name=%s request_id=%s",
                    name,
                    request.request_id,
                )
                return self._report(
                    request,
                    plans,
                    status=d.HandlingRequestStatus.FAILED,
                    error_code=d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE,
                )

            await plans.context.conversation.append((ConversationEntry(
                entry_id=str(uuid4()),
                timestamp=datetime.now(),
                source="agent",
                content=TextContent(prepared.text),
            ),))
            await plans.emit(ActionPlanDraft(
                source_stimulus_ids=(stimulus.stimulus_id,),
                actions=(d.Say(
                    action_id=str(uuid4()),
                    content=prepared.text,
                    sound_content=None,
                    prepared_audio_ref=d.MediaRef(media_id=name),
                    tone=d.Tone(value="normal"),
                    expression=d.ChangeExpression(expression_id=prepared.expression),
                    delivery=d.OutputDelivery.CONVERSATION,
                ),),
            ))

        return self._report(request, plans)

    @staticmethod
    def _report(
        request: d.HandleStimulusRequest,
        plans: PlanEmitter,
        *,
        status: d.HandlingRequestStatus = d.HandlingRequestStatus.COMPLETED,
        error_code: d.HandlingErrorCode | None = None,
    ) -> d.HandlingReport:
        return d.HandlingReport(
            request_id=request.request_id,
            trigger_stimulus_id=request.stimulus.stimulus_id,
            basis_interaction_revision=request.interaction.interaction_revision,
            request_status=status,
            considered_pending_stimulus_ids=(),
            consumed_pending_stimulus_ids=(),
            retained_pending_stimulus_ids=(),
            emitted_plan_ids=tuple(plans.accepted_ids),
            retryable=False,
            error_code=error_code,
        )
