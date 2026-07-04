from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable, List, Optional
import asyncio
import time
from datetime import datetime, timezone
import traceback
from src.utils.logger import get_logger
from src.chat_session.dependency.global_speaking_worker import SpeakingJob
from src.chat_session.chat_pipeline.reflection_worker import CompletedTurn
from src.agent.main_chat import OneResponseLine, SongSegmentChat, ContextType
from src.domain.chat import ChatInputEventType
from src.system.observability import get_observability_service, new_trace_id
if TYPE_CHECKING:
    from src.system.system_runtime import SystemRuntime
    from src.domain.chat import ExtractedTopic
    from src.system.user_interface.types import ChatResponse


class TopicReplier:
    def __init__(
        self,
        config: dict,
        username: str,
        user_id: str,
        character_id: str = "luotianyi",
        context_provider: Optional[Callable[..., Awaitable[str | dict[str, Any]]]] = None,
        reflection_submitter: Optional[Callable[[CompletedTurn], Awaitable[None]]] = None,
    ):
        self.config = config
        self.username = username
        self.user_id = user_id
        self.character_id = character_id
        self.send_reply_callback: Optional[Callable[["ChatResponse"], Awaitable[None]]] = None
        self.logger = get_logger(f"{username}TopicReplier")
        self.topic_queue = asyncio.Queue()
        self.processor_task: asyncio.Task | None = None
        self.system_runtime: "SystemRuntime" | None = None
        self.is_processing: bool = False
        self.change_state_callback : Optional[Callable[[bool, bool], Awaitable[None]]] = None # thinking, speaking
        self.context_provider: Optional[Callable[..., Awaitable[str | dict[str, Any]]]] = context_provider
        self.reflection_submitter = reflection_submitter

        # 触摸事件指针机制
        self._touch_pending: Optional["ExtractedTopic"] = None  # 队列中待处理的触摸 Topic 引用
        self._touch_processing: bool = False  # 正在处理触摸 Topic
        self._touch_lock = asyncio.Lock()  # 触摸指针并发锁

    def set_system_runtime(self, system_runtime: "SystemRuntime"):
        self.system_runtime = system_runtime

    def set_change_state_callback(self, change_state_callback: Callable[[bool, bool], Awaitable[None]]):
        self.change_state_callback = change_state_callback

    def set_send_reply_callback(self, send_reply_callback: Callable[["ChatResponse"], Awaitable[None]]):
        self.send_reply_callback = send_reply_callback

    def set_context_provider(self, provider: Callable[..., Awaitable[str | dict[str, Any]]]):
        self.context_provider = provider

    def set_reflection_submitter(self, submitter: Callable[[CompletedTurn], Awaitable[None]]):
        self.reflection_submitter = submitter

    def ensure_dependencies(self) -> None:
        """检查话题回复器依赖已经初始化。"""
        required = {
            "system_runtime": self.system_runtime,
            "send_reply_callback": self.send_reply_callback,
            "change_state_callback": self.change_state_callback,
            "context_provider": self.context_provider,
            "reflection_submitter": self.reflection_submitter,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"TopicReplier dependencies are missing: {', '.join(missing)}")

    def start_processing(self):
        if self.processor_task is None or self.processor_task.done():
            self.processor_task = asyncio.create_task(self.topic_processor())
            self.logger.info("TopicPlanner processor task started")

    def _is_touch_topic(self, topic: "ExtractedTopic") -> bool:
        """判断一个 ExtractedTopic 是否来自触摸事件"""
        if getattr(topic, "source_event_type", None) == ChatInputEventType.USER_TOUCH.value:
            return True
        content = topic.topic_content or ""
        return content.startswith("[") and ("触摸" in content or "摸了摸" in content or "碰了碰" in content or "戳了戳" in content or "握了握" in content)

    async def add_topic(self, topic: "ExtractedTopic"):
        if self._is_touch_topic(topic):
            async with self._touch_lock:
                if self._touch_processing:
                    self.logger.info("Touch event ignored: touch topic is currently being processed")
                    return
                if self._touch_pending is not None:
                    # 更新队列中已有的触摸 Topic 内容
                    self._touch_pending.topic_content = topic.topic_content
                    self._touch_pending.source_messages = topic.source_messages
                    self.logger.info("Touch topic updated (was queued, not yet processed)")
                    return
                # 新的触摸 Topic，入队并记录指针
                self._touch_pending = topic
                await self.topic_queue.put(topic)
                self.logger.info("Touch topic enqueued")
        else:
            await self.topic_queue.put(topic)

    async def topic_processor(self):
        while True:
            topic = None
            try:
                topic = await self.topic_queue.get()
                self.is_processing = True
                if self._is_touch_topic(topic):
                    async with self._touch_lock:
                        self._touch_processing = True

                await self._reply_one_topic(topic)

            except asyncio.CancelledError:
                self.logger.info("TopicReplier processor task cancelled")
                break
            except Exception as e:
                self.logger.error(f"Error in topic_processor: {e} \n{traceback.format_exc()}")
            finally:
                if topic is not None:
                    self.topic_queue.task_done()
                    if self._is_touch_topic(topic):
                        async with self._touch_lock:
                            self._touch_pending = None
                            self._touch_processing = False
                self.is_processing = False
                if self.topic_queue.empty() and self.change_state_callback is not None:
                    await self.change_state_callback(thinking = False) # 进入思考状态

    async def _reply_one_topic(self, topic: "ExtractedTopic") -> None:
        agent = self._agent_for_topic(topic)
        if agent is None:
            self.logger.error("SystemRuntime or agent is not ready, skip replying topic")
            return
        character_id = self.character_id
        trace_id = getattr(topic, "trace_id", None) or new_trace_id("topic")
        setattr(topic, "trace_id", trace_id)
        observability = get_observability_service()

        if self.change_state_callback is not None:
            await self.change_state_callback(thinking = True) # 进入思考状态

        # Read application conversation context once and reuse it for this turn.
        conversation_history = await self._get_conversation_context()

        if observability is not None:
            with observability.span(
                trace_id=trace_id,
                user_id=self.user_id,
                topic_id=topic.topic_id,
                span_name="topic_replier.topic_to_reply_generated",
                metadata={
                    "topic_content": topic.topic_content,
                    "memory_attempt_count": len(topic.memory_attempts or []),
                    "fact_constraint_count": len(topic.fact_constraints or []),
                    "sing_attempt_count": len(topic.sing_attempts or []),
                },
            ):
                attention_plan = await self.system_runtime.agent_runtime.plan_topic_turn(
                    character_id=character_id,
                    user_id=self.user_id,
                    topic=topic,
                    conversation_history=conversation_history,
                    external_context=None,
                )

                reply_items = await self.system_runtime.agent_runtime.realize_topic_plan(
                    character_id=character_id,
                    user_id=self.user_id,
                    plan=attention_plan,
                )
        else:
            attention_plan = await self.system_runtime.agent_runtime.plan_topic_turn(
                character_id=character_id,
                user_id=self.user_id,
                topic=topic,
                conversation_history=conversation_history,
                external_context=None,
            )

            reply_items = await self.system_runtime.agent_runtime.realize_topic_plan(
                character_id=character_id,
                user_id=self.user_id,
                plan=attention_plan,
            )
        reply_generated_monotonic = time.perf_counter()
        reply_generated_ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        for item in reply_items:
            if isinstance(item, SongSegmentChat):
                lyrics = self.system_runtime.capabilities.singing.get_segment_lyrics(
                    character_id, item.song, item.segment
                )
                item.lyrics = lyrics

        uuid_list = await self.system_runtime.conversation_service.persist_agent_replies(
            user_id=self.user_id,
            reply_items=reply_items,
            character_id=character_id,
        )

        for item, uuid in zip(reply_items, uuid_list or []):
            if uuid is None:
                continue
            item.uuid = uuid
            await self._submit_speaking_job(
                self.send_reply_callback,
                item,
                character_id,
                trace_id=trace_id,
                topic_id=topic.topic_id,
                reply_generated_monotonic=reply_generated_monotonic,
                reply_generated_ts=reply_generated_ts,
            )

        await self._submit_reflection_turn(
            topic=topic,
            reply_items=reply_items,
            attention_plan=attention_plan,
            conversation_history=conversation_history,
        )

    async def _submit_speaking_job(
        self,
        send_reply_callback: Callable[["ChatResponse"], Awaitable[None]],
        item: OneResponseLine,
        character_id: str,
        *,
        trace_id: str | None = None,
        topic_id: str | None = None,
        reply_generated_monotonic: float | None = None,
        reply_generated_ts: str | None = None,
    ) -> None:
        if item.type not in {ContextType.TEXT, ContextType.SING}:
            self.logger.warning(f"Unsupported topic reply type: {item.type}")
            return

        
        await self.system_runtime.global_speaking_worker.enqueue(
            SpeakingJob(
                send_reply_callback=send_reply_callback,
                job_content=item,
                character_id=character_id,
                trace_id=trace_id,
                user_id=self.user_id,
                topic_id=topic_id,
                reply_generated_monotonic=reply_generated_monotonic,
                reply_generated_ts=reply_generated_ts,
            )
        )


    def _agent_for_topic(self, topic: "ExtractedTopic"):
        if self.system_runtime is None:
            return None
        target_id = self.character_id
        runtime = getattr(self.system_runtime, "agent_runtime", None)
        if runtime is not None:
            try:
                return runtime.get_agent(target_id)
            except KeyError as e:
                self.logger.warning(f"Unknown target character {target_id}, fallback to default agent: {e}")
        return self.system_runtime.agent


    async def _submit_reflection_turn(
        self,
        topic: "ExtractedTopic",
        reply_items: List[OneResponseLine],
        attention_plan: Any,
        conversation_history: str,
    ) -> None:
        if self.reflection_submitter is None:
            self.logger.warning("No reflection submitter set, skip post-turn reflection")
            return
        await self.reflection_submitter(
            CompletedTurn(
                user_id=self.user_id,
                character_id=self.character_id,
                topic=topic,
                reply_items=reply_items,
                attention_plan=attention_plan,
                conversation_history=conversation_history,
            )
        )

    async def _get_conversation_context(self) -> str:
        if self.context_provider is not None:
            context = await self.context_provider(force_refresh=True)
            return context if isinstance(context, str) else ""
        return await self.system_runtime.conversation_service.get_context(self.user_id)

