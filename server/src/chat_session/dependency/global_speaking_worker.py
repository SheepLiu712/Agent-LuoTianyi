from __future__ import annotations

import asyncio
from contextlib import aclosing
from dataclasses import dataclass
from typing import TYPE_CHECKING, AsyncGenerator
from datetime import datetime, timezone
import time

from src.utils.logger import get_logger
import base64
from src.agent.main_chat import OneSentenceChat, SongSegmentChat
from typing import Callable, Awaitable, Dict, Any
from src.system.observability import get_observability_service
from src.utils.asyncio_helpers import (
    DEFAULT_OWNED_TASK_STOP_TIMEOUT_SECONDS,
    cancel_task_once,
    run_sync_owned,
    wait_for_owned_tasks,
)

if TYPE_CHECKING:
    from src.capabilities import CapabilityManager
    from src.system.user_interface.types import ChatResponse


_sentinel = object()


async def _run_sync_in_executor(call, *args, executor=None):
    """Await a sync call without abandoning its thread when cancellation arrives."""
    return await run_sync_owned(call, *args, executor=executor)


async def _iter_sync_gen_in_executor(gen, executor=None):
    """Wrap a sync generator as an async generator by driving it in a thread."""
    try:
        while True:
            chunk = await _run_sync_in_executor(next, gen, _sentinel, executor=executor)
            if chunk is _sentinel:
                break
            yield chunk
    finally:
        close = getattr(gen, "close", None)
        if close is not None:
            await _run_sync_in_executor(close, executor=executor)


@dataclass
class SpeakingJob:
    """全局 speaking 队列中的任务。"""
    send_reply_callback: Callable[[ChatResponse], Awaitable[None]]
    job_content: "OneSentenceChat | SongSegmentChat | str" 
    character_id: str = "luotianyi"
    trace_id: str | None = None
    user_id: str | None = None
    topic_id: str | None = None
    reply_generated_monotonic: float | None = None
    reply_generated_ts: str | None = None
    song_audio_generated_callback: Callable[[str, str], None] | None = None
    enqueued_monotonic: float | None = None
    enqueued_ts: str | None = None


