from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from src.agent import Agent
from src.agent.context import ContextFactory
from src.agent.handlers.action.dynamic import PublishDynamicHandler
from src.agent.handlers.action.dynamic_reply import ReplyDynamicHandler
from src.agent.handlers.action.restore_expression import RestoreExpressionHandler
from src.agent.handlers.action.router import ActionRouter
from src.agent.handlers.action.say import SayHandler
from src.agent.handlers.action.sing import SingHandler
from src.agent.handlers.action.song_learning import RequestSongLearningHandler
from src.agent.handlers.action.write_diary import WriteDiaryHandler
from src.agent.handlers.stimulus.chat import (
    ChatPreprocessingHandler,
    ChatReflectionHandler,
    ChatReplyHandler,
)
from src.agent.handlers.stimulus.citywalk import (
    CITYWALK_OBSERVATION_KIND,
    CitywalkObservationHandler,
)
from src.agent.handlers.stimulus.diary_due import DiaryPlanningDueHandler
from src.agent.handlers.stimulus.dynamic_observed import DynamicObservedHandler
from src.agent.handlers.stimulus.interaction import InteractionEndingHandler
from src.agent.handlers.stimulus.proactive import FirstLoginHandler
from src.agent.handlers.stimulus.router import StimulusRouter
from src.agent.handlers.stimulus.song_knowledge import SongKnowledgeHandler
from src.agent.handlers.stimulus.song_learned import SongLearnedHandler
from src.agent.handlers.stimulus.touch import TouchInteractionHandler
from src.agent.handlers.stimulus.world_activity import (
    WORLD_ACTIVITY_STIMULUS_KINDS,
    WorldActivityHandler,
)
from src.agent.skills import Skills
from src.agent.skills.adapters.memory import AgentMemory
from src.agent.skills.cognitive import (
    CharacterReplyGenerator,
    ExplicitMemoryIntentSkill,
    ImagePreprocessingSkill,
    ResponseCompositionSkill,
    TextPreprocessingSkill,
)
from src.agent.skills.cognitive.dynamic_topic_memory import DynamicTopicMemorySkill
from src.agent.skills.cognitive.learned_song_experience import (
    LearnedSongExperienceSkill,
)
from src.agent.skills.conversation.compaction import ConversationCompactionSkill
from src.agent.skills.expression.diary_writing import DiaryWritingSkill
from src.agent.skills.expression.dynamic_publishing import DynamicPublishingSkill
from src.agent.skills.expression.dynamic_reply import DynamicReplySkill
from src.agent.skills.expression.singing import SingingSkill
from src.agent.skills.expression.song_learning import SongLearningDispatchSkill
from src.agent.skills.expression.speaking import SpeakingSkill
from src.agent.skills.expression.touch import TouchPolicy, TouchReactionSkill
from src.agent.skills.knowledge.song_acceptance import SongKnowledgeAcceptanceSkill
from src.agent.skills.mutation import IntentionalMemoryCommit
from src.agent.skills.reflection import ReflectionSkill
from src.agent_runtime.character_registry import CharacterRegistry
from src.capabilities.speech.streaming import AsyncTTS
from src.domain.agent import ActionKind, StimulusKind
from src.resources.prepared_speech import PreparedSpeechResources
from src.system.database.vector_store import (
    clear_vector_store,
    get_vector_store,
    init_vector_store,
)
from src.utils.asyncio_helpers import (
    DEFAULT_OWNED_TASK_STOP_TIMEOUT_SECONDS,
    run_sync_owned,
    wait_for_owned_tasks,
)
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.capabilities import CapabilityManager
    from src.system.database import DatabaseManager
    from src.utils.llm_service import LLMService


