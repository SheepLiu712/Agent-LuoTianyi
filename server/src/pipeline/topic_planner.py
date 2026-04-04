from typing import TYPE_CHECKING, List, Optional, Any
from .modules.unread_store import UnreadMessage, UnreadStore, UnreadMessageSnapshot
from .modules.listen_timer import ListenTimer
import asyncio
from dataclasses import dataclass
import time
from uuid import uuid4

from .chat_events import ChatInputEvent, ChatInputEventType
from ..utils.logger import get_logger

if TYPE_CHECKING:
    from ..interface.service_hub import ServiceHub


@dataclass
class ExtractedTopic:
    topic_id: str
    source_messages: list[str]
    topic_content: str
    memory_attempts: list[str]
    fact_constraints: list[str]
    sing_attempts: list[str]
    
    is_forced_from_incomplete: bool = False

class TopicPlanner:
    def __init__(self, username: str, user_id: str):
        self.service_hub: "ServiceHub" | None = None
        self.user_id = user_id
        self.logger = get_logger(f"{username}TopicPlanner")

        self.unread_store: UnreadStore | None = UnreadStore(username=username, user_id=user_id)  
        self.listen_timer: ListenTimer = ListenTimer(username=username, user_id=user_id)
        self.processor_task: Optional[asyncio.Task] = None
        self.topic_consumer = None  # 由外部设置的回调函数，用于接收提取的话题
        self._wake_event = asyncio.Event()
        self._state_lock = asyncio.Lock()
        self._unread_version: int = 0
        self.logger.info(f"TopicPlanner initialized for user_id={user_id}")

    def set_service_hub(self, service_hub: "ServiceHub"):
        self.service_hub = service_hub

    async def feed_unread_message(self, message: ChatInputEvent):
        if message.event_type == ChatInputEventType.USER_TYPING:
            await self._handle_user_typing(message)
            return

        if self.unread_store is None:
            self.logger.warning("UnreadStore is not initialized, skip incoming message")
            return

        unread_msg = UnreadStore.trans_ChatInputEvent_to_UnreadMessage(message)
        await self.unread_store.append(unread_msg)
        await self.listen_timer.set_deadline(timeout=1.0)  # 新消息来了，取消之前的等待超时
        self._wake_event.set()
    
    def start_processing(self):
        if self.processor_task is None or self.processor_task.done():
            self.processor_task = asyncio.create_task(self.message_processor())
            self.logger.info("TopicPlanner processor task started")

    def set_topic_consumer(self, consumer):
        self.topic_consumer = consumer

    async def message_processor(self):
        while True:
            try:
                should_force_extract = False
                deadline = await self.listen_timer.deadline
                has_unread = await self.unread_store.has_unread()
                if has_unread and deadline is not None: # 有未读且处于“等待用户补全”阶段：等待新事件或超时。
                    timeout = max(0.0, deadline - time.monotonic())
                    try:
                        await asyncio.wait_for(self._wake_event.wait(), timeout=timeout)
                        self._wake_event.clear()
                        continue
                    except asyncio.TimeoutError:
                        should_force_extract = True
                elif has_unread and deadline is None: # 有未读且无需等待：直接提取。
                    pass
                else: # 没有未读：等待唤醒。
                    await self._wake_event.wait()
                    self._wake_event.clear()
                    continue # 重新进入循环，检查状态并决定是否提取。

                # 开始提取
                unread_message_snapshot = await self.unread_store.snapshot()

                extracted_topics, remaining_unread = await self._extract_topics(
                    unread_message_snapshot,
                    force_complete=should_force_extract,
                )

                await self._commit_extraction_result(
                    snapshot=unread_message_snapshot,
                    remaining_unread=remaining_unread,
                )

                if extracted_topics:
                    await self._consume_topics(extracted_topics)

            except asyncio.CancelledError:
                self.logger.info("TopicPlanner processor task cancelled")
                await self.unread_store.clear()  # 清理未读消息，避免重启后旧消息干扰流程
                break
            except Exception as e:
                self.logger.exception(f"TopicPlanner processor error: {e}")
                await asyncio.sleep(0.1)

    async def _handle_user_typing(self, event: "ChatInputEvent"):
        """处理用户输入中的事件，重置超时等待。"""
        _ = event
        if not await self.unread_store.has_unread():  
            return # 没有未读消息，不需要重置等待。
        await self.listen_timer.set_deadline()  # 用户正在输入，重置等待超时
        self._wake_event.set()  # 唤醒处理循环，重新评估状态

    async def _commit_extraction_result(
        self,
        snapshot: UnreadMessageSnapshot,
        remaining_unread: List[UnreadMessage],
    ) -> None:
        if self.unread_store is None:
            self.logger.error("UnreadStore is not initialized, cannot commit extraction result")
            return

        has_new_message = await self.unread_store.has_unread()
        await self.unread_store.update_unread_message(snapshot, remaining_unread) # 将剩余的信息加入未读消息中

        if has_new_message:
            self._wake_event.set()
            await self.listen_timer.set_deadline(timeout=1.0)  # 已经有新消息了，不需要等待补全，直接进入下一轮提取
        else:
            if remaining_unread:
                await self.listen_timer.set_deadline()  # 没有新消息，但还有剩余未读，继续等待补全
            else:
                await self.listen_timer.remove_deadline()  # 没有新消息且没有剩余未读，清除等待状态

    async def _extract_topics(self, unread_snapshot: UnreadMessageSnapshot, force_complete: bool) -> tuple[List[ExtractedTopic], List[UnreadMessage]]:
        """调用 agent 话题提取接口；失败时降级为简单规则提取。"""
        if unread_snapshot is None or not unread_snapshot.messages:
            return [], []
        
        # 启发式：如果全都是图片信息，认为用户会补一句话，即所有消息都是不完整话题消息
        for msg in unread_snapshot.messages:
            if msg.message_type != "image":
                break
        else:
            return [], unread_snapshot.messages

        try:
            topics, remaining = await self.service_hub.agent.extract_topics_for_pipeline(
                user_id=self.user_id,
                unread_snapshot=unread_snapshot,
                force_complete=force_complete,
            )
            return topics or [], remaining or []
        except Exception as e:
            self.logger.exception(f"Topic extraction failed: {e}")
            return self._fallback_extract(unread_snapshot, force_complete)

    def _fallback_extract(self, unread_snapshot: UnreadMessageSnapshot, force_complete: bool) -> tuple[List[ExtractedTopic], List[UnreadMessage]]:
        """最小兜底策略：整批消息作为一个话题，或继续保留等待补全。"""
        messages = unread_snapshot.messages
        if not messages:
            return [], []

        latest_content = (messages[-1].content or "").strip()
        terminal_tokens = ("。", "！", "？", ".", "!", "?", "~")
        likely_complete = (
            len(messages) >= 2
            or messages[-1].message_type == "image"
            or latest_content.endswith(terminal_tokens)
            or len(latest_content) >= 16
        )

        if not force_complete and not likely_complete:
            return [], messages

        topic = ExtractedTopic(
            topic_id=str(uuid4()),
            source_messages=messages,
            topic_content="\n".join(m.content for m in messages if m.content),
            memory_attempts=[],
            fact_constraints=[],
            sing_attempts=[],
            is_forced_from_incomplete=force_complete,
        )
        return [topic], []
    
    async def _consume_topics(self, topics: List[ExtractedTopic]):
        if self.topic_consumer is None:
            self.logger.error(f"No topic_consumer set, skip {len(topics)} extracted topics")
            return

        for topic in topics:
            await self.topic_consumer(topic)