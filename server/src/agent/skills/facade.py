"""所有角色共享的一组显式业务技能。"""

from __future__ import annotations

from src.agent.skills.adapters.memory import AgentMemory
from src.agent.skills.cognitive import (
    AudioUnderstandingSkill,
    ExplicitMemoryIntentSkill,
    ImageUnderstandingSkill,
    ResponseCompositionSkill,
    TextPreprocessingSkill,
    TopicExtractionSkill,
)
from src.agent.skills.cognitive.call_settlement import CallMaintenanceSkill, CallSummarySkill
from src.agent.skills.cognitive.reply import ReplySkill
from src.agent.skills.cognitive_maintenance import CognitiveMaintenanceSkill
from src.agent.skills.conversation.compaction import ConversationCompactionSkill
from src.agent.skills.expression.diary import DiarySkill
from src.agent.skills.expression.dynamic import DynamicSkill
from src.agent.skills.expression.prepared_speech import PreparedSpeechCatalog
from src.agent.skills.expression.singing import SingingSkill
from src.agent.skills.expression.song_learning import SongLearningTasks
from src.agent.skills.expression.speaking import SpeakingSkill
from src.agent.skills.expression.touch import TouchReactionSkill
from src.agent.skills.knowledge.song_acceptance import SongKnowledgeStore
from src.agent.skills.memory_retrieval import MemoryRetrievalSkill
from src.agent.skills.memory_write import MemoryWriteSkill
from src.agent.skills.resources import SkillResources
from src.infrastructure.config.skills import SkillsConfig


class SharedSkills:
    """一个 AgentRuntime 中所有 Agent 共用的完整 Skill 集合。

    角色级模型、记忆适配器和资源表只是共享 Skill 的内部依赖；调用身份由
    SkillInvocation 显式传入。这里使用具名属性而不是通用 get/register，避免
    运行时服务定位和不完整装配。
    """

    def __init__(self, config: SkillsConfig, *, resources: SkillResources) -> None:
        llm_service = resources.llm_service
        database_manager = resources.database
        media_resolver = resources.media_resolver
        characters = resources.characters
        memory_config = {
            **config.get("memory_retrieval"),
            "memory_writer": config.get("memory_write"),
            "user_profile": config.get("cognitive_maintenance").get("user_profile", {}),
        }
        memories = {
            key: AgentMemory(
                memory_config,
                llm_service,
                database_manager=database_manager,
                vector_store=resources.vector_store,
                owner_character_id=key,
            )
            for key in characters
        }
        self._memories = memories
        self.reply = ReplySkill(config.get("reply"), llm_service=llm_service, characters=characters)
        narratives = self.reply.narratives()
        prepared_speech = PreparedSpeechCatalog(config.get("prepared_speech").get("characters", {}))
        touch_configs = config.get("touch_reaction").get("characters", {})
        # 先完成所有可能失败的配置与模型装配，最后创建拥有进程的语音技能。
        self.singing = SingingSkill(config.get("singing"), llm_service)
        self.conversation_compaction = ConversationCompactionSkill(
            config.get("cognitive_maintenance").get("conversation_compaction", {}),
            llm_service,
        )
        self.text_preprocessing = TextPreprocessingSkill(
            config.get("jargon_recognition"),
            song_names=self.singing.song_names(),
        )
        self.explicit_memory_intent = ExplicitMemoryIntentSkill(config.get("explicit_memory_intent"))
        self.image_understanding = (
            ImageUnderstandingSkill(config.get("image_understanding"), media_resolver, llm_service)
            if media_resolver is not None
            else None
        )
        self.audio_understanding = (
            AudioUnderstandingSkill(config.get("audio_understanding"), media_resolver, llm_service)
            if media_resolver is not None
            else None
        )

        self.song_knowledge = SongKnowledgeStore(config.get("knowledge"))
        self.memory_retrieval = MemoryRetrievalSkill(
            config.get("memory_retrieval"), memories=memories, singing=self.singing, knowledge=self.song_knowledge
        )
        self.response_composition = ResponseCompositionSkill(
            config.get("response_composition"),
            retrieval=self.memory_retrieval,
            singing=self.singing,
            reply=self.reply,
            topic_extraction=TopicExtractionSkill(
                config.get("topic_extraction"), llm_service, understanding=self.text_preprocessing
            ),
        )
        self.call_summary = CallSummarySkill(config.get("call_summary"), llm_service=llm_service, characters=characters)
        self.call_maintenance = CallMaintenanceSkill(
            dict(memories), getattr(database_manager, "call_maintenance_batches", None)
        )
        self.cognitive_maintenance = CognitiveMaintenanceSkill(
            memories=memories,
            compaction=self.conversation_compaction,
            call_maintenance=self.call_maintenance,
        )
        self.memory_write = MemoryWriteSkill(
            config.get("memory_write"),
            llm_service=llm_service,
            memory_store=database_manager.memory_store,
            vector_store=resources.vector_store,
            characters=characters,
        )

        self.dynamic = DynamicSkill(
            config.get("dynamic"), llm_service=llm_service, database=database_manager, narratives=narratives
        )
        self.diary = DiarySkill(config.get("diary"), dynamic=self.dynamic, database=database_manager)
        self.song_learning_tasks = SongLearningTasks(self.singing.backend)
        self.prepared_speech = prepared_speech
        self.touch_reaction = TouchReactionSkill(touch_configs, prepared_speech)
        self.speaking = SpeakingSkill(config.get("speaking"))

    def ensure_dependencies(self) -> None:
        for memory in self._memories.values():
            memory.ensure_dependencies()

    async def stop(self) -> None:
        """关闭由共享 Skill 拥有的长生命周期资源。"""
        await self.speaking.stop()

    def abort_initialization(self) -> None:
        """同步回滚已启动但尚未发布的 Skill 资源。"""
        self.speaking.abort_initialization()
