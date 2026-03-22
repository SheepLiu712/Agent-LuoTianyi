from typing import TYPE_CHECKING
from dataclasses import dataclass
import asyncio
from ..utils.logger import get_logger
if TYPE_CHECKING:
    from ..service.service_hub import ServiceHub
    from .topic_planner import ExtractedTopic, UnreadMessage


# class ExtractedTopic:
#     topic_id: str
#     source_messages: list[str]
#     topic_content: str
#     memory_attempts: list[str]
#     fact_constraints: list[str]
#     sing_attempts: list[str]
    
#     is_forced_from_incomplete: bool = False

class TopicReplier:
    def __init__(self, username: str, user_id: str):
        self.username = username
        self.user_id = user_id
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
            try:
                await self.topic_queue.get()

            except asyncio.CancelledError:
                self.logger.info("TopicReplier processor task cancelled")
                break
            except Exception as e:
                import traceback
                self.logger.error(f"Error in topic_processor: {e} \n{traceback.format_exc()}")


    async def _memory_search(self):
        pass

    async def _fact_search(self):
        pass

    async def _sing_plan(self):
        pass
    