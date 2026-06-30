import asyncio
import time
from typing import Dict, Iterator, Optional, TYPE_CHECKING, Any, Tuple

from src.system.user_interface.websocket_service import WebSocketConnection
from src.chat_session.chat_pipeline.chat_stream import ChatStream
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.system.system_runtime import SystemRuntime
    from src.chat_session.dependency.conversation_service import ConversationService
    from src.chat_session.dependency.global_speaking_worker import GlobalSpeakingWorker
    from src.chat_session.dependency.activity_context_provider import ActivityContextProvider
    from src.chat_session.dependency.proactive_topic_maker import ProactiveTopicMaker


class ChatStreamManager:
    """
    管理所有聊天流的单例类。
    负责维护用户与聊天流之间的映射关系，以及提供全局访问接口。
    """

    def __init__(
        self,
        config: Dict[str, Any],
        conversation_service: "ConversationService",
        global_speaking_worker: "GlobalSpeakingWorker",
        proactive_topic_maker: "ProactiveTopicMaker",
        activity_context_provider: "ActivityContextProvider"
    ):
        self.config = config
        self.logger = get_logger(__name__)

        self.conversation_service: "ConversationService" | None = conversation_service
        self.global_speaking_worker: "GlobalSpeakingWorker" | None = global_speaking_worker
        self.proactive_topic_maker: "ProactiveTopicMaker" | None = proactive_topic_maker
        self.activity_context_provider: "ActivityContextProvider" | None = activity_context_provider


        self.user_streams: Dict[Tuple[str, str], ChatStream] = {}
        self.cleanup_task: asyncio.Task | None = None
        self.default_expiration_seconds = config.get("default_expiration_seconds", 3600)
        self.heartbeat_timeout_seconds = config.get("heartbeat_timeout_seconds", 60)

    def wire_dependencies(
        self,
        *,
        conversation_service: "ConversationService",
        global_speaking_worker: "GlobalSpeakingWorker",
        proactive_topic_maker: "ProactiveTopicMaker",
        activity_context_provider: "ActivityContextProvider",
    ) -> None:
        """注入聊天流管理器创建 ChatStream 所需的依赖。"""
        self.conversation_service = conversation_service
        self.global_speaking_worker = global_speaking_worker
        self.proactive_topic_maker = proactive_topic_maker
        self.activity_context_provider = activity_context_provider
        self.ensure_dependencies()

    def ensure_dependencies(self) -> None:
        """检查聊天流管理器依赖已经初始化。"""
        required = {
            "conversation_service": self.conversation_service,
            "global_speaking_worker": self.global_speaking_worker,
            "proactive_topic_maker": self.proactive_topic_maker,
            "activity_context_provider": self.activity_context_provider,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"ChatStreamManager dependencies are missing: {', '.join(missing)}")

    async def get_or_register_chat_stream(
        self,
        ws_connection: WebSocketConnection,
        character: Optional[str] = "luotianyi",
        system_runtime: Optional["SystemRuntime"] = None,
    ) -> ChatStream:
        """
        根据 WebSocket 连接获取对应的聊天流实例。
        如果不存在，则创建一个新的聊天流实例并注册。
        """
        user_uuid = ws_connection.user_uuid
        if user_uuid is None:
            raise ValueError("WebSocketConnection must have a user_uuid for chat stream management.")

        if (user_uuid, character) not in self.user_streams:  # 创建新的聊天流实例并注册
            chat_stream = ChatStream(self.config.get("chat_stream", {}), ws_connection, character_id=character)
            chat_stream.set_system_runtime(system_runtime)
            await chat_stream.start_if_needed()
            self.user_streams[(user_uuid, character)] = chat_stream
        else: # 如果已经存在聊天流实例，则更新 WebSocket 连接
            chat_stream = self.user_streams[(user_uuid, character)]
            chat_stream.set_system_runtime(system_runtime)
            await chat_stream.reconnect(ws_connection)
        if self.proactive_topic_maker is not None:
            asyncio.create_task(self.proactive_topic_maker.on_user_login(user_uuid, chat_stream=chat_stream))
        return chat_stream

    def get_stream_by_user_uuid(self, user_uuid: str, character: str = "luotianyi") -> ChatStream | None:
        return self.user_streams.get((user_uuid, character))

    def iter_active_streams(self, character_id: str | None = None) -> Iterator[tuple[str, str, ChatStream]]:
        """遍历当前仍在线的聊天流。"""
        for (user_uuid, stream_character_id), chat_stream in list(self.user_streams.items()):
            if character_id is not None and stream_character_id != character_id:
                continue
            if chat_stream is None or chat_stream.is_connection_lost():
                continue
            yield user_uuid, stream_character_id, chat_stream


    def ws_lost_connection(self, ws_connection: WebSocketConnection):
        """
        当 WebSocket 连接丢失时，调用此方法进行清理。
        """
        user_uuid = ws_connection.user_uuid
        if not user_uuid:
            return
        for (stream_user_uuid, _character), chat_stream in self.user_streams.items():
            if stream_user_uuid == user_uuid:
                chat_stream.lost_connection()

    async def cleanup_expired_streams(self, expiration_seconds: int = 3600):
        """
        定期清理过期的聊天流实例。
        """
        while True:
            current_time = time.time()
            current_time_ms = int(current_time * 1000)

            for stream_key in list(self.user_streams.keys()):
                stream = self.user_streams[stream_key]
                ws_connection = stream.ws_connection
                if (
                    ws_connection
                    and ws_connection.last_ping_time
                    and (current_time_ms - ws_connection.last_ping_time > self.heartbeat_timeout_seconds * 1000)
                ):
                    await ws_connection.websocket.close()
                    self.ws_lost_connection(ws_connection)

            expired_stream_keys = []
            for stream_key, chat_stream in list(self.user_streams.items()):
                if chat_stream.connection_lost_time and (current_time - chat_stream.connection_lost_time > expiration_seconds):
                    expired_stream_keys.append(stream_key)

            for stream_key in expired_stream_keys:
                user_uuid, _character = stream_key
                chat_stream = self.user_streams[stream_key]
                chat_stream.clean_up()
                del self.user_streams[stream_key]
                self.logger.info(f"Cleaned up expired chat stream for user_uuid={user_uuid}")

            await asyncio.sleep(60)

    def start_cleanup_task(self, expiration_seconds: Optional[int] = None):
        self.ensure_dependencies()
        if self.cleanup_task is not None and not self.cleanup_task.done():
            return
        if expiration_seconds is None:
            expiration_seconds = self.default_expiration_seconds
        self.cleanup_task = asyncio.create_task(self.cleanup_expired_streams(expiration_seconds))

    async def stop_cleanup_task(self):
        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                self.logger.info("ChatStreamManager cleanup task cancelled")
        self.cleanup_task = None


chat_stream_manager: ChatStreamManager | None = None


def get_GCSM() -> ChatStreamManager:
    global chat_stream_manager
    if chat_stream_manager is None:
        raise RuntimeError("ChatStreamManager has not been initialized.")
    return chat_stream_manager
