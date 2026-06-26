from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.agent.main_chat import MainChat, OneResponseLine
    from src.subconscious.attention import TopicAttentionPlan


@dataclass(frozen=True)
class UserExpressionContext:
    nickname: str
    description: str = ""
    preference_context: str = ""


class ResponseRealizer:
    """Turns a conscious attention plan into legacy response line objects."""

    def __init__(self, main_chat: "MainChat") -> None:
        self.main_chat = main_chat

    async def realize_topic_plan(
        self,
        *,
        plan: "TopicAttentionPlan",
        user_context: UserExpressionContext,
    ) -> list["OneResponseLine"]:
        return await self.main_chat.generate_response(
            reply_topic=plan.topic_content,
            user_nickname=user_context.nickname,
            user_description=user_context.description,
            preference_context=user_context.preference_context,
            conversation_history=plan.conversation_history,
            fact_hits=plan.fact_hits,
            memory_hits=plan.memory_hits,
            sing_plan=plan.sing_plan,
        )
