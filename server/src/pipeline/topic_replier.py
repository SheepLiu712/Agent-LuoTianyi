from typing import TYPE_CHECKING, List, Optional, Tuple
import asyncio
from ..utils.logger import get_logger
from .global_speaking_worker import SpeakingJob
from ..agent.main_chat import OneResponseLine, SongSegmentChat, ContextType
from typing import Callable, Awaitable
from ..interface.types import ChatResponse
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
    def __init__(self, username: str, user_id: str, send_reply_callback: Callable[[ChatResponse], Awaitable[None]]):
        self.username = username
        self.user_id = user_id
        self.send_reply_callback = send_reply_callback
        self.logger = get_logger(f"{username}TopicReplier")
        self.topic_queue = asyncio.Queue()
        self.processor_task: asyncio.Task | None = None
        self.service_hub: "ServiceHub" | None = None
        self.is_processing: bool = False
        self.change_state_callback : Optional[Callable[[bool, bool], Awaitable[None]]] = None # thinking, speaking

    def set_service_hub(self, service_hub: "ServiceHub"):
        self.service_hub = service_hub

    def set_change_state_callback(self, change_state_callback: Callable[[bool, bool], Awaitable[None]]):
        self.change_state_callback = change_state_callback

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
                self.is_processing = True
                if self.change_state_callback is not None:
                    await self.change_state_callback(thinking = True) # 进入思考状态
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
                self.is_processing = False

    async def _reply_one_topic(self, topic: "ExtractedTopic") -> None:
        if self.service_hub is None or self.service_hub.agent is None:
            self.logger.error("ServiceHub or agent is not ready, skip replying topic")
            return


        memory_task = asyncio.create_task(self._memory_search(topic.memory_attempts or []))
        fact_task = asyncio.create_task(self._fact_search(topic.fact_constraints or []))
        sing_task = asyncio.create_task(self._sing_plan(topic.sing_attempts or []))
        memory_hits, fact_hits, sing_plan = await asyncio.gather(memory_task, fact_task, sing_task)

        reply_items = await self.service_hub.agent.generate_topic_reply_for_pipeline(
            user_id=self.user_id,
            topic_content=topic.topic_content,
            memory_hits=memory_hits,
            fact_hits=fact_hits,
            sing_plan=sing_plan,
        )
        for item in reply_items:
            if isinstance(item, SongSegmentChat):
                lyrics = self.service_hub.agent.singing_manager.get_segment_lyrics(item.song, item.segment)
                item.lyrics = lyrics

        uuid_list = await self.service_hub.agent.persist_topic_replies_for_pipeline(
            user_id=self.user_id,
            reply_items=reply_items,
        )

        for item, uuid in zip(reply_items, uuid_list or []):
            item.uuid = uuid # 给每个回复项分配一个UUID，供前端关联文本和TTS音频使用
            await self._submit_speaking_job(self.send_reply_callback, item)

        

        memory_write_task = asyncio.create_task(self._schedule_memory_write(topic, reply_items, memory_hits))
        huge_update_task = asyncio.create_task(self._schedule_profile_context_update()) # 我们考虑，当上下文需要压缩时，进行一次用户画像的更新。

        # 等上面两个任务都完成后再进行下一轮回复，确保用户画像和记忆的更新能够尽可能快地反映在后续的回复中
        await asyncio.gather(memory_write_task, huge_update_task)

    async def _submit_speaking_job(
        self,
        send_reply_callback: Callable[[ChatResponse], Awaitable[None]],
        item: OneResponseLine,
    ) -> None:
        if item.type not in {ContextType.TEXT, ContextType.SING}:
            self.logger.warning(f"Unsupported topic reply type: {item.type}")
            return

        
        await self.service_hub.global_speaking_worker.enqueue(
            SpeakingJob(send_reply_callback=send_reply_callback, job_content=item)
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
        # 特殊处理：如果 fact_constraints 包含 "/SongsCanSing"，调用 SingingManager 获取可唱歌曲列表
        if self.service_hub is None or self.service_hub.agent is None:
            self.logger.warning("ServiceHub or agent is not ready for fact search")
            return []
        if not fact_constraints:
            return []

        # 处理 /SongsCanSing 特殊指令
        special_hits = []
        regular_constraints = []
        
        for constraint in fact_constraints:
            if constraint == "/SongsCanSing":
                try:
                    singing_manager = self.service_hub.agent.singing_manager
                    songs_json = await singing_manager.get_songs_can_sing_llm(max_song_num=15)
                    special_hits.append(f"可唱歌曲推荐：{songs_json}")
                except Exception as e:
                    self.logger.error(f"Failed to get songs can sing: {e}")
            else:
                regular_constraints.append(constraint)
        
        # 获取常规的歌曲事实
        regular_hits = []
        if regular_constraints:
            regular_hits = await self.service_hub.agent.search_song_facts_for_topic(regular_constraints)
        
        return special_hits + regular_hits

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
        reply_items: List[OneResponseLine],
        memory_hits: List[str],
    ) -> None:
        if self.service_hub is None or self.service_hub.agent is None:
            self.logger.error("ServiceHub or agent is not ready, skip scheduling memory write")
            return
        if len(topic.source_messages or []) == 0:
            self.logger.info("No source messages for topic, skip scheduling memory write")
            return

        current_dialogue = self._build_current_dialogue(topic, reply_items)

        async def _task():
            try:
                await self.service_hub.agent.write_topic_memories_for_pipeline(
                    user_id=self.user_id,
                    current_dialogue=current_dialogue,
                    related_memories=memory_hits,
                )
            except Exception as e:
                self.logger.warning(f"Topic memory write task failed: {e}")

        asyncio.create_task(_task())

    async def _schedule_profile_context_update(
        self
    ) -> None:
        if self.service_hub is None or self.service_hub.agent is None:
            self.logger.error("ServiceHub or agent is not ready, skip scheduling profile/context update")
            return
        
        await self.service_hub.agent.update_profile_context_for_pipeline(user_id=self.user_id)

    def _build_current_dialogue(self, topic: "ExtractedTopic", reply_items: List[OneResponseLine]) -> str:
        lines: List[str] = []

        for msg in getattr(topic, "source_messages", []) or []:
            content = (getattr(msg, "content", "") or "").strip()
            if content:
                lines.append(f"user: {content}")

        for item in reply_items:
            lines.append(f"agent: {item.get_content()}")

        return "\n".join(lines)

