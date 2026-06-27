from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Callable, Awaitable
import asyncio

from src.domain.chat import ChatInputEvent, ChatInputEventType
from src.utils.logger import get_logger


if TYPE_CHECKING:
    from src.system.system_runtime import SystemRuntime
    from src.system.user_interface.types import ChatResponse

class IngressHelper:
    '''
    Chat Stream的预处理类
    负责处理来自WebSocket的输入事件，转化为需要被Agent理解的消息，投入topic_planner
    '''
    def __init__(self, config: Dict[str, Any], username, user_id, character_id: str = "luotianyi", send_reply_callback: Callable[["ChatResponse"], Awaitable[None]] = None):
        self.config = config
        self.username = username
        self.user_uuid = user_id
        self.character_id = character_id or "luotianyi"
        self.logger = get_logger(f"{self.username}IngressHelper")
        self.ingress_queue: asyncio.Queue[ChatInputEvent] = asyncio.Queue()
        self.ingress_worker_task: asyncio.Task | None = None
        self.system_runtime: "SystemRuntime" | None = None
        self.send_reply_callback: Callable[["ChatResponse"], Awaitable[None]] = send_reply_callback

    def start_processing(self):
        if self.ingress_worker_task is None or self.ingress_worker_task.done():
            self.ingress_worker_task = asyncio.create_task(self.ingress_worker_loop())
            self.logger.info("Started ingress worker task")

    async def put(self, event: ChatInputEvent):
        """将事件放入 ingress 队列，供 ingress worker 处理。"""
        await self.ingress_queue.put(event)

    # ————————————————————设置依赖————————————————————————

    def set_system_runtime(self, system_runtime: "SystemRuntime"):
        self.system_runtime = system_runtime

    def set_msg_consumer(self, consumer_callback):
        """设置消息消费者回调函数，用于将处理后的消息传递给下游组件。"""
        self.msg_consumer = consumer_callback

    def ensure_dependencies(self) -> None:
        """检查 ingress worker 依赖已经初始化。"""
        required = {
            "system_runtime": self.system_runtime,
            "send_reply_callback": self.send_reply_callback,
            "msg_consumer": getattr(self, "msg_consumer", None),
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"IngressHelper dependencies are missing: {', '.join(missing)}")

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

        # 尝试使用 ReflexPipeline 处理事件，如果处理成功则直接返回
        reflex_pipeline = (
            self.system_runtime.chat_session_manager.reflex_pipeline if self.system_runtime is not None else None
        )
        handled = await reflex_pipeline.try_handle(event, self.send_reply_callback) if reflex_pipeline else False
        if handled:
            return

        if self._is_user_message_event(event):
            if self.system_runtime is not None and self.user_uuid is not None:
                event = await self.ingress_message(event)  # 预处理
                if event.event_type in {ChatInputEventType.USER_TEXT, ChatInputEventType.USER_IMAGE}:
                    await self.system_runtime.conversation_service.persist_user_event(
                        self.user_uuid,
                        event,
                        character_id=self.character_id,
                    )
            else:
                self.logger.warning("System runtime or user uuid is missing, skip user message preprocessing")

        await self.msg_consumer(event)

    def _is_user_message_event(self, event: ChatInputEvent) -> bool:
        return event.event_type in {ChatInputEventType.USER_TEXT, ChatInputEventType.USER_IMAGE, ChatInputEventType.USER_TOUCH}
    
    async def ingress_message(self, message: ChatInputEvent) -> ChatInputEvent:
        """Delegate chat stimulus preprocessing to the agent runtime."""
        if self.system_runtime is None:
            self.logger.error("SystemRuntime is not set in ingress_message")
        else:
            event = await self.system_runtime.agent_runtime.preprocess_chat_event(
                character_id=self.character_id,
                user_id=self.user_uuid,
                event=message,
            )
        
        return event
