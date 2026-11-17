from __future__ import annotations

import base64
import hashlib
import math
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

from ..network.event_types import AgentMessage, is_audio_terminal
from ..network.network_client import NetworkClient
from ..utils.image_encoding import prepare_image_payload

_SAFE_UUID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class SessionState(str, Enum):
    NEW = "new"
    CONNECTING = "connecting"
    READY = "ready"
    DISCONNECTED = "disconnected"
    AUTH_FAILED = "auth_failed"
    CLOSED = "closed"


@dataclass(frozen=True)
class SessionEvent:
    kind: str
    data: object


@dataclass(frozen=True)
class AggregatedReply:
    uuid: str
    texts: tuple[str, ...]
    expressions: tuple[str, ...]
    complete: bool
    audio_path: str | None
    audio_error: bool
    error_code: str | None
    display_in_chat: bool
    is_ephemeral: bool
    audio_byte_count: int = 0


class SessionError(RuntimeError):
    pass


class SessionConnectionError(SessionError):
    pass


class SessionReadyTimeout(SessionError):
    pass


class SessionNotReadyError(SessionError):
    pass


class ReplyTimeoutError(SessionError):
    pass


class SessionClosedError(SessionError):
    pass


class SessionImageError(SessionError):
    pass


class SessionVoiceError(SessionError):
    pass


@dataclass
class _ReplyBuffer:
    uuid: str
    texts: list[str] = field(default_factory=list)
    expressions: list[str] = field(default_factory=list)
    audio: bytearray = field(default_factory=bytearray)
    complete: bool = False
    audio_path: str | None = None
    audio_error: bool = False
    error_code: str | None = None
    display_in_chat: bool = True
    is_ephemeral: bool = False

    def snapshot(self) -> AggregatedReply:
        return AggregatedReply(
            uuid=self.uuid,
            texts=tuple(self.texts),
            expressions=tuple(self.expressions),
            complete=self.complete,
            audio_path=self.audio_path,
            audio_error=self.audio_error,
            error_code=self.error_code,
            display_in_chat=self.display_in_chat,
            is_ephemeral=self.is_ephemeral,
            audio_byte_count=len(self.audio),
        )


