import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, AsyncGenerator

from ..utils.logger import get_logger
import base64
from ..agent.main_chat import OneSentenceChat, SongSegmentChat
from ..interface.types import ChatResponse
from typing import Callable, Awaitable

if TYPE_CHECKING:
    from ..agent.luotianyi_agent import LuoTianyiAgent


_sentinel = object()


async def _iter_sync_gen_in_executor(gen, executor=None):
    """Wrap a sync generator as an async generator by driving it in a thread."""
    loop = asyncio.get_event_loop()
    while True:
        chunk = await loop.run_in_executor(executor, next, gen, _sentinel)
        if chunk is _sentinel:
            break
        yield chunk


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

    def set_agent(self, agent: "LuoTianyiAgent"):
        """将Agent实例传递给全局speaking worker，方便它在处理说话任务时调用Agent的接口"""
        self.agent = agent

    async def enqueue(self, job: SpeakingJob):
        self.start_if_needed()
        await self.queue.put(job)


    async def _run(self):
        while True:
            job = await self.queue.get()
            try:
                if isinstance(job.job_content, OneSentenceChat):
                    text = job.job_content.content
                    expression = job.job_content.expression
                    # Drive the sync TTS generator in a thread so the event loop
                    # can service other tasks between chunks.
                    sync_gen = self.agent.tts_say_stream(text, job.job_content.tone)
                    is_first = True
                    async for audio_chunk in _iter_sync_gen_in_executor(sync_gen):
                        chunk_text = text if is_first else ""
                        is_first = False
                        resp = ChatResponse(
                            uuid=job.job_content.uuid, audio=audio_chunk,
                            is_final_package=False, text=chunk_text, expression=expression,
                        )
                        await job.send_reply_callback(resp)
                    final_resp = ChatResponse(
                        uuid=job.job_content.uuid,
                        audio="", is_final_package=True,
                        text="", expression="",
                    )
                    await job.send_reply_callback(final_resp)

                elif isinstance(job.job_content, SongSegmentChat):
                    text = f"(唱了《{job.job_content.song}》)\n{job.job_content.lyrics}"
                    expression = "唱歌"
                    audio = await asyncio.to_thread(
                        self.agent.sing, job.job_content.song, job.job_content.segment
                    )
                    CHUNK_SIZE = 48 * 1024
                    for i in range(0, len(audio), CHUNK_SIZE):
                        chunk = audio[i:i+CHUNK_SIZE]
                        chunk_base64 = base64.b64encode(chunk).decode("utf-8")
                        chunk_text = "" if i > 0 else text
                        is_final_package = (i + CHUNK_SIZE) >= len(audio)
                        chunk_resp = ChatResponse(
                            uuid=job.job_content.uuid, audio=chunk_base64,
                            is_final_package=is_final_package, text=chunk_text,
                            expression=expression,
                        )
                        await job.send_reply_callback(chunk_resp)
                else:
                    self.logger.warning(f"Unsupported speaking job type: {type(job.job_content)}")
                    continue

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
