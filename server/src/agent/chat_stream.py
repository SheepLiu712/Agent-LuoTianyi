import asyncio
import time
from typing import List, Optional, Tuple

from ..service.types import ChatResponse
from ..service.websocket_service import WebSocketConnection
from ..utils.logger import get_logger
from .chat_events import ChatInputEvent, ChatInputEventType
from ..service.service_hub import ServiceHub
from ..service.types import WSEventType


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
        self.message_queue = asyncio.Queue(maxsize=256)
        self.thinking_task: asyncio.Task | None = None
        self.processor_task: asyncio.Task | None = None
        self.current_state: str = self.STATE_WAITING
        self.listening_timeout_seconds: float = 1.5
        self.listening_deadline: Optional[float] = None
        self.state_lock = asyncio.Lock()

    def set_service_hub(self, service_hub: ServiceHub):
        self.service_hub = service_hub

    def start_if_needed(self):
        """启动常驻消息处理协程（仅启动一次）。"""
        if self.processor_task is None or self.processor_task.done():
            self.processor_task = asyncio.create_task(self.message_processor())
            self.logger.info("ChatStream processor task started")

    async def feed_event(self, event: ChatInputEvent):
        """接收 service 层转换后的聊天事件。"""
        if self._is_user_message_event(event):
            if self.current_state == self.STATE_THINKING and self.thinking_task and not self.thinking_task.done():
                self.thinking_task.cancel()
        await self._send_ack(event)
        await self.message_queue.put(event)

    async def message_processor(self):
        """持续运行的状态机逻辑层，仅处理 ChatInputEvent。"""
        while True:
            unread_user_messages: List[ChatInputEvent] = []

            first_event = await self.message_queue.get()
            try:
                # 获取积压的信息，同时处理用户输入事件和用户输入中事件（重置超时）
                if self._is_user_typing_event(first_event):
                    self._handle_user_typing(first_event)
                    self.message_queue.task_done()
                    continue

                unread_user_messages.append(first_event)
                while True:
                    try:
                        event = self.message_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

                    if self._is_user_typing_event(event):
                        self._handle_user_typing(event)
                        self.message_queue.task_done()
                        continue
                    unread_user_messages.append(event)

                await self.service_hub.agent.feed_user_messages(self.service_hub, self.user_uuid, unread_user_messages)

                # 进入 listening 状态，等待用户输入结束的信号（超时或符合结束条件）
                await self._transition_to(self.STATE_LISTENING)
                self.listening_deadline = time.monotonic() + self.listening_timeout_seconds
                username = self.user_name
                while self.current_state == self.STATE_LISTENING:
                    self.logger.debug(f"{username}进入 listening 状态，等待用户继续输入（已收到消息数={len(unread_user_messages)}）")
                    timeout = max(0.0, self.listening_deadline - time.monotonic())
                    try:
                        next_event = await asyncio.wait_for(self.message_queue.get(), timeout=timeout)
                    except asyncio.TimeoutError:
                        await self._transition_to(self.STATE_THINKING)
                        self.logger.debug(f"{username} listening 超时，进入 thinking 状态")
                        break

                    if self._is_user_typing_event(next_event):
                        self._handle_user_typing(next_event)
                        self.message_queue.task_done()
                        continue

                    await self.service_hub.agent.feed_user_messages(self.service_hub, self.user_uuid, [next_event])

                if self.current_state != self.STATE_THINKING:
                    await self._transition_to(self.STATE_THINKING)

                self.thinking_task = asyncio.create_task(self.service_hub.agent.do_think_for_chat_stream(self.service_hub, self.user_uuid))
                interrupted = False
                try:
                    await self.thinking_task
                except asyncio.CancelledError:
                    interrupted = True
                finally:
                    self.thinking_task = None

                if interrupted:
                    await self._transition_to(self.STATE_LISTENING)
                    self.listening_deadline = time.monotonic() + self.listening_timeout_seconds
                    username = self.user_name
                    self.logger.debug(f"{username} thinking 阶段被打断，进入 listening 状态")
                    continue

                await self._transition_to(self.STATE_REFLECTION)
                await self._transition_to(self.STATE_WAITING)
            finally:
                for _ in unread_user_messages:
                    self.message_queue.task_done()

    async def send_response(self, response: ChatResponse):
        if self.ws_connection is None or self.ws_connection.websocket is None:
            return
        ws_service = self.service_hub.websocket_service if self.service_hub else None
        if ws_service is None:
            self.logger.warning("WebSocket service is not available, cannot send response")
            return
        event = ws_service._make_event(WSEventType.AGENT_MESSAGE, response.model_dump() if hasattr(response, "model_dump") else response.dict())
        await self.ws_connection.websocket.send_json(event)


    def _handle_user_typing(self, event: ChatInputEvent):
        """处理用户输入事件：listening 阶段重置超时。"""
        _ = event
        if self.current_state == self.STATE_LISTENING:
            self.listening_deadline = time.monotonic() + self.listening_timeout_seconds

    async def _send_ack(self, event: ChatInputEvent):
        """对于用户消息事件，发送 ACK 确认收到。"""
        if not (self._is_user_message_event(event) or self._is_user_typing_event(event)):
            return
        if self.ws_connection is None or self.ws_connection.websocket is None:
            return
        ws_service = self.service_hub.websocket_service if self.service_hub else None
        if ws_service is None:
            self.logger.warning("WebSocket service is not available, cannot send ACK")
            return
        received_event_type = event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
        ack_event = ws_service._make_event(
            WSEventType.SERVER_ACK,
            {"received_event_type": received_event_type},
            reply_to=event.client_msg_id,
        )
        await self.ws_connection.websocket.send_json(ack_event)

    async def _transition_to(self, new_state: str):
        async with self.state_lock:
            if self.current_state == new_state:
                return
            old_state = self.current_state
            self.current_state = new_state

        self.logger.info(f"state transition: {old_state} -> {new_state}")
        if self.service_hub is None or self.ws_connection is None or self.ws_connection.websocket is None:
            return
        try:
            await self.service_hub.websocket_service.send_agent_state_event(self.ws_connection.websocket, new_state)
        except Exception as e:
            self.logger.warning(f"failed to send state event: {e}")


    def _is_user_message_event(self, event: ChatInputEvent) -> bool:
        return event.event_type in {ChatInputEventType.USER_TEXT, ChatInputEventType.USER_IMAGE}

    def _is_user_typing_event(self, event: ChatInputEvent) -> bool:
        return event.event_type == ChatInputEventType.USER_TYPING

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
        if self.thinking_task and not self.thinking_task.done():
            self.thinking_task.cancel()
        if self.processor_task and not self.processor_task.done():
            self.processor_task.cancel()
        self.listening_deadline = None
        self.current_state = self.STATE_WAITING

        # 丢弃旧队列，避免断连后遗留消息影响重连流程。
        self.message_queue = asyncio.Queue(maxsize=256)
