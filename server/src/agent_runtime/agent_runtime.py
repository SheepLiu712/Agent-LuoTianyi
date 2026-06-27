from __future__ import annotations

from typing import Any, Dict, TYPE_CHECKING

from src.agent.luotianyi_agent import LuoTianyiAgent
from src.agent_runtime.agent_registry import AgentRegistry
from src.agent_runtime.character_registry import CharacterRegistry
from src.agent_runtime.character_runtime import CharacterRuntime
from src.subconscious.character_mind import CharacterSubconscious
from src.subconscious.memory import SubconsciousMemory
from src.subconscious.preprocessing import ChatPreprocessor
from src.system.database.vector_store import get_vector_store, init_vector_store
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.capabilities import CapabilityManager
    from src.system.database import DatabaseManager
    from src.utils.llm_service import LLMService


class AgentRuntime:
    """管理角色运行时，并直接提供聊天管线需要调用的 Agent 接口。"""

    def __init__(
        self,
        config: Dict[str, Any],
        llm_service: "LLMService",
        capability_manager: "CapabilityManager",
        database_manager: "DatabaseManager",
    ) -> None:
        """初始化所有角色的意识、潜意识、预处理器和注册表。"""
        self.logger = get_logger(__name__)
        self.config = config
        
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

        self.agent_registry = AgentRegistry(
            self.config.get("agent_registry", {}),
            self.character_registry,
            self.character_runtimes,
        )

        self.default_character_id = self.character_registry.default_character_id
        global _agent_runtime
        _agent_runtime = self

    def get_agent(self, character_id: str | None = None) -> LuoTianyiAgent:
        """获取指定角色的意识 Agent，未指定时返回默认角色。"""
        return self.agent_registry.get(character_id or self.default_character_id)

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
    ):
        """根据话题、上下文和记忆检索结果规划本轮回复。"""
        runtime = self.get_character_runtime(character_id)
        return await runtime.mind.plan_topic_turn(
            user_id=user_id,
            topic=topic,
            conversation_history=conversation_history,
            external_context=external_context,
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
    ) -> None:
        """在完成一轮回复后异步提取并写入长期记忆。"""
        runtime = self.get_character_runtime(character_id)
        await runtime.mind.write_topic_memories(
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

    def _build_character_runtimes(
        self,
        *,
        agent_config: dict[str, Any],
        llm_service: "LLMService",
        capability_manager: "CapabilityManager",
        database_manager: "DatabaseManager",
    ) -> dict[str, CharacterRuntime]:
        """为每个启用角色创建潜意识、意识 Agent 和角色运行时对象。"""
        vector_store = self._initialize_vector_store(agent_config)
        character_runtimes: dict[str, CharacterRuntime] = {}
        for profile in self.character_registry.characters.values():
            if not profile.enabled:
                continue
            llm_modules = self._register_character_llm_modules(llm_service, profile.character_id, agent_config)
            memory = SubconsciousMemory(
                agent_config["memory_manager"],
                llm_modules,
                vector_store=vector_store,
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
            )
        return character_runtimes

    @staticmethod
    def _initialize_vector_store(agent_config: Dict[str, Any]) -> Any:
        """根据 Agent 配置初始化并返回共享向量存储。"""
        vector_cfg = agent_config.get("memory_manager", {}).get("vector_store", {})
        if vector_cfg:
            init_vector_store(vector_cfg)
        return get_vector_store()

    @staticmethod
    def _register_character_llm_modules(llm_service: "LLMService", character_id: str, agent_config: Dict[str, Any]) -> dict[str, Any]:
        """为指定角色注册聊天、话题提取、记忆写入等 LLM 模块。"""
        modules: dict[str, Any] = {
            "topic_extractor": llm_service.register_llm_module(
                f"{character_id}_topic_extractor",
                agent_config["topic_extractor"]["llm_module"],
            ),
            "memory_writer": llm_service.register_llm_module(
                f"{character_id}_memory_writer",
                agent_config["memory_manager"]["memory_writer"]["llm_module"],
            ),
            "user_profile_updater": llm_service.register_llm_module(
                f"{character_id}_user_profile_updater",
                agent_config["memory_manager"]["user_profile"]["llm_module"],
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


def get_agent_runtime() -> AgentRuntime:
    """返回全局 AgentRuntime 实例，未初始化时抛出错误。"""
    if _agent_runtime is None:
        raise ValueError("AgentRuntime has not been initialized.")
    return _agent_runtime


def get_default_agent() -> LuoTianyiAgent:
    """返回默认角色的意识 Agent。"""
    return get_agent_runtime().get_agent()
