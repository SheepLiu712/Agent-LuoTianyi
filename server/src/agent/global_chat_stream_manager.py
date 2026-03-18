import asyncio
import time
from typing import Dict

from ..service.websocket_service import WebSocketConnection
from ..service.service_hub import ServiceHub
from .chat_stream import ChatStream
from ..utils.logger import get_logger


class GlobalChatStreamManager:
    """
    管理所有聊天流的单例类。
    负责维护用户与聊天流之间的映射关系，以及提供全局访问接口。
    """

    def __init__(self):
        self.user_streams: Dict[str, ChatStream] = {}
        self.cleanup_task: asyncio.Task | None = None
        self.logger = get_logger("GlobalChatStreamManager")

    def get_or_register_chat_stream(
        self,
        ws_connection: WebSocketConnection,
        service_hub: ServiceHub | None = None,
    ) -> ChatStream:
        """
        根据 WebSocket 连接获取对应的聊天流实例。
        如果不存在，则创建一个新的聊天流实例并注册。
        """
        user_uuid = ws_connection.user_uuid
        if user_uuid is None:
            raise ValueError("WebSocketConnection must have a user_uuid for chat stream management.")

        if user_uuid not in self.user_streams:
            chat_stream = ChatStream(ws_connection)
            if service_hub is not None:
                chat_stream.set_service_hub(service_hub)
            chat_stream.start_if_needed()
            self.user_streams[user_uuid] = chat_stream
            return chat_stream

        chat_stream = self.user_streams[user_uuid]
        if service_hub is not None:
            chat_stream.set_service_hub(service_hub)
        chat_stream.reconnect(ws_connection)
        return chat_stream

    def get_stream_by_user_uuid(self, user_uuid: str) -> ChatStream | None:
        return self.user_streams.get(user_uuid)

    def ws_lost_connection(self, ws_connection: WebSocketConnection):
        """
        当 WebSocket 连接丢失时，调用此方法进行清理。
        """
        user_uuid = ws_connection.user_uuid
        if not user_uuid or user_uuid not in self.user_streams:
            return
        chat_stream = self.user_streams[user_uuid]
        chat_stream.lost_connection()

    async def cleanup_expired_streams(self, expiration_seconds: int = 3600):
        """
        定期清理过期的聊天流实例。
        """
        while True:
            current_time = time.time()
            current_time_ms = int(current_time * 1000)

            for user_uuid in list(self.user_streams.keys()):
                stream = self.user_streams[user_uuid]
                ws_connection = stream.ws_connection
                if ws_connection and ws_connection.last_ping_time and (current_time_ms - ws_connection.last_ping_time > 60 * 1000):
                    await ws_connection.websocket.close()
                    self.ws_lost_connection(ws_connection)

            expired_user_uuids = []
            for user_uuid, chat_stream in list(self.user_streams.items()):
                if chat_stream.connection_lost_time and (current_time - chat_stream.connection_lost_time > expiration_seconds):
                    expired_user_uuids.append(user_uuid)

            for user_uuid in expired_user_uuids:
                chat_stream = self.user_streams[user_uuid]
                chat_stream.clean_up()
                del self.user_streams[user_uuid]

            await asyncio.sleep(60)

    def start_cleanup_task(self, expiration_seconds: int = 3600):
        self.cleanup_task = asyncio.create_task(self.cleanup_expired_streams(expiration_seconds))
    
    async def stop_cleanup_task(self):
        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                self.logger.info("GlobalChatStreamManager cleanup task cancelled")


chat_stream_manager: GlobalChatStreamManager | None = None


def get_GCSM() -> GlobalChatStreamManager:
    global chat_stream_manager
    if chat_stream_manager is None:
        chat_stream_manager = GlobalChatStreamManager()
    return chat_stream_manager
