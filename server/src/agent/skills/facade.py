"""所有角色共享的一组显式业务技能。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from src.agent.skills.adapters.memory import AgentMemory
from src.agent.skills.cognitive import (
    CharacterReplyGenerator,
    ExplicitMemoryIntentSkill,
    ImageUnderstandingSkill,
    ResponseCompositionSkill,
    TextPreprocessingSkill,
)
from src.agent.skills.cognitive.dynamic_topic_memory import DynamicTopicMemorySkill
from src.agent.skills.cognitive.learned_song_experience import LearnedSongExperienceSkill
from src.agent.skills.contracts import CharacterNarrative
from src.agent.skills.conversation.compaction import ConversationCompactionSkill
from src.agent.skills.expression._diary_operations import DiaryOperations
from src.agent.skills.expression._dynamic_operations import DynamicOperations
from src.agent.skills.expression.diary_writing import DiaryWritingSkill
from src.agent.skills.expression.dynamic_publishing import DynamicPublishingSkill
from src.agent.skills.expression.dynamic_reply import DynamicReplySkill
from src.agent.skills.expression.prepared_speech import PreparedSpeechCatalog
from src.agent.skills.expression.singing import SingingSkill
from src.agent.skills.expression.song_learning import SongLearningDispatchSkill
from src.agent.skills.expression.speaking import SpeakingSkill
from src.agent.skills.expression.touch import TouchReactionSkill
from src.agent.skills.knowledge.song_acceptance import SongKnowledgeAcceptanceSkill
from src.agent.skills.mutation import IntentionalMemoryCommit
from src.agent.skills.reflection import ReflectionSkill
from src.infrastructure.media import MediaResolver

if TYPE_CHECKING:
    from src.infrastructure.models.service import LLMService
    from src.infrastructure.persistence.database import DatabaseManager


class SharedSkills:
    """一个 AgentRuntime 中所有 Agent 共用的完整 Skill 集合。

    角色级模型、记忆适配器和资源表只是共享 Skill 的内部依赖；调用身份由
    SkillInvocation 显式传入。这里使用具名属性而不是通用 get/register，避免
    运行时服务定位和不完整装配。
    """

    def __init__(
        self,
        config: dict[str, Any],
        llm_service: LLMService,
        *,
        memories: Mapping[str, AgentMemory],
        reply_generators: Mapping[str, CharacterReplyGenerator],
        narratives: Mapping[str, CharacterNarrative],
        touch_configs: Mapping[str, Mapping[str, object]],
        prepared_speech: PreparedSpeechCatalog,
        preprocessing_config: dict[str, Any] | None,
        explicit_memory_config: dict[str, Any] | None,
        reply_composition_config: dict[str, Any],
        reflection_config: dict[str, Any],
        song_knowledge_config: dict[str, Any],
        database_manager: DatabaseManager,
        media_resolver: MediaResolver | None = None,
    ) -> None:
        if not isinstance(config, dict):
            raise TypeError("skills 必须是字典")
        if not memories or set(memories) != set(reply_generators) or set(memories) != set(narratives):
            raise ValueError("共享技能要求每个启用角色具备完整的记忆、生成器和叙事资料")

        dynamics = DynamicOperations(config.get("dynamic", {}))
        dynamics.create_llm_module(llm_service)
        dynamics.wire_dependencies(database_manager=database_manager)
        diary = DiaryOperations(config.get("diary", {}))
        diary.create_llm_module(llm_service)
        diary.wire_dependencies(database_manager=database_manager, dynamic_operations=dynamics)

        self.speaking = SpeakingSkill(config.get("speaking", {}))
        self.singing = SingingSkill(config.get("singing", {}), llm_service)
        self.conversation_compaction = ConversationCompactionSkill(
            config.get("conversation_compaction", {}),
            llm_service,
        )
        self.text_preprocessing = TextPreprocessingSkill(preprocessing_config)
        self.explicit_memory_intent = ExplicitMemoryIntentSkill(explicit_memory_config)
        self.image_understanding = (
            ImageUnderstandingSkill(config.get("image_understanding", {}), media_resolver, llm_service)
            if media_resolver is not None
            else None
        )

        self.response_composition = ResponseCompositionSkill(
            reply_composition_config,
            memories=memories,
            singing=self.singing.backend,
            generators=reply_generators,
        )
        self.reflection = ReflectionSkill(reflection_config, memories)
        self.intentional_memory = IntentionalMemoryCommit(lambda character_id: memories[character_id])
        self.dynamic_topic_memory = DynamicTopicMemorySkill(memories)
        self.learned_song_experience = LearnedSongExperienceSkill(memories)

        self.dynamic_publishing = DynamicPublishingSkill(dynamics, narratives)
        self.dynamic_reply = DynamicReplySkill(dynamics, narratives)
        self.diary_writing = DiaryWritingSkill(diary, dynamics, narratives)
        self.song_learning = SongLearningDispatchSkill(self.singing.backend)
        self.prepared_speech = prepared_speech
        self.touch_reaction = TouchReactionSkill(touch_configs, prepared_speech)
        self.song_knowledge = SongKnowledgeAcceptanceSkill(song_knowledge_config)

    async def stop(self) -> None:
        """关闭由共享 Skill 拥有的长生命周期资源。"""
        await self.speaking.stop()

    def abort_initialization(self) -> None:
        """同步回滚已启动但尚未发布的 Skill 资源。"""
        self.speaking.abort_initialization()
