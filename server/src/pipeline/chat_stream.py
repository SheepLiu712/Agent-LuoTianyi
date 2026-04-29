import asyncio
import time
from typing import List, Optional, Tuple

from ..interface.types import ChatResponse
from ..interface.websocket_service import WebSocketConnection
from ..utils.logger import get_logger
from .chat_events import ChatInputEvent, ChatInputEventType
from ..interface.service_hub import ServiceHub
from ..interface.types import WSEventType

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
        self.topic_replier = TopicReplier(username=self.user_name, user_id=self.user_uuid, send_reply_callback=self.feed_response)
        self.topic_planner.set_topic_consumer(self.topic_replier.add_topic)
        self.topic_replier.set_change_state_callback(self.change_state)
        self.ingress_queue: asyncio.Queue[ChatInputEvent] = asyncio.Queue()
        self.ingress_worker_task: asyncio.Task | None = None
        self.response_queue: asyncio.Queue[ChatResponse] = asyncio.Queue()
        self.response_sender_task: asyncio.Task | None = None

        self.state = self.STATE_WAITING
        self.state_lock = asyncio.Lock()

    def set_service_hub(self, service_hub: ServiceHub):
        if service_hub is None:
            self.logger.warning("Setting service hub to None, chat stream cannot function properly")
            return
        if self.service_hub is not None and self.service_hub != service_hub:
            self.logger.warning("Service hub is already set, overwriting with new value")
        self.service_hub = service_hub
        self.topic_planner.set_service_hub(service_hub)
        self.topic_replier.set_service_hub(service_hub)

    def start_if_needed(self):
        """启动常驻消息处理协程（仅启动一次）。"""
        self._start_ingress_worker()
        self.topic_planner.start_processing()
        self.topic_replier.start_processing()
        self._start_response_sender()

    async def feed_event(self, event: ChatInputEvent):
        """接收 service 层转换后的聊天事件，并交给 ingress worker。"""
        await self.ingress_queue.put(event)

    async def ingress_worker_loop(self):
        while True:
            event: ChatInputEvent | None = None
            try:
                event = await self.ingress_queue.get()
                await self._process_ingress_event(event)
            except asyncio.CancelledError:
                self.logger.info("Ingress worker task cancelled")
                break
            except Exception as e:
                self.logger.exception(f"Error in ingress worker loop: {e}")
                await asyncio.sleep(0.1)
            finally:
                if event is not None:
                    self.ingress_queue.task_done()

    async def _process_ingress_event(self, event: ChatInputEvent):
        if self._is_user_message_event(event):
            if self.service_hub is not None and self.user_uuid is not None:
                await self.service_hub.activity_maker.on_user_message(self.user_uuid)
                await ingress_message(self.service_hub, self.user_uuid, event)  # 预处理
                await self.service_hub.agent.add_conversation(self.service_hub, self.user_uuid, event)  # 入库
            else:
                self.logger.warning("Service hub or user uuid is missing, skip user message preprocessing")

        await self.topic_planner.feed_unread_message(event)

    async def feed_response(self, response: ChatResponse):
        """接收 topic replier 生成的回复，并发送给用户。"""
        await self.response_queue.put(response)

    async def response_sender_loop(self):
        while True:
            response = None
            try:
                response = await self.response_queue.get()
                while True:
                    sent = await self._send_response(response)
                    if sent:
                        break
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                self.logger.info("Response sender task cancelled")
                break
            except Exception as e:
                self.logger.error(f"Error in response sender loop: {e}")
                await asyncio.sleep(1)
            finally:
                if response is not None:
                    self.response_queue.task_done()

    async def change_state(self, thinking: Optional[bool] = None, speaking: Optional[bool] = None):
        async with self.state_lock:
            if thinking == True: # 由replier调用，进入思考状态时必然更新状态
                self.state = self.STATE_THINKING
                await self._send_agent_state(self.STATE_THINKING)
                return
            if speaking == True: # 由chat_stream的_send_response调用，此时如果不在思考，则认为进入WAITING状态
                if not self.topic_replier.is_processing and self.state != self.STATE_WAITING:
                    self.state = self.STATE_WAITING
                    await self._send_agent_state(self.STATE_WAITING)
                return
            if thinking == False:
                if self.state != self.STATE_WAITING:
                    self.state = self.STATE_WAITING
                    await self._send_agent_state(self.STATE_WAITING)
                return

    async def _send_response(self, response: ChatResponse) -> bool:
        if self.ws_connection is None or self.ws_connection.websocket is None:
            return False
        ws_service = self.service_hub.websocket_service if self.service_hub else None
        if ws_service is None:
            self.logger.warning("WebSocket service is not available, cannot send response")
            return False
        try:
            await self.change_state(speaking=True) # 发送回复前更新状态
            event = ws_service._make_event(
                WSEventType.AGENT_MESSAGE,
                response.model_dump() if hasattr(response, "model_dump") else response.dict(),
            )
            await self.ws_connection.websocket.send_json(event)
            return True
        except Exception as e:
            self.logger.warning(f"Send response failed, will retry: {e}")
            return False
        
    async def _send_agent_state(self, state: str) -> bool:
        if self.ws_connection is None or self.ws_connection.websocket is None:
            return False
        ws_service = self.service_hub.websocket_service if self.service_hub else None
        if ws_service is None:
            self.logger.warning("WebSocket service is not available, cannot send agent state")
            return False
        try:
            self.logger.info(f"Sending agent state change event: {state}")
            event = ws_service._make_event(
                WSEventType.AGENT_STATE_CHANGED,
                {"state": state},
            )
            await self.ws_connection.websocket.send_json(event)
            return True
        except Exception as e:
            self.logger.warning(f"Send agent state failed, will retry: {e}")
            return False

    def _start_response_sender(self):
        if self.response_sender_task is None or self.response_sender_task.done():
            self.response_sender_task = asyncio.create_task(self.response_sender_loop())
            self.logger.info("Started response sender task")

    def _start_ingress_worker(self):
        if self.ingress_worker_task is None or self.ingress_worker_task.done():
            self.ingress_worker_task = asyncio.create_task(self.ingress_worker_loop())
            self.logger.info("Started ingress worker task")

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
        if self.ingress_worker_task and not self.ingress_worker_task.done():
            self.ingress_worker_task.cancel()
        if self.topic_planner.processor_task and not self.topic_planner.processor_task.done():
            self.topic_planner.processor_task.cancel()
        if self.topic_replier.processor_task and not self.topic_replier.processor_task.done():
            self.topic_replier.processor_task.cancel()
        if self.response_sender_task and not self.response_sender_task.done():
            self.response_sender_task.cancel()
