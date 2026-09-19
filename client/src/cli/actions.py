from __future__ import annotations

import os
import re
import time
import uuid
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path
from typing import Callable

from .output import Redactor
from .media import DefaultPlaybackBackend, PlaybackBackend, PlaybackResult, read_wav_format
from ..utils import image_rules
from ..session import (
    AggregatedReply,
    HeadlessSession,
    ReplyTimeoutError,
    SessionClosedError,
    SessionConnectionError,
    SessionImageError,
    SessionNotReadyError,
    SessionReadyTimeout,
    SessionState,
)


class ExitCode(IntEnum):
    SUCCESS = 0
    ASSERTION_FAILED = 2
    INPUT_ERROR = 3
    AUTH_TRANSPORT_ERROR = 4
    TIMEOUT = 5


def parse_action(raw: object) -> tuple[str, str, dict]:
    if not isinstance(raw, dict):
        raise ValueError("action input must be an object")
    action = raw.get("action")
    if not isinstance(action, str) or not action.strip():
        raise ValueError("action must be a non-empty string")
    params = raw.get("params", {})
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    action_id = raw.get("action_id") or f"a-{uuid.uuid4().hex[:12]}"
    if not isinstance(action_id, str):
        raise ValueError("action_id must be a string")
    return action.strip(), action_id, params


