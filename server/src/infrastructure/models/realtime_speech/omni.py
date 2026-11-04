"""Qwen 持续音频输入、文本输出及唯一记忆工具的协议适配。"""

from __future__ import annotations

import asyncio
import base64
import json
import struct
import time
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from uuid import UUID, uuid4

from websockets.asyncio.client import connect

from src.domain.call.omni import (
    AudioFrame,
    InstructionText,
    MemoryLookupRequested,
    MemoryLookupResult,
    OmniEvent,
    ReplyFinished,
    ReplySegment,
    ReplyStarted,
    SpeechStarted,
    SpeechStopped,
    TranscriptFinal,
)
from src.infrastructure.observability.call_latency import call_latency
from src.utils.logger import get_logger

from .config import AliyunRealtimeSpeechConfig, RealtimeSpeechUnavailable


@dataclass
class _Reply:
    item_id: str | None
    buffer: str = ""
    tone: str = "中性"
    tag: str | None = None
    index: int = 0
    first_delta: bool = False
    generating: bool = True
    cancelled: bool = False


class QwenOmniSessionFactory:
    def __init__(self, config: AliyunRealtimeSpeechConfig | None, *, connector=connect):
        self._config = config
        self._connector = connector

    @classmethod
    def from_mapping(cls, value, *, connector=connect):
        if not isinstance(value, dict) or type(value.get("enabled", False)) is not bool:
            raise ValueError("realtime_speech must be an object with boolean enabled")
        config = AliyunRealtimeSpeechConfig.from_mapping(value) if value.get("enabled", False) else None
        if config is not None and (not config.model.startswith("qwen") or "realtime" not in config.model):
            raise ValueError("通话必须使用 Qwen Realtime 模型")
        return cls(config, connector=connector)

    @property
    def is_configured(self):
        return self._config is not None

    async def open(self, call_id: UUID, instructions: str) -> QwenOmniSession:
        if self._config is None:
            raise RealtimeSpeechUnavailable("实时模型未配置")
        session = QwenOmniSession(self._config, call_id, connector=self._connector)
        try:
            await session.start(instructions)
        except BaseException:
            await session.close()
            raise
        return session


