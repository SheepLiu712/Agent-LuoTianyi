from __future__ import annotations

import asyncio
import base64
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, AsyncGenerator, Awaitable, Callable, Dict

from src.agent.main_chat import OneSentenceChat, SongSegmentChat
from src.chat_session.call_models import CallTTSLine
from src.system.observability import get_observability_service
from src.utils.asyncio_helpers import (
    DEFAULT_OWNED_TASK_STOP_TIMEOUT_SECONDS,
    cancel_task_once,
    run_sync_owned,
    wait_for_owned_tasks,
)
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.capabilities import CapabilityManager
    from src.system.user_interface.types import ChatResponse


_sentinel = object()


async def _run_sync_in_executor(call, *args, executor=None):
    """Await a sync call without abandoning its thread when cancellation arrives."""
    return await run_sync_owned(call, *args, executor=executor)


async def _iter_sync_gen_in_executor(gen, executor=None):
    """Wrap a sync generator and retain ownership until it is closed."""
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
    send_reply_callback: Callable[["ChatResponse"], Awaitable[None]]
    job_content: "OneSentenceChat | SongSegmentChat | CallTTSLine | str"
    character_id: str = "luotianyi"
    stream_id: str = "default"
    stream_seq: int = 0
    trace_id: str | None = None
    user_id: str | None = None
    topic_id: str | None = None
    response_id: str | None = None
    reply_generated_monotonic: float | None = None
    reply_generated_ts: str | None = None
    song_audio_generated_callback: Callable[[str, str], None] | None = None
    on_error: Callable[[Exception], Awaitable[None] | None] | None = None
    cancellation_event: asyncio.Event | None = None
    enqueued_monotonic: float | None = None
    enqueued_ts: str | None = None
    estimated_seconds: float | None = None

    def is_cancelled(self) -> bool:
        return bool(self.cancellation_event and self.cancellation_event.is_set())

    def estimate_duration(self) -> float:
        if self.estimated_seconds is not None:
            return max(0.3, float(self.estimated_seconds))
        if isinstance(self.job_content, OneSentenceChat):
            count = len(self.job_content.sound_content or self.job_content.content)
        elif isinstance(self.job_content, CallTTSLine):
            count = len(self.job_content.content)
        else:
            count = len(self.job_content.get_content()) if hasattr(self.job_content, "get_content") else len(str(self.job_content))
        return max(count / 200 * 60, 0.3)


class _SpeakingQueueView:
    """Expose queue capacity and drain semantics for lifecycle callers."""

    def __init__(self, worker: "GlobalSpeakingWorker", maxsize: int) -> None:
        self._worker = worker
        self.maxsize = maxsize

    async def join(self) -> None:
        await self._worker.wait_until_idle()


