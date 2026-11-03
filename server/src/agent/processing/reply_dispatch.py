"""处理器共用的回复交付：维护交互状态、记录与行动计划。"""

import src.domain.agent as d
from src.agent.processing.plan_emitter import ActionPlanDraft, _DeliveryCancelled
from src.agent.processing.reply_delivery import build_reply_delivery
from src.domain.call import CallAudioRoute, CallSpeechDelivery


class ReplyDelivery:
    """共享无状态交付流程；不调用模型或生成回复。"""

    async def deliver(self, request, plans, generate, *, prefix, sources, call=False):
        delivered = 0
        basis = request.interaction.interaction_revision

        async def emit(drafts):
            nonlocal delivered
            if request.cancellation.is_cancelled or request.interaction.interaction_revision != basis:
                raise _DeliveryCancelled()
            offset = delivered
            delivered += len(drafts)
            if call:
                actions = tuple(
                    self.call_say(request, draft, suffix=f"{prefix}-{offset + index}")
                    for index, draft in enumerate(drafts)
                    if draft.sing is None and draft.sound_content.strip()
                )
            else:
                entries, actions = build_reply_delivery(request, tuple(drafts), prefix=f"{prefix}-{offset}-")
                if actions:
                    plans.set_interruptible(False)
                    await plans.context.conversation.append(entries)
            if actions:
                await plans.emit(ActionPlanDraft(source_stimulus_ids=sources, actions=actions))

        drafts = await generate(emit)
        # 批量生成（包括演唱）仅在完整结果就绪后交付；已交付的流式前缀不重复发送。
        await emit(drafts[delivered:])
        return drafts

    @staticmethod
    def call_say(request, draft, *, suffix, provisional=False):
        return d.Say(
            action_id=f"{request.request_id}-{suffix}",
            content=draft.content,
            sound_content=draft.sound_content,
            prepared_audio_ref=None,
            tone=d.Tone(value=draft.tone or "normal"),
            expression=d.ChangeExpression(expression_id=draft.expression) if draft.expression else None,
            delivery=d.OutputDelivery.EPHEMERAL_REACTION,
            message_id=None,
            call_delivery=CallSpeechDelivery(
                audio_route=CallAudioRoute.CALL,
                display_in_chat=False,
                is_ephemeral=True,
                provisional=provisional,
                response_id=f"{request.request_id}-{suffix}",
            ),
        )
