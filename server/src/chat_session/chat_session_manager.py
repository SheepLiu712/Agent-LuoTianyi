from typing import Dict, TYPE_CHECKING
from .global_chat_stream_manager import GlobalChatStreamManager
from .global_speaking_worker import GlobalSpeakingWorker
from .proactive_topic_maker import ProactiveTopicMaker
if TYPE_CHECKING:
    from src.utils.llm_service import LLMService

class ChatSessionManager:
    def __init__(self, config: Dict, llm_service: LLMService):
        self.llm_service = llm_service
        self.global_chat_stream_manager = GlobalChatStreamManager(config.get("global_chat_stream_manager", {}))
        self.global_speaking_worker = GlobalSpeakingWorker(config.get("global_speaking_worker", {}))
        self.proactive_topic_maker = ProactiveTopicMaker(config.get("proactive_topic_maker", {}))


    def start_background_services(self):
        '''
        启动全局聊天流管理器和全局 speaking worker 的后台服务。
        '''
        self.global_chat_stream_manager.start_cleanup_task()
        self.global_speaking_worker.start_if_needed()

    async def stop_background_services(self):
        '''
        停止全局聊天流管理器和全局 speaking worker 的后台服务。
        '''
        await self.global_chat_stream_manager.stop_cleanup_task()
        await self.global_speaking_worker.stop()

    async def on_user_login(self, user_uuid: str, elapsed_from_last_login: float):
        """
        当用户登录时，触发 ProactiveTopicMaker 的用户登录活动处理。
        """
        await self.proactive_topic_maker.add_user_login_activity(user_uuid, elapsed_from_last_login)