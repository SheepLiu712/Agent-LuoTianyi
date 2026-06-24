from typing import TYPE_CHECKING, List, Optional
import asyncio
import traceback
from src.utils.logger import get_logger
from src.chat_session.global_speaking_worker import SpeakingJob
from src.agent.main_chat import OneResponseLine, SongSegmentChat, ContextType
from typing import Callable, Awaitable
from src.system.user_interface.types import ChatResponse
from src.agent.chat.chat_events import ChatInputEventType
if TYPE_CHECKING:
    from src.system.system_runtime import SystemRuntime
    from src.agent.chat.topic_planner import ExtractedTopic


class TopicReplier:
    def __init__(self, username: str, user_id: str, send_reply_callback: Callable[[ChatResponse], Awaitable[None]]):
        self.username = username
        self.user_id = user_id
        self.send_reply_callback = send_reply_callback
        self.logger = get_logger(f"{username}TopicReplier")
        self.topic_queue = asyncio.Queue()
        self.processor_task: asyncio.Task | None = None
        self.system_runtime: "SystemRuntime" | None = None
        self.is_processing: bool = False
        self.change_state_callback : Optional[Callable[[bool, bool], Awaitable[None]]] = None # thinking, speaking

        # 触摸事件指针机制
        self._touch_pending: Optional["ExtractedTopic"] = None  # 队列中待处理的触摸 Topic 引用
        self._touch_processing: bool = False  # 正在处理触摸 Topic
        self._touch_lock = asyncio.Lock()  # 触摸指针并发锁

    def set_system_runtime(self, system_runtime: "SystemRuntime"):
        self.system_runtime = system_runtime

    def set_change_state_callback(self, change_state_callback: Callable[[bool, bool], Awaitable[None]]):
        self.change_state_callback = change_state_callback

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

        if self.change_state_callback is not None:
            await self.change_state_callback(thinking = True) # 进入思考状态

        # Read application conversation context once and reuse it for this turn.
        conversation_history = await self.system_runtime.conversation_service.get_context(self.user_id)

        # 它不用等到回复完成就能检测日期，因此把日期检测放在这里，和回复workflow并行
        asyncio.create_task(self._process_date_detection(topic, conversation_history=conversation_history))

        attention_plan = await agent.plan_topic_turn_for_pipeline(
            user_id=self.user_id,
            topic=topic,
            conversation_history=conversation_history,
            external_context=None,
        )

        reply_items = await agent.realize_topic_plan_for_pipeline(
            user_id=self.user_id,
            plan=attention_plan,
        )
        for item in reply_items:
            if isinstance(item, SongSegmentChat):
                lyrics = self.system_runtime.capabilities.singing.get_segment_lyrics(item.song, item.segment)
                item.lyrics = lyrics

        uuid_list = await self.system_runtime.conversation_service.persist_agent_replies(
            user_id=self.user_id,
            reply_items=reply_items,
        )

        for item, uuid in zip(reply_items, uuid_list or []):
            if uuid is None:
                continue
            item.uuid = uuid
            await self._submit_speaking_job(self.send_reply_callback, item)

        # Fire-and-forget: memory write and profile update run in background,
        # don't block the next topic.
        asyncio.create_task(self._schedule_memory_write(
            topic, reply_items, attention_plan.memory_hits, conversation_history=conversation_history
        ))
        asyncio.create_task(self._schedule_profile_context_update(topic))

    async def _submit_speaking_job(
        self,
        send_reply_callback: Callable[[ChatResponse], Awaitable[None]],
        item: OneResponseLine,
    ) -> None:
        if item.type not in {ContextType.TEXT, ContextType.SING}:
            self.logger.warning(f"Unsupported topic reply type: {item.type}")
            return

        
        await self.system_runtime.global_speaking_worker.enqueue(
            SpeakingJob(send_reply_callback=send_reply_callback, job_content=item)
        )


    def _agent_for_topic(self, topic: "ExtractedTopic"):
        if self.system_runtime is None:
            return None
        target_ids = getattr(topic, "target_character_ids", None) or ("luotianyi",)
        target_id = target_ids[0]
        runtime = getattr(self.system_runtime, "agent_runtime", None)
        if runtime is not None:
            try:
                return runtime.get_agent(target_id)
            except KeyError as e:
                self.logger.warning(f"Unknown target character {target_id}, fallback to default agent: {e}")
        return self.system_runtime.agent


    async def _schedule_memory_write(
        self,
        topic: "ExtractedTopic",
        reply_items: List[OneResponseLine],
        memory_hits: List[str],
        conversation_history: Optional[str] = None,
    ) -> None:
        agent = self._agent_for_topic(topic)
        if agent is None:
            self.logger.error("SystemRuntime or agent is not ready, skip scheduling memory write")
            return
        if len(topic.source_messages or []) == 0:
            self.logger.info("No source messages for topic, skip scheduling memory write")
            return

        current_dialogue = self._build_current_dialogue(topic, reply_items)

        try:
            await agent.write_topic_memories_for_pipeline(
                user_id=self.user_id,
                current_dialogue=current_dialogue,
                related_memories=memory_hits,
                conversation_history=conversation_history,
            )
        except Exception as e:
            self.logger.warning(f"Topic memory write task failed: {e}")

    async def _process_date_detection(self, topic: "ExtractedTopic", conversation_history: Optional[str] = None) -> None:
        """从话题的源消息中检测重要日期，按置信度处理。"""
        agent = self._agent_for_topic(topic)
        if agent is None:
            return

        user_texts = []
        for msg in getattr(topic, "source_messages", []) or []:
            content = getattr(msg, "content", "") or ""
            if content.strip():
                user_texts.append(content.strip())
        if not user_texts:
            return

        if not hasattr(agent, 'date_detector') or agent.date_detector is None:
            return

        date_info = await agent.date_detector.detect('\n'.join(user_texts), conversation_history=conversation_history or "")
        if date_info is None:
            return

        self.logger.debug(f"DateDetector: {date_info}")

        from src.agent.date_processor import process_detected_date
        result = await process_detected_date(
            date_info=date_info,
            user_id=self.user_id,
            open_sql_session=agent._runtime_hub.open_sql_session,
            reply_topic_callback=lambda t: self._safe_add_topic(t),
        )

        if result is True:
            self.logger.info(f"Date auto-saved from topic {topic.topic_id}")
        elif result is False:
            self.logger.debug(f"Date discarded from topic {topic.topic_id}")
        else:
            self.logger.info(f"Date confirmation topic created from topic {topic.topic_id}")

    def _safe_add_topic(self, topic: "ExtractedTopic") -> None:
        try:
            asyncio.create_task(self.add_topic(topic))
        except Exception as e:
            self.logger.warning(f"Failed to add confirmation topic: {e}")

    async def _schedule_profile_context_update(
        self,
        topic: "ExtractedTopic",
    ) -> None:
        agent = self._agent_for_topic(topic)
        if agent is None:
            self.logger.error("SystemRuntime or agent is not ready, skip scheduling profile/context update")
            return

        try:
            context = await self.system_runtime.conversation_service.update_context_if_needed(self.user_id)
            if context is None:
                return
            db = agent._runtime_hub.open_sql_session()
            try:
                await agent.memory_updates.update_user_profile_by_context(
                    db, agent._runtime_hub.redis_client, self.user_id, context
                )
            finally:
                db.close()
        except Exception as e:
            self.logger.warning(f"Profile/context update task failed: {e}")

    def _build_current_dialogue(self, topic: "ExtractedTopic", reply_items: List[OneResponseLine]) -> str:
        lines: List[str] = []

        for msg in getattr(topic, "source_messages", []) or []:
            content = (getattr(msg, "content", "") or "").strip()
            if content:
                lines.append(f"user: {content}")

        for item in reply_items:
            lines.append(f"agent: {item.get_content()}")

        return "\n".join(lines)

