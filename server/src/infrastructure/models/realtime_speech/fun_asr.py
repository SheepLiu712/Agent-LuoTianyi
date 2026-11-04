"""Fun-ASR 纯转写会话：二进制音频输入、句子事件输出，无回复生成和取消。"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from collections.abc import AsyncIterator
from traceback import extract_stack
from uuid import UUID, uuid4

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from src.domain.call import CallAudioSemantic
from src.utils.logger import get_logger

from .aliyun import Connector, _diagnostic_token, _exception_locations
from .config import AliyunRealtimeSpeechConfig
from .contracts import (
    AudioFrame,
    ProviderFailed,
    RealtimeSpeechConfig,
    RealtimeSpeechEvent,
    SpeechStarted,
    SpeechStopped,
    TranscriptUpdated,
    TurnCompleted,
    TurnInvalid,
)

logger = get_logger(__name__)


class FunAsrRealtimeSpeechSession:
    """将每个独立识别任务转换为通话领域事件，并在供应商失效时立即终止。"""

    def __init__(
        self,
        config: AliyunRealtimeSpeechConfig,
        *,
        connector: Connector | None = None,
        call_id: UUID | None = None,
        call_metrics=None,
    ) -> None:
        self._config = config
        self._connector = connector or connect
        self._call_id = call_id
        self._task_id = uuid4().hex
        self._socket = None
        self._reader = None
        self._writer = None
        self._ready = None
        self._finished = asyncio.Event()
        self._terminal = asyncio.Event()
        self._failure = None
        self._closed = False
        self._closing = False
        self._shutdown_lock = asyncio.Lock()
        self._writes = asyncio.Queue(maxsize=config.write_queue_size)
        self._events: deque[RealtimeSpeechEvent] = deque()
        self._condition = asyncio.Condition()
        self._consumer = False
        self._active_sentence: int | None = None
        self._speech_started = False
        self._last_completed = 0
        self._audio_samples = 0
        self._audio_arrivals: deque[tuple[int, int, float]] = deque(maxlen=4096)

    async def start(self, config: RealtimeSpeechConfig) -> None:
        if self._ready is not None or self._closed:
            raise RuntimeError("Fun-ASR session cannot be started twice")
        self._ready = asyncio.get_running_loop().create_future()
        try:
            self._socket = await self._connector(
                self._config.websocket_url,
                additional_headers={"Authorization": f"Bearer {self._config.api_key}"},
                open_timeout=self._config.connect_timeout_seconds,
                close_timeout=self._config.close_timeout_seconds,
                max_size=1024 * 1024,
            )
            self._reader = asyncio.create_task(self._read_loop(), name="fun-asr-reader")
            self._writer = asyncio.create_task(self._write_loop(), name="fun-asr-writer")
            parameters = {
                "format": "pcm",
                "sample_rate": 16000,
                "heartbeat": True,
                "max_sentence_silence": self._config.max_sentence_silence,
            }
            if config.language:
                parameters["language_hints"] = [config.language]
            await self._enqueue(
                self._command(
                    "run-task",
                    {
                        "task_group": "audio",
                        "task": "asr",
                        "function": "recognition",
                        "model": self._config.model,
                        "parameters": parameters,
                        "input": {},
                    },
                )
            )
            await asyncio.wait_for(asyncio.shield(self._ready), self._config.session_timeout_seconds)
        except asyncio.CancelledError:
            await self._shutdown()
            raise
        except Exception as error:
            await self._fail("provider_start_failed", exception=error)
            # 连接失败也会完成 ready；取出异常，避免产生未检索 Future 日志。
            if self._ready.done() and not self._ready.cancelled():
                self._ready.exception()
            raise RuntimeError("Fun-ASR initialization failed") from error

    def _command(self, action: str, payload: dict) -> str:
        return json.dumps(
            {"header": {"action": action, "task_id": self._task_id, "streaming": "duplex"}, "payload": payload}
        )

    async def push_audio(self, frame: AudioFrame) -> None:
        if self._closing or self._ready is None or not self._ready.done() or self._ready.exception() is not None:
            raise RuntimeError("Fun-ASR session is not ready")
        if (frame.encoding, frame.sample_rate, frame.channels) != ("pcm_s16le", 16000, 1):
            raise ValueError("Fun-ASR requires 16 kHz mono PCM16")
        if len(frame.payload) % 2 or len(frame.payload) > self._config.max_audio_frame_bytes:
            raise ValueError("invalid PCM16 frame size")
        samples = len(frame.payload) // 2
        self._audio_arrivals.append((self._audio_samples, self._audio_samples + samples, time.monotonic()))
        self._audio_samples += samples
        await self._enqueue(frame.payload)

    async def _enqueue(self, message: str | bytes) -> None:
        if self._closed or self._terminal.is_set():
            raise RuntimeError("Fun-ASR session is unavailable")
        put = asyncio.create_task(self._writes.put(message))
        terminal = asyncio.create_task(self._terminal.wait())
        try:
            done, _ = await asyncio.wait((put, terminal), return_when=asyncio.FIRST_COMPLETED)
            if terminal in done:
                raise RuntimeError("Fun-ASR session is unavailable")
            await put
        finally:
            for task in (put, terminal):
                task.cancel()
            await asyncio.gather(put, terminal, return_exceptions=True)

    async def _write_loop(self) -> None:
        try:
            while True:
                await self._socket.send(await self._writes.get())
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await self._fail("provider_write_failed", exception=error)

    async def _read_loop(self) -> None:
        try:
            while not self._closed:
                event = json.loads(await self._socket.recv())
                await self._handle_event(event)
                if self._finished.is_set() or self._failure:
                    return
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await self._fail("provider_receive_failed", exception=error)

    async def _handle_event(self, event: dict) -> None:
        header = event["header"]
        if header["task_id"] != self._task_id:
            raise ValueError("Fun-ASR returned an unexpected task id")
        kind = header["event"]
        if kind == "task-started":
            if not self._ready.done():
                self._ready.set_result(None)
        elif kind == "task-failed":
            await self._fail("provider_task_failed", header=header)
        elif kind == "task-finished":
            if not self._closing:
                raise RuntimeError("Fun-ASR task finished before client requested termination")
            self._finished.set()
        elif kind == "result-generated":
            await self._sentence(event["payload"]["output"]["sentence"])
        else:
            raise ValueError("unexpected Fun-ASR event")

    async def _sentence(self, sentence: dict) -> None:
        if sentence.get("heartbeat"):
            return
        identity = sentence["sentence_id"]
        if type(identity) is not int or identity < 1:
            raise ValueError("invalid Fun-ASR sentence id")
        if identity <= self._last_completed:
            return
        item_id = f"{self._task_id}:{identity}"
        if self._active_sentence is None:
            self._active_sentence = identity
        elif identity != self._active_sentence:
            raise ValueError("Fun-ASR started another sentence without finalizing the previous one")
        # 供应商在全零静音输入下也会返回空的 sentence_begin，不能据此打断播放。
        text = sentence["text"].strip()
        if text and not self._speech_started:
            self._speech_started = True
            await self._emit(SpeechStarted(item_id))
        if not sentence["sentence_end"]:
            if text:
                await self._emit(TranscriptUpdated(text, item_id))
            return
        self._last_completed = identity
        self._active_sentence = None
        await self._complete_sentence(item_id, text, sentence.get("end_time"))

    def _speech_end_time(self, end_ms: object) -> float | None:
        if type(end_ms) not in (int, float) or end_ms < 0:
            return None
        sample = end_ms * 16
        for start, end, arrived in reversed(self._audio_arrivals):
            if start <= sample <= end:
                return arrived - (end - sample) / 16000
        return None

    async def _complete_sentence(self, item_id: str, text: str, end_ms: object) -> None:
        if not self._speech_started:
            return
        self._speech_started = False
        await self._emit(SpeechStopped(item_id))
        if text:
            await self._emit(
                TurnCompleted(
                    CallAudioSemantic(transcript=text),
                    item_id,
                    speech_ended_at=self._speech_end_time(end_ms),
                    recognized_at=time.monotonic(),
                )
            )
        else:
            await self._emit(TurnInvalid("empty_transcript", item_id))

    async def _emit(self, event: RealtimeSpeechEvent) -> None:
        async with self._condition:
            if len(self._events) >= self._config.event_queue_size:
                raise RuntimeError("Fun-ASR consumer event queue overflow")
            self._events.append(event)
            self._condition.notify_all()

    async def events(self) -> AsyncIterator[RealtimeSpeechEvent]:
        if self._consumer:
            raise RuntimeError("Fun-ASR events support one consumer")
        self._consumer = True
        try:
            while True:
                async with self._condition:
                    await self._condition.wait_for(lambda: self._events or self._terminal.is_set())
                    if not self._events:
                        return
                    event = self._events.popleft()
                yield event
        finally:
            self._consumer = False

    async def wait_failure(self) -> ProviderFailed | None:
        await self._terminal.wait()
        return self._failure

    async def close(self) -> None:
        if self._closed:
            return
        if self._closing:
            await self._terminal.wait()
            return
        self._closing = True
        try:
            if self._ready is not None and self._ready.done() and self._ready.exception() is None:
                await asyncio.wait_for(self._finish(), self._config.close_timeout_seconds)
        except Exception as error:
            await self._fail("provider_finish_failed", exception=error)
            raise
        finally:
            await self._shutdown()

    async def _finish(self) -> None:
        await self._enqueue(self._command("finish-task", {"input": {}}))
        await self._finished.wait()

    async def _fail(self, code: str, *, exception: BaseException | None = None, header: dict | None = None) -> None:
        if self._failure or self._closed:
            return
        header = header or {}
        self._failure = ProviderFailed(code, retryable=False)
        closed = exception if isinstance(exception, ConnectionClosed) else None
        logger.error(
            "Fun-ASR failed call_id=%s task_id=%s error_code=%s provider_code=%s "
            "received_close_code=%s sent_close_code=%s exceptions=%s origin=%s",
            self._call_id,
            self._task_id,
            code,
            _diagnostic_token(header.get("error_code")),
            closed.rcvd.code if closed and closed.rcvd else None,
            closed.sent.code if closed and closed.sent else None,
            _exception_locations(exception),
            [(f.filename, f.lineno, f.name) for f in extract_stack(limit=6)[:-1]],
        )
        if self._ready is not None and not self._ready.done():
            self._ready.set_exception(RuntimeError("Fun-ASR task failed"))
        async with self._condition:
            self._events.append(self._failure)
        self._finished.set()
        await self._shutdown()

    async def _shutdown(self) -> None:
        async with self._shutdown_lock:
            if self._closed:
                return
            self._closed = True
            self._terminal.set()
            async with self._condition:
                self._condition.notify_all()
            tasks = [
                t
                for t in (self._reader, self._writer)
                if t is not None and t is not asyncio.current_task() and not t.done()
            ]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if self._socket is not None:
                await asyncio.wait_for(self._socket.close(), self._config.close_timeout_seconds)
