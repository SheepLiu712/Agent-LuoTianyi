from typing import Dict
from ..service.websocket_service import WebSocketConnection
from .chat_stream import ChatStream
from .service_hub import ServiceHub
import time
import asyncio

class GlobalChatStreamManager:
    """
    管理所有聊天流的单例类。
    负责维护用户与聊天流之间的映射关系，以及提供全局访问接口。
    """
    def __init__(self):
        self.user_streams: Dict[str, ChatStream] = {}
    
    def get_or_register_chat_stream(self, ws_connection: WebSocketConnection, service_hub: ServiceHub | None = None) -> ChatStream:
        """
        根据WebSocket连接获取对应的聊天流实例。
        如果不存在，则创建一个新的聊天流实例并注册。
        """
        user_uuid = ws_connection.user_uuid
        if user_uuid is None:
            raise ValueError("WebSocketConnection must have a user_uuid for chat stream management.")
        
        # 新用户：创建新的聊天流实例并注册
        if user_uuid not in self.user_streams:
            chat_stream = ChatStream(ws_connection)
            if service_hub is not None:
                chat_stream.set_service_hub(service_hub)
            chat_stream.start_if_needed()
            self.user_streams[user_uuid] = chat_stream
            return chat_stream

        # 老用户重连：复用现有流并更新连接
        chat_stream = self.user_streams[user_uuid]
        if service_hub is not None:
            chat_stream.set_service_hub(service_hub)
        chat_stream.reconnect(ws_connection)
        return chat_stream

    def get_stream_by_user_uuid(self, user_uuid: str) -> ChatStream:
        return self.user_streams.get(user_uuid)
    
    def ws_lost_connection(self, ws_connection: WebSocketConnection):
        """
        当WebSocket连接丢失时，调用此方法进行清理。
        根据连接的用户UUID找到对应的聊天流实例，并执行必要的清理操作。
        """
        # ws_connection丢失，不代表要马上关闭聊天流实例，因为用户可能会重连。这里我们可以选择暂时保留聊天流实例，或者根据实际需求进行清理。
        user_uuid = ws_connection.user_uuid
        if not user_uuid or not user_uuid in self.user_streams:
            return
        chat_stream = self.user_streams[user_uuid]
        chat_stream.lost_connection()  # 调用聊天流实例的连接丢失处理方法

    async def cleanup_expired_streams(self, expiration_seconds: int = 3600):
        """
        定期清理过期的聊天流实例。
        如果一个聊天流实例的连接丢失时间超过了指定的过期时间，则将其从管理器中移除。
        """
        while True:
            current_time = time.time()
            current_time_ms = int(current_time * 1000)
            # 检查ws 心跳包是否过期，如果过期执行清理逻辑
            for user_uuid in list(self.user_streams.keys()):
                if self.user_streams[user_uuid].ws_connection \
                and self.user_streams[user_uuid].ws_connection.last_ping_time \
                and (current_time_ms - self.user_streams[user_uuid].ws_connection.last_ping_time > 60 * 1000): # 这里以60秒为例，实际可以根据需求调整
                    await self.user_streams[user_uuid].ws_connection.websocket.close()  # 关闭WebSocket连接
                    self.ws_lost_connection(self.user_streams[user_uuid].ws_connection)

            # 找出所有过期的用户UUID
            expired_user_uuids = []
            for user_uuid, chat_stream in list(self.user_streams.items()):
                if chat_stream.connection_lost_time and (current_time - chat_stream.connection_lost_time > expiration_seconds):
                    expired_user_uuids.append(user_uuid)
            
            for user_uuid in expired_user_uuids:
                chat_stream = self.user_streams[user_uuid]
                chat_stream.clean_up()
                del self.user_streams[user_uuid]
            await asyncio.sleep(60)  # 等待一段时间再进行下一次清理


chat_stream_manager = None

def get_GCSM():
    global chat_stream_manager
    if chat_stream_manager is None:
        chat_stream_manager = GlobalChatStreamManager()
    return chat_stream_manager
