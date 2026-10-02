"""主动刺激处理器。"""

from datetime import datetime
from uuid import uuid4

import src.domain.agent as d
from src.agent.context import ConversationEntry, TextContent
from src.agent.processing.plan_emitter import ActionPlanDraft, PlanEmitter
from src.agent.processing.reply_delivery import build_reply_delivery, render_conversation_history
from src.agent.skills.cognitive import ResponseCompositionSkill
from src.agent.skills.expression.prepared_speech import PreparedSpeechCatalog
from src.agent.skills.invocation import handling_invocation
from src.utils.logger import get_logger


class FirstLoginHandler:
    """按配置顺序持久化并交付首次登录预制欢迎。"""

    def __init__(
        self,
        *,
        prepared_names: tuple[str, ...],
        prepared_speech: PreparedSpeechCatalog,
        composition: ResponseCompositionSkill,
    ) -> None:
        self._prepared_names = prepared_names
        self._prepared_speech = prepared_speech
        self._composition = composition
        self._logger = get_logger(__name__)

    async def handle(
        self,
        request: d.HandleStimulusRequest,
        plans: PlanEmitter,
    ) -> d.HandlingReport:
        """处理首次欢迎或到期提醒，并把内容交付为正常 Say 计划。"""
        stimulus = request.stimulus
        if not isinstance(stimulus, d.ProactivePromptDue):
            raise TypeError("FirstLoginHandler requires ProactivePromptDue")
        if stimulus.reason.value != "first_login":
            context = plans.context
            plans.set_interruptible(True)
            drafts = await self._composition.compose(
                handling_invocation(request, context),
                user_context=context.user.read(),
                reply_topic=self._reminder_topic(stimulus),
                conversation_history=render_conversation_history(context.conversation.read()),
                excluded_segments=set(),
            )
            if request.cancellation.is_cancelled:
                return self._report(request, plans, status=d.HandlingRequestStatus.CANCELLED)
            entries, actions = build_reply_delivery(request, tuple(drafts), prefix="reminder")
            if not actions:
                return self._report(request, plans)
            plans.set_interruptible(False)
            await context.conversation.append(entries)
            await plans.emit(
                ActionPlanDraft(
                    source_stimulus_ids=(stimulus.stimulus_id,),
                    actions=actions,
                )
            )
            return self._report(request, plans)

        for name in self._prepared_names:
            try:
                prepared = self._prepared_speech.get(plans.context.identity.character_id, name)
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

            await plans.context.conversation.append(
                (
                    ConversationEntry(
                        entry_id=str(uuid4()),
                        timestamp=datetime.now(),  # noqa: DTZ005 - conversation storage uses local naive timestamps
                        source="agent",
                        content=TextContent(prepared.text),
                    ),
                )
            )
            await plans.emit(
                ActionPlanDraft(
                    source_stimulus_ids=(stimulus.stimulus_id,),
                    actions=(
                        d.Say(
                            action_id=str(uuid4()),
                            content=prepared.text,
                            sound_content=None,
                            prepared_audio_ref=d.MediaRef(media_id=name),
                            tone=d.Tone(value="normal"),
                            expression=d.ChangeExpression(expression_id="normal"),
                            delivery=d.OutputDelivery.CONVERSATION,
                        ),
                    ),
                )
            )

        return self._report(request, plans)

    @staticmethod
    def _reminder_topic(stimulus: d.ProactivePromptDue) -> str:
        """从 Stage 提供的提醒事实生成只供角色回复生成器使用的内部话题。"""
        reasons = stimulus.reason.value.split("+")
        labels = {
            "holiday": "节日",
            "travel": "旅行见闻",
            "new_song": "新歌",
            "birthday": "生日",
            "anniversary": "纪念日",
        }
        subjects = "、".join(labels.get(reason, reason) for reason in reasons)
        return f"有一项到期提醒（{subjects}），请自然地告诉用户并关心用户的安排。"

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