class ActionExecutor:
    def __init__(
        self,
        *,
        session_factory: Callable[..., HeadlessSession] = HeadlessSession,
        environ: dict[str, str] | None = None,
        session_id: str | None = None,
        playback_backend: PlaybackBackend | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._environ = os.environ if environ is None else environ
        self._session: HeadlessSession | None = None
        self._playback = playback_backend or DefaultPlaybackBackend()
        self._image_selection: dict | None = None
        self.session_id = session_id or f"s-{uuid.uuid4().hex[:12]}"
        self.redactor = Redactor()

    def execute(self, raw: object) -> tuple[dict, ExitCode]:
        started = time.monotonic()
        action = None
        action_id = f"a-{uuid.uuid4().hex[:12]}"
        try:
            action, action_id, params = parse_action(raw)
            data, correlation_id = self._dispatch(action, params)
            return self._record(
                action_id, action, "passed", data, None, correlation_id, started
            ), ExitCode.SUCCESS
        except _ActionFailure as exc:
            status = "timed_out" if exc.exit_code == ExitCode.TIMEOUT else "failed"
            return self._record(
                action_id,
                action,
                status,
                exc.data,
                exc.error,
                exc.correlation_id,
                started,
            ), exc.exit_code
        except _Suppressed as exc:
            return self._record(
                action_id,
                action,
                "suppressed",
                exc.data,
                None,
                exc.correlation_id,
                started,
            ), ExitCode.SUCCESS
        except ValueError as exc:
            return self._failure_record(
                action_id, action, "INVALID_INPUT", str(exc), "input", started
            ), ExitCode.INPUT_ERROR
        except (ReplyTimeoutError, SessionReadyTimeout) as exc:
            return self._failure_record(
                action_id, action, "TIMEOUT", str(exc), "timeout", started,
                status="timed_out",
            ), ExitCode.TIMEOUT
        except (SessionConnectionError, SessionNotReadyError, SessionClosedError) as exc:
            code = "SESSION_NOT_READY" if isinstance(exc, SessionNotReadyError) else "AUTH_OR_TRANSPORT_FAILED"
            return self._failure_record(
                action_id, action, code, str(exc), "auth_transport", started
            ), ExitCode.AUTH_TRANSPORT_ERROR
        except Exception as exc:
            return self._failure_record(
                action_id,
                action,
                "AUTH_OR_TRANSPORT_FAILED",
                str(exc),
                "auth_transport",
                started,
            ), ExitCode.AUTH_TRANSPORT_ERROR

    def close(self) -> None:
        if self._session is not None:
            self._session.close()

    def _dispatch(self, action: str, params: dict) -> tuple[dict, str | None]:
        handlers = {
            "session.connect": self._connect,
            "session.status": self._status,
            "session.close": self._close,
            "chat.send_text": self._send_text,
            "reply.wait": self._wait_reply,
            "reply.read": self._read_reply,
            "audio.replay": self._replay_audio,
            "image.select": self._select_image,
            "image.cancel": self._cancel_image,
            "image.send": self._send_image,
            "touch.send": self._send_touch,
        }
        handler = handlers.get(action)
        if handler is None:
            raise _ActionFailure(
                ExitCode.INPUT_ERROR,
                "UNKNOWN_ACTION",
                f"unknown action: {action}",
                "input",
            )
        return handler(params)

    def _connect(self, params: dict) -> tuple[dict, None]:
        base_url = _required_string(params, "base_url")
        username = _required_string(params, "username")
        password = params.get("password")
        password_env = params.get("password_env")
        if password is None and isinstance(password_env, str):
            password = self._environ.get(password_env)
        if not isinstance(password, str) or not password:
            raise ValueError("password or password_env is required")
        self.redactor.add_secret(password)
        verify_ssl = params.get("verify_ssl", True)
        if not isinstance(verify_ssl, bool):
            raise ValueError("verify_ssl must be a boolean")
        timeout = _number(params, "timeout", 10.0)
        self._session = self._session_factory(
            base_url=base_url,
            verify_ssl=verify_ssl,
        )
        self._session.connect(username, password, timeout=timeout)
        return {"state": self._session.state.value}, None

    def _status(self, _params: dict) -> tuple[dict, None]:
        state = self._session.state if self._session else SessionState.NEW
        return {"state": state.value}, None

    def _close(self, _params: dict) -> tuple[dict, None]:
        if self._session:
            self._session.close()
        return {"state": SessionState.CLOSED.value}, None

    def _send_text(self, params: dict) -> tuple[dict, str]:
        session = self._require_session()
        text = _required_string(params, "text")
        request_id = params.get("client_msg_id") or f"c-{uuid.uuid4().hex[:12]}"
        if not isinstance(request_id, str):
            raise ValueError("client_msg_id must be a string")
        ack = session.send_text(
            text,
            client_msg_id=request_id,
            ack_timeout=_number(params, "ack_timeout", 10.0),
        )
        self._ensure_positive_ack(ack, correlation_id=request_id)
        return {"ack": True}, request_id

    def _wait_reply(self, params: dict) -> tuple[dict, str]:
        reply_uuid = _required_string(params, "reply_uuid")
        reply = self._require_session().wait_for_reply(
            reply_uuid,
            _number(params, "timeout", 30.0),
        )
        return self._reply_result(reply, params), reply_uuid

    def _read_reply(self, params: dict) -> tuple[dict, str]:
        reply_uuid = _required_string(params, "reply_uuid")
        reply = self._require_session().get_reply(reply_uuid)
        if reply is None or not reply.complete:
            raise _ActionFailure(
                ExitCode.ASSERTION_FAILED,
                "REPLY_NOT_FOUND",
                f"complete reply not found: {reply_uuid}",
                "assertion",
                correlation_id=reply_uuid,
            )
        return self._reply_result(reply, params), reply_uuid

    def _ensure_positive_ack(self, ack: dict, *, correlation_id: str | None) -> None:
        if ack.get("ok"):
            return
        message = str(ack.get("error") or "server rejected input")
        if "timeout" in message.lower():
            raise _ActionFailure(
                ExitCode.TIMEOUT, "TIMEOUT", message, "timeout",
                correlation_id=correlation_id,
            )
        raise _ActionFailure(
            ExitCode.ASSERTION_FAILED,
            "ACK_REJECTED",
            message,
            "assertion",
            correlation_id=correlation_id,
        )

    def _select_image(self, params: dict) -> tuple[dict, None]:
        session = self._require_session()
        path_str = _required_string(params, "path")
        ack = session.select_image(ack_timeout=_number(params, "ack_timeout", 5.0))
        self._image_selection = None
        self._ensure_positive_ack(ack, correlation_id=None)
        path = self._validate_image_path(path_str)
        self._image_selection = {
            "path": str(path),
            "mime_type": image_rules.detect_image_mime(str(path)),
            "byte_count": path.stat().st_size,
        }
        return {
            "selected": True,
            "reference": path.name,
            "mime_type": self._image_selection["mime_type"],
            "byte_count": self._image_selection["byte_count"],
        }, None

    def _cancel_image(self, params: dict) -> tuple[dict, None]:
        session = self._require_session()
        ack = session.cancel_image_selection(ack_timeout=_number(params, "ack_timeout", 5.0))
        self._ensure_positive_ack(ack, correlation_id=None)
        self._image_selection = None
        return {"selected": False}, None

    def _send_image(self, params: dict) -> tuple[dict, str]:
        session = self._require_session()
        explicit = params.get("path")
        if explicit is not None:
            path = self._validate_image_path(_required_string(params, "path"))
        elif self._image_selection is not None:
            path = Path(self._image_selection["path"])
        else:
            raise _ActionFailure(
                ExitCode.INPUT_ERROR,
                "IMAGE_NOT_SELECTED",
                "no image selected and no explicit path provided",
                "input",
            )
        request_id = params.get("client_msg_id") or f"c-{uuid.uuid4().hex[:12]}"
        if not isinstance(request_id, str):
            raise ValueError("client_msg_id must be a string")
        try:
            ack = session.send_image(
                str(path),
                client_msg_id=request_id,
                ack_timeout=_number(params, "ack_timeout", 10.0),
            )
        except SessionImageError as exc:
            raise _ActionFailure(
                ExitCode.INPUT_ERROR,
                "IMAGE_FILE_UNREADABLE",
                str(exc),
                "input",
            ) from exc
        self._ensure_positive_ack(ack, correlation_id=request_id)
        return {"ack": True}, request_id

    def _validate_image_path(self, path_str: str) -> Path:
        path = Path(path_str)
        if not path.is_file():
            raise _ActionFailure(
                ExitCode.INPUT_ERROR,
                "IMAGE_FILE_NOT_FOUND",
                f"image file not found: {path.name}",
                "input",
            )
        if path.stat().st_size == 0:
            raise _ActionFailure(
                ExitCode.INPUT_ERROR,
                "IMAGE_FILE_EMPTY",
                f"image file is empty: {path.name}",
                "input",
            )
        mime_type = image_rules.detect_image_mime(str(path))
        if mime_type is None or mime_type not in image_rules.ALLOWED_IMAGE_MIME_TYPES:
            raise _ActionFailure(
                ExitCode.INPUT_ERROR,
                "IMAGE_TYPE_UNSUPPORTED",
                f"unsupported image type: {path.name}",
                "input",
            )
        if path.stat().st_size > image_rules.MAX_IMAGE_BYTES:
            raise _ActionFailure(
                ExitCode.INPUT_ERROR,
                "IMAGE_TOO_LARGE",
                f"image file too large: {path.name}",
                "input",
            )
        return path

    def _send_touch(self, params: dict) -> tuple[dict, str]:
        session = self._require_session()
        touch_area = params.get("touch_area")
        if isinstance(touch_area, str):
            if not touch_area.strip():
                raise ValueError("touch_area must be a non-empty string or a non-empty list of strings")
        elif isinstance(touch_area, list) and touch_area and all(
            isinstance(item, str) and item.strip() for item in touch_area
        ):
            pass
        else:
            raise ValueError("touch_area must be a non-empty string or a non-empty list of strings")
        click_frequency = params.get("click_frequency")
        if click_frequency is not None and not isinstance(click_frequency, dict):
            raise ValueError("click_frequency must be an object")
        touch_meta = params.get("touch_meta")
        if touch_meta is not None and not isinstance(touch_meta, dict):
            raise ValueError("touch_meta must be an object")
        if session.is_server_audio_active:
            raise _Suppressed({"suppressed": True, "reason": "server_audio_active"})
        request_id = params.get("client_msg_id") or f"c-{uuid.uuid4().hex[:12]}"
        if not isinstance(request_id, str):
            raise ValueError("client_msg_id must be a string")
        ack = session.send_touch(
            touch_area,
            click_frequency=click_frequency,
            touch_meta=touch_meta,
            client_msg_id=request_id,
            ack_timeout=_number(params, "ack_timeout", 10.0),
        )
        self._ensure_positive_ack(ack, correlation_id=request_id)
        return {"ack": True}, request_id

    def _replay_audio(self, params: dict) -> tuple[dict, str]:
        reply_uuid = _required_string(params, "reply_uuid")
        session = self._require_session()
        reply = session.get_reply(reply_uuid)
        if reply is None:
            self._replay_failure("AUDIO_REPLY_NOT_FOUND", f"reply not found: {reply_uuid}", reply_uuid)
        if not reply.complete:
            self._replay_failure("AUDIO_NOT_READY", f"reply is not complete: {reply_uuid}", reply_uuid)
        if reply.is_ephemeral or not reply.display_in_chat:
            self._replay_failure("AUDIO_EPHEMERAL", f"reply is ephemeral: {reply_uuid}", reply_uuid)
        if reply.audio_error:
            self._replay_failure("AUDIO_STREAM_FAILED", f"reply audio stream failed: {reply_uuid}", reply_uuid)
        path = Path(reply.audio_path) if reply.audio_path else None
        if path is None or not path.exists() or path.stat().st_size == 0:
            self._replay_failure("AUDIO_FILE_MISSING", f"audio file missing: {reply_uuid}", reply_uuid)
        if read_wav_format(path) is None:
            self._replay_failure(
                "AUDIO_FORMAT_INVALID", f"audio file is not a decodable wav: {reply_uuid}", reply_uuid
            )
        result = self._playback.play(path)
        if result == PlaybackResult.DEVICE_UNAVAILABLE:
            self._replay_failure("DEVICE_UNAVAILABLE", "no available playback device", reply_uuid)
        if result == PlaybackResult.INTERRUPTED:
            self._replay_failure("PLAYBACK_INTERRUPTED", "playback was interrupted", reply_uuid)
        return {
            "reply_uuid": reply.uuid,
            "playback": "completed",
            "audio": self._audio_metadata(reply),
        }, reply_uuid

    def _replay_failure(self, code: str, message: str, reply_uuid: str) -> None:
        raise _ActionFailure(
            ExitCode.ASSERTION_FAILED,
            code,
            message,
            "assertion",
            correlation_id=reply_uuid,
        )

    def _audio_metadata(self, reply: AggregatedReply) -> dict:
        empty = {"available": False, "byte_count": 0, "format": None, "reference": None}
        path = Path(reply.audio_path) if reply.audio_path else None
        if path is None:
            return dict(empty)
        if not path.exists() or path.stat().st_size == 0:
            return dict(empty)
        byte_count = path.stat().st_size
        audio_format = read_wav_format(path)
        eligible = (
            reply.complete
            and not reply.is_ephemeral
            and reply.display_in_chat
            and not reply.audio_error
        )
        if not eligible or audio_format is None:
            return {
                "available": False,
                "byte_count": byte_count,
                "format": audio_format,
                "reference": None,
            }
        return {
            "available": True,
            "byte_count": byte_count,
            "format": audio_format,
            "reference": path.name,
        }

    def _reply_result(self, reply: AggregatedReply, params: dict) -> dict:
        text = "".join(reply.texts)
        failure = None
        if params.get("non_empty") is True and not text:
            failure = "reply text is empty"
        contains = params.get("contains")
        if contains is not None:
            if not isinstance(contains, str):
                raise ValueError("contains must be a string")
            if contains not in text:
                failure = f"reply text does not contain {contains!r}"
        pattern = params.get("regex")
        if pattern is not None:
            if not isinstance(pattern, str):
                raise ValueError("regex must be a string")
            try:
                matched = re.search(pattern, text)
            except re.error as exc:
                raise ValueError(f"invalid regex: {exc}") from exc
            if not matched:
                failure = f"reply text does not match {pattern!r}"
        if failure:
            raise _ActionFailure(
                ExitCode.ASSERTION_FAILED,
                "ASSERTION_FAILED",
                failure,
                "assertion",
                correlation_id=reply.uuid,
            )
        return {
            "reply_uuid": reply.uuid,
            "text": text,
            "texts": list(reply.texts),
            "expressions": list(reply.expressions),
            "complete": reply.complete,
            "audio": self._audio_metadata(reply),
            "audio_error": reply.audio_error,
            "error_code": reply.error_code,
            "display_in_chat": reply.display_in_chat,
            "is_ephemeral": reply.is_ephemeral,
        }

    def _require_session(self) -> HeadlessSession:
        if self._session is None:
            raise SessionNotReadyError("session is not ready")
        return self._session

    def _failure_record(self, action_id, action, code, message, category, started, *, status="failed"):
        return self._record(
            action_id,
            action,
            status,
            {},
            {"code": code, "message": message, "category": category},
            None,
            started,
        )

    def _record(self, action_id, action, status, data, error, correlation_id, started):
        return {
            "schema_version": "1.0",
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "session_id": self.session_id,
            "action_id": action_id,
            "action": action,
            "event": "action_result",
            "status": status,
            "duration_ms": max(0, int((time.monotonic() - started) * 1000)),
            "correlation_id": correlation_id,
            "data": data,
            "error": error,
        }


class _ActionFailure(Exception):
    def __init__(self, exit_code, code, message, category, *, data=None, correlation_id=None):
        super().__init__(message)
        self.exit_code = exit_code
        self.error = {"code": code, "message": message, "category": category}
        self.data = data or {}
        self.correlation_id = correlation_id


class _Suppressed(Exception):
    def __init__(self, data, *, correlation_id=None):
        super().__init__("suppressed")
        self.data = data
        self.correlation_id = correlation_id


def _required_string(params: dict, key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _number(params: dict, key: str, default: float) -> float:
    value = params.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{key} must be a non-negative number")
    return float(value)
