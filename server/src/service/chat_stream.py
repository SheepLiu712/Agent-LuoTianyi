from fastapi import WebSocketDisconnect
from ..service.websocket_service import WebSocketConnection, WebSocketService
from .service_hub import ServiceHub
from ..service.types import ClientMessage
import asyncio
from ..utils.logger import get_logger
import time

class ChatStream:
    def __init__(self, ws_connection: WebSocketConnection):
        self.logger = get_logger("TianyiChatStream")
        self.ws_connection = ws_connection
        self.service_hub: ServiceHub | None = None
        self.connection_lost_time = None
        self.message_queue = asyncio.Queue()
        self.thinking_task = None  # 用于追踪当前的思考任务
        self.processor_task: asyncio.Task | None = None

    def set_service_hub(self, service_hub: ServiceHub):
        self.service_hub = service_hub

    def start_if_needed(self):
        """启动常驻消息处理协程（仅启动一次）。"""
        if self.processor_task is None or self.processor_task.done():
            self.processor_task = asyncio.create_task(self.message_processor())
            self.logger.info("ChatStream processor task started")

    async def listen_connection(self, websocket_service: WebSocketService):
        """只负责读取当前 WebSocket 连接并将消息投递进队列。"""
        try:
            while True:
                data: ClientMessage = await websocket_service.try_recv_client_msg(self.ws_connection)
                if data is None:
                    continue
                # 收到新消息，直接扔进队列
                await self.message_queue.put(data)
                    
        except WebSocketDisconnect:
            self.logger.info(f"用户{self.ws_connection.user_name}下线，保留 ChatStream 继续运行")
            raise

    async def message_processor(self):
        """持续运行的思考逻辑层"""
        while True:
            client_msg_list = []
            task_done_count = 0

            # 1. 在这里休眠，直到队列里有东西
            client_msg_list.append(await self.message_queue.get())
            task_done_count += 1
            while not self.message_queue.empty(): # 处理积压的消息，这是可能存在的，因为后面的逻辑有多慢我们还不知道
                client_msg_list.append(self.message_queue.get_nowait())
                task_done_count += 1

            
            # 2. 创建并追踪一个新的思考任务
            self.thinking_task = asyncio.create_task(self.do_think_and_speak(client_msg_list))
            
            try:
                await self.thinking_task
            except asyncio.CancelledError:
                pass
            finally:
                for _ in range(task_done_count):
                    self.message_queue.task_done()

    async def do_think_and_speak(self, msg):
        """真正的 LLM 推理、检索和发送逻辑"""
        # 推荐资源使用方式（每次消息处理按需创建并关闭）：
        # if self.service_hub is not None:
        #     db = self.service_hub.open_sql_session()
        #     knowledge_db = self.service_hub.open_song_session()
        #     try:
        #         ... 调用 agent / redis / vector_store ...
        #     finally:
        #         db.close()
        #         knowledge_db.close()
        pass


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
        self.start_if_needed()

    def clean_up(self):
        """清理资源的逻辑，比如关闭文件、数据库连接等"""
        if self.thinking_task and not self.thinking_task.done():
            self.thinking_task.cancel()
        if self.processor_task and not self.processor_task.done():
            self.processor_task.cancel()