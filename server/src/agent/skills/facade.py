"""共享技能的统一装配和查询入口。"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING, TypeVar, cast

from .conversation.compaction import ConversationCompactionSkill

if TYPE_CHECKING:
    from src.utils.llm_service import LLMService

SkillT = TypeVar("SkillT")


class Skills:
    """持有一个 AgentRuntime 内所有角色共享的技能实例。"""

    def __init__(self, config: dict[str, Any], llm_service: LLMService) -> None:
        """按 config 的技能分组初始化实例，并派发模型依赖 llm_service。"""
        self._skills: dict[type, object] = {
            ConversationCompactionSkill: ConversationCompactionSkill(
                config.get("conversation_compaction", {}), llm_service,
            ),
        }

    def get(self, skill_type: type[SkillT]) -> SkillT:
        """按技能类型返回共享实例；非类型参数抛 TypeError，未注册类型抛 KeyError。"""
        if not isinstance(skill_type, type):
            raise TypeError("skill_type 应为技能类型")
        return cast(SkillT, self._skills[skill_type])
