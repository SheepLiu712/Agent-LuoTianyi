from __future__ import annotations

from typing import Any, Dict, Optional, TYPE_CHECKING

from .dependency.activity_context_provider import ActivityContextProvider
from .call_stream_manager import CallStreamManager
from .dependency.conversation_service import ConversationService
from .chat_stream_manager import ChatStreamManager
from . import chat_stream_manager as chat_stream_manager_module
from .dependency.global_speaking_worker import GlobalSpeakingWorker
from .dependency.proactive_topic_maker import ProactiveTopicMaker

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
        chat_stream_manager_module.chat_stream_manager = self.chat_stream_manager
        self.proactive_topic_maker.configure(
            conversation_service=self.conversation_service,
            database_manager=self.database_manager,
            chat_stream_manager=self.chat_stream_manager,
        )
        self.call_stream_manager = CallStreamManager(
            config.get("call_stream_manager", {}),
            conversation_service = self.conversation_service,
            global_speaking_worker = self.global_speaking_worker,
            proactive_topic_maker = self.proactive_topic_maker,
            activity_context_provider = self.activity_context_provider,
            )

    def wire_dependencies(
        self,
        *,
        database_manager: "DatabaseManager",
        llm_service: "LLMService",
        capability_manager,
    ) -> None:
        """向聊天会话模块及其子模块派发依赖。"""
        self.database_manager = database_manager
        self.llm_service = llm_service
        self.conversation_service.wire_dependencies(database=database_manager, llm_service=llm_service)
        self.global_speaking_worker.wire_dependencies(capabilities=capability_manager)
        self.proactive_topic_maker.configure(
            conversation_service=self.conversation_service,
            database_manager=database_manager,
            chat_stream_manager=self.chat_stream_manager,
        )
        self.activity_context_provider.ensure_dependencies()
        self.chat_stream_manager.wire_dependencies(
            conversation_service=self.conversation_service,
            global_speaking_worker=self.global_speaking_worker,
            proactive_topic_maker=self.proactive_topic_maker,
            activity_context_provider=self.activity_context_provider,
        )
        self.call_stream_manager.wire_dependencies(
            conversation_service=self.conversation_service,
            global_speaking_worker=self.global_speaking_worker,
            proactive_topic_maker=self.proactive_topic_maker,
            activity_context_provider=self.activity_context_provider,
        )
        self.ensure_dependencies()

    def ensure_dependencies(self) -> None:
        """检查聊天会话模块和子模块依赖已经初始化。"""
        required = {
            "llm_service": self.llm_service,
            "database_manager": self.database_manager,
            "conversation_service": self.conversation_service,
            "global_speaking_worker": self.global_speaking_worker,
            "proactive_topic_maker": self.proactive_topic_maker,
            "activity_context_provider": self.activity_context_provider,
            "chat_stream_manager": self.chat_stream_manager,
            "call_stream_manager": self.call_stream_manager,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"ChatSessionManager dependencies are missing: {', '.join(missing)}")
        self.conversation_service.ensure_dependencies()
        self.global_speaking_worker.ensure_dependencies()
        self.proactive_topic_maker.ensure_dependencies()
        self.activity_context_provider.ensure_dependencies()
        self.chat_stream_manager.ensure_dependencies()
        self.call_stream_manager.ensure_dependencies()

    def start_background_services(self) -> None:
        """启动聊天、通话和 speaking worker 后台服务。"""
        self.ensure_dependencies()
        self.global_speaking_worker.start_if_needed()
        self.chat_stream_manager.start_cleanup_task()
        self.call_stream_manager.start_background_services()


    async def stop_background_services(self) -> None:
        """停止聊天、通话和 speaking worker 后台服务。"""
        await self.chat_stream_manager.stop_cleanup_task()
        await self.call_stream_manager.stop_background_services()
        await self.global_speaking_worker.stop()

    async def on_user_login(self, user_uuid: str, elapsed_from_last_login: Optional[float]) -> None:
        """用户登录时，记录主动话题所需的登录活动。"""
        await self.proactive_topic_maker.on_user_login(user_uuid, elapsed_from_last_login)
