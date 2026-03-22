import asyncio
import time
from typing import List, Optional, Tuple

from ..service.types import ChatResponse
from ..service.websocket_service import WebSocketConnection
from ..utils.logger import get_logger
from .chat_events import ChatInputEvent, ChatInputEventType
from ..service.service_hub import ServiceHub
from ..service.types import WSEventType

from .modules.ingress import ingress_message
from .topic_planner import TopicPlanner
from .topic_replier import TopicReplier


class ChatStream:
    STATE_WAITING = "waiting"
    STATE_REFLECTION = "reflection"
    STATE_LISTENING = "listening"
    STATE_THINKING = "thinking"

    def __init__(self, ws_connection: WebSocketConnection):
        self.ws_connection = ws_connection
        self.user_name: str = ws_connection.user_name if ws_connection else "unknown"
        self.user_uuid: Optional[str] = ws_connection.user_uuid if ws_connection else None
        self.logger = get_logger(f"{self.user_name}ChatStream")
        self.service_hub: ServiceHub | None = None
        self.connection_lost_time = None
        self.topic_planner = TopicPlanner(username=self.user_name, user_id=self.user_uuid)
        self.topic_replier = TopicReplier(username=self.user_name, user_id=self.user_uuid)
        self.topic_planner.set_topic_consumer(self.topic_replier.add_topic)

        self.state_lock = asyncio.Lock()

    def set_service_hub(self, service_hub: ServiceHub):
        self.service_hub = service_hub
        self.topic_planner.set_service_hub(service_hub)
        self.topic_replier.set_service_hub(service_hub)

    def start_if_needed(self):
        """启动常驻消息处理协程（仅启动一次）。"""
        self.topic_planner.start_processing()
        self.topic_replier.start_processing()

    async def feed_event(self, event: ChatInputEvent):
        """接收 service 层转换后的聊天事件。"""
        if self._is_user_message_event(event):
            await ingress_message(self.service_hub, self.user_name, event)
            await self.service_hub.agent.add_conversation(self.service_hub, self.user_uuid, event)
        await self.topic_planner.feed_unread_message(event)

    async def send_response(self, response: ChatResponse):
        if self.ws_connection is None or self.ws_connection.websocket is None:
            return
        ws_service = self.service_hub.websocket_service if self.service_hub else None
        if ws_service is None:
            self.logger.warning("WebSocket service is not available, cannot send response")
            return
        event = ws_service._make_event(WSEventType.AGENT_MESSAGE, response.model_dump() if hasattr(response, "model_dump") else response.dict())
        await self.ws_connection.websocket.send_json(event)


    def _is_user_message_event(self, event: ChatInputEvent) -> bool:
        return event.event_type in {ChatInputEventType.USER_TEXT, ChatInputEventType.USER_IMAGE}


    ####### 下方为连接管理相关方法 #######

    def lost_connection(self):
        """连接丢失时的清理逻辑"""
        self.ws_connection = None
        self.connection_lost_time = time.time()

    def is_connection_lost(self):
        """检查连接是否丢失"""
        return self.ws_connection is None

    def reconnect(self, new_ws_connection: WebSocketConnection):
        """用户重连时调用，更新 WebSocket 连接"""
        self.logger.info(f"User {self.user_name} reconnected")
        self.ws_connection = new_ws_connection
        self.user_name = new_ws_connection.user_name if new_ws_connection else self.user_name
        self.connection_lost_time = None
        self.current_state = self.STATE_WAITING
        self.start_if_needed()

    def clean_up(self):
        """清理资源的逻辑，比如关闭文件、数据库连接等"""
        if self.topic_planner.processor_task and not self.topic_planner.processor_task.done():
            self.topic_planner.processor_task.cancel()
        if self.topic_replier.processor_task and not self.topic_replier.processor_task.done():
            self.topic_replier.processor_task.cancel()
