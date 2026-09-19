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
from ..session import (
    AggregatedReply,
    HeadlessSession,
    ReplyTimeoutError,
    SessionClosedError,
    SessionConnectionError,
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
    ) -> None:
        self._session_factory = session_factory
        self._environ = os.environ if environ is None else environ
        self._session: HeadlessSession | None = None
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
        if not ack.get("ok"):
            message = str(ack.get("error") or "server rejected input")
            if "timeout" in message.lower():
                raise _ActionFailure(
                    ExitCode.TIMEOUT, "TIMEOUT", message, "timeout",
                    correlation_id=request_id,
                )
            raise _ActionFailure(
                ExitCode.ASSERTION_FAILED,
                "ACK_REJECTED",
                message,
                "assertion",
                correlation_id=request_id,
            )
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
        path = Path(reply.audio_path) if reply.audio_path else None
        byte_count = path.stat().st_size if path and path.exists() else 0
        return {
            "reply_uuid": reply.uuid,
            "text": text,
            "texts": list(reply.texts),
            "expressions": list(reply.expressions),
            "complete": reply.complete,
            "audio": {
                "available": bool(path and byte_count),
                "byte_count": byte_count,
                "format": path.suffix.lstrip(".") or None if path else None,
                "reference": path.name if path else None,
            },
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
