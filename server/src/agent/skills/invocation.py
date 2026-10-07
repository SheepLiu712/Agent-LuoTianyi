"""从 Agent 两个入口构造一次性的 Skill 调用上下文。"""

from __future__ import annotations

import src.domain.agent as d
from src.agent.context import InteractionContext
from src.agent.skills.contracts import SkillInvocation


def handling_invocation(
    request: d.HandleStimulusRequest,
    context: InteractionContext,
    *,
    user_id: str | None = None,
) -> SkillInvocation:
    """使用 Stage 已校验的交互身份构造认知 Skill 调用上下文。"""
    identity = context.identity
    return SkillInvocation(
        character_id=identity.character_id,
        user_id=identity.user_id if user_id is None else user_id,
        interaction_id=identity.interaction_id,
        cancellation=request.cancellation,
    )


def execution_invocation(
    character_id: str,
    context: d.ExecutionContext,
    *,
    user_id: str | None = None,
) -> SkillInvocation:
    """使用计划目标角色及本次执行令牌构造效果 Skill 调用上下文。"""
    return SkillInvocation(
        character_id=character_id,
        user_id=user_id,
        interaction_id=context.interaction_id,
        cancellation=context.cancellation,
    )
