"""Shared construction helpers for Agent Skill interface tests."""

import src.domain.agent as d
from src.agent.skills import SkillInvocation


def invocation(
    character_id: str = "luotianyi",
    user_id: str | None = "u",
    interaction_id: str = "i",
    cancellation: d.CancellationToken | None = None,
) -> SkillInvocation:
    return SkillInvocation(
        character_id=character_id,
        user_id=user_id,
        interaction_id=interaction_id,
        cancellation=cancellation or d.CancellationToken(),
    )
