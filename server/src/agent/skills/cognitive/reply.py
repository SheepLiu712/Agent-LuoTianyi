"""聊天与通话共用的回复技能：调用生成流程并逐段交付行动计划。"""

import src.domain.agent as d
from src.agent.processing.plan_emitter import ActionPlanDraft, _DeliveryCancelled
from src.agent.processing.reply_delivery import build_reply_delivery
from src.domain.call import CallAudioRoute, CallSpeechDelivery
from src.utils.logger import get_logger

from ._streaming_reply_parser import StreamingReplyParser


class ReplySkill:
    """生成函数通过 on_drafts 交付增量；返回值包含全部草稿，包括完整演唱指令。"""

    @staticmethod
    async def generate_stream(llm, prompt, response_parser, *, sing_plan=None, on_drafts=None):
        if sing_plan is not None:
            response = await llm.generate_response(**prompt)
            return response_parser.parse(response, sing_plan)
        parser = StreamingReplyParser(response_parser)
        drafts = []

        async def accept(items):
            drafts.extend(items)
            if items and on_drafts is not None:
                await on_drafts(items)

        async def delta(text):
            await accept(parser.feed(text))

        try:
            await llm.generate_response(on_delta=delta, **prompt)
            await accept(parser.finish())
        except Exception as error:
            get_logger(__name__).error("流式回复失败 error_type={}", type(error).__name__)
            raise
        return tuple(drafts)

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
