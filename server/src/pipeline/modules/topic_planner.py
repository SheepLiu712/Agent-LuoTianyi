from typing import TYPE_CHECKING, List, Optional
from .unread_store import UnreadMessage, UnreadStore
import asyncio
from dataclasses import dataclass
from ...utils.logger import get_logger

if TYPE_CHECKING:
    from ...service.service_hub import ServiceHub
    from ..chat_events import ChatInputEvent, ChatInputEventType


@dataclass
class ExtractedTopic:
    topic_id: str
    topic_type: str  # "greeting", "question", "share", "reply_context", "comfort", "other"
    topic_content: str
    topic_keywords: list[str]
    fact_constraints: list[str]
    source_message_ids: list[str]
    is_forced_from_incomplete: bool = False

class TopicPlanner:
    def __init__(self, username: str, user_id: str):
        self.service_hub: "ServiceHub" | None = None
        self.logger = get_logger(f"{username}TopicPlanner")

        self.unread_store: UnreadStore | None = UnreadStore(username=username, user_id=user_id)  
        self.processor_task: Optional[asyncio.Task] = None
        self.topic_consumer = None  # 由外部设置的回调函数，用于接收提取的话题
        
        self.listening_timeout_seconds: float = 1.5
        self.listening_deadline: Optional[float] = None
        # TODO：超时监控逻辑，当话题提取器产出不完整话题对应的消息时开始计时，如果超过 listening_timeout_seconds 则强制提取当前积压的消息（不完整话题）并传递给 topic_consumer

    def set_service_hub(self, service_hub: "ServiceHub"):
        self.service_hub = service_hub

    async def feed_unread_message(self, message: ChatInputEvent):
        if message.event_type == ChatInputEventType.USER_TYPING:
            self._handle_user_typing(message) # 只更新时间，不加入消息列表
            return
        # 将消息转换为 UnreadMessage 并存储
        # TODO
        # 唤起话题提取逻辑。注意，状态机已经不需要了。
    
    def start_processing(self):
        if self.processor_task is None or self.processor_task.done():
            self.processor_task = asyncio.create_task(self.message_processor())
            self.logger.info("ChatStream processor task started")

    def set_topic_consumer(self, consumer):
        self.topic_consumer = consumer

    async def message_processor(self):
        # TODO：话题提取逻辑，需要①调用话题提取器；②提取之后更新剩余的未读消息列表，开启定时器并③调用 self.topic_consumer(extracted_topics) 将提取的话题传递出去
        # TODO：话题提取器需要在service_hub.agent中增加一个接口，目前可以暂时不实现。
        pass

    def _handle_user_typing(self, event: "ChatInputEvent"):
        """处理用户输入中的事件，重置超时等待。"""
        pass