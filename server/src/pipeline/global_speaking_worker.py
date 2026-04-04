import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..utils.logger import get_logger
import uuid
from ..agent.main_chat import OneSentenceChat, SongSegmentChat
from ..interface.types import ChatResponse
from typing import Callable, Awaitable


@dataclass
class SpeakingJob:
    """全局 speaking 队列中的任务。"""
    send_reply_callback: Callable[[ChatResponse], Awaitable[None]]
    job_content: "OneSentenceChat | SongSegmentChat | str" 


class GlobalSpeakingWorker:
    """全局唯一 speaking consumer：串行处理 TTS/多媒体生成任务。"""

    def __init__(self):
        self.logger = get_logger("GlobalSpeakingWorker")
        self.queue: asyncio.Queue[SpeakingJob] = asyncio.Queue(maxsize=512)
        self.worker_task: asyncio.Task | None = None

    def start_if_needed(self):
        if self.worker_task is None or self.worker_task.done():
            self.worker_task = asyncio.create_task(self._run())
            self.logger.info("Global speaking worker started")

    async def enqueue(self, job: SpeakingJob):
        self.start_if_needed()
        await self.queue.put(job)


    async def _run(self):
        while True:
            job = await self.queue.get()
            try:
                # 生成ChatResponse并通过ChatStream发送给前端
                if isinstance(job.job_content, str):
                    text = job.job_content
                    expression = "微笑脸"
                elif isinstance(job.job_content, OneSentenceChat):
                    text = job.job_content.content
                    expression = job.job_content.expression
                elif isinstance(job.job_content, SongSegmentChat):
                    text = f"(唱了{job.job_content.song}){job.job_content.lyrics}"
                    expression = "唱歌"
                else:
                    self.logger.warning(f"Unsupported speaking job type: {type(job.job_content)}")
                    continue
                
                resp = ChatResponse(uuid=str(uuid.uuid4()), audio="", is_final_package=True, text=text, expression=expression)
                await job.send_reply_callback(resp)
            except Exception as e:
                self.logger.error(f"Error processing speaking job: {e}")
                continue
            finally:
                self.queue.task_done()

    async def stop(self):
        if self.worker_task:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                self.logger.info("Global speaking worker stopped")


_global_speaking_worker: GlobalSpeakingWorker | None = None


def get_global_speaking_worker() -> GlobalSpeakingWorker:
    global _global_speaking_worker
    if _global_speaking_worker is None:
        _global_speaking_worker = GlobalSpeakingWorker()
    return _global_speaking_worker
