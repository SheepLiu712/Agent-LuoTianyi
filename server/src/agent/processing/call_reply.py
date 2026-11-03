"""处理器侧的通话草稿筛选；生成仍由共享回复技能负责。"""

from contextlib import aclosing

from src.infrastructure.observability.call_reply_timing import mark_reply_phase


async def generate_call_reply(
    reply, invocation, *, reply_topic, user_context, conversation_history, memory_pool, on_drafts=None
):
    drafts = []
    async with aclosing(
        reply.generate(
            invocation.character_id,
            scene="call",
            reply_topic=reply_topic,
            user_context=user_context,
            conversation_history=conversation_history,
            fact_hits=[],
            memory_hits=list(memory_pool),
            sing_plan=None,
        )
    ) as stream:
        async for draft in stream:
            if draft.sing is None and draft.content.strip() and draft.sound_content.strip():
                mark_reply_phase("reply_generated")
                drafts.append(draft)
                if on_drafts is not None:
                    await on_drafts((draft,))
    return tuple(drafts)
