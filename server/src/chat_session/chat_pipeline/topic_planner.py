from typing import TYPE_CHECKING, Awaitable, Callable, List, Optional, Any, Tuple
from src.chat_session.chat_pipeline.unread_store import UnreadMessage, UnreadStore, UnreadMessageSnapshot
from src.chat_session.chat_pipeline.listen_timer import ListenTimer
import asyncio
import time
from datetime import datetime, timezone
from uuid import uuid4

from src.domain.chat import ChatInputEvent, ChatInputEventType, ExtractedTopic
from src.system.observability import get_observability_service, new_trace_id
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.system.system_runtime import SystemRuntime

class TopicPlanner:
    def __init__(self, config: dict, username: str, user_id: str, character_id: str = "luotianyi", context_provider: Optional[Callable[..., Awaitable[str | dict[str, Any]]]] = None):
        self.config = config
        self.system_runtime: "SystemRuntime" | None = None
        self.user_id = user_id
        self.character_id = character_id
        self.context_provider = context_provider
        self.logger = get_logger(f"{username}TopicPlanner")

        self.unread_store: UnreadStore | None = UnreadStore(
            config.get("unread_store", {}), username=username, user_id=user_id
        )
        self.listen_timer: ListenTimer = ListenTimer(
            config.get("listen_timer", {}), username=username, user_id=user_id
        )
        self.processor_task: Optional[asyncio.Task] = None
        self.topic_consumer = None  # 由外部设置的回调函数，用于接收提取的话题
        self._wake_event = asyncio.Event()
        self._unread_version: int = 0
        self.logger.info(f"TopicPlanner initialized for user_id={user_id}")

    def set_system_runtime(self, system_runtime: "SystemRuntime"):
        self.system_runtime = system_runtime

    async def feed_unread_message(self, message: ChatInputEvent):
        if message.event_type in [ChatInputEventType.USER_IMAGE_SELECTING, ChatInputEventType.USER_IMAGE_SELECTING_CANCEL]:
            await self._handle_user_image_selecting(message)
            return

        if message.event_type == ChatInputEventType.USER_TYPING:
            await self._handle_user_typing(message)
            return

        # 触摸事件：绕过未读缓冲，直接生成 ExtractedTopic 送入 replier
        if message.event_type == ChatInputEventType.USER_TOUCH:
            await self._handle_touch_event(message)
            return

        if self.unread_store is None:
            self.logger.warning("UnreadStore is not initialized, skip incoming message")
            return

        unread_msg = UnreadStore.trans_ChatInputEvent_to_UnreadMessage(message)
        setattr(unread_msg, "_observability_trace_id", new_trace_id("topic"))
        setattr(unread_msg, "_observability_entered_monotonic", time.perf_counter())
        setattr(
            unread_msg,
            "_observability_entered_ts",
            datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        )
        await self.unread_store.append(unread_msg)
        await self.listen_timer.set_deadline()  # 新消息来了，重置等待超时
        self._wake_event.set()
    
    def start_processing(self):
        if self.processor_task is None or self.processor_task.done():
            self.processor_task = asyncio.create_task(self._message_processor())
            self.logger.info("TopicPlanner processor task started")

    def set_topic_consumer(self, consumer):
        self.topic_consumer = consumer

    def ensure_dependencies(self) -> None:
        """检查话题规划器依赖已经初始化。"""
        required = {
            "system_runtime": self.system_runtime,
            "context_provider": self.context_provider,
            "unread_store": self.unread_store,
            "listen_timer": self.listen_timer,
            "topic_consumer": self.topic_consumer,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"TopicPlanner dependencies are missing: {', '.join(missing)}")

    async def _message_processor(self):
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
                elif has_unread and deadline is None: # 有未读且无需等待：直接提取。目前这个状态不会进入，之后可能有用。
                    pass
                else: # 没有未读：等待唤醒。
                    await self._wake_event.wait()
                    self._wake_event.clear()
                    continue # 重新进入循环，检查状态并决定是否提取。

                # 开始提取
                unread_message_snapshot = await self.unread_store.snapshot()

                extracted_topic, remaining_unread = await self._extract_topics(
                    unread_message_snapshot,
                    force_complete=should_force_extract,
                )

                # 提取结果提交后，可能会被新消息打断，导致提取结果无效；也可能没有新消息，提取结果有效。根据是否有新消息来决定保留提取结果还是丢弃。
                extracted_topics = await self._commit_extraction_result(
                    snapshot=unread_message_snapshot,
                    extracted_topics=[extracted_topic] if extracted_topic else [],
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

    async def _handle_touch_event(self, event: "ChatInputEvent"):
        """处理触摸事件：直接生成 ExtractedTopic 送入 replier"""
        text = event.text or "[用户触摸了天依]"
        unread_msg = UnreadStore.trans_ChatInputEvent_to_UnreadMessage(event)
        touch_topic = ExtractedTopic(
            topic_id=str(uuid4()),
            source_messages=[unread_msg],
            topic_content=text,
            memory_attempts=[],
            fact_constraints=[],
            sing_attempts=[],
            target_character_ids=unread_msg.target_character_ids,
            source_event_type=ChatInputEventType.USER_TOUCH.value,
        )
        setattr(touch_topic, "trace_id", new_trace_id("topic"))
        self.logger.info(f"Touch event -> ExtractedTopic: {text}")
        await self._consume_topics([touch_topic])

    async def _handle_user_typing(self, event: "ChatInputEvent"):
        """处理用户输入中的事件，重置超时等待。"""
        text_length = event.payload["text_length"]
        if not await self.unread_store.has_unread():  
            return # 没有未读消息，不需要重置等待。
        if text_length > 0:
            await self.listen_timer.set_deadline(timeout=10)  # 认为用户明确地有话要说，设置一个更长的等待时间
        else:
            await self.listen_timer.set_deadline() # 用户开始输入了，重置等待时间，给用户更多时间输入。
        self._wake_event.set()  # 唤醒处理循环，重新评估状态

    async def _handle_user_image_selecting(self, event: "ChatInputEvent"):
        if event.event_type == ChatInputEventType.USER_IMAGE_SELECTING:
            # 用户正在选择图片：设置 30 秒等待，给用户足够时间
            if await self.unread_store.has_unread():
                await self.listen_timer.set_deadline(timeout=30.0)
                self._wake_event.set()

        if event.event_type == ChatInputEventType.USER_IMAGE_SELECTING_CANCEL:
            if not await self.unread_store.has_unread():
                await self.listen_timer.remove_deadline()
            else:
                await self.listen_timer.set_deadline()  # 用户取消了选择，但还有未读消息，重置等待时间，继续等待补全
                self._wake_event.set()

    async def _commit_extraction_result(
        self,
        snapshot: UnreadMessageSnapshot,
        extracted_topics: List[ExtractedTopic],
        remaining_unread: List[UnreadMessage],
    ) -> List[ExtractedTopic]:
        if self.unread_store is None:
            self.logger.error("UnreadStore is not initialized, cannot commit extraction result")
            return []

        has_new_message = await self.unread_store.has_unread()
        if has_new_message:
            remaining_unread = snapshot.messages.copy()  # 已经有新消息了，丢弃提取时的剩余未读，保留新消息继续等待补全
            new_extracted_topics = []  # 已经有新消息了，丢弃提取结果，保留新消息继续等待补全
        else:
            new_extracted_topics = extracted_topics  # 没有新消息，提取结果有效
        
        await self.unread_store.update_unread_message(snapshot, remaining_unread) # 将剩余的信息加入未读消息中

        if has_new_message:
            self._wake_event.set()
            await self.listen_timer.set_deadline()  # 已经有新消息了，不需要等待补全，直接进入下一轮提取
        else:
            if remaining_unread:
                await self.listen_timer.set_deadline()  # 没有新消息，但还有剩余未读，继续等待补全
            else:
                await self.listen_timer.remove_deadline()  # 没有新消息且没有剩余未读，清除等待状态
        return new_extracted_topics

    async def _extract_topics(self, unread_snapshot: UnreadMessageSnapshot, force_complete: bool) -> tuple[Optional[ExtractedTopic], List[UnreadMessage]]:
        """调用 agent 话题提取接口；失败时降级为简单规则提取。"""
        if unread_snapshot is None or not unread_snapshot.messages:
            return [], []

        trace_id = self._trace_id_from_snapshot(unread_snapshot)
        observability = get_observability_service()
        try:
            conversation_history = await self._get_conversation_context()
            character_id = self._target_character_ids_from_messages(unread_snapshot.messages)[0]
            if observability is not None:
                with observability.span(
                    trace_id=trace_id,
                    user_id=self.user_id,
                    span_name="topic_planner.extract_topic_llm",
                    metadata={"force_complete": force_complete, "message_count": len(unread_snapshot.messages)},
                ):
                    topic, remaining = await self.system_runtime.agent_runtime.extract_topic(
                        character_id=character_id,
                        user_id=self.user_id,
                        unread_snapshot=unread_snapshot,
                        force_complete=force_complete,
                        conversation_history=conversation_history,
                    )
            else:
                topic, remaining = await self.system_runtime.agent_runtime.extract_topic(
                    character_id=character_id,
                    user_id=self.user_id,
                    unread_snapshot=unread_snapshot,
                    force_complete=force_complete,
                    conversation_history=conversation_history,
                )
            if topic is not None:
                topic.target_character_ids = self._target_character_ids_from_messages(unread_snapshot.messages)
                setattr(topic, "trace_id", trace_id)
                self._record_topic_commands(trace_id, topic, conversation_history)
                self._record_last_message_to_topic_span(unread_snapshot, topic)
            return topic, remaining or []
        except Exception as e:
            self.logger.exception(f"Topic extraction failed: {e}")
            topic, remaining = self._fallback_extract(unread_snapshot, force_complete)
            if topic is not None:
                setattr(topic, "trace_id", trace_id)
                self._record_topic_commands(trace_id, topic, "", fallback=True)
                self._record_last_message_to_topic_span(unread_snapshot, topic, fallback=True)
            return topic, remaining

    def _record_topic_commands(
        self,
        trace_id: str,
        topic: ExtractedTopic,
        conversation_history: str,
        *,
        fallback: bool = False,
    ) -> None:
        observability = get_observability_service()
        if observability is None:
            return

        source_context = self._build_topic_source_context(topic, conversation_history)
        commands = [
            ("memory_command", "memory_attempt", command, True)
            for command in (topic.memory_attempts or [])
        ] + [
            ("fact_command", "fact_constraint", command, True)
            for command in (topic.fact_constraints or [])
        ] + [
            ("sing_command", "sing_attempt", command, True)
            for command in (topic.sing_attempts or [])
        ]
        for event_type, item_type, command, annotation_required in commands:
            observability.record_memory_trace_event(
                trace_id=trace_id,
                user_id=self.user_id,
                topic_id=topic.topic_id,
                event_type=event_type,
                item_type=item_type,
                command_text=command,
                content_text=topic.topic_content,
                source_context=source_context,
                annotation_required=annotation_required,
                metadata={"fallback": fallback},
            )

    @staticmethod
    def _build_topic_source_context(topic: ExtractedTopic, conversation_history: str) -> str:
        source_messages = []
        for msg in getattr(topic, "source_messages", []) or []:
            content = (getattr(msg, "content", "") or "").strip()
            if content:
                source_messages.append(content)
        parts = []
        if source_messages:
            parts.append("用户消息：\n" + "\n".join(source_messages))
        if conversation_history:
            parts.append("会话上下文：\n" + conversation_history)
        return "\n\n".join(parts)

    async def _get_conversation_context(self) -> str:
        if self.context_provider is not None:
            context = await self.context_provider(force_refresh=True)
            return context if isinstance(context, str) else ""
        return await self.system_runtime.conversation_service.get_context(self.user_id)

    def _fallback_extract(self, unread_snapshot: UnreadMessageSnapshot, force_complete: bool) -> tuple[Optional[ExtractedTopic], List[UnreadMessage]]:
        """最小兜底策略：整批消息作为一个话题，或继续保留等待补全。"""
        messages = unread_snapshot.messages
        if not messages:
            return None, []

        latest_content = (messages[-1].content or "").strip()
        terminal_tokens = ("。", "！", "？", ".", "!", "?", "~")
        likely_complete = (
            len(messages) >= 2
            or messages[-1].message_type == "image"
            or latest_content.endswith(terminal_tokens)
            or len(latest_content) >= 16
        )

        if not force_complete and not likely_complete:
            return None, messages

        topic = ExtractedTopic(
            topic_id=str(uuid4()),
            source_messages=messages,
            topic_content="\n".join(m.content for m in messages if m.content),
            memory_attempts=[],
            fact_constraints=[],
            sing_attempts=[],
            target_character_ids=self._target_character_ids_from_messages(messages),
            is_forced_from_incomplete=force_complete,
        )
        setattr(topic, "trace_id", self._trace_id_from_snapshot(unread_snapshot))
        return topic, []

    def _target_character_ids_from_messages(self, messages: List[UnreadMessage]) -> tuple[str, ...]:
        targets = []
        seen = set()
        for message in messages or []:
            for character_id in getattr(message, "target_character_ids", None) or ("luotianyi",):
                if character_id not in seen:
                    seen.add(character_id)
                    targets.append(character_id)
        return tuple(targets or ["luotianyi"])
    
    async def _consume_topics(self, topics: List[ExtractedTopic]):
        if self.topic_consumer is None:
            self.logger.error(f"No topic_consumer set, skip {len(topics)} extracted topics")
            return

        for topic in topics:
            await self.topic_consumer(topic)

    def _trace_id_from_snapshot(self, unread_snapshot: UnreadMessageSnapshot) -> str:
        messages = unread_snapshot.messages or []
        if not messages:
            return new_trace_id("topic")
        trace_id = getattr(messages[-1], "_observability_trace_id", None)
        if trace_id:
            return trace_id
        trace_id = new_trace_id("topic")
        setattr(messages[-1], "_observability_trace_id", trace_id)
        return trace_id

    def _record_last_message_to_topic_span(
        self,
        unread_snapshot: UnreadMessageSnapshot,
        topic: ExtractedTopic,
        *,
        fallback: bool = False,
    ) -> None:
        observability = get_observability_service()
        if observability is None or not unread_snapshot.messages:
            return
        last_message = unread_snapshot.messages[-1]
        entered_monotonic = getattr(last_message, "_observability_entered_monotonic", None)
        entered_ts = getattr(last_message, "_observability_entered_ts", None)
        if entered_monotonic is None or entered_ts is None:
            return
        observability.record_pipeline_span(
            trace_id=getattr(topic, "trace_id", self._trace_id_from_snapshot(unread_snapshot)),
            user_id=self.user_id,
            topic_id=topic.topic_id,
            span_name="topic_planner.last_message_to_extracted_topic",
            start_ts=entered_ts,
            end_ts=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            duration_ms=(time.perf_counter() - float(entered_monotonic)) * 1000.0,
            status="fallback" if fallback else "success",
            metadata={
                "message_count": len(unread_snapshot.messages),
                "force_complete_topic": topic.is_forced_from_incomplete,
            },
        )
