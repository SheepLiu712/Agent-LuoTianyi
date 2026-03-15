from fastapi import WebSocketDisconnect
from ..service.websocket_service import WebSocketConnection, WebSocketService
from .service_hub import ServiceHub
from ..service.types import WSMessage, WSEventType
import asyncio
from ..utils.logger import get_logger
import time
from typing import Optional, List, Tuple


class ChatStream:
    STATE_WAITING = "waiting"
    STATE_REFLECTION = "reflection"
    STATE_LISTENING = "listening"
    STATE_THINKING = "thinking"

    def __init__(self, ws_connection: WebSocketConnection):
        self.logger = get_logger("TianyiChatStream")
        self.ws_connection = ws_connection
        self.user_name: str = ws_connection.user_name if ws_connection else "unknown"
        self.service_hub: ServiceHub | None = None
        self.connection_lost_time = None
        self.message_queue = asyncio.Queue(maxsize=256)
        self.thinking_task: asyncio.Task | None = None  # 用于追踪当前的思考任务
        self.reply_queue = asyncio.Queue()  # 用于存储需要说的话，speaker协程会持续监听这个队列并发送消息
        self.speaking_task: asyncio.Task | None = None  # 用于追踪当前的说话任务
        self.processor_task: asyncio.Task | None = None
        self.current_state: str = self.STATE_WAITING
        self.listening_timeout_seconds: float = 3.0
        self.listening_deadline: Optional[float] = None
        self.state_lock = asyncio.Lock()

    def set_service_hub(self, service_hub: ServiceHub):
        self.service_hub = service_hub

    def start_if_needed(self):
        """启动常驻消息处理协程（仅启动一次）。"""
        if self.processor_task is None or self.processor_task.done():
            self.processor_task = asyncio.create_task(self.message_processor())
            self.logger.info("ChatStream processor task started")
        if self.speaking_task is None or self.speaking_task.done():
            self.speaking_task = asyncio.create_task(self.reply_speaker()) # 占位，后续改为实际消息
            self.logger.info("ChatStream speaking task started")


    async def listen_connection(self, websocket_service: WebSocketService):
        """只负责读取当前 WebSocket 连接并将消息投递进队列。"""
        try:
            while True:
                data: WSMessage = await websocket_service.try_recv_client_msg(self.ws_connection)
                if data is None:
                    continue
                # 收到新消息，直接扔进队列
                if data.event_type == WSEventType.HB_PING.value: # 心跳消息直接回复，不进入思考流程
                    await websocket_service.handle_ping_event(self.ws_connection, data)
                    continue

                # thinking 阶段可被用户消息打断；speaking / reflection 不可打断
                if self._is_user_message_event(data):
                    if self.current_state == self.STATE_THINKING and self.thinking_task and not self.thinking_task.done():
                        self.thinking_task.cancel()

                await self.message_queue.put(data)
                    
        except WebSocketDisconnect:
            self.logger.info(f"用户{self.ws_connection.user_name}下线，保留 ChatStream 继续运行")
            raise

    async def message_processor(self):
        """持续运行的状态机逻辑层，此处，我们保证进来的所有消息都是有实际输入的消息（用户消息、系统事件等），不包含心跳和typing等控制消息。"""
        while True:
            unread_user_messages: List[WSMessage] = []  # 本轮已读取但尚未 task_done 的用户消息

            # 1. 进入本轮会话，读取所有未处理的消息。
            first_event = await self.message_queue.get()
            try:
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

                # 处理消息，考虑是否进入 listening 状态（等待用户继续输入）或者直接进入 thinking 状态（用户已经输入完成）
                will_listen, interpreted_user_messages = self._interpret_messages(unread_user_messages)

                if will_listen:
                    await self._transition_to(self.STATE_LISTENING)
                    self.listening_deadline = time.monotonic() + self.listening_timeout_seconds
                    while self.current_state == self.STATE_LISTENING:
                        username = self.user_name
                        self.logger.debug(f"{username}进入 listening 状态，等待用户继续输入（已收到消息数={len(unread_user_messages)}）")
                        timeout = max(0.0, self.listening_deadline - time.monotonic())
                        try:
                            next_event = await asyncio.wait_for(self.message_queue.get(), timeout=timeout)
                        except asyncio.TimeoutError: # 超时未收到新消息，认为用户输入完成
                            await self._transition_to(self.STATE_THINKING)
                            self.logger.debug(f"{username} listening 超时，进入 thinking 状态")
                            break

                        # 如果收到的是typing事件，说明用户还在输入，继续等待
                        if self._is_user_typing_event(next_event):
                            self._handle_user_typing(next_event)
                            self.message_queue.task_done()
                            continue

                        # 若收到消息，重新判断是否继续 listening 或者进入 thinking
                        unread_user_messages.append(next_event)
                        will_listen, interpreted_user_messages = self._interpret_messages(unread_user_messages)
                        if not will_listen:
                            await self._transition_to(self.STATE_THINKING)
                            self.logger.debug(f"{username} listening 收到新消息，进入 thinking 状态")
                            break
                else:
                    await self._transition_to(self.STATE_THINKING)

                # 此时 interpreted_user_messages 中存储了用户本轮输入的所有消息，进入 thinking 和 reply_queue 流程
                if not interpreted_user_messages:
                    await self._transition_to(self.STATE_WAITING)
                    continue
                if self.current_state != self.STATE_THINKING:
                    await self._transition_to(self.STATE_THINKING)

                self.thinking_task = asyncio.create_task(self.do_think(interpreted_user_messages))
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
                await self._do_reflection(user_text=interpreted_user_messages)
                await self._transition_to(self.STATE_WAITING)
            finally:
                for _ in unread_user_messages:
                    self.message_queue.task_done()

    async def do_think(self, user_text: str):
        """执行 thinking，一旦有了thinking结果，丢到 speak_task_queue 里等待说话协程发送。"""
        if self.service_hub is None:
            self.logger.warning("ServiceHub is not set, skip think and speak")
            return
        if self.ws_connection is None or self.ws_connection.user_uuid is None:
            self.logger.warning("WebSocket connection not ready, skip think and speak")
            return
        pass # placeholder

    async def reply_speaker(self):
        """持续监听 reply_queue，一旦有需要说的话，就发送给用户。"""
        while True:
            response = await self.reply_queue.get() # 等待需要说的话
            try:
                await self._send_agent_message(response)
            finally:
                self.reply_queue.task_done()

    async def _do_reflection(self, user_text: str):
        """reflection 阶段占位：后续可补充摘要、知识图谱抽取等。"""
        _ = user_text
        await asyncio.sleep(0)

    def _handle_user_typing(self, event: WSMessage):
        """处理用户输入事件：如果在 listening 阶段，重置超时；如果在其他阶段，可以选择进入 listening 或者忽略。"""
        _ = event
        if self.current_state == self.STATE_LISTENING:
            self.listening_deadline = time.monotonic() + self.listening_timeout_seconds

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

    def _interpret_messages(self, messages: List[WSMessage], interpreted_user_messages: Optional[str] = None) -> Tuple[bool, str]:
        '''
        解释消息列表。处理黑话并进行意图识别，判断是否继续等待用户输入（进入 listening 状态）或者认为用户输入完成（进入 thinking 状态）。
        @param messages: 消息列表，包含用户消息、系统事件等
        @param interpreted_user_messages: 已经解释过的用户消息列表，供增量解释使用
        @return: (是否继续等待用户输入, 解释后的用户消息文本)
        '''
        text_parts: List[str] = []
        if interpreted_user_messages:
            text_parts.append(interpreted_user_messages)

        for msg in messages:
            if not self._is_user_message_event(msg):
                continue
            if not isinstance(msg.payload, dict):
                continue
            if msg.event_type == WSEventType.USER_IMAGE.value:
                text_parts.append("[用户发送了一张图片]")
                continue
            for key in ("message", "text", "content"):
                value = msg.payload.get(key)
                if isinstance(value, str) and value.strip():
                    text_parts.append(value.strip())
                    break

        interpreted_text = "\n".join(text_parts).strip()

        # 占位策略：末尾为明显结束标点时视为说完，否则继续 listening。
        if interpreted_text.endswith(("。", "！", "？", "!", "?", "~", "…")):
            return False, interpreted_text
        if len(interpreted_text) >= 30:
            return False, interpreted_text
        return True, interpreted_text

    def _is_user_message_event(self, event: WSMessage) -> bool:
        event_type = event.event_type
        return event_type in {
            WSEventType.USER_MESSAGE.value,
            WSEventType.USER_TEXT.value,
            WSEventType.USER_IMAGE.value,
            "message",
            "chat_message",
            "chat",
        }

    def _is_user_typing_event(self, event: WSMessage) -> bool:
        event_type = event.event_type
        return event_type in {
            WSEventType.USER_TYPING.value,
        }

    async def _send_agent_message(self, response):
        pass # placeholder


    #######    下方为连接管理相关方法     #######

    def lost_connection(self):
        """连接丢失时的清理逻辑"""
        # 这里可以选择保留聊天流实例，或者根据实际需求进行清理
        self.ws_connection = None
        self.connection_lost_time = time.time()  # 记录连接丢失的时间，以便后续清理过期的聊天流实例

    def is_connection_lost(self):
        """检查连接是否丢失"""
        return self.ws_connection is None
    
    def reconnect(self, new_ws_connection: WebSocketConnection):
        """用户重连时调用，更新 WebSocket 连接"""
        self.ws_connection = new_ws_connection
        self.connection_lost_time = None  # 重置丢失时间
        self.current_state = self.STATE_WAITING
        self.start_if_needed()

    def clean_up(self):
        """清理资源的逻辑，比如关闭文件、数据库连接等"""
        if self.thinking_task and not self.thinking_task.done():
            self.thinking_task.cancel()
        if self.processor_task and not self.processor_task.done():
            self.processor_task.cancel()
        if self.speaking_task and not self.speaking_task.done():
            self.speaking_task.cancel()
        self.listening_deadline = None
        self.current_state = self.STATE_WAITING

        # 丢弃旧队列，避免断连后遗留消息影响重连流程。
        self.message_queue = asyncio.Queue(maxsize=256)
        self.reply_queue = asyncio.Queue()