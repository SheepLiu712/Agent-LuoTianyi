from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from src.agent import Agent
from src.agent.context import ContextFactory
from src.agent.handlers.action.dynamic import PublishDynamicHandler
from src.agent.handlers.action.restore_expression import RestoreExpressionHandler
from src.agent.handlers.action.router import ActionRouter
from src.agent.handlers.action.say import SayHandler
from src.agent.handlers.action.sing import SingHandler
from src.agent.handlers.stimulus.chat import (
    ChatPreprocessingHandler,
    ChatReflectionHandler,
    ChatReplyHandler,
)
from src.agent.handlers.stimulus.citywalk import (
    CITYWALK_OBSERVATION_KIND,
    CitywalkObservationHandler,
)
from src.agent.handlers.stimulus.interaction import InteractionEndingHandler
from src.agent.handlers.stimulus.proactive import FirstLoginHandler
from src.agent.handlers.stimulus.router import StimulusRouter
from src.agent.handlers.stimulus.song_knowledge import SongKnowledgeHandler
from src.agent.handlers.stimulus.touch import TouchInteractionHandler
from src.agent.handlers.stimulus.world_activity import (
    WORLD_ACTIVITY_STIMULUS_KINDS,
    WorldActivityHandler,
)
from src.agent.luotianyi_agent import LuoTianyiAgent
from src.agent.reflex import CharacterReflex
from src.agent.skills import Skills
from src.agent.skills.cognitive import (
    ExplicitMemoryIntentSkill,
    ImagePreprocessingSkill,
    ResponseCompositionSkill,
    TextPreprocessingSkill,
)
from src.agent.skills.conversation.compaction import ConversationCompactionSkill
from src.agent.skills.expression.dynamic_publishing import DynamicPublishingSkill
from src.agent.skills.expression.singing import SingingSkill
from src.agent.skills.expression.speaking import SpeakingSkill
from src.agent.skills.expression.touch import TouchPolicy, TouchReactionSkill
from src.agent.skills.knowledge.song_acceptance import SongKnowledgeAcceptanceSkill
from src.agent.skills.mutation import IntentionalMemoryCommit
from src.agent.skills.reflection import ReflectionSkill
from src.agent_runtime.agent_registry import AgentRegistry
from src.agent_runtime.character_registry import CharacterRegistry
from src.agent_runtime.character_runtime import CharacterRuntime
from src.capabilities.speech.streaming import AsyncTTS
from src.domain.agent import ActionKind, StimulusKind
from src.resources.prepared_speech import PreparedSpeechResources
from src.subconscious.character_mind import CharacterSubconscious
from src.subconscious.memory import SubconsciousMemory
from src.subconscious.preprocessing import ChatPreprocessor
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
    """装配角色门面及旧角色运行时，管理查找和关闭生命周期。"""

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
            first_login_names = self._first_login_prepared_names(
                self.config.get("proactive", {})
            )
            self.skills = Skills(self.config.get("skills", {}), llm_service,
                                 tts_engine=AsyncTTS(capability_manager.speech),
                                 preprocessing_config=self.config.get("agent", {}).get("preprocessing", {}),
                                 explicit_memory_config=self.config.get("agent", {}).get("memory", {}).get("explicit_intent", {}),
                                 reply_composition_config=self.config.get("reply_composition", {}),
                                 singing=capability_manager.singing,
                                 media_resolver=capability_manager.media_resolver,
                                 image_understanding=capability_manager.image_understanding)
            # 动态发布按来源身份落库；角色上下文由能力自身的装配提供
            self.dynamic_publishing = DynamicPublishingSkill(capability_manager.dynamics)
            # 歌曲知识接纳使用与记忆查询相同的 agent.song_knowledge 配置，保证读写同一知识库
            self.song_knowledge = SongKnowledgeAcceptanceSkill(
                self.config.get("agent", {}).get("song_knowledge", {})
            )
            # 公用的预处理器，用于处理用户输入事件，例如图片理解、歌曲实体抽取和日期线索抽取
            self.preprocessor = ChatPreprocessor(
                self.config.get("agent", {}).get("preprocessing", {}),
                capability_manager
            )

            self.character_registry = CharacterRegistry(config.get("character_registry", {}))
            self.character_runtimes = self._build_character_runtimes(
                agent_config=self.config["agent"],
                llm_service=llm_service,
                capability_manager=capability_manager,
                database_manager=database_manager,
            )

            self.skills.register(ResponseCompositionSkill, ResponseCompositionSkill(
                self.skills.reply_composition_config,
                lambda character_id: self.character_runtimes[character_id],
            ))
            self.skills.register(ReflectionSkill, ReflectionSkill(
                self.config.get("reflection", {}),
                lambda character_id: self.character_runtimes[character_id],
            ))
            self.skills.register(IntentionalMemoryCommit, IntentionalMemoryCommit(
                lambda character_id: self.character_runtimes[character_id].mind.memory,
            ))

            self.agent_registry = AgentRegistry(
                self.config.get("agent_registry", {}),
                self.character_registry,
                self.character_runtimes,
            )

            self.default_character_id = self.character_registry.default_character_id
            self.context_factories = {
                character_id: ContextFactory(character_id=character_id, database=database_manager.conversation_service)
                for character_id in self.character_runtimes
            }
            world_activity = WorldActivityHandler(branches={
                CITYWALK_OBSERVATION_KIND: CitywalkObservationHandler(self.dynamic_publishing),
            })
            self._agents = {
                character_id: Agent(
                        character_id=character_id,
                        stimulus_router=StimulusRouter((
                            (StimulusKind.INTERACTION_ENDING, InteractionEndingHandler()),
                            (StimulusKind.PROACTIVE_PROMPT_DUE, FirstLoginHandler(
                                prepared_names=first_login_names,
                                prepared_speech=self.prepared_speech,
                        )),
                        (StimulusKind.INTERACTION_DEADLINE, ChatReplyHandler(
                            self.skills.get(ResponseCompositionSkill),
                             self.skills.get(TextPreprocessingSkill),
                             self.skills.get(ExplicitMemoryIntentSkill),
                             self.skills.get(IntentionalMemoryCommit))),
                        (StimulusKind.TOUCH_INTERACTION, TouchInteractionHandler(
                            *self._touch_reaction(character_id))),
                            (StimulusKind.SONG_KNOWLEDGE_DISCOVERED,
                             SongKnowledgeHandler(self.song_knowledge)),
                            *((kind, world_activity) for kind in WORLD_ACTIVITY_STIMULUS_KINDS
                              if kind is not StimulusKind.SONG_KNOWLEDGE_DISCOVERED),
                        *((kind, ChatPreprocessingHandler(
                            self.skills.get(TextPreprocessingSkill),
                            self.skills.get(ImagePreprocessingSkill))) for kind in (
                            StimulusKind.TEXT_MESSAGE, StimulusKind.IMAGE_MESSAGE, StimulusKind.VOICE_MESSAGE,
                            StimulusKind.USER_TYPING, StimulusKind.IMAGE_SELECTION_OPENED,
                            StimulusKind.IMAGE_SELECTION_CLOSED)),
                    ), reflection_handler=ChatReflectionHandler(
                        self.skills.get(ReflectionSkill),
                        self.skills.get(ConversationCompactionSkill))),
                    action_router=ActionRouter((
                        (ActionKind.SAY, SayHandler(
                            character_id, self.skills.get(SpeakingSkill), self.prepared_speech)),
                            (ActionKind.SING, SingHandler(
                                character_id, self.skills.get(SingingSkill))),
                            (ActionKind.RESTORE_EXPRESSION, RestoreExpressionHandler()),
                            (ActionKind.PUBLISH_DYNAMIC, PublishDynamicHandler(
                                character_id, self.dynamic_publishing)),
                        )),
                )
                for character_id in self.character_runtimes
            }
            set_agent_runtime(self)
        except BaseException:
            try:
                self._abort_initialization()
            except Exception as cleanup_error:  # noqa: BLE001 - initialization boundary must preserve cleanup logging
                self.logger.error(
                    f"AgentRuntime initialization rollback failed: {cleanup_error}"
                )
            raise

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
        for agent in getattr(self, "_agents", {}).values():
            agent._stop_accepting()
        async with self._shutdown_lock:
            if self._shutdown_complete:
                return
            inflight = tuple(
                completion for agent in getattr(self, "_agents", {}).values()
                for completion in agent._inflight
            )
            if inflight:
                # asyncio.wait 超时或被取消均不取消业务调用的完成信号。
                _, pending = await asyncio.wait(
                    inflight, timeout=self.shutdown_timeout_seconds,
                )
                if pending:
                    raise RuntimeError("Agent calls are still running")
            close = getattr(self.vector_store, "close", None)
            if close is not None:
                shutdown_task = getattr(self, "_shutdown_task", None)
                if shutdown_task is None:
                    shutdown_task = asyncio.create_task(run_sync_owned(close))
                    self._shutdown_task = shutdown_task
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
                try:
                    shutdown_task.result()
                except BaseException:
                    self._shutdown_task = None
                    raise
                if cancellation is not None:
                    raise cancellation
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
        """记录运行时外部依赖，并检查角色子运行时。"""
        self.llm_service = llm_service
        self.capability_manager = capability_manager
        self.database_manager = database_manager
        self.ensure_dependencies()

    def ensure_dependencies(self) -> None:
        """检查 AgentRuntime 和所有角色运行时依赖已经初始化。"""
        required = {
            "llm_service": self.llm_service,
            "capability_manager": self.capability_manager,
            "database_manager": self.database_manager,
            "vector_store": self.vector_store,
            "preprocessor": self.preprocessor,
            "character_registry": self.character_registry,
            "character_runtimes": self.character_runtimes,
            "agent_registry": self.agent_registry,
            "default_character_id": self.default_character_id,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"AgentRuntime dependencies are missing: {', '.join(missing)}")
        if not self.character_runtimes:
            raise RuntimeError("AgentRuntime dependency is missing: character_runtimes")
        self.preprocessor.ensure_dependencies()
        for runtime in self.character_runtimes.values():
            runtime.ensure_dependencies()

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

    def get_character_runtime(self, character_id: str | None = None) -> CharacterRuntime:
        """获取指定角色的完整运行时，包括意识、潜意识和角色档案。"""
        profile = self.character_registry.get(character_id or self.default_character_id)
        try:
            return self.character_runtimes[profile.character_id]
        except KeyError as exc:
            raise KeyError(f"No character runtime registered for {profile.character_id}") from exc

    def get_state(self, character_id: str | None = None):
        """获取指定角色当前潜意识状态的快照。"""
        return self.get_character_runtime(character_id).mind.get_state()

    async def preprocess_chat_event(self, *,  character_id: str, user_id: str, event: Any):
        """预处理用户输入事件，例如图片理解、歌曲实体抽取和日期线索抽取。"""
        return await self.preprocessor.preprocess_chat_event(character_id=character_id, user_id=user_id, event=event)

    async def try_handle_reflex(
        self,
        *,
        character_id: str | None,
        event: Any,
        send_reply_callback,
    ) -> bool:
        """尝试用角色反射处理输入事件，成功时不再进入话题管线。"""
        runtime = self.get_character_runtime(character_id)
        return await runtime.reflex.try_handle(event, send_reply_callback)

    async def extract_topic(
        self,
        *,
        character_id: str | None,
        user_id: str,
        unread_snapshot: Any,
        force_complete: bool = False,
        conversation_history: str | None = None,
    ):
        """将未读消息快照整理成一个可回复的话题。"""
        runtime = self.get_character_runtime(character_id)
        return await runtime.mind.extract_topics(
            user_id=user_id,
            unread_snapshot=unread_snapshot,
            force_complete=force_complete,
            conversation_history=conversation_history,
        )

    async def plan_topic_turn(
        self,
        *,
        character_id: str | None,
        user_id: str,
        topic: Any,
        conversation_history: str,
        external_context: str | None = None,
        sing_excluded_segments: set[tuple[str, str]] | None = None,
        sing_emotion_context: str = "",
    ):
        """根据话题、上下文和记忆检索结果规划本轮回复。"""
        runtime = self.get_character_runtime(character_id)
        return await runtime.mind.plan_topic_turn(
            user_id=user_id,
            topic=topic,
            conversation_history=conversation_history,
            external_context=external_context,
            sing_excluded_segments=sing_excluded_segments,
            sing_emotion_context=sing_emotion_context,
        )

    async def realize_topic_plan(self, *, character_id: str | None, user_id: str, plan: Any):
        """将潜意识规划转换成最终的文本、表情、语气或唱歌回复。"""
        runtime = self.get_character_runtime(character_id)
        return await runtime.conscious.realize_topic_plan_for_pipeline(user_id=user_id, plan=plan)

    async def write_topic_memories(
        self,
        *,
        character_id: str | None,
        user_id: str,
        current_dialogue: str,
        related_memories: list[str] | None = None,
        conversation_history: str | None = None,
    ) -> dict[str, Any]:
        """在完成一轮回复后异步提取并写入长期记忆。"""
        runtime = self.get_character_runtime(character_id)
        return await runtime.mind.write_topic_memories(
            user_id=user_id,
            current_dialogue=current_dialogue,
            related_memories=related_memories,
            conversation_history=conversation_history,
        )

    async def detect_dates_for_topic(
        self,
        *,
        character_id: str | None,
        user_id: str,
        topic: Any,
        conversation_history: str | None,
        reply_topic_callback,
    ):
        """从话题中识别重要日期，并在需要时触发补充回复。"""
        runtime = self.get_character_runtime(character_id)
        return await runtime.mind.detect_dates_for_topic(
            user_id=user_id,
            topic=topic,
            conversation_history=conversation_history,
            reply_topic_callback=reply_topic_callback,
        )

    async def update_user_profile_by_context(
        self,
        *,
        character_id: str | None,
        user_id: str,
        context: dict[str, Any],
    ) -> str | None:
        """根据最近对话上下文更新用户画像摘要。"""
        runtime = self.get_character_runtime(character_id)
        return await runtime.mind.update_user_profile_by_context(user_id=user_id, context=context)

    def _touch_reaction(self, character_id: str) -> tuple[TouchReactionSkill, TouchPolicy]:
        """按角色 touch.fast_reply 配置构造触摸资源选择技能与准入策略。"""
        fast_reply = (self.character_registry.get(character_id)
                      .reflex.get("touch", {}).get("fast_reply", {}))
        return TouchReactionSkill(fast_reply), TouchPolicy.from_config(fast_reply.get("policy"))

    def _build_character_runtimes(
        self,
        *,
        agent_config: dict[str, Any],
        llm_service: LLMService,
        capability_manager: CapabilityManager,
        database_manager: DatabaseManager,
    ) -> dict[str, CharacterRuntime]:
        """为每个启用角色创建潜意识、意识 Agent 和角色运行时对象。"""
        character_runtimes: dict[str, CharacterRuntime] = {}
        for profile in self.character_registry.characters.values():
            if not profile.enabled:
                continue
            llm_modules = self._register_character_llm_modules(llm_service, profile.character_id, agent_config)
            memory = SubconsciousMemory(
                agent_config["memory"],
                llm_modules,
                database_manager=database_manager,
                vector_store=self.vector_store,
                owner_character_id=profile.character_id,
            )
            mind = CharacterSubconscious(
                agent_config,
                database_manager=database_manager,
                capability_manager=capability_manager,
                memory=memory,
                llm_modules=llm_modules,
                character_profile=profile,
            )
            conscious = LuoTianyiAgent(
                agent_config,
                database_manager,
                capability_manager,
                llm_modules["main_chat"],
                character_profile=profile,
                mind=mind,
            )
            character_runtimes[profile.character_id] = CharacterRuntime(
                profile=profile,
                conscious=conscious,
                mind=mind,
                reflex=CharacterReflex(profile),
                capability_manager=capability_manager,
            )
        return character_runtimes

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
            raise ValueError(
                "proactive.first_login.prepared_names must contain two unique nonblank names"
            )
        return tuple(names)

    @staticmethod
    def _initialize_vector_store(agent_config: dict[str, Any]) -> Any:
        """根据 Agent 配置初始化并返回共享向量存储。"""
        vector_cfg = agent_config.get("memory", {}).get("vector_store", {})
        if vector_cfg:
            init_vector_store(vector_cfg)
        return get_vector_store()

    @staticmethod
    def _register_character_llm_modules(llm_service: LLMService, character_id: str, agent_config: dict[str, Any]) -> dict[str, Any]:
        """为指定角色注册聊天、话题提取、记忆写入等 LLM 模块。"""
        modules: dict[str, Any] = {
            "topic_extractor": llm_service.register_llm_module(
                f"{character_id}_topic_extractor",
                agent_config["topic_extractor"]["llm_module"],
            ),
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
            "date_detector": llm_service.register_llm_module(
                f"{character_id}_date_detector",
                agent_config["date_detector"]["llm_module"],
            )
        }
        return modules


_agent_runtime: AgentRuntime | None = None


def set_agent_runtime(runtime: AgentRuntime | None) -> None:
    """设置旧调用链使用的全局运行时引用；None 表示清除引用。"""
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


def get_default_agent() -> LuoTianyiAgent:
    """返回默认角色的意识 Agent。"""
    return get_agent_runtime().get_character_runtime().conscious
