from __future__ import annotations

from typing import Any, Dict, TYPE_CHECKING

from .dependency.activity_context_provider import ActivityContextProvider
from .call_stream_manager import CallStreamManager
from .dependency.conversation_service import ConversationService
from .chat_stream_manager import ChatStreamManager
from .dependency.global_speaking_worker import GlobalSpeakingWorker
from .dependency.proactive_topic_maker import ProactiveTopicMaker
from .reflex_pipeline import ReflexPipeline

if TYPE_CHECKING:
    from src.system.database import DatabaseManager
    from src.utils.llm_service import LLMService


class ChatSessionManager:
    """Owns fast-changing user/character interaction sessions."""

    def __init__(
        self,
        config: Dict[str, Any],
        llm_service: LLMService,
        database_manager: DatabaseManager,
    ) -> None:
        self.config = config
        self.llm_service = llm_service
        self.database_manager = database_manager

        # 会话所依赖的基础模块的的初始化
        self.conversation_service = ConversationService(
            config.get("conversation_service", {}),
            database=database_manager,
            llm_service=llm_service,
        )
        self.global_speaking_worker = GlobalSpeakingWorker(config.get("global_speaking_worker", {}))
        self.proactive_topic_maker = ProactiveTopicMaker(config.get("proactive_topic_maker", {}))
        self.activity_context_provider = ActivityContextProvider(config.get("activity_context_provider", {}))

        # 聊天流和通话流管理器的初始化
        self.chat_stream_manager = ChatStreamManager(
            config.get("chat_stream_manager", {}),
            conversation_service = self.conversation_service,
            global_speaking_worker = self.global_speaking_worker,
            proactive_topic_maker = self.proactive_topic_maker,
            activity_context_provider = self.activity_context_provider,
        )
        self.call_stream_manager = CallStreamManager(
            config.get("call_stream_manager", {}),
            conversation_service = self.conversation_service,
            global_speaking_worker = self.global_speaking_worker,
            proactive_topic_maker = self.proactive_topic_maker,
            activity_context_provider = self.activity_context_provider,
            )

        self.reflex_pipeline = ReflexPipeline(config.get("reflex_pipeline", {}))

    def start_background_services(self) -> None:
        """启动聊天、通话和 speaking worker 后台服务。"""
        self.global_speaking_worker.start_if_needed()
        self.chat_stream_manager.start_cleanup_task()
        self.call_stream_manager.start_background_services()


    async def stop_background_services(self) -> None:
        """停止聊天、通话和 speaking worker 后台服务。"""
        await self.chat_stream_manager.stop_cleanup_task()
        await self.call_stream_manager.stop_background_services()
        await self.global_speaking_worker.stop()

    async def on_user_login(self, user_uuid: str, elapsed_from_last_login: float) -> None:
        """用户登录时，记录主动话题所需的登录活动。"""
        return 
        await self.proactive_topic_maker.add_user_login_activity(user_uuid, elapsed_from_last_login)
