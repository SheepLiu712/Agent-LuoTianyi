from typing import TYPE_CHECKING, List, Optional, Tuple
import asyncio
from ..utils.logger import get_logger
from .global_speaking_worker import SpeakingJob
from ..agent.main_chat import SongSegmentChat
from ..agent.main_chat import TopicReplyResult
if TYPE_CHECKING:
    from ..interface.service_hub import ServiceHub
    from .topic_planner import ExtractedTopic


# class ExtractedTopic:
#     topic_id: str
#     source_messages: list[str]
#     topic_content: str
#     memory_attempts: list[str]
#     fact_constraints: list[str]
#     sing_attempts: list[str]
    
#     is_forced_from_incomplete: bool = False

class TopicReplier:
    def __init__(self, username: str, user_id: str, parent_chat_stream):
        self.username = username
        self.user_id = user_id
        self.parent_chat_stream = parent_chat_stream
        self.logger = get_logger(f"{username}TopicReplier")
        self.topic_queue = asyncio.Queue()
        self.processor_task: asyncio.Task | None = None
        self.service_hub: "ServiceHub" | None = None

    def set_service_hub(self, service_hub: "ServiceHub"):
        self.service_hub = service_hub

    def start_processing(self):
        if self.processor_task is None or self.processor_task.done():
            self.processor_task = asyncio.create_task(self.topic_processor())
            self.logger.info("TopicPlanner processor task started")

    async def add_topic(self, topic: "ExtractedTopic"):
        await self.topic_queue.put(topic)

    async def topic_processor(self):
        while True:
            topic = None
            try:
                topic = await self.topic_queue.get()
                await self._reply_one_topic(topic)

            except asyncio.CancelledError:
                self.logger.info("TopicReplier processor task cancelled")
                break
            except Exception as e:
                import traceback
                self.logger.error(f"Error in topic_processor: {e} \n{traceback.format_exc()}")
            finally:
                if topic is not None:
                    self.topic_queue.task_done()

    async def _reply_one_topic(self, topic: "ExtractedTopic") -> None:
        if self.service_hub is None or self.service_hub.agent is None:
            self.logger.warning("ServiceHub or agent is not ready, skip replying topic")
            return


        memory_task = asyncio.create_task(self._memory_search(topic.memory_attempts or []))
        fact_task = asyncio.create_task(self._fact_search(topic.fact_constraints or []))
        sing_task = asyncio.create_task(self._sing_plan(topic.sing_attempts or []))
        memory_hits, fact_hits, sing_plan = await asyncio.gather(memory_task, fact_task, sing_task)

        planned_song = sing_plan[0] if sing_plan and sing_plan[0] else None
        reply_items = await self.service_hub.agent.generate_topic_reply_for_pipeline(
            user_id=self.user_id,
            topic_content=topic.topic_content,
            memory_hits=memory_hits,
            fact_hits=fact_hits,
            sing_song=planned_song,
        )

        for item in reply_items:
            await self._dispatch_reply_item(self.parent_chat_stream, item, sing_plan)

        await self.service_hub.agent.persist_topic_replies_for_pipeline(
            user_id=self.user_id,
            reply_items=reply_items,
            sing_plan=sing_plan,
        )

        await self._schedule_user_profile_update(topic, reply_items)

        await self._schedule_memory_write(topic, reply_items, memory_hits)

    async def _dispatch_reply_item(
        self,
        chat_stream,
        item: TopicReplyResult,
        sing_plan: Tuple[Optional[str], Optional[str]],
    ) -> None:
        if item.reply_type not in {"text", "sing"}:
            self.logger.warning(f"Unsupported topic reply type: {item.reply_type}")
            return

        if item.reply_type == "text" and item.reply_text.strip():
            # 当文本非空时加入回复流。如果文本为空则不加入。
            await self.service_hub.global_speaking_worker.enqueue(
                SpeakingJob(chat_stream=chat_stream, job_content=item.reply_text)
            )
            return

        plan_song, plan_segment = sing_plan
        target_song = (item.reply_text or "").strip() or (plan_song or "")
        if not target_song:
            self.logger.warning("Skip sing item because song name is empty")
            return

        target_segment = plan_segment
        if not target_segment:
            target_segment = self.service_hub.agent.singing_manager.pick_segment_for_song(target_song)
        if not target_segment:
            self.logger.warning(f"Skip sing item because no available segment for song: {target_song}")
            return

        lyrics = self.service_hub.agent.singing_manager.get_segment_lyrics(target_song, target_segment)
        await self.service_hub.global_speaking_worker.enqueue(
            SpeakingJob(
                chat_stream=self.parent_chat_stream,
                job_content=SongSegmentChat(song=target_song, segment=target_segment, lyrics=lyrics),
            )
        )


    async def _memory_search(self, memory_attempts: List[str], approximity_threshold: float = 0.8) -> List[str]:
        # 从向量数据库vector_store中检索记忆。利用并修改在的memory_search接口
        # 将memory_attempts的每一个元素作为查询输入，并行地进行查询并返回相关记忆片段列表。
        # 要求向量相似度作为参数传入，并且只返回相似度高于阈值的记忆片段。
        # 要求返回地记忆片段不重复，利用set去重后再返回。
        if self.service_hub is None or self.service_hub.agent is None:
            self.logger.warning("ServiceHub or agent is not ready for memory search")
            return []
        if not memory_attempts:
            return []

        return await self.service_hub.agent.search_memories_for_topic(
            user_id=self.user_id,
            queries=memory_attempts,
            similarity_threshold=approximity_threshold,
        )

    async def _fact_search(self, fact_constraints: List[str]) -> List[str]:
        # 利用music/knowledge_service.py，获取歌曲的简介和歌词并返回
        if self.service_hub is None or self.service_hub.agent is None:
            self.logger.warning("ServiceHub or agent is not ready for fact search")
            return []
        if not fact_constraints:
            return []

        return await self.service_hub.agent.search_song_facts_for_topic(fact_constraints)

    async def _sing_plan(self, sing_attempts: List[str]) -> Tuple[Optional[str], Optional[str]]:
        # 利用并修改singing_manager，判断sing_attempts中所给出的用户的唱歌指令能否满足，如果能满足则返回准备唱的歌曲名称和唱段，如果不能满足则返回None
        # 如果有明确歌名，查询这首歌能不能唱，能唱的话随机选择一段
        # 如果没有明确歌名(歌名为random_song)，则从歌曲数据库中随机选择一首歌，并随机选择一个唱段
        # 如果为空则直接返回
        if self.service_hub is None or self.service_hub.agent is None:
            self.logger.warning("ServiceHub or agent is not ready for sing planning")
            return None, None
        if not sing_attempts:
            return None, None

        return self.service_hub.agent.build_sing_plan_for_topic(sing_attempts)

    async def _schedule_memory_write(
        self,
        topic: "ExtractedTopic",
        reply_items: List[TopicReplyResult],
        memory_hits: List[str],
    ) -> None:
        if self.service_hub is None or self.service_hub.agent is None:
            return

        current_dialogue = self._build_current_dialogue(topic, reply_items)
        agent_response_content = self._extract_agent_response_content(reply_items)

        async def _task():
            try:
                await self.service_hub.agent.write_topic_memories_for_pipeline(
                    user_id=self.user_id,
                    topic_content=topic.topic_content,
                    current_dialogue=current_dialogue,
                    agent_response_content=agent_response_content,
                    related_memories=memory_hits,
                )
            except Exception as e:
                self.logger.warning(f"Topic memory write task failed: {e}")

        asyncio.create_task(_task())

    async def _schedule_user_profile_update(
        self,
        topic: "ExtractedTopic",
        reply_items: List[TopicReplyResult],
    ) -> None:
        if self.service_hub is None or self.service_hub.agent is None:
            return

        current_dialogue = self._build_current_dialogue(topic, reply_items)

        async def _task():
            try:
                await self.service_hub.agent.update_user_profile_for_topic_pipeline(
                    user_id=self.user_id,
                    current_dialogue=current_dialogue,
                )
            except Exception as e:
                self.logger.warning(f"Topic user profile update task failed: {e}")

        asyncio.create_task(_task())

    def _build_current_dialogue(self, topic: "ExtractedTopic", reply_items: List[TopicReplyResult]) -> str:
        lines: List[str] = []

        for msg in getattr(topic, "source_messages", []) or []:
            content = (getattr(msg, "content", "") or "").strip()
            if content:
                lines.append(f"user: {content}")

        for item in reply_items:
            if item.reply_type == "text":
                text = (item.reply_text or "").strip()
                if text:
                    lines.append(f"agent: {text}")
            elif item.reply_type == "sing":
                song = (item.reply_text or "").strip()
                if song:
                    lines.append(f"agent: （唱了{song}）")

        return "\n".join(lines)

    def _extract_agent_response_content(self, reply_items: List[TopicReplyResult]) -> List[str]:
        contents: List[str] = []
        for item in reply_items:
            if item.reply_type == "text":
                text = (item.reply_text or "").strip()
                if text:
                    contents.append(text)
            elif item.reply_type == "sing":
                song = (item.reply_text or "").strip()
                if song:
                    contents.append(f"（唱了{song}）")
        return contents
    