class HeadlessSession:
    VOICE_CHUNK_BYTES = 48 * 1024
    VOICE_MAX_BYTES = 1024 * 1024
    VOICE_MAX_CHUNKS = 32

    def __init__(
        self,
        base_url: str,
        *,
        verify_ssl: bool = True,
        audio_output_dir: str | Path | None = None,
        network_client: NetworkClient | None = None,
    ) -> None:
        self._network_client = network_client or NetworkClient(
            base_url,
            verify_ssl=verify_ssl,
        )
        self._transport = self._network_client.ws_transport
        self._audio_output_dir = Path(audio_output_dir or Path.cwd() / "temp" / "tts_output")
        self._condition = threading.Condition(threading.RLock())
        self._state = SessionState.NEW
        self._listeners: list[Callable[[SessionEvent], None]] = []
        self._replies: dict[str, _ReplyBuffer] = {}
        self._completion_order: list[str] = []
        self._server_audio_active = False
        self._initial_history: tuple[list, int, int] = ([], -1, 0)
        self._events: list[dict] = []
        self._event_seq = 0
        self._install_transport_listeners()

    @property
    def state(self) -> SessionState:
        with self._condition:
            state = self._state
        if state == SessionState.READY and not self._transport.is_ready():
            return SessionState.DISCONNECTED
        return state

    @property
    def is_server_audio_active(self) -> bool:
        with self._condition:
            return self._server_audio_active

    @property
    def login_token(self) -> str | None:
        return self._network_client.login_token

    @property
    def initial_history(self) -> tuple[list, int, int]:
        with self._condition:
            items, start_index, attempts = self._initial_history
            return list(items), start_index, attempts

    def connect(
        self,
        username: str,
        password: str,
        *,
        timeout: float = 10.0,
        request_token: bool = False,
    ) -> None:
        self._begin_connect()
        success, message = self._network_client.login(
            username,
            password,
            request_token=request_token,
        )
        if not success:
            self._set_state(SessionState.AUTH_FAILED)
            safe_message = (message or "login failed").replace(password, "***")
            raise SessionConnectionError(safe_message)
        self._wait_until_ready(timeout)

    def register(self, username: str, password: str, invite_code: str) -> tuple[bool, str]:
        return self._network_client.register(username, password, invite_code)

    def connect_with_token(
        self,
        username: str,
        login_token: str,
        *,
        timeout: float = 10.0,
    ) -> None:
        self._begin_connect()
        if not self._network_client.auto_login(username, login_token):
            self._set_state(SessionState.AUTH_FAILED)
            raise SessionConnectionError("automatic login failed")
        self._wait_until_ready(timeout)

    def close(self) -> None:
        with self._condition:
            if self._state == SessionState.CLOSED:
                return
        self._transport.stop()
        self._set_state(SessionState.CLOSED)

    def subscribe(
        self,
        listener: Callable[[SessionEvent], None],
    ) -> Callable[[], None]:
        with self._condition:
            self._listeners.append(listener)
        removed = False

        def unsubscribe() -> None:
            nonlocal removed
            with self._condition:
                if removed:
                    return
                removed = True
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe

    def send_text(
        self,
        text: str,
        *,
        client_msg_id: str,
        ack_timeout: float = 10.0,
    ) -> dict:
        if self.state != SessionState.READY:
            raise SessionNotReadyError("session is not ready")
        return self._network_client.send_chat(
            text,
            ack_timeout=ack_timeout,
            client_msg_id=client_msg_id,
        )

    def send_typing(
        self,
        text_length: int,
        *,
        client_msg_id: str,
        ack_timeout: float = 10.0,
    ) -> dict:
        if self.state != SessionState.READY:
            raise SessionNotReadyError("session is not ready")
        return self._network_client.send_typing(
            text_length,
            ack_timeout=ack_timeout,
            client_msg_id=client_msg_id,
        )

    def select_image(self, *, ack_timeout: float = 5.0) -> dict:
        if self.state != SessionState.READY:
            raise SessionNotReadyError("session is not ready")
        return self._network_client.send_image_selecting(ack_timeout=ack_timeout)

    def cancel_image_selection(self, *, ack_timeout: float = 5.0) -> dict:
        if self.state != SessionState.READY:
            raise SessionNotReadyError("session is not ready")
        return self._network_client.send_image_selecting_cancel(ack_timeout=ack_timeout)

    def send_image(
        self,
        image_path: str,
        *,
        client_msg_id: str,
        ack_timeout: float = 10.0,
    ) -> dict:
        if self.state != SessionState.READY:
            raise SessionNotReadyError("session is not ready")
        payload = prepare_image_payload(image_path)
        if not payload.get("ok"):
            raise SessionImageError(payload.get("error") or "image encoding failed")
        return self._network_client.send_image(
            image_base64=payload["image_base64"],
            mime_type=payload["mime_type"],
            image_client_path=payload["image_client_path"],
            ack_timeout=ack_timeout,
            client_msg_id=client_msg_id,
        )

    def send_voice(
        self,
        audio_path: str | Path,
        *,
        upload_id: str,
        ack_timeout: float = 10.0,
        retry_budget: float = 15.0,
    ) -> dict:
        """Upload an M4A file through begin/chunk/finalize and return server metadata."""
        if self.state != SessionState.READY:
            raise SessionNotReadyError("session is not ready")
        path = Path(audio_path)
        if path.suffix.lower() != ".m4a":
            raise SessionVoiceError("voice input must be an M4A file")
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise SessionVoiceError(f"voice input could not be read: {exc}") from exc
        if not data or len(data) > self.VOICE_MAX_BYTES:
            raise SessionVoiceError("voice input size must be between 1 byte and 1 MiB")
        total_chunks = math.ceil(len(data) / self.VOICE_CHUNK_BYTES)
        if total_chunks > self.VOICE_MAX_CHUNKS:
            raise SessionVoiceError("voice input exceeds the 32 chunk limit")
        chunks = [
            data[offset : offset + self.VOICE_CHUNK_BYTES]
            for offset in range(0, len(data), self.VOICE_CHUNK_BYTES)
        ]
        deadline = time.monotonic() + max(0.0, retry_budget)

        recording_ack = self._transport.submit_voice_recording_started(upload_id, ack_timeout=min(5.0, ack_timeout))
        if not recording_ack.get("ok"):
            raise SessionVoiceError(recording_ack.get("error") or "voice recording start rejected")

        begin = self._submit_voice_phase(
            "begin",
            upload_id,
            ack_timeout,
            deadline,
            byte_length=len(data),
            total_chunks=total_chunks,
        )
        if not begin.get("ok"):
            raise SessionVoiceError(begin.get("error") or "voice begin rejected")
        self._upload_voice_chunks(chunks, upload_id, ack_timeout, deadline, abort_on_failure=True)
        final = self._finalize_voice_upload(chunks, upload_id, ack_timeout, deadline)
        if not final.get("ok"):
            self._abort_voice_upload(upload_id, ack_timeout)
            raise SessionVoiceError(final.get("error") or "voice finalize rejected")
        message_uuid = final.get("message_uuid")
        duration_ms = final.get("duration_ms")
        if not isinstance(message_uuid, str) or type(duration_ms) is not int:
            raise SessionVoiceError("voice finalize ACK omitted message metadata")
        return {"message_uuid": message_uuid, "duration_ms": duration_ms}

    def _submit_voice_phase(
        self,
        phase: str,
        upload_id: str,
        ack_timeout: float,
        deadline: float,
        **kwargs,
    ) -> dict:
        while True:
            result = self._transport.submit_user_voice(
                phase,
                upload_id,
                ack_timeout=min(ack_timeout, max(0.1, deadline - time.monotonic())),
                **kwargs,
            )
            if phase == "finalize" and result.get("code") == "VOICE_MISSING_CHUNKS":
                return result
            retryable = result.get("retryable", not result.get("drop", False))
            if result.get("ok") or not retryable or time.monotonic() >= deadline:
                return result
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))

    def _upload_voice_chunks(
        self,
        chunks: list[bytes],
        upload_id: str,
        ack_timeout: float,
        deadline: float,
        *,
        abort_on_failure: bool,
    ) -> None:
        for index, chunk in enumerate(chunks):
            ack = self._submit_voice_phase(
                "chunk",
                upload_id,
                ack_timeout,
                deadline,
                chunk_index=index,
                audio_chunk=chunk,
            )
            if ack.get("ok"):
                continue
            if abort_on_failure:
                self._abort_voice_upload(upload_id, ack_timeout)
            suffix = "" if abort_on_failure else " retry"
            raise SessionVoiceError(ack.get("error") or f"voice chunk {index}{suffix} rejected")

    def _finalize_voice_upload(
        self,
        chunks: list[bytes],
        upload_id: str,
        ack_timeout: float,
        deadline: float,
    ) -> dict:
        final = self._submit_voice_phase("finalize", upload_id, ack_timeout, deadline)
        missing_chunks = not final.get("ok") and final.get("code") == "VOICE_MISSING_CHUNKS"
        if not missing_chunks or time.monotonic() >= deadline:
            return final
        self._upload_voice_chunks(chunks, upload_id, ack_timeout, deadline, abort_on_failure=False)
        return self._submit_voice_phase("finalize", upload_id, ack_timeout, deadline)

    def _abort_voice_upload(self, upload_id: str, ack_timeout: float) -> None:
        try:
            self._transport.submit_user_voice("abort", upload_id, ack_timeout=ack_timeout)
        except Exception:
            pass

    def assert_voice_in_history(
        self,
        message_uuid: str,
        duration_ms: int | None = None,
        *,
        count: int = 100,
    ):
        """Return the matching sanitized audio history item or fail the driver."""
        history, _ = self.get_history(count=count, end_index=-1)
        matches = [item for item in history if item.uuid == message_uuid and item.type == "audio"]
        if len(matches) != 1:
            raise AssertionError(f"expected exactly one audio history item for {message_uuid}, got {len(matches)}")
        item = matches[0]
        if item.content != "[语音消息]" or item.audio_available is not True:
            raise AssertionError("audio history metadata is missing or not sanitized")
        if duration_ms is not None and item.duration_ms != duration_ms:
            raise AssertionError(f"audio duration mismatch: expected {duration_ms}, got {item.duration_ms}")
        return item

    def assert_download_sha256(self, message_uuid: str, source_path: str | Path) -> str:
        """Download an owned voice and assert its bytes equal the source digest."""
        expected = hashlib.sha256(Path(source_path).read_bytes()).hexdigest()
        actual = hashlib.sha256(self._network_client.download_audio(message_uuid)).hexdigest()
        if actual != expected:
            raise AssertionError(f"audio SHA-256 mismatch: expected {expected}, got {actual}")
        return actual

    def send_touch(
        self,
        touch_area: str | list,
        click_frequency: dict | None = None,
        touch_meta: dict | None = None,
        *,
        client_msg_id: str | None = None,
        ack_timeout: float = 10.0,
    ) -> dict:
        if self.state != SessionState.READY:
            raise SessionNotReadyError("session is not ready")
        return self._network_client.send_touch(
            touch_area,
            click_frequency=click_frequency,
            touch_meta=touch_meta,
            ack_timeout=ack_timeout,
            client_msg_id=client_msg_id,
        )

    def get_dynamics(self, limit: int = 50, cursor: str | None = None) -> dict:
        if self.state != SessionState.READY:
            raise SessionNotReadyError("session is not ready")
        return self._network_client.get_dynamics(limit=limit, cursor=cursor)

    def get_history(self, count: int = 20, end_index: int = -1) -> tuple[list, int]:
        if self.state != SessionState.READY:
            raise SessionNotReadyError("session is not ready")
        return self._network_client.get_history(count, end_index)

    def get_dynamic_comments(
        self,
        dynamic_id: str,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict:
        if self.state != SessionState.READY:
            raise SessionNotReadyError("session is not ready")
        return self._network_client.get_dynamic_comments(dynamic_id, limit=limit, cursor=cursor)

    def create_dynamic(self, content: str) -> dict:
        if self.state != SessionState.READY:
            raise SessionNotReadyError("session is not ready")
        return self._network_client.create_dynamic(content)

    def mark_dynamics_read(self) -> dict:
        if self.state != SessionState.READY:
            raise SessionNotReadyError("session is not ready")
        return self._network_client.mark_dynamics_read()

    def get_preferences(self) -> dict:
        if self.state != SessionState.READY:
            raise SessionNotReadyError("session is not ready")
        return self._network_client.get_preferences()

    def overwrite_preferences(self, preferences: dict) -> dict:
        if self.state != SessionState.READY:
            raise SessionNotReadyError("session is not ready")
        response = self._network_client.overwrite_preferences(preferences)
        if not isinstance(response, dict):
            return {"ok": False, "error": "invalid preference response"}
        if response.get("ok") is True or response.get("status") == "success":
            return {"ok": True}
        return {
            "ok": False,
            "error": str(response.get("error") or response.get("message") or "server rejected input"),
        }

    def get_reply(self, reply_uuid: str) -> AggregatedReply | None:
        with self._condition:
            reply = self._replies.get(reply_uuid)
            return reply.snapshot() if reply else None

    def read_events(self, after_seq: int = 0, kind: str | None = None) -> list[dict]:
        with self._condition:
            return [
                dict(event)
                for event in self._events
                if event["seq"] > after_seq and (kind is None or event["kind"] == kind)
            ]

    def wait_for_event(
        self,
        kind: str,
        *,
        after_seq: int = 0,
        timeout: float = 30.0,
        value: str | None = None,
        contains: str | None = None,
    ) -> dict:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            while True:
                for event in self._events:
                    if event["seq"] <= after_seq or event["kind"] != kind:
                        continue
                    if value is not None and event["value"] != value:
                        continue
                    if contains is not None and contains not in event["value"]:
                        continue
                    return dict(event)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ReplyTimeoutError(f"no matching {kind} event before timeout")
                self._condition.wait(remaining)

    def wait_for_reply(self, reply_uuid: str, timeout: float) -> AggregatedReply:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            while True:
                if self._state == SessionState.CLOSED:
                    raise SessionClosedError("session is closed")
                reply = self._replies.get(reply_uuid)
                if reply and reply.complete:
                    return reply.snapshot()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ReplyTimeoutError(f"reply {reply_uuid!r} did not complete")
                self._condition.wait(remaining)

    def wait_for_next_reply(self, timeout: float) -> AggregatedReply:
        """等待调用时刻之后第一条新的完整回复（串行场景语义）。"""
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            start_index = len(self._completion_order)
            while True:
                if self._state == SessionState.CLOSED:
                    raise SessionClosedError("session is closed")
                if len(self._completion_order) > start_index:
                    reply_uuid = self._completion_order[start_index]
                    return self._replies[reply_uuid].snapshot()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ReplyTimeoutError("no new complete reply before timeout")
                self._condition.wait(remaining)

    def audio_path_for(self, reply_uuid: str) -> str | None:
        reply = self.get_reply(reply_uuid)
        return reply.audio_path if reply else None

    def _install_transport_listeners(self) -> None:
        setter = getattr(self._network_client, "network_set_message_listener", None)
        if setter is not None:
            setter(
                self._on_agent_message,
                self._on_agent_state,
                self._on_system_message,
            )
            return
        self._transport.set_agent_message_listener(
            self._on_agent_message,
            self._on_agent_state,
            self._on_system_message,
        )

    def _begin_connect(self) -> None:
        if self.state == SessionState.CLOSED:
            raise SessionClosedError("session is closed")
        self._set_state(SessionState.CONNECTING)

    def _wait_until_ready(self, timeout: float) -> None:
        if not self._transport.wait_until_ready(timeout):
            self._set_state(SessionState.DISCONNECTED)
            raise SessionReadyTimeout("WebSocket did not become ready before timeout")
        self._set_state(SessionState.READY)
        getter = getattr(self._network_client, "get_history", None)
        if getter is not None:
            items, start_index = getter(20, -1)
            with self._condition:
                self._initial_history = (list(items), start_index, 1)
            self._publish(SessionEvent("history_loaded", {"count": len(items), "start_index": start_index}))

    def _set_state(self, state: SessionState) -> None:
        with self._condition:
            self._state = state
            self._condition.notify_all()
        self._publish(SessionEvent("state", state))

    def _on_agent_state(self, state: str) -> None:
        self._publish(SessionEvent("agent_state", state))

    def _on_system_message(self, text: str) -> None:
        self._publish(SessionEvent("system_message", text))

    def _on_agent_message(self, message: AgentMessage) -> None:
        self._publish(SessionEvent("agent_message", message))
        if not message.uuid:
            return

        completed = None
        with self._condition:
            reply = self._replies.setdefault(message.uuid, _ReplyBuffer(message.uuid))
            if reply.complete:
                return
            if message.text:
                reply.texts.append(message.text)
            if message.expression:
                reply.expressions.append(message.expression)
            if message.audio:
                try:
                    reply.audio.extend(base64.b64decode(message.audio))
                except Exception:
                    pass
                self._server_audio_active = True
            reply.audio_error = reply.audio_error or message.audio_error
            reply.error_code = message.error_code or reply.error_code
            reply.display_in_chat = reply.display_in_chat and message.display_in_chat
            reply.is_ephemeral = reply.is_ephemeral or message.is_ephemeral

            if is_audio_terminal(message):
                reply.complete = True
                self._completion_order.append(reply.uuid)
                self._server_audio_active = False
                if self._should_save_audio(reply):
                    reply.audio_path = self._save_audio(reply.uuid, bytes(reply.audio))
                completed = reply.snapshot()
                self._condition.notify_all()

        if completed is not None:
            self._publish(SessionEvent("reply_completed", completed))

    @staticmethod
    def _should_save_audio(reply: _ReplyBuffer) -> bool:
        return bool(
            reply.audio
            and not reply.audio_error
            and not reply.is_ephemeral
            and reply.display_in_chat
            and _SAFE_UUID_RE.fullmatch(reply.uuid)
        )

    def _save_audio(self, reply_uuid: str, audio: bytes) -> str | None:
        try:
            self._audio_output_dir.mkdir(parents=True, exist_ok=True)
            path = self._audio_output_dir / f"{reply_uuid}.wav"
            path.write_bytes(audio)
            return str(path)
        except OSError:
            return None

    def _publish(self, event: SessionEvent) -> None:
        with self._condition:
            observed = self._event_record(event)
            if observed is not None:
                self._event_seq += 1
                observed["seq"] = self._event_seq
                observed["timestamp_ms"] = int(time.time() * 1000)
                self._events.append(observed)
                if len(self._events) > 1000:
                    del self._events[:-1000]
                self._condition.notify_all()
            listeners = tuple(self._listeners)
        for listener in listeners:
            try:
                listener(event)
            except Exception:
                pass

    @staticmethod
    def _event_record(event: SessionEvent) -> dict | None:
        if event.kind == "state":
            return {"kind": "state", "value": event.data.value}
        if event.kind in ("agent_state", "system_message"):
            return {"kind": event.kind, "value": str(event.data)}
        if event.kind == "history_loaded":
            return {"kind": event.kind, "value": "loaded", "data": dict(event.data)}
        if event.kind == "reply_completed":
            reply = event.data
            text = "".join(reply.texts)
            return {
                "kind": event.kind,
                "value": text,
                "data": {
                    "reply_uuid": reply.uuid,
                    "text": text,
                    "expressions": list(reply.expressions),
                    "audio_saved": bool(reply.audio_path),
                    "audio_received": reply.audio_byte_count > 0,
                    "audio_byte_count": reply.audio_byte_count,
                    "is_ephemeral": reply.is_ephemeral,
                    "display_in_chat": reply.display_in_chat,
                },
            }
        return None