class GlobalSpeakingWorker:
    """全局唯一 speaking consumer：串行处理 TTS/多媒体生成任务。"""

    def __init__(self, config: Dict):
        self.config = config
        self.logger = get_logger("GlobalSpeakingWorker")
        queue_maxsize = max(1, int(config.get("queue_maxsize", 512)))
        self.queue: asyncio.Queue[SpeakingJob] = asyncio.Queue(maxsize=queue_maxsize)
        self.worker_task: asyncio.Task | None = None
        self.capabilities: "CapabilityManager | None" = None
        self._stopping = False
        self.terminal_send_max_attempts = max(
            1,
            int(config.get("terminal_send_max_attempts", 3)),
        )
        self.terminal_send_retry_delay_seconds = max(
            0.0,
            float(config.get("terminal_send_retry_delay_seconds", 0.05)),
        )
        self.shutdown_timeout_seconds = max(
            0.001,
            float(
                config.get(
                    "shutdown_timeout_seconds",
                    DEFAULT_OWNED_TASK_STOP_TIMEOUT_SECONDS,
                )
            ),
        )

    def start_if_needed(self):
        if self._stopping:
            raise RuntimeError("Global speaking worker is stopping and cannot be restarted")
        if self.worker_task is None or self.worker_task.done():
            self.worker_task = asyncio.create_task(self._run())
            self.logger.info("Global speaking worker started")

    def set_capabilities(self, capabilities: "CapabilityManager"):
        """Inject action capabilities used by the speaking worker."""
        self.capabilities = capabilities

    def wire_dependencies(self, *, capabilities: "CapabilityManager") -> None:
        """注入 speaking worker 所需能力。"""
        self.set_capabilities(capabilities)
        self.ensure_dependencies()

    def ensure_dependencies(self) -> None:
        """检查 speaking worker 依赖已经初始化。"""
        if self.capabilities is None:
            raise RuntimeError("GlobalSpeakingWorker dependency is missing: capabilities")

    async def enqueue(self, job: SpeakingJob):
        self.start_if_needed()
        if job.enqueued_monotonic is None:
            job.enqueued_monotonic = time.perf_counter()
        if job.enqueued_ts is None:
            job.enqueued_ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        await self.queue.put(job)


    async def _run(self):
        from src.system.user_interface.types import ChatResponse

        while True:
            job = await self.queue.get()
            job_start_monotonic = time.perf_counter()
            job_start_ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            self._record_queue_wait(job, job_start_ts, job_start_monotonic)
            terminal_sent = False

            async def send_terminal(
                *,
                text: str,
                expression: str,
                audio: str = "",
                error_code: str | None = None,
            ) -> None:
                nonlocal terminal_sent
                if terminal_sent:
                    return
                response = ChatResponse(
                    uuid=job.job_content.uuid,
                    audio=audio,
                    is_final_package=True,
                    text=text,
                    expression=expression,
                    audio_error=error_code is not None,
                    error_code=error_code,
                )
                for attempt in range(1, self.terminal_send_max_attempts + 1):
                    try:
                        await job.send_reply_callback(response)
                    except asyncio.CancelledError:
                        raise
                    except Exception as error:
                        if attempt >= self.terminal_send_max_attempts:
                            raise
                        self.logger.warning(
                            "Terminal response was not accepted "
                            f"({attempt}/{self.terminal_send_max_attempts}): {error}"
                        )
                        if self.terminal_send_retry_delay_seconds:
                            await asyncio.sleep(self.terminal_send_retry_delay_seconds)
                    else:
                        terminal_sent = True
                        return

            try:
                if isinstance(job.job_content, OneSentenceChat):
                    display_text = job.job_content.content
                    sound_text = job.job_content.sound_content
                    expression = job.job_content.expression
                    if not sound_text.strip():
                        await send_terminal(
                            text=display_text,
                            expression=expression,
                        )
                        continue

                    # Drive the sync TTS generator in a thread so the event loop
                    # can service other tasks between chunks.
                    sync_gen = self.capabilities.speech.say_stream(
                        job.character_id, sound_text, job.job_content.tone
                    )
                    audio_sent = False
                    try:
                        async with aclosing(_iter_sync_gen_in_executor(sync_gen)) as audio_chunks:
                            async for audio_chunk in audio_chunks:
                                if not audio_chunk:
                                    continue
                                chunk_text = display_text if not audio_sent else ""
                                if not audio_sent:
                                    self._record_first_packet(job, job_start_ts, job_start_monotonic)
                                audio_sent = True
                                resp = ChatResponse(
                                    uuid=job.job_content.uuid, audio=audio_chunk,
                                    is_final_package=False, text=chunk_text, expression=expression,
                                )
                                await job.send_reply_callback(resp)
                    except Exception as error:
                        self.logger.error(f"Streaming TTS failed: {error}")
                        await send_terminal(
                            text="" if audio_sent else display_text,
                            expression="" if audio_sent else expression,
                            error_code="TTS_STREAM_ERROR",
                        )
                        continue

                    if not audio_sent:
                        await send_terminal(
                            text=display_text,
                            expression=expression,
                            error_code="TTS_EMPTY",
                        )
                    else:
                        await send_terminal(text="", expression="")

                elif isinstance(job.job_content, SongSegmentChat):
                    text = f"(唱了《{job.job_content.song}》)\n{job.job_content.lyrics}"
                    expression = "唱歌"
                    try:
                        audio = await _run_sync_in_executor(
                            self.capabilities.singing.sing,
                            job.character_id,
                            job.job_content.song,
                            job.job_content.segment,
                        )
                    except Exception as error:
                        self.logger.error(f"Singing synthesis failed: {error}")
                        await send_terminal(
                            text=text,
                            expression=expression,
                            error_code="TTS_STREAM_ERROR",
                        )
                        continue
                    if not audio:
                        self.logger.warning(f"No audio generated for song: {job.job_content.song}")
                        await send_terminal(
                            text=text,
                            expression=expression,
                            error_code="TTS_EMPTY",
                        )
                        continue
                    if job.song_audio_generated_callback is not None:
                        job.song_audio_generated_callback(job.job_content.song, job.job_content.segment)
                    CHUNK_SIZE = 48 * 1024
                    for i in range(0, len(audio), CHUNK_SIZE):
                        chunk = audio[i:i+CHUNK_SIZE]
                        chunk_base64 = base64.b64encode(chunk).decode("utf-8")
                        chunk_text = "" if i > 0 else text
                        if i == 0:
                            self._record_first_packet(job, job_start_ts, job_start_monotonic)
                        is_final_package = (i + CHUNK_SIZE) >= len(audio)
                        if is_final_package:
                            await send_terminal(
                                audio=chunk_base64,
                                text=chunk_text,
                                expression=expression,
                            )
                        else:
                            chunk_resp = ChatResponse(
                                uuid=job.job_content.uuid, audio=chunk_base64,
                                is_final_package=False, text=chunk_text,
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

    def _record_queue_wait(self, job: SpeakingJob, job_start_ts: str, job_start_monotonic: float) -> None:
        observability = get_observability_service()
        if observability is None or not job.trace_id or job.enqueued_monotonic is None or job.enqueued_ts is None:
            return
        observability.record_pipeline_span(
            trace_id=job.trace_id,
            user_id=job.user_id,
            topic_id=job.topic_id,
            span_name="tts.queue_wait",
            start_ts=job.enqueued_ts,
            end_ts=job_start_ts,
            duration_ms=(job_start_monotonic - job.enqueued_monotonic) * 1000.0,
            metadata={
                "character_id": job.character_id,
                "job_type": type(job.job_content).__name__,
            },
        )

    def _record_first_packet(self, job: SpeakingJob, job_start_ts: str, job_start_monotonic: float) -> None:
        observability = get_observability_service()
        if observability is None or not job.trace_id:
            return
        first_packet_monotonic = time.perf_counter()
        first_packet_ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        observability.record_pipeline_span(
            trace_id=job.trace_id,
            user_id=job.user_id,
            topic_id=job.topic_id,
            span_name="tts.start_to_first_packet",
            start_ts=job_start_ts,
            end_ts=first_packet_ts,
            duration_ms=(first_packet_monotonic - job_start_monotonic) * 1000.0,
            metadata={
                "character_id": job.character_id,
                "job_type": type(job.job_content).__name__,
            },
        )
        if job.reply_generated_monotonic is None or job.reply_generated_ts is None:
            return
        observability.record_pipeline_span(
            trace_id=job.trace_id,
            user_id=job.user_id,
            topic_id=job.topic_id,
            span_name="reply_generated_to_first_tts_packet",
            start_ts=job.reply_generated_ts,
            end_ts=first_packet_ts,
            duration_ms=(first_packet_monotonic - job.reply_generated_monotonic) * 1000.0,
            metadata={
                "character_id": job.character_id,
                "job_type": type(job.job_content).__name__,
            },
        )

    async def stop(self):
        self._stopping = True
        signal_error: Exception | None = None
        speech = getattr(self.capabilities, "speech", None)
        request_stop = getattr(speech, "request_stop", None)
        if request_stop is not None:
            try:
                request_stop()
            except Exception as error:
                signal_error = error

        task = self.worker_task
        if task is not None:
            cancel_task_once(task)
            done, pending = await wait_for_owned_tasks(
                (task,),
                timeout_seconds=self.shutdown_timeout_seconds,
            )
            if pending:
                raise RuntimeError("Global speaking worker is still stopping")
            try:
                task.result()
            except asyncio.CancelledError:
                self.logger.info("Global speaking worker stopped")
            finally:
                if self.worker_task is task:
                    self.worker_task = None

        if signal_error is not None:
            raise RuntimeError(f"Failed to signal TTS shutdown: {signal_error}") from signal_error


_global_speaking_worker: GlobalSpeakingWorker | None = None


def get_global_speaking_worker() -> GlobalSpeakingWorker:
    global _global_speaking_worker
    if _global_speaking_worker is None:
        _global_speaking_worker = GlobalSpeakingWorker({})
    return _global_speaking_worker