class QwenOmniSession:
    def __init__(self, config, call_id, *, connector=connect):
        self._config, self._call_id, self._connector = config, call_id, connector
        self._socket = None
        self._reader = None
        self._close_task = None
        self._closed = False
        self._error = None
        self._ready = asyncio.Event()
        self._events = asyncio.Queue(config.event_queue_size)
        self._available = asyncio.Event()
        self._write_lock = asyncio.Lock()
        self._replies = {}
        self._tools = {}
        self._submitted = set()
        self._continuations = deque()
        self._next_origins = deque()
        self._last_item = None
        self._input_epoch = 0
        self._samples = 0
        self._active_windows = deque(maxlen=8000)
        self._speech_floor = 0

    async def start(self, instructions):
        self._socket = await asyncio.wait_for(
            self._connector(
                self._config.websocket_url,
                additional_headers={"Authorization": f"Bearer {self._config.api_key}"},
                open_timeout=self._config.connect_timeout_seconds,
                close_timeout=self._config.close_timeout_seconds,
                max_size=4 * 1024 * 1024,
            ),
            self._config.connect_timeout_seconds,
        )
        self._reader = asyncio.create_task(self._read(), name=f"omni-read-{self._call_id}")
        await self._send(
            "session.update",
            session={
                "modalities": ["text"],
                "instructions": instructions,
                "input_audio_format": "pcm16",
                "input_audio_transcription": {"model": "qwen3-asr-flash-realtime"},
                "turn_detection": {"type": "server_vad", "silence_duration_ms": self._config.max_sentence_silence},
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup_call_memory",
                            "description": "查询已授权的用户和角色记忆；无依据时先查询，不得编造共同经历。",
                            "parameters": {
                                "type": "object",
                                "properties": {"query": {"type": "string"}},
                                "required": ["query"],
                                "additionalProperties": False,
                            },
                        },
                    }
                ],
                "tool_choice": "auto",
            },
        )
        await asyncio.wait_for(self._ready.wait(), self._config.session_timeout_seconds)
        self._check_open()

    def _check_open(self):
        if self._error is not None:
            raise RuntimeError("Qwen realtime session failed") from self._error
        if self._closed:
            raise RuntimeError("Qwen realtime session closed")

    async def _send(self, event_type, **fields):
        async with self._write_lock:
            self._check_open()
            try:
                await self._socket.send(json.dumps({"event_id": uuid4().hex, "type": event_type, **fields}))
            except Exception as error:
                self._fail(error)
                raise

    async def push(self, frame: AudioFrame | InstructionText) -> None:
        if isinstance(frame, AudioFrame):
            if (frame.encoding, frame.sample_rate, frame.channels) != ("pcm_s16le", 16000, 1):
                raise ValueError("Qwen input requires mono 16 kHz PCM16")
            if len(frame.payload) % 2 or len(frame.payload) > self._config.max_audio_frame_bytes:
                raise ValueError("invalid PCM frame size")
            self._observe_pcm(frame)
            await self._send("input_audio_buffer.append", audio=base64.b64encode(frame.payload).decode("ascii"))
        elif isinstance(frame, InstructionText):
            self._next_origins.append((None, None, self._input_epoch))
            prompts = {
                "opening": "电话刚刚接通，请用一句简短口语向用户打招呼。",
                "silence": "通话短暂安静了，请用一句简短口语自然关心用户或开启话题。",
            }
            await self._send(
                "conversation.item.create",
                item={
                    "type": "message",
                    "role": "system",
                    "content": [
                        {"type": "input_text", "text": frame.text if frame.text != frame.kind else prompts[frame.kind]}
                    ],
                },
            )
            await self._send("response.create")
        else:
            raise TypeError("unsupported omni input")

    async def events(self) -> AsyncIterator[OmniEvent]:
        while True:
            await self._available.wait()
            while not self._events.empty():
                yield self._events.get_nowait()
            self._available.clear()
            if self._error is not None:
                raise RuntimeError("Qwen realtime receive failed") from self._error
            if self._closed:
                return

    def _emit(self, event):
        self._events.put_nowait(event)
        self._available.set()

    def _fail(self, error):
        if self._error is None:
            self._error = error
            get_logger(__name__).error("实时模型失败 call=%s type=%s", self._call_id, type(error).__name__)
        self._ready.set()
        self._available.set()

    async def _read(self):
        try:
            while not self._closed:
                event = json.loads(await self._socket.recv())
                await self._dispatch(event)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if not self._closed:
                self._fail(error)

    def _observe_pcm(self, frame):
        # 10 ms 窗口的均方根阈值，仅供诊断；不改变断句策略或保存音频。
        arrival = frame.ingress_ns if frame.ingress_ns is not None else time.monotonic_ns()
        samples = len(frame.payload) // 2
        for offset in range(0, samples, 160):
            count = min(160, samples - offset)
            window = struct.unpack_from(f"<{count}h", frame.payload, 2 * offset)
            if sum(x * x for x in window) >= count * 200**2:
                end = offset + count
                self._active_windows.append((self._samples + end, arrival - (samples - end) * 62500))
        self._samples += samples

    def _estimated_end(self, end_ms):
        if type(end_ms) not in (int, float) or not 0 <= end_ms * 16 <= self._samples:
            self._speech_floor = self._samples  # 避免下一轮误用本轮的有声窗口。
            return None
        end = end_ms * 16
        estimate = next((ns for pos, ns in reversed(self._active_windows) if self._speech_floor < pos <= end), None)
        self._speech_floor = max(self._speech_floor, end)
        return estimate

    def _start_input(self, event):
        start_ms = event.get("audio_start_ms")
        if type(start_ms) in (int, float):
            self._speech_floor = max(self._speech_floor, start_ms * 16)
        self._input_epoch += 1
        self._emit(SpeechStarted(event["item_id"]))

    async def _dispatch(self, event):
        kind = event["type"]
        if kind == "error":
            code = event.get("error", {}).get("code", "unknown")
            raise RuntimeError(f"Qwen protocol error: {code}")
        if kind == "session.updated":
            self._ready.set()
        elif kind == "input_audio_buffer.speech_started":
            self._start_input(event)
        elif kind == "input_audio_buffer.speech_stopped":
            self._last_item = event["item_id"]
            self._next_origins.append((self._last_item, None, self._input_epoch))
            self._emit(SpeechStopped(self._last_item, self._estimated_end(event.get("audio_end_ms"))))
        elif kind == "conversation.item.input_audio_transcription.completed":
            self._emit(TranscriptFinal(event["item_id"], event["transcript"]))
        elif kind == "response.created":
            await self._created(event["response"]["id"])
        elif kind == "response.text.delta":
            self._text(event["response_id"], event["delta"])
        elif kind == "response.function_call_arguments.done":
            self._tool(event)
        elif kind == "response.done":
            await self._done(event["response"], event.get("event_id"))

    async def _created(self, response_id):
        origin, parent, epoch = (
            self._next_origins.popleft() if self._next_origins else (self._last_item, None, self._input_epoch)
        )
        stale = epoch != self._input_epoch or (parent is not None and self._replies[parent].cancelled)
        self._replies[response_id] = _Reply(origin)
        if stale:
            await self.interrupt(response_id)
        else:
            call_latency(
                "reply.model_link", self._call_id, response_id=response_id, parent_response_id=parent, item_id=origin
            )
            self._emit(ReplyStarted(response_id, origin))

    def _text(self, response_id, delta):
        reply = self._replies[response_id]
        if reply.cancelled or not reply.generating:
            return
        if delta and not reply.first_delta:
            reply.first_delta = True
            call_latency("reply.first_text_delta", self._call_id, response_id=response_id)
        for char in delta:
            self._text_character(response_id, reply, char)

    def _text_character(self, response_id, reply, char):
        if reply.tag is not None:
            if char != "]":
                reply.tag += char
                return
            tone = reply.tag.strip()
            if not tone or tone.lower() == "sing":
                raise ValueError("通话回复必须使用语气标签，不允许演唱指令")
            reply.tone, reply.tag = tone, None
        elif char == "[":
            self._flush_text(response_id, reply)
            reply.tag = ""
        else:
            reply.buffer += char
            if char in "。！？!?；;\n":
                self._flush_text(response_id, reply)

    def _flush_text(self, response_id, reply):
        text, reply.buffer = reply.buffer.strip(), ""
        if text:
            self._emit(ReplySegment(response_id, reply.index, text, reply.tone))
            reply.index += 1

    def _tool(self, event):
        response_id, call_id = event["response_id"], event["call_id"]
        if self._replies[response_id].cancelled or call_id in self._tools:
            return
        arguments = json.loads(event["arguments"])
        if event["name"] != "lookup_call_memory" or set(arguments) != {"query"}:
            raise ValueError("invalid memory tool arguments")
        query = arguments["query"]
        if not isinstance(query, str) or not query.strip():
            raise ValueError("empty memory query")
        self._tools[call_id] = response_id
        self._emit(MemoryLookupRequested(response_id, call_id, query))

    def _terminal_reply(self, response, event_id):
        response_id = response.get("id")
        status = response.get("status")
        details = response.get("status_details") or {}
        error = details.get("error") or {}
        diagnostic = (
            f"event_id={event_id!r} response_id={response_id!r} status={status!r} "
            f"reason={details.get('reason')!r} error_type={error.get('type')!r} error_code={error.get('code')!r}"
        )
        if status not in {"completed", "cancelled"}:
            raise RuntimeError(f"Qwen response ended unsuccessfully: {diagnostic}")
        if response_id:
            if response_id not in self._replies:
                raise RuntimeError(f"Qwen finished an unknown response: {diagnostic}")
            return self._replies[response_id]

        # 未创建回复就结束：只能结算唯一待创建来源，绝不能猜测正在播放的回复 ID。
        active = any(reply.generating for reply in self._replies.values())
        if active or response.get("output") or len(self._next_origins) > 1:
            raise RuntimeError(f"Cannot correlate anonymous Qwen response: {diagnostic}")
        origin = self._next_origins.popleft() if self._next_origins else None
        get_logger(__name__).warning(
            "Qwen ended without creating a reply call=%s item_id=%s %s",
            self._call_id,
            origin[0] if origin else None,
            diagnostic,
        )
        return None

    async def _done(self, response, event_id):
        reply = self._terminal_reply(response, event_id)
        if reply is None or not reply.generating:
            return
        response_id = response["id"]
        status = response["status"]
        reply.generating = False
        if status == "cancelled":
            reply.cancelled = True
        if not reply.cancelled:
            if reply.tag is not None:
                raise ValueError("通话回复以未闭合的语气标签结束")
            self._flush_text(response_id, reply)
        reply.buffer = ""
        self._emit(ReplyFinished(response_id))
        await self._continue_tools()

    async def submit_tool_result(self, tool_call_id, result: MemoryLookupResult):
        response_id = self._tools.get(tool_call_id)
        if self._closed or response_id is None or tool_call_id in self._submitted:
            return
        reply = self._replies[response_id]
        if reply.cancelled:
            return
        self._submitted.add(tool_call_id)
        await self._send(
            "conversation.item.create",
            item={
                "type": "function_call_output",
                "call_id": tool_call_id,
                "output": json.dumps(asdict(result), ensure_ascii=False),
            },
        )
        self._continuations.append(response_id)
        await self._continue_tools()

    async def _continue_tools(self):
        if any(reply.generating for reply in self._replies.values()):
            return
        while self._continuations:
            response_id = self._continuations.popleft()
            reply = self._replies[response_id]
            if reply.cancelled:
                continue
            calls = {key for key, owner in self._tools.items() if owner == response_id}
            if not calls.issubset(self._submitted):
                self._continuations.appendleft(response_id)
                return
            self._continuations = deque(owner for owner in self._continuations if owner != response_id)
            self._next_origins.append((reply.item_id, response_id, self._input_epoch))
            call_latency("reply.continuation_requested", self._call_id, response_id=response_id, item_id=reply.item_id)
            await self._send("response.create")
            return

    async def interrupt(self, response_id: str) -> None:
        reply = self._replies.get(response_id)
        if reply is None or reply.cancelled or self._closed:
            return
        reply.cancelled = True
        reply.buffer = ""
        reply.tag = None
        if reply.generating:
            await self._send("response.cancel", response_id=response_id)

    async def close(self):
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
        await asyncio.shield(self._close_task)

    async def _close(self):
        self._closed = True
        self._available.set()
        self._ready.set()
        if self._reader is not None:
            self._reader.cancel()
            await asyncio.gather(self._reader, return_exceptions=True)
        if self._socket is not None:
            await asyncio.wait_for(self._socket.close(), self._config.close_timeout_seconds)
        self._tools.clear()
        self._continuations.clear()