class AgentRuntime:
    """装配角色 Agent 及其私有技能，管理查找和关闭生命周期。"""

    def __init__(
        self,
        config: dict[str, Any],
        llm_service: LLMService,
        capability_manager: CapabilityManager,
        database_manager: DatabaseManager,
    ) -> None:
        """初始化启用角色及注册表，为门面注入数据库会话工厂；初始化失败回滚资源。"""
        self.logger = get_logger(__name__)
        self.config = config
        self.llm_service = llm_service
        self.capability_manager = capability_manager
        self.database_manager = database_manager
        self._shutdown_lock = asyncio.Lock()
        self._shutdown_complete = False
        self._shutdown_task: asyncio.Task | None = None
        self.shutdown_timeout_seconds = DEFAULT_OWNED_TASK_STOP_TIMEOUT_SECONDS
        self.vector_store = self._initialize_vector_store(self.config["agent"])
        try:
            self.prepared_speech = PreparedSpeechResources(self.config.get("prepared_speech", {}))
            first_login_names = self._first_login_prepared_names(self.config.get("proactive", {}))
            self.skills = Skills(
                self.config.get("skills", {}),
                llm_service,
                tts_engine=AsyncTTS(capability_manager.speech),
                preprocessing_config=self.config.get("agent", {}).get("preprocessing", {}),
                explicit_memory_config=self.config.get("agent", {}).get("memory", {}).get("explicit_intent", {}),
                singing=capability_manager.singing,
                media_resolver=capability_manager.media_resolver,
                image_understanding=capability_manager.image_understanding,
            )
            self.character_memories: dict[str, AgentMemory] = {}
            self.reply_generators: dict[str, CharacterReplyGenerator] = {}
            self.response_compositions: dict[str, ResponseCompositionSkill] = {}
            self.reflections: dict[str, ReflectionSkill] = {}
            # 动态发布按来源身份落库；角色上下文由能力自身的装配提供
            self.dynamic_publishing = DynamicPublishingSkill(capability_manager.dynamics)
            # 歌曲知识接纳使用与记忆查询相同的 agent.song_knowledge 配置，保证读写同一知识库
            self.song_knowledge = SongKnowledgeAcceptanceSkill(self.config.get("agent", {}).get("song_knowledge", {}))
            self.character_registry = CharacterRegistry(config.get("character_registry", {}))
            self._build_character_skills(
                agent_config=self.config["agent"],
                llm_service=llm_service,
                database_manager=database_manager,
            )
            self.skills.register(
                IntentionalMemoryCommit,
                IntentionalMemoryCommit(lambda character_id: self.character_memories[character_id]),
            )

            self.default_character_id = self.character_registry.default_character_id
            self.character_ids = tuple(self.character_memories)
            self.context_factories = {
                character_id: ContextFactory(character_id=character_id, database=database_manager.conversation_service)
                for character_id in self.character_ids
            }
            self._agents = self._build_agents(first_login_names)
            set_agent_runtime(self)
        except BaseException:
            try:
                self._abort_initialization()
            except Exception as cleanup_error:  # noqa: BLE001 - initialization boundary must preserve cleanup logging
                self.logger.error(f"AgentRuntime initialization rollback failed: {cleanup_error}")
            raise

    def _build_agents(self, first_login_names: tuple[str, ...]) -> dict[str, Agent]:
        """完整构造所有角色门面后一次性发布，避免暴露半装配状态。"""
        world_activity = WorldActivityHandler(
            branches={CITYWALK_OBSERVATION_KIND: CitywalkObservationHandler(self.dynamic_publishing)}
        )
        agents: dict[str, Agent] = {}
        for character_id in self.character_ids:
            agents[character_id] = self._build_agent(character_id, first_login_names, world_activity)
        return agents

    def _build_agent(
        self,
        character_id: str,
        first_login_names: tuple[str, ...],
        world_activity: WorldActivityHandler,
    ) -> Agent:
        """为一个角色装配私有路由；共享处理器只在其行为无角色状态时复用。"""
        song_learning = SongLearningDispatchSkill(self._singing_manager(character_id))
        return Agent(
            character_id=character_id,
            stimulus_router=self._build_stimulus_router(
                character_id,
                first_login_names,
                world_activity,
                song_learning,
            ),
            action_router=self._build_action_router(character_id, song_learning),
        )

    def _build_stimulus_router(
        self,
        character_id: str,
        first_login_names: tuple[str, ...],
        world_activity: WorldActivityHandler,
        song_learning: SongLearningDispatchSkill,
    ) -> StimulusRouter:
        """登记一个角色可处理的刺激，并复用无状态的输入预处理器。"""
        preprocessing = ChatPreprocessingHandler(
            self.skills.get(TextPreprocessingSkill),
            self.skills.get(ImagePreprocessingSkill),
        )
        registrations = [
            (StimulusKind.INTERACTION_ENDING, InteractionEndingHandler()),
            (
                StimulusKind.PROACTIVE_PROMPT_DUE,
                FirstLoginHandler(
                    prepared_names=first_login_names,
                    prepared_speech=self.prepared_speech,
                ),
            ),
            (
                StimulusKind.INTERACTION_DEADLINE,
                ChatReplyHandler(
                    self.response_compositions[character_id],
                    self.skills.get(TextPreprocessingSkill),
                    self.skills.get(ExplicitMemoryIntentSkill),
                    self.skills.get(IntentionalMemoryCommit),
                ),
            ),
            (
                StimulusKind.TOUCH_INTERACTION,
                TouchInteractionHandler(*self._touch_reaction(character_id)),
            ),
            (StimulusKind.SONG_KNOWLEDGE_DISCOVERED, SongKnowledgeHandler(self.song_knowledge)),
            (
                StimulusKind.DYNAMIC_OBSERVED,
                DynamicObservedHandler(
                    character_id,
                    self._dynamic_reply_skill(character_id),
                    DynamicTopicMemorySkill(self.character_memories.get(character_id)),
                ),
            ),
            (
                StimulusKind.DIARY_PLANNING_DUE,
                DiaryPlanningDueHandler(self._diary_writing_skill(character_id)),
            ),
            (
                StimulusKind.SONG_LEARNED,
                SongLearnedHandler(
                    character_id,
                    LearnedSongExperienceSkill(self.character_memories.get(character_id)),
                    self.dynamic_publishing,
                    song_learning,
                ),
            ),
        ]
        reserved_world_kinds = {
            StimulusKind.DYNAMIC_OBSERVED,
            StimulusKind.DIARY_PLANNING_DUE,
            StimulusKind.SONG_KNOWLEDGE_DISCOVERED,
            StimulusKind.SONG_LEARNED,
        }
        registrations.extend(
            (kind, world_activity) for kind in WORLD_ACTIVITY_STIMULUS_KINDS if kind not in reserved_world_kinds
        )
        registrations.extend(
            (kind, preprocessing)
            for kind in (
                StimulusKind.TEXT_MESSAGE,
                StimulusKind.IMAGE_MESSAGE,
                StimulusKind.VOICE_MESSAGE,
                StimulusKind.USER_TYPING,
                StimulusKind.IMAGE_SELECTION_OPENED,
                StimulusKind.IMAGE_SELECTION_CLOSED,
            )
        )
        return StimulusRouter(
            registrations,
            reflection_handler=ChatReflectionHandler(
                self.reflections[character_id],
                self.skills.get(ConversationCompactionSkill),
            ),
        )

    def _build_action_router(
        self,
        character_id: str,
        song_learning: SongLearningDispatchSkill,
    ) -> ActionRouter:
        """登记一个角色可实现的行动。"""
        return ActionRouter(
            (
                (
                    ActionKind.SAY,
                    SayHandler(character_id, self.skills.get(SpeakingSkill), self.prepared_speech),
                ),
                (ActionKind.SING, SingHandler(character_id, self.skills.get(SingingSkill))),
                (ActionKind.RESTORE_EXPRESSION, RestoreExpressionHandler()),
                (ActionKind.PUBLISH_DYNAMIC, PublishDynamicHandler(character_id, self.dynamic_publishing)),
                (
                    ActionKind.REQUEST_SONG_LEARNING,
                    RequestSongLearningHandler(character_id, song_learning),
                ),
                (
                    ActionKind.REPLY_DYNAMIC,
                    ReplyDynamicHandler(character_id, self._dynamic_reply_skill(character_id)),
                ),
                (ActionKind.WRITE_DIARY, WriteDiaryHandler(self._diary_writing_skill(character_id))),
            )
        )

    def _abort_initialization(self) -> None:
        vector_store = getattr(self, "vector_store", None)
        try:
            close = getattr(vector_store, "close", None)
            if close is not None:
                close()
        finally:
            if vector_store is not None:
                clear_vector_store(vector_store)
            clear_agent_runtime(self)

    async def shutdown(self) -> None:
        """停止接受并等待门面调用退出后关闭资源，成功后幂等。

        在途等待超时抛 RuntimeError 并保留依赖，重试继续等待；调用方取消
        关闭不取消业务工作。资源关闭任务同样保留所有权供后续关闭重试。
        """
        self._stop_accepting_agents()
        async with self._shutdown_lock:
            if self._shutdown_complete:
                return
            await self._wait_for_inflight_calls()
            await self._close_owned_vector_store()
            self._finalize_shutdown()

    def _stop_accepting_agents(self) -> None:
        """先拒绝新调用，使后续在途快照只会收敛。"""
        for agent in getattr(self, "_agents", {}).values():
            agent._stop_accepting()

    async def _wait_for_inflight_calls(self) -> None:
        """等待当前门面调用完成；超时不取消业务调用。"""
        inflight = tuple(
            completion for agent in getattr(self, "_agents", {}).values() for completion in agent._inflight
        )
        if not inflight:
            return
        _, pending = await asyncio.wait(inflight, timeout=self.shutdown_timeout_seconds)
        if pending:
            raise RuntimeError("Agent calls are still running")

    async def _close_owned_vector_store(self) -> None:
        """关闭运行时拥有的向量库；关闭任务可跨超时或调用方取消继续完成。"""
        close = getattr(self.vector_store, "close", None)
        if close is None:
            return
        shutdown_task = getattr(self, "_shutdown_task", None)
        if shutdown_task is None:
            shutdown_task = asyncio.create_task(run_sync_owned(close))
            self._shutdown_task = shutdown_task
        cancellation = await self._wait_for_vector_store_close(shutdown_task)
        try:
            shutdown_task.result()
        except BaseException:
            self._shutdown_task = None
            raise
        if cancellation is not None:
            raise cancellation

    async def _wait_for_vector_store_close(
        self,
        shutdown_task: asyncio.Task,
    ) -> asyncio.CancelledError | None:
        """等待关闭任务；调用方取消时先替运行时收回任务结果。"""
        cancellation: asyncio.CancelledError | None = None
        try:
            _done, pending = await wait_for_owned_tasks(
                (shutdown_task,),
                timeout_seconds=getattr(
                    self,
                    "shutdown_timeout_seconds",
                    DEFAULT_OWNED_TASK_STOP_TIMEOUT_SECONDS,
                ),
            )
        except asyncio.CancelledError as error:
            cancellation = error
            _done, pending = await asyncio.shield(
                wait_for_owned_tasks(
                    (shutdown_task,),
                    timeout_seconds=getattr(
                        self,
                        "shutdown_timeout_seconds",
                        DEFAULT_OWNED_TASK_STOP_TIMEOUT_SECONDS,
                    ),
                )
            )
        if pending:
            raise RuntimeError("Vector store close task is still running")
        return cancellation

    def _finalize_shutdown(self) -> None:
        """仅在所有拥有资源成功关闭后清除全局引用。"""
        clear_vector_store(self.vector_store)
        clear_agent_runtime(self)
        self._shutdown_complete = True

    def wire_dependencies(
        self,
        *,
        llm_service: LLMService,
        capability_manager: CapabilityManager,
        database_manager: DatabaseManager,
    ) -> None:
        """记录运行时外部依赖，并检查角色私有技能。"""
        self.llm_service = llm_service
        self.capability_manager = capability_manager
        self.database_manager = database_manager
        self.ensure_dependencies()

    def ensure_dependencies(self) -> None:
        """检查 AgentRuntime 和所有角色私有技能依赖已经初始化。"""
        required = {
            "llm_service": self.llm_service,
            "capability_manager": self.capability_manager,
            "database_manager": self.database_manager,
            "vector_store": self.vector_store,
            "character_registry": self.character_registry,
            "character_memories": self.character_memories,
            "reply_generators": self.reply_generators,
            "response_compositions": self.response_compositions,
            "reflections": self.reflections,
            "default_character_id": self.default_character_id,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"AgentRuntime dependencies are missing: {', '.join(missing)}")
        if not self.character_ids:
            raise RuntimeError("AgentRuntime dependency is missing: character_ids")
        for memory in self.character_memories.values():
            memory.ensure_dependencies()

    def get_agent(self, character_id: str | None = None) -> Agent:
        """返回角色的缓存门面；仅 None 选择默认角色。

        未知、禁用或空白 ID 抛出 KeyError，非字符串 ID 抛出 TypeError。
        关闭后仍返回同一门面，但门面拒绝接受新工作。
        """
        if character_id is None:
            character_id = self.default_character_id
        if not isinstance(character_id, str):
            raise TypeError("character_id must be str or None")
        if not character_id.strip():
            raise KeyError(character_id)
        return self._agents[character_id]

    def _dynamic_reply_skill(self, character_id: str) -> DynamicReplySkill:
        """按角色构造动态回复技能；角色名取角色档案，缺失时回落角色 ID。"""
        profile = self.character_registry.get(character_id)
        display_name = profile.display_name or character_id
        return DynamicReplySkill(
            self.capability_manager.dynamics,
            character_id=character_id,
            character_name=display_name,
        )

    def _diary_writing_skill(self, character_id: str) -> DiaryWritingSkill:
        """按角色装配日记生成上下文与日记/动态能力。"""
        profile = self.character_registry.get(character_id)
        generator = self.reply_generators[character_id]
        return DiaryWritingSkill(
            getattr(self.capability_manager, "diary", None),
            self.capability_manager.dynamics,
            character_id=character_id,
            character_name=profile.display_name or character_id,
            character_persona=generator.character_persona,
            speaking_style=generator.speaking_style,
        )

    def _singing_manager(self, character_id: str):
        """返回该角色的唱歌管理器；能力未装配时返回 None。"""
        singing = getattr(self.capability_manager, "singing", None)
        managers = getattr(singing, "singing_manager", None) or {}
        return managers.get(character_id)

    def _touch_reaction(self, character_id: str) -> tuple[TouchReactionSkill, TouchPolicy]:
        """按角色 touch.fast_reply 配置构造触摸资源选择技能与准入策略。"""
        fast_reply = self.character_registry.get(character_id).reflex.get("touch", {}).get("fast_reply", {})
        return TouchReactionSkill(fast_reply), TouchPolicy.from_config(fast_reply.get("policy"))

    def _build_character_skills(
        self,
        *,
        agent_config: dict[str, Any],
        llm_service: LLMService,
        database_manager: DatabaseManager,
    ) -> None:
        """为每个启用角色创建记忆、回复生成、编排和反思技能。"""
        for profile in self.character_registry.characters.values():
            if not profile.enabled:
                continue
            llm_modules = self._register_character_llm_modules(llm_service, profile.character_id, agent_config)
            memory = AgentMemory(
                agent_config["memory"],
                llm_modules,
                database_manager=database_manager,
                vector_store=self.vector_store,
                owner_character_id=profile.character_id,
            )
            self.character_memories[profile.character_id] = memory
            generator = CharacterReplyGenerator(
                agent_config["main_chat"],
                llm_modules["main_chat"],
                profile,
            )
            self.reply_generators[profile.character_id] = generator
            self.response_compositions[profile.character_id] = ResponseCompositionSkill(
                self.config.get("reply_composition", {}),
                character_id=profile.character_id,
                memory=memory,
                singing=self.capability_manager.singing,
                generator=generator,
            )
            self.reflections[profile.character_id] = ReflectionSkill(self.config.get("reflection", {}), memory)

    @staticmethod
    def _first_login_prepared_names(config: dict[str, Any]) -> tuple[str, ...]:
        """读取 proactive.first_login.prepared_names；配置存在时要求恰好两项。"""
        if not isinstance(config, dict):
            raise TypeError("proactive must be a dictionary")
        first_login = config.get("first_login")
        if first_login is None:
            return ()
        if not isinstance(first_login, dict):
            raise TypeError("proactive.first_login must be a dictionary")
        names = first_login.get("prepared_names")
        if not isinstance(names, list):
            raise TypeError("proactive.first_login.prepared_names must be a list")
        if (
            len(names) != 2
            or any(not isinstance(name, str) or not name.strip() for name in names)
            or len(set(names)) != len(names)
        ):
            raise ValueError("proactive.first_login.prepared_names must contain two unique nonblank names")
        return tuple(names)

    @staticmethod
    def _initialize_vector_store(agent_config: dict[str, Any]) -> Any:
        """根据 Agent 配置初始化并返回共享向量存储。"""
        vector_cfg = agent_config.get("memory", {}).get("vector_store", {})
        if vector_cfg:
            init_vector_store(vector_cfg)
        return get_vector_store()

    @staticmethod
    def _register_character_llm_modules(
        llm_service: LLMService, character_id: str, agent_config: dict[str, Any]
    ) -> dict[str, Any]:
        """为指定角色注册回复生成、记忆写入和画像更新 LLM 模块。"""
        modules: dict[str, Any] = {
            "memory_writer": llm_service.register_llm_module(
                f"{character_id}_memory_writer",
                agent_config["memory"]["memory_writer"]["llm_module"],
            ),
            "user_profile_updater": llm_service.register_llm_module(
                f"{character_id}_user_profile_updater",
                agent_config["memory"]["user_profile"]["llm_module"],
            ),
            "main_chat": llm_service.register_llm_module(
                f"{character_id}_main_chat",
                agent_config["main_chat"]["llm_module"],
            ),
        }
        return modules


_agent_runtime: AgentRuntime | None = None


def set_agent_runtime(runtime: AgentRuntime | None) -> None:
    """设置进程内 AgentRuntime 引用；None 表示清除引用。"""
    global _agent_runtime
    _agent_runtime = runtime


def clear_agent_runtime(expected: AgentRuntime | None = None) -> bool:
    """清除匹配的全局引用；被其他实例替换时返回 False，清除后返回 True。"""
    global _agent_runtime
    if expected is not None and _agent_runtime is not expected:
        return False
    _agent_runtime = None
    return True


def get_agent_runtime() -> AgentRuntime:
    """返回全局 AgentRuntime 实例，未初始化时抛出错误。"""
    if _agent_runtime is None:
        raise ValueError("AgentRuntime has not been initialized.")
    return _agent_runtime
