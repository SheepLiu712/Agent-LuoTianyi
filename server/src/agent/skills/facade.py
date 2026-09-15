"""共享技能的统一装配和查询入口。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar, cast

from src.agent.skills.expression.speaking import SpeakingSkill
from src.capabilities.speech.streaming import AsyncTTS

from .cognitive import ExplicitMemoryIntentSkill, TextPreprocessingSkill
from .conversation.compaction import ConversationCompactionSkill
from .expression.singing import SingingSkill

if TYPE_CHECKING:
    from src.utils.llm_service import LLMService

SkillT = TypeVar("SkillT")


class Skills:
    """持有一个 AgentRuntime 内所有角色共享的技能实例。"""

    def __init__(self, config: dict[str, Any], llm_service: LLMService, *, tts_engine: AsyncTTS,
                 preprocessing_config: dict[str, Any] | None = None,
                 explicit_memory_config: dict[str, Any] | None = None,
                 reply_composition_config: dict[str, Any] | None = None,
                 singing: object = None) -> None:
        """按 config 的技能分组初始化实例，并派发 llm_service、tts_engine 与演唱能力。

        reply_composition_config 由运行时在注册回复生成技能时取回，保证慢召回
        临时文案等用户可见内容只来自配置。
        """
        if not isinstance(config, dict):
            raise TypeError("skills 必须是字典")
        if reply_composition_config is not None and not isinstance(reply_composition_config, dict):
            raise TypeError("reply_composition 必须是字典")
        self._reply_composition_config = dict(reply_composition_config or {})
        self._skills: dict[type, object] = {
            SpeakingSkill: SpeakingSkill(config.get("speaking", {}), tts_engine),
            ConversationCompactionSkill: ConversationCompactionSkill(
                config.get("conversation_compaction", {}), llm_service,
            ),
            TextPreprocessingSkill: TextPreprocessingSkill(preprocessing_config),
            ExplicitMemoryIntentSkill: ExplicitMemoryIntentSkill(explicit_memory_config),
            SingingSkill: SingingSkill(config.get("singing", {}), singing),
        }

    @property
    def reply_composition_config(self) -> dict[str, Any]:
        """返回回复生成技能的配置副本，供运行时装配需要角色运行时的技能。"""
        return dict(self._reply_composition_config)

    def get(self, skill_type: type[SkillT]) -> SkillT:
        """按技能类型返回共享实例；非类型参数抛 TypeError，未注册类型抛 KeyError。"""
        if not isinstance(skill_type, type):
            raise TypeError("skill_type 应为技能类型")
        return cast(SkillT, self._skills[skill_type])

    def register(self, skill_type: type[SkillT], instance: SkillT) -> None:
        """注册或替换一个共享技能实例，供需要运行时装配的依赖使用。"""
        if not isinstance(skill_type, type):
            raise TypeError("skill_type 应为技能类型")
        self._skills[skill_type] = instance
