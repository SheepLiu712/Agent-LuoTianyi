"""Aliyun Qwen-Audio realtime WebSocket adapter."""

from __future__ import annotations

import asyncio
import base64
import json
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

import websockets
from websockets.exceptions import ConnectionClosed

from src.domain.call import CallAudioSemantic

from .config import AliyunRealtimeSpeechConfig
from .contracts import (
    AmbientAudio,
    AudioFrame,
    ProviderFailed,
    RealtimeSpeechConfig,
    RealtimeSpeechEvent,
    SpeechStarted,
    SpeechStopped,
    TurnCompleted,
    TurnInvalid,
)

_STOP = object()


class _WebSocket(Protocol):
    async def send(self, message: str) -> None: ...

    async def recv(self) -> str | bytes: ...

    async def close(self) -> None: ...


Connector = Callable[..., Awaitable[_WebSocket]]


@dataclass(slots=True)
class _ResponseCleanup:
    cancel_requested: bool = False
    cancel_confirmed: bool = False
    done_seen: bool = False
    assistant_items: set[str] = field(default_factory=set)
    delete_requested_items: set[str] = field(default_factory=set)
    pending_deletes: set[str] = field(default_factory=set)
    deadline: float | None = None


class AliyunRealtimeSpeechSession:
    """One isolated provider session with bounded I/O and fail-closed cleanup."""

    def __init__(self, config: AliyunRealtimeSpeechConfig, *, connector: Connector | None = None) -> None:
        self._config = config
        self._connector = connector or websockets.connect
        self._socket: _WebSocket | None = None
        self._writes: asyncio.Queue[dict[str, object] | object] = asyncio.Queue(maxsize=config.write_queue_size)
        self._event_buffer: deque[RealtimeSpeechEvent] = deque()
        self._event_condition = asyncio.Condition()
        self._event_consumer_active = False
        self._pending_delivery: RealtimeSpeechEvent | None = None
        self._terminal_failure: ProviderFailed | None = None
        self._session_updated: asyncio.Future[None] | None = None
        self._writer: asyncio.Task[None] | None = None
        self._reader: asyncio.Task[None] | None = None
        self._cleanup: asyncio.Task[None] | None = None
        self._cleanup_changed = asyncio.Event()
        self._closed = False
        self._closed_event = asyncio.Event()
        self._failed = False
        self._terminal_sent = False
        self._shutdown_lock = asyncio.Lock()
        self._invalid_items: set[str] = set()
        self._completed_items: set[str] = set()
        self._responses: dict[str, _ResponseCleanup] = {}
        self._retired_responses: set[str] = set()
        self._item_owners: dict[str, str] = {}
        self.usage_totals: dict[str, int] = {}

    async def start(self, config: RealtimeSpeechConfig) -> None:
        if self._closed:
            raise RuntimeError("realtime speech session is closed")
        if self._socket is not None:
            raise RuntimeError("realtime speech session is already started")
        try:
            self._socket = await self._connector(
                self._config.websocket_url,
                extra_headers={"Authorization": f"Bearer {self._config.api_key}"},
                open_timeout=self._config.connect_timeout_seconds,
                close_timeout=self._config.close_timeout_seconds,
                max_size=1024 * 1024,
            )
            self._session_updated = asyncio.get_running_loop().create_future()
            self._writer = asyncio.create_task(self._write_loop(), name="aliyun-realtime-speech-writer")
            self._reader = asyncio.create_task(self._read_loop(), name="aliyun-realtime-speech-reader")
            self._cleanup = asyncio.create_task(self._cleanup_loop(), name="aliyun-realtime-speech-cleanup")
            await self._enqueue(self._session_update(config))
            await asyncio.wait_for(self._session_updated, timeout=self._config.session_timeout_seconds)
        except asyncio.CancelledError:
            await self.close()
            raise
        except Exception as exc:
            await self._fail("provider_start_failed", retryable=True)
            raise RuntimeError("realtime speech provider initialization failed") from exc

    async def push_audio(self, frame: AudioFrame) -> None:
        if self._closed or self._failed:
            raise RuntimeError("realtime speech session is unavailable")
        if self._socket is None or self._session_updated is None or not self._session_updated.done():
            raise RuntimeError("realtime speech session is not ready")
        if frame.encoding != "pcm_s16le" or frame.sample_rate != 16_000 or frame.channels != 1:
            raise ValueError("Aliyun realtime speech requires 16 kHz mono PCM16")
        if len(frame.payload) % 2:
            raise ValueError("PCM16 payload must contain complete samples")
        if len(frame.payload) > self._config.max_audio_frame_bytes:
            raise ValueError("audio frame exceeds configured size limit")
        await self._enqueue(
            {"type": "input_audio_buffer.append", "audio": base64.b64encode(frame.payload).decode("ascii")}
        )

    async def events(self) -> AsyncIterator[RealtimeSpeechEvent]:
        await self._acquire_event_consumer()
        try:
            while True:
                event = await self._next_event()
                if event is None:
                    return
                self._pending_delivery = None
                yield event
        finally:
            async with self._event_condition:
                if self._pending_delivery is not None:
                    self._event_buffer.appendleft(self._pending_delivery)
                    self._pending_delivery = None
                self._event_consumer_active = False
                self._event_condition.notify_all()

    async def close(self) -> None:
        await self._shutdown()

    async def _enqueue(self, message: dict[str, object]) -> None:
        if self._closed or self._failed:
            raise RuntimeError("realtime speech session is unavailable")
        put_task = asyncio.create_task(self._writes.put(message))
        close_task = asyncio.create_task(self._closed_event.wait())
        done, _ = await asyncio.wait({put_task, close_task}, return_when=asyncio.FIRST_COMPLETED)
        if close_task in done:
            put_task.cancel()
            await asyncio.gather(put_task, return_exceptions=True)
            raise RuntimeError("realtime speech session is unavailable")
        close_task.cancel()
        await asyncio.gather(close_task, return_exceptions=True)
        await put_task

    async def _emit(self, event: RealtimeSpeechEvent) -> None:
        async with self._event_condition:
            while (
                len(self._event_buffer) + int(self._pending_delivery is not None) >= self._config.event_queue_size
                and not self._failed
                and not self._closed
            ):
                await self._event_condition.wait()
            if self._failed or self._closed:
                return
            self._event_buffer.append(event)
            self._event_condition.notify_all()

    async def _acquire_event_consumer(self) -> None:
        async with self._event_condition:
            if self._event_consumer_active:
                raise RuntimeError("realtime speech events support one consumer")
            if self._pending_delivery is not None:
                self._event_buffer.appendleft(self._pending_delivery)
                self._pending_delivery = None
            self._event_consumer_active = True

    async def _next_event(self) -> RealtimeSpeechEvent | None:
        async with self._event_condition:
            while not self._event_buffer and not self._terminal_sent:
                await self._event_condition.wait()
            if self._event_buffer:
                event = self._event_buffer.popleft()
                self._pending_delivery = event
                self._event_condition.notify_all()
                return event
            failure = self._terminal_failure
            if failure is not None:
                self._pending_delivery = failure
                self._terminal_failure = None
            return cast(RealtimeSpeechEvent | None, failure)

    def _session_update(self, config: RealtimeSpeechConfig) -> dict[str, object]:
        session: dict[str, object] = {
            "modalities": ["text", "audio"],
            "input_audio_format": "pcm",
            "output_audio_format": "pcm",
            "turn_detection": {"type": "smart_turn"},
        }
        if config.language:
            session["input_audio_transcription"] = {"language": config.language}
        return {"type": "session.update", "session": session}

    async def _write_loop(self) -> None:
        try:
            while True:
                message = await self._writes.get()
                if message is _STOP:
                    return
                socket = self._socket
                if socket is None:
                    return
                await socket.send(json.dumps(message, separators=(",", ":")))
        except asyncio.CancelledError:
            raise
        except Exception:
            await self._fail("provider_write_failed", retryable=True)

    async def _read_loop(self) -> None:
        try:
            while not self._failed and not self._closed:
                socket = self._socket
                if socket is None:
                    return
                await self._handle_message(self._decode_message(await socket.recv()))
        except asyncio.CancelledError:
            raise
        except ConnectionClosed as exc:
            if not self._closed and not self._failed:
                await self._fail("provider_connection_closed", retryable=exc.code != 1008)
        except Exception:
            await self._fail("provider_receive_failed", retryable=True)

    @staticmethod
    def _decode_message(raw: str | bytes) -> dict[str, Any]:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        value = json.loads(raw)
        if not isinstance(value, dict) or not isinstance(value.get("type"), str):
            raise ValueError("provider message has an invalid envelope")
        return value

    async def _handle_message(self, message: dict[str, Any]) -> None:
        if self._failed or self._closed:
            return
        event_type = message["type"]
        if event_type == "session.updated":
            if self._session_updated is not None and not self._session_updated.done():
                self._session_updated.set_result(None)
        elif event_type == "input_audio_buffer.speech_started":
            await self._emit(SpeechStarted())
        elif event_type == "input_audio_buffer.speech_stopped":
            await self._handle_speech_stopped(message)
        elif event_type == "conversation.item.input_audio_transcription.completed":
            await self._handle_user_transcript(message)
        elif event_type == "conversation.item.ambient_audio_transcription.completed":
            transcript = _clean_string(message.get("transcript"))
            if transcript:
                await self._emit(AmbientAudio(transcript))
        else:
            await self._handle_provider_output(message)

    async def _handle_provider_output(self, message: dict[str, Any]) -> None:
        event_type = message["type"]
        if event_type == "response.created":
            await self._cancel_response(message)
        elif event_type in {"response.output_item.added", "response.output_item.done"}:
            await self._track_assistant_item(message)
        elif event_type.startswith("response.") and "item_id" in message:
            await self._validate_assistant_stream_event(message)
        elif event_type == "conversation.item.created" and _mapping(message.get("item")).get("role") == "assistant":
            await self._handle_conversation_item_created(message)
        elif event_type == "conversation.item.deleted":
            await self._confirm_item_deleted(message)
        elif event_type == "response.done":
            await self._handle_response_done(message)
        elif event_type == "error":
            error_type = _clean_string(_mapping(message.get("error")).get("type"))
            await self._fail("provider_server_error" if error_type == "server_error" else "provider_error", True)

    async def _handle_speech_stopped(self, message: dict[str, Any]) -> None:
        item_id = _clean_string(message.get("item_id"))
        if message.get("reason") == "turn_invalid":
            if item_id and item_id in self._invalid_items:
                return
            if item_id:
                self._invalid_items.add(item_id)
            await self._emit(TurnInvalid("turn_invalid"))
            return
        await self._emit(SpeechStopped())

    async def _handle_user_transcript(self, message: dict[str, Any]) -> None:
        item_id = _clean_string(message.get("item_id"))
        if not item_id or item_id in self._invalid_items or item_id in self._completed_items:
            return
        self._completed_items.add(item_id)
        transcript = _clean_string(message.get("transcript"))
        if transcript is None:
            await self._emit(TurnInvalid("empty_transcript"))
            return
        await self._emit(TurnCompleted(CallAudioSemantic(transcript=transcript)))

    async def _cancel_response(self, message: dict[str, Any]) -> None:
        response_id = _clean_string(_mapping(message.get("response")).get("id"))
        if not response_id:
            await self._fail("provider_response_identity_missing", retryable=False)
            return
        state = self._responses.setdefault(response_id, _ResponseCleanup())
        if state.cancel_requested:
            return
        state.cancel_requested = True
        await self._enqueue({"type": "response.cancel"})

    async def _track_assistant_item(self, message: dict[str, Any]) -> None:
        response_id = _clean_string(message.get("response_id"))
        item = _mapping(message.get("item"))
        if item.get("role") != "assistant":
            return
        item_id = _clean_string(item.get("id"))
        if response_id in self._retired_responses:
            await self._fail("provider_assistant_context_uncertain", retryable=False)
            return
        state = self._responses.get(response_id or "")
        if not response_id or state is None or not state.cancel_requested or not item_id:
            await self._fail("provider_assistant_context_uncertain", retryable=False)
            return
        existing_owner = self._item_owners.get(item_id)
        if existing_owner is not None and existing_owner != response_id:
            await self._fail("provider_assistant_context_uncertain", retryable=False)
            return
        self._item_owners[item_id] = response_id
        state.assistant_items.add(item_id)
        if item_id in state.delete_requested_items:
            return
        state.delete_requested_items.add(item_id)
        state.pending_deletes.add(item_id)
        if state.done_seen:
            state.deadline = asyncio.get_running_loop().time() + self._config.cleanup_timeout_seconds
            self._cleanup_changed.set()
        await self._enqueue({"type": "conversation.item.delete", "item_id": item_id})

    async def _handle_conversation_item_created(self, message: dict[str, Any]) -> None:
        item_id = _clean_string(_mapping(message.get("item")).get("id"))
        response_id = self._item_owners.get(item_id or "")
        if not item_id or response_id is None:
            await self._fail("provider_assistant_context_uncertain", retryable=False)
            return
        state = self._responses.get(response_id)
        if state is None or item_id not in state.assistant_items:
            await self._fail("provider_assistant_context_uncertain", retryable=False)

    async def _confirm_item_deleted(self, message: dict[str, Any]) -> None:
        item_id = _clean_string(message.get("item_id"))
        if not item_id:
            return
        response_id = self._item_owners.get(item_id)
        if response_id is None:
            return
        state = self._responses.get(response_id)
        if state is None or item_id not in state.pending_deletes:
            return
        state.pending_deletes.remove(item_id)
        if state.done_seen and not state.pending_deletes:
            state.deadline = None
        self._cleanup_changed.set()

    async def _validate_assistant_stream_event(self, message: dict[str, Any]) -> None:
        response_id = _clean_string(message.get("response_id"))
        item_id = _clean_string(message.get("item_id"))
        if not response_id or not item_id or self._item_owners.get(item_id) != response_id:
            await self._fail("provider_assistant_context_uncertain", retryable=False)

    async def _handle_response_done(self, message: dict[str, Any]) -> None:
        response = _mapping(message.get("response"))
        response_id = _clean_string(response.get("id"))
        state = self._responses.get(response_id or "")
        if not response_id or state is None or not state.cancel_requested or response.get("status") != "cancelled":
            await self._fail("provider_assistant_context_uncertain", retryable=False)
            return
        state.done_seen = True
        state.cancel_confirmed = True
        self._record_usage(response.get("usage"))
        state.deadline = asyncio.get_running_loop().time() + self._config.cleanup_timeout_seconds
        self._cleanup_changed.set()

    async def _cleanup_loop(self) -> None:
        try:
            while True:
                deadlines = [state.deadline for state in self._responses.values() if state.deadline is not None]
                if not deadlines:
                    self._cleanup_changed.clear()
                    await self._cleanup_changed.wait()
                    continue
                timeout = max(0.0, min(deadlines) - asyncio.get_running_loop().time())
                self._cleanup_changed.clear()
                try:
                    await asyncio.wait_for(self._cleanup_changed.wait(), timeout=timeout)
                except asyncio.TimeoutError:
                    now = asyncio.get_running_loop().time()
                    expired = [
                        response_id
                        for response_id, state in self._responses.items()
                        if state.deadline is not None and state.deadline <= now
                    ]
                    if any(self._responses[response_id].pending_deletes for response_id in expired):
                        await self._fail("provider_assistant_cleanup_timeout", retryable=False)
                        return
                    for response_id in expired:
                        self._responses.pop(response_id, None)
                        self._retired_responses.add(response_id)
        except asyncio.CancelledError:
            raise

    def _record_usage(self, value: object) -> None:
        usage = _mapping(value)
        for key in ("total_tokens", "input_tokens", "output_tokens"):
            amount = usage.get(key)
            if type(amount) is int and amount >= 0:
                self.usage_totals[key] = self.usage_totals.get(key, 0) + amount

    async def _fail(self, error_code: str, retryable: bool) -> None:
        if self._failed or self._closed:
            return
        self._failed = True
        if self._session_updated is not None and not self._session_updated.done():
            self._session_updated.set_exception(RuntimeError("realtime speech provider failed"))
        await self._set_terminal(ProviderFailed(error_code=error_code, retryable=retryable))
        await self._shutdown()

    async def _set_terminal(self, failure: ProviderFailed | None = None) -> None:
        async with self._event_condition:
            if self._terminal_sent:
                return
            self._terminal_sent = True
            self._terminal_failure = failure
            self._event_condition.notify_all()

    async def _shutdown(self) -> None:
        async with self._shutdown_lock:
            if self._closed:
                return
            self._closed = True
            self._closed_event.set()
            self._cleanup_changed.set()
            async with self._event_condition:
                self._event_condition.notify_all()
            current = asyncio.current_task()
            tasks = [
                task
                for task in (self._writer, self._reader, self._cleanup)
                if task is not None and task is not current and not task.done()
            ]
            for task in tasks:
                task.cancel()
            if tasks:
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True), timeout=self._config.close_timeout_seconds
                    )
            if self._socket is not None:
                with suppress(Exception):
                    await asyncio.wait_for(self._socket.close(), timeout=self._config.close_timeout_seconds)
            if not self._terminal_sent:
                await self._set_terminal()


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _clean_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None