class GlobalSpeakingWorker:
    """单 GPU TTS worker：每流 FIFO，流头按等待/估算时长动态选择。"""

    def __init__(self, config: Dict):
        self.config = config or {}
        self.logger = get_logger("GlobalSpeakingWorker")
        self.worker_task: asyncio.Task | None = None
        self.capabilities: "CapabilityManager | None" = None
        self._stream_queues: dict[str, deque[SpeakingJob]] = {}
        self._last_started_at: dict[str, float] = {}
        self._condition = asyncio.Condition()
        self._total_jobs = 0
        self._active_job: SpeakingJob | None = None
        self._max_total_jobs = max(
            1,
            int(self.config.get("max_total_jobs", self.config.get("queue_maxsize", 512))),
        )
        self._max_stream_jobs = max(1, int(self.config.get("max_stream_jobs", 64)))
        self.queue = _SpeakingQueueView(self, self._max_total_jobs)
        self._stopping = False
        self.terminal_send_max_attempts = max(
            1,
            int(self.config.get("terminal_send_max_attempts", 3)),
        )
        self.terminal_send_retry_delay_seconds = max(
            0.0,
            float(self.config.get("terminal_send_retry_delay_seconds", 0.05)),
        )
        self.shutdown_timeout_seconds = max(
            0.001,
            float(
                self.config.get(
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
        self.capabilities = capabilities

    def wire_dependencies(self, *, capabilities: "CapabilityManager") -> None:
        self.set_capabilities(capabilities)
        self.ensure_dependencies()

    def ensure_dependencies(self) -> None:
        if self.capabilities is None:
            raise RuntimeError("GlobalSpeakingWorker dependency is missing: capabilities")

    async def enqueue(self, job: SpeakingJob):
        self.start_if_needed()
        if job.enqueued_monotonic is None:
            job.enqueued_monotonic = time.perf_counter()
        if job.enqueued_ts is None:
            job.enqueued_ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        async with self._condition:
            stream_queue = self._stream_queues.setdefault(job.stream_id, deque())
            if self._total_jobs >= self._max_total_jobs or len(stream_queue) >= self._max_stream_jobs:
                raise RuntimeError("speaking queue is full")
            stream_queue.append(job)
            self._total_jobs += 1
            self._condition.notify()

    async def cancel_pending(self, *, stream_id: str, response_id: str | None = None, reason: str = "cancelled") -> int:
        _ = reason
        removed = 0
        async with self._condition:
            active = self._active_job
            if (
                active is not None
                and active.stream_id == stream_id
                and (response_id is None or active.response_id == response_id)
                and active.cancellation_event is not None
            ):
                # GPT-SoVITS 的同步生成器无法被 asyncio 强制抢占；设置取消令牌后，
                # 处理循环会在当前生成调用返回时立即丢弃剩余音频，不再发送后续包。
                active.cancellation_event.set()
            queue = self._stream_queues.get(stream_id)
            if queue is None:
                return 0
            kept = deque()
            while queue:
                job = queue.popleft()
                if response_id is None or job.response_id == response_id:
                    if job.cancellation_event:
                        job.cancellation_event.set()
                    removed += 1
                    self._total_jobs -= 1
                else:
                    kept.append(job)
            if kept:
                self._stream_queues[stream_id] = kept
            else:
                self._stream_queues.pop(stream_id, None)
            self._condition.notify_all()
        return removed

    def has_work(self, stream_id: str) -> bool:
        queue = self._stream_queues.get(stream_id)
        return bool(queue) or bool(self._active_job and self._active_job.stream_id == stream_id)

    async def wait_until_idle(self) -> None:
        async with self._condition:
            while self._total_jobs > 0 or self._active_job is not None:
                await self._condition.wait()

    async def _take_next_job(self) -> SpeakingJob:
        async with self._condition:
            while self._total_jobs <= 0:
                await self._condition.wait()
            now = time.perf_counter()
            candidates: list[tuple[float, float, str, SpeakingJob]] = []
            for stream_id, queue in self._stream_queues.items():
                if not queue:
                    continue
                job = queue[0]
                last_started = self._last_started_at.get(stream_id)
                priority = 1.0 if last_started is None else max((now - last_started) / job.estimate_duration(), 1.0)
                candidates.append((priority, -(job.enqueued_monotonic or now), stream_id, job))
            _, _, stream_id, job = max(candidates, key=lambda item: (item[0], item[1]))
            queue = self._stream_queues[stream_id]
            queue.popleft()
            if not queue:
                self._stream_queues.pop(stream_id, None)
            self._total_jobs -= 1
            self._last_started_at[stream_id] = time.perf_counter()
            self._active_job = job
            return job

    async def _run(self):
        from src.system.user_interface.types import ChatResponse

        while True:
            job = await self._take_next_job()
            job_start_monotonic = time.perf_counter()
            job_start_ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            self._record_queue_wait(job, job_start_ts, job_start_monotonic)
            try:
                if job.is_cancelled():
                    continue
                if isinstance(job.job_content, OneSentenceChat):
                    await self._process_sentence_job(job, job_start_ts, job_start_monotonic, ChatResponse)
                elif isinstance(job.job_content, SongSegmentChat):
                    await self._process_song_job(job, job_start_ts, job_start_monotonic, ChatResponse)
                elif isinstance(job.job_content, CallTTSLine):
                    await self._process_call_job(job, job_start_ts, job_start_monotonic, ChatResponse)
                else:
                    self.logger.warning("Unsupported speaking job type: %s", type(job.job_content))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.logger.exception("Error processing speaking job")
                if job.on_error is not None:
                    result = job.on_error(exc)
                    if asyncio.iscoroutine(result):
                        await result
            finally:
                async with self._condition:
                    self._active_job = None
                    self._condition.notify_all()

    async def _send_terminal(self, job, response) -> None:
        for attempt in range(1, self.terminal_send_max_attempts + 1):
            try:
                await job.send_reply_callback(response)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                if attempt >= self.terminal_send_max_attempts:
                    raise
                self.logger.warning(
                    "Terminal response was not accepted (%s/%s): %s",
                    attempt,
                    self.terminal_send_max_attempts,
                    error,
                )
                if self.terminal_send_retry_delay_seconds:
                    await asyncio.sleep(self.terminal_send_retry_delay_seconds)
            else:
                return

    async def _process_sentence_job(self, job, start_ts, start_monotonic, ChatResponse):
        display_text = job.job_content.content
        sound_text = job.job_content.sound_content
        expression = job.job_content.expression
        if not sound_text.strip():
            await self._send_terminal(
                job,
                ChatResponse(
                    uuid=job.job_content.uuid,
                    audio="",
                    is_final_package=True,
                    text=display_text,
                    expression=expression,
                ),
            )
            return
        sync_gen = self.capabilities.speech.say_stream(job.character_id, sound_text, job.job_content.tone)
        audio_sent = False
        try:
            async for audio_chunk in _iter_sync_gen_in_executor(sync_gen):
                if job.is_cancelled():
                    return
                if not audio_chunk:
                    continue
                if not audio_sent:
                    self._record_first_packet(job, start_ts, start_monotonic)
                first = not audio_sent
                audio_sent = True
                await job.send_reply_callback(
                    ChatResponse(
                        uuid=job.job_content.uuid,
                        audio=audio_chunk,
                        is_final_package=False,
                        text=display_text if first else "",
                        expression=expression,
                    )
                )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.logger.error("Streaming TTS failed: %s", error)
            if not job.is_cancelled():
                await self._send_terminal(
                    job,
                    ChatResponse(
                        uuid=job.job_content.uuid,
                        audio="",
                        is_final_package=True,
                        text="" if audio_sent else display_text,
                        expression="" if audio_sent else expression,
                        audio_error=True,
                        error_code="TTS_STREAM_ERROR",
                    ),
                )
            return
        if not job.is_cancelled():
            await self._send_terminal(
                job,
                ChatResponse(
                    uuid=job.job_content.uuid,
                    audio="",
                    is_final_package=True,
                    text="" if audio_sent else display_text,
                    expression="" if audio_sent else expression,
                    audio_error=not audio_sent,
                    error_code=None if audio_sent else "TTS_EMPTY",
                ),
            )

    async def _process_call_job(self, job, start_ts, start_monotonic, ChatResponse):
        line = job.job_content
        sync_gen = self.capabilities.speech.say_stream(job.character_id, line.content, line.tone)
        is_first = True
        async for audio_chunk in _iter_sync_gen_in_executor(sync_gen):
            if job.is_cancelled():
                return
            if is_first:
                self._record_first_packet(job, start_ts, start_monotonic)
            first = is_first
            is_first = False
            await job.send_reply_callback(
                ChatResponse(
                    uuid=line.audio_id,
                    audio=audio_chunk,
                    is_final_package=False,
                    text=line.content if first else "",
                    expression=line.expression if first else "",
                )
            )
        if not job.is_cancelled():
            await self._send_terminal(
                job,
                ChatResponse(uuid=line.audio_id, audio="", is_final_package=True, text="", expression=""),
            )

    async def _process_song_job(self, job, start_ts, start_monotonic, ChatResponse):
        content = job.job_content
        text = f"(唱了《{content.song}》)\n{content.lyrics}"
        expression = "唱歌"
        try:
            audio = await _run_sync_in_executor(
                self.capabilities.singing.sing,
                job.character_id,
                content.song,
                content.segment,
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.logger.error("Singing synthesis failed: %s", error)
            if not job.is_cancelled():
                await self._send_terminal(
                    job,
                    ChatResponse(
                        uuid=content.uuid,
                        audio="",
                        is_final_package=True,
                        text=text,
                        expression=expression,
                        audio_error=True,
                        error_code="TTS_STREAM_ERROR",
                    ),
                )
            return
        if job.is_cancelled():
            return
        if not audio:
            self.logger.warning("No audio generated for song: %s", content.song)
            await self._send_terminal(
                job,
                ChatResponse(
                    uuid=content.uuid,
                    audio="",
                    is_final_package=True,
                    text=text,
                    expression=expression,
                    audio_error=True,
                    error_code="TTS_EMPTY",
                ),
            )
            return
        if job.song_audio_generated_callback is not None:
            job.song_audio_generated_callback(content.song, content.segment)
        chunk_size = 48 * 1024
        for i in range(0, len(audio), chunk_size):
            if job.is_cancelled():
                return
            chunk = base64.b64encode(audio[i:i + chunk_size]).decode("utf-8")
            if i == 0:
                self._record_first_packet(job, start_ts, start_monotonic)
            response = ChatResponse(
                uuid=job.job_content.uuid,
                audio=chunk,
                is_final_package=(i + chunk_size >= len(audio)),
                text=text if i == 0 else "",
                expression=expression if i == 0 else "",
            )
            if response.is_final_package:
                await self._send_terminal(job, response)
            else:
                await job.send_reply_callback(response)

    def _record_queue_wait(self, job, job_start_ts, job_start_monotonic) -> None:
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
            metadata={"character_id": job.character_id, "job_type": type(job.job_content).__name__, "stream_id": job.stream_id},
        )

    def _record_first_packet(self, job, job_start_ts, job_start_monotonic) -> None:
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
            metadata={"character_id": job.character_id, "job_type": type(job.job_content).__name__, "stream_id": job.stream_id},
        )
        if job.reply_generated_monotonic is not None and job.reply_generated_ts is not None:
            observability.record_pipeline_span(
                trace_id=job.trace_id,
                user_id=job.user_id,
                topic_id=job.topic_id,
                span_name="reply_generated_to_first_tts_packet",
                start_ts=job.reply_generated_ts,
                end_ts=first_packet_ts,
                duration_ms=(first_packet_monotonic - job.reply_generated_monotonic) * 1000.0,
                metadata={"character_id": job.character_id, "job_type": type(job.job_content).__name__, "stream_id": job.stream_id},
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
        async with self._condition:
            self._stream_queues.clear()
            self._total_jobs = 0
            self._active_job = None
            self._condition.notify_all()
        if signal_error is not None:
            raise RuntimeError(f"Failed to signal TTS shutdown: {signal_error}") from signal_error


_global_speaking_worker: GlobalSpeakingWorker | None = None


def get_global_speaking_worker() -> GlobalSpeakingWorker:
    global _global_speaking_worker
    if _global_speaking_worker is None:
        _global_speaking_worker = GlobalSpeakingWorker({})
    return _global_speaking_worker
