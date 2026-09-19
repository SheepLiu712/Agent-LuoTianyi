from __future__ import annotations

import base64
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

from ..network.event_types import AgentMessage, is_audio_terminal
from ..network.network_client import NetworkClient


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
        )


class HeadlessSession:
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
        self._audio_output_dir = Path(
            audio_output_dir or Path.cwd() / "temp" / "tts_output"
        )
        self._condition = threading.Condition(threading.RLock())
        self._state = SessionState.NEW
        self._listeners: list[Callable[[SessionEvent], None]] = []
        self._replies: dict[str, _ReplyBuffer] = {}
        self._install_transport_listeners()

    @property
    def state(self) -> SessionState:
        with self._condition:
            state = self._state
        if state == SessionState.READY and not self._transport.is_ready():
            return SessionState.DISCONNECTED
        return state

    def connect(
        self,
        username: str,
        password: str,
        *,
        timeout: float = 10.0,
    ) -> None:
        self._begin_connect()
        success, message = self._network_client.login(
            username,
            password,
            request_token=False,
        )
        if not success:
            self._set_state(SessionState.AUTH_FAILED)
            safe_message = (message or "login failed").replace(password, "***")
            raise SessionConnectionError(safe_message)
        self._wait_until_ready(timeout)

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

    def get_reply(self, reply_uuid: str) -> AggregatedReply | None:
        with self._condition:
            reply = self._replies.get(reply_uuid)
            return reply.snapshot() if reply else None

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
            reply.audio_error = reply.audio_error or message.audio_error
            reply.error_code = message.error_code or reply.error_code
            reply.display_in_chat = reply.display_in_chat and message.display_in_chat
            reply.is_ephemeral = reply.is_ephemeral or message.is_ephemeral

            if is_audio_terminal(message):
                reply.complete = True
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
            listeners = tuple(self._listeners)
        for listener in listeners:
            try:
                listener(event)
            except Exception:
                pass
