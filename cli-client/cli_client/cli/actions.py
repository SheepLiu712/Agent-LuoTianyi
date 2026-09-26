from __future__ import annotations

import os
import re
import time
import uuid
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path
from typing import Callable

from .auth_store import CredentialStoreError, load_login, save_login
from .media import DefaultPlaybackBackend, PlaybackBackend, PlaybackResult, read_wav_format
from .output import Redactor
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
        self._dynamics_state: dict | None = None
        self._preferences_snapshot: dict | None = None
        self.session_id = session_id or f"s-{uuid.uuid4().hex[:12]}"
        self.redactor = Redactor()

    def execute(self, raw: object) -> tuple[dict, ExitCode]:
        started = time.monotonic()
        action = None
        action_id = f"a-{uuid.uuid4().hex[:12]}"
        try:
            action, action_id, params = parse_action(raw)
            data, correlation_id = self._dispatch(action, params)
            return self._record(action_id, action, "passed", data, None, correlation_id, started), ExitCode.SUCCESS
        except _ActionFailure as exc:
            status = "timed_out" if exc.exit_code == ExitCode.TIMEOUT else "failed"
            return (
                self._record(
                    action_id,
                    action,
                    status,
                    exc.data,
                    exc.error,
                    exc.correlation_id,
                    started,
                ),
                exc.exit_code,
            )
        except _Suppressed as exc:
            return (
                self._record(
                    action_id,
                    action,
                    "suppressed",
                    exc.data,
                    None,
                    exc.correlation_id,
                    started,
                ),
                ExitCode.SUCCESS,
            )
        except ValueError as exc:
            return (
                self._failure_record(action_id, action, "INVALID_INPUT", str(exc), "input", started),
                ExitCode.INPUT_ERROR,
            )
        except (ReplyTimeoutError, SessionReadyTimeout) as exc:
            return (
                self._failure_record(
                    action_id,
                    action,
                    "TIMEOUT",
                    str(exc),
                    "timeout",
                    started,
                    status="timed_out",
                ),
                ExitCode.TIMEOUT,
            )
        except (SessionConnectionError, SessionNotReadyError, SessionClosedError) as exc:
            code = "SESSION_NOT_READY" if isinstance(exc, SessionNotReadyError) else "AUTH_OR_TRANSPORT_FAILED"
            return (
                self._failure_record(action_id, action, code, str(exc), "auth_transport", started),
                ExitCode.AUTH_TRANSPORT_ERROR,
            )
        except Exception as exc:
            return (
                self._failure_record(
                    action_id,
                    action,
                    "AUTH_OR_TRANSPORT_FAILED",
                    str(exc),
                    "auth_transport",
                    started,
                ),
                ExitCode.AUTH_TRANSPORT_ERROR,
            )

    def close(self) -> None:
        if self._session is not None:
            self._session.close()

    def _dispatch(self, action: str, params: dict) -> tuple[dict, str | None]:
        handlers = {
            "account.register": self._register,
            "session.connect": self._connect,
            "session.auto_connect": self._auto_connect,
            "session.status": self._status,
            "session.close": self._close,
            "history.initial": self._initial_history,
            "history.load": self._load_history,
            "events.read": self._read_events,
            "events.wait": self._wait_event,
            "chat.send_text": self._send_text,
            "chat.send_typing": self._send_typing,
            "reply.wait": self._wait_reply,
            "reply.read": self._read_reply,
            "audio.replay": self._replay_audio,
            "image.select": self._select_image,
            "image.cancel": self._cancel_image,
            "image.send": self._send_image,
            "touch.send": self._send_touch,
            "dynamics.open": self._open_dynamics,
            "dynamics.read": self._read_dynamic,
            "dynamics.load": self._load_dynamics,
            "dynamics.post": self._post_dynamic,
            "preferences.open": self._open_preferences,
            "preferences.read": self._read_preferences,
            "preferences.update": self._update_preferences,
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

    def _register(self, params: dict) -> tuple[dict, None]:
        base_url = _required_string(params, "base_url")
        username = _required_string(params, "username")
        password = params.get("password")
        if password is None and isinstance(params.get("password_env"), str):
            password = self._environ.get(params["password_env"])
        confirmation = params.get("password_confirm")
        if confirmation is None and isinstance(params.get("password_confirm_env"), str):
            confirmation = self._environ.get(params["password_confirm_env"])
        if not isinstance(password, str) or not password:
            raise ValueError("password or password_env is required")
        self.redactor.add_secret(password)
        if not isinstance(confirmation, str) or not confirmation:
            raise ValueError("password_confirm or password_confirm_env is required")
        self.redactor.add_secret(confirmation)
        if password != confirmation:
            raise _ActionFailure(
                ExitCode.INPUT_ERROR,
                "PASSWORD_MISMATCH",
                "passwords do not match",
                "input",
            )
        invite_code = _required_string(params, "invite_code")
        self.redactor.add_secret(invite_code)
        session = self._session_factory(base_url=base_url, verify_ssl=True)
        try:
            success, message = session.register(username, password, invite_code)
        finally:
            session.close()
        if not success:
            raise _ActionFailure(
                ExitCode.ASSERTION_FAILED,
                "REGISTRATION_FAILED",
                str(message),
                "assertion",
            )
        return {"registered": True, "username": username}, None

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
        remember_login = params.get("remember_login", False)
        if not isinstance(remember_login, bool):
            raise ValueError("remember_login must be a boolean")
        if remember_login:
            self._session.connect(username, password, timeout=timeout, request_token=True)
            token = self._session.login_token
            if not token:
                raise _ActionFailure(
                    ExitCode.AUTH_TRANSPORT_ERROR,
                    "AUTO_LOGIN_TOKEN_MISSING",
                    "server did not issue an auto-login token",
                    "auth_transport",
                )
            self.redactor.add_secret(token)
            try:
                save_login(self._credential_file(params), base_url, username, token)
            except CredentialStoreError as exc:
                raise _ActionFailure(
                    ExitCode.INPUT_ERROR,
                    "CREDENTIAL_STORAGE_UNAVAILABLE",
                    str(exc),
                    "input",
                ) from exc
        else:
            self._session.connect(username, password, timeout=timeout)
        return {"state": self._session.state.value}, None

    def _auto_connect(self, params: dict) -> tuple[dict, None]:
        try:
            base_url, username, token = load_login(self._credential_file(params))
        except CredentialStoreError as exc:
            raise _ActionFailure(
                ExitCode.INPUT_ERROR,
                "SAVED_LOGIN_UNAVAILABLE",
                str(exc),
                "input",
            ) from exc
        self.redactor.add_secret(token)
        self._session = self._session_factory(base_url=base_url, verify_ssl=True)
        self._session.connect_with_token(username, token, timeout=_number(params, "timeout", 10.0))
        replacement = self._session.login_token or token
        self.redactor.add_secret(replacement)
        if replacement != token:
            save_login(self._credential_file(params), base_url, username, replacement)
        return {"state": self._session.state.value, "automatic": True}, None

    @staticmethod
    def _credential_file(params: dict) -> Path:
        raw = params.get("credential_file")
        if raw is None:
            return Path.cwd() / "temp" / "cli_auto_login.json"
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("credential_file must be a non-empty path")
        return Path(raw)

    def _status(self, _params: dict) -> tuple[dict, None]:
        state = self._session.state if self._session else SessionState.NEW
        return {"state": state.value}, None

    def _close(self, _params: dict) -> tuple[dict, None]:
        if self._session:
            self._session.close()
        return {"state": SessionState.CLOSED.value}, None

    def _initial_history(self, _params: dict) -> tuple[dict, None]:
        items, start_index, attempts = self._require_session().initial_history
        return self._history_data(items, start_index, attempts), None

    def _load_history(self, params: dict) -> tuple[dict, None]:
        count = params.get("count", 20)
        end_index = params.get("end_index", -1)
        if type(count) is not int or not 1 <= count <= 200:
            raise ValueError("count must be an integer between 1 and 200")
        if type(end_index) is not int:
            raise ValueError("end_index must be an integer")
        items, start_index = self._require_session().get_history(count, end_index)
        if start_index < 0:
            raise _ActionFailure(
                ExitCode.AUTH_TRANSPORT_ERROR,
                "HISTORY_LOAD_FAILED",
                "history could not be loaded",
                "auth_transport",
            )
        return self._history_data(items, start_index, 1), None

    @staticmethod
    def _history_data(items: list, start_index: int, attempts: int) -> dict:
        return {
            "loaded": start_index >= 0,
            "load_count": attempts,
            "start_index": start_index,
            "items": [
                {
                    "timestamp": item.timestamp,
                    "source": item.source,
                    "type": item.type,
                    "content": item.content,
                    "uuid": item.uuid,
                }
                for item in items
            ],
        }

    def _read_events(self, params: dict) -> tuple[dict, None]:
        after_seq = self._after_seq(params)
        kind = params.get("kind")
        if kind is not None and (not isinstance(kind, str) or not kind):
            raise ValueError("kind must be a non-empty string")
        events = self._require_session().read_events(after_seq=after_seq, kind=kind)
        return {"events": events, "count": len(events)}, None

    def _wait_event(self, params: dict) -> tuple[dict, None]:
        kind = _required_string(params, "kind")
        value = params.get("value")
        contains = params.get("contains")
        if value is not None and not isinstance(value, str):
            raise ValueError("value must be a string")
        if contains is not None and not isinstance(contains, str):
            raise ValueError("contains must be a string")
        event = self._require_session().wait_for_event(
            kind,
            after_seq=self._after_seq(params),
            timeout=_number(params, "timeout", 30.0),
            value=value,
            contains=contains,
        )
        return {"event": event}, None

    @staticmethod
    def _after_seq(params: dict) -> int:
        after_seq = params.get("after_seq", 0)
        if type(after_seq) is not int or after_seq < 0:
            raise ValueError("after_seq must be a non-negative integer")
        return after_seq

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

    def _send_typing(self, params: dict) -> tuple[dict, str]:
        length = params.get("text_length")
        if type(length) is not int or not 0 <= length <= 100_000:
            raise ValueError("text_length must be an integer between 0 and 100000")
        request_id = params.get("client_msg_id") or f"c-{uuid.uuid4().hex[:12]}"
        if not isinstance(request_id, str):
            raise ValueError("client_msg_id must be a string")
        ack = self._require_session().send_typing(
            length,
            client_msg_id=request_id,
            ack_timeout=_number(params, "ack_timeout", 10.0),
        )
        self._ensure_positive_ack(ack, correlation_id=request_id)
        return {"ack": True, "text_length": length}, request_id

    def _wait_reply(self, params: dict) -> tuple[dict, str]:
        session = self._require_session()
        timeout = _number(params, "timeout", 30.0)
        explicit = params.get("reply_uuid")
        if explicit is not None:
            reply_uuid = _required_string(params, "reply_uuid")
            reply = session.wait_for_reply(reply_uuid, timeout)
        else:
            reply = session.wait_for_next_reply(timeout)
            reply_uuid = reply.uuid
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
                ExitCode.TIMEOUT,
                "TIMEOUT",
                message,
                "timeout",
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
        elif (
            isinstance(touch_area, list)
            and touch_area
            and all(isinstance(item, str) and item.strip() for item in touch_area)
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

    def _open_dynamics(self, params: dict) -> tuple[dict, None]:
        session = self._require_session()
        page = session.get_dynamics(limit=_number(params, "limit", 50))
        if page.get("ok") is False:
            raise _ActionFailure(
                ExitCode.AUTH_TRANSPORT_ERROR,
                "DYNAMICS_LOAD_FAILED",
                str(page.get("message") or "dynamic feed could not be loaded"),
                "auth_transport",
            )
        items = list(page.get("items") or [])
        self._dynamics_state = {
            "items": items,
            "cursor": page.get("next_cursor"),
            "has_more": bool(page.get("has_more")),
            "seen": {self._dynamic_key(item) for item in items},
        }
        marked_read = True
        mark_error = None
        try:
            mark = session.mark_dynamics_read()
            if not mark.get("ok"):
                marked_read = False
                mark_error = str(mark.get("error") or "mark read failed")
        except Exception as exc:
            marked_read = False
            mark_error = str(exc)
        return {
            "items": items,
            "count": len(items),
            "has_more": self._dynamics_state["has_more"],
            "marked_read": marked_read,
            "mark_error": mark_error,
        }, None

    def _read_dynamic(self, params: dict) -> tuple[dict, None]:
        session = self._require_session()
        dynamic_id = _required_string(params, "dynamic_id")
        page = session.get_dynamic_comments(dynamic_id, limit=_number(params, "comment_limit", 100))
        if page.get("ok") is False:
            raise _ActionFailure(
                ExitCode.AUTH_TRANSPORT_ERROR,
                "DYNAMICS_READ_FAILED",
                str(page.get("message") or "dynamic comments could not be loaded"),
                "auth_transport",
            )
        comments = list(page.get("items") or [])
        post = None
        if self._dynamics_state is not None:
            for item in self._dynamics_state["items"]:
                if self._dynamic_key(item) == dynamic_id:
                    post = item
                    break
        return {
            "dynamic_id": dynamic_id,
            "post": post,
            "comments": comments,
            "comment_count": len(comments),
        }, None

    def _load_dynamics(self, params: dict) -> tuple[dict, None]:
        session = self._require_session()
        if self._dynamics_state is None:
            raise _ActionFailure(
                ExitCode.INPUT_ERROR,
                "DYNAMICS_NOT_OPENED",
                "dynamics view is not opened",
                "input",
            )
        state = self._dynamics_state
        appended = 0
        if state["has_more"]:
            page = session.get_dynamics(limit=_number(params, "limit", 50), cursor=state["cursor"])
            if page.get("ok") is False:
                raise _ActionFailure(
                    ExitCode.AUTH_TRANSPORT_ERROR,
                    "DYNAMICS_LOAD_FAILED",
                    str(page.get("message") or "dynamic feed could not be loaded"),
                    "auth_transport",
                )
            for item in page.get("items") or []:
                key = self._dynamic_key(item)
                if key in state["seen"]:
                    continue
                state["seen"].add(key)
                state["items"].append(item)
                appended += 1
            state["cursor"] = page.get("next_cursor")
            state["has_more"] = bool(page.get("has_more"))
        return {
            "appended": appended,
            "count": len(state["items"]),
            "has_more": state["has_more"],
            "end_of_feed": not state["has_more"],
            "items": list(state["items"]),
        }, None

    def _post_dynamic(self, params: dict) -> tuple[dict, None]:
        session = self._require_session()
        content = _required_string(params, "content")
        response = session.create_dynamic(content)
        self._ensure_positive_ack(response, correlation_id=None)
        created = response.get("item") if isinstance(response.get("item"), dict) else {}
        dynamic_id = created.get("id") or response.get("dynamic_id") or response.get("id")
        page = session.get_dynamics()
        if page.get("ok") is False:
            raise _ActionFailure(
                ExitCode.AUTH_TRANSPORT_ERROR,
                "DYNAMICS_LOAD_FAILED",
                str(page.get("message") or "created dynamic could not be verified"),
                "auth_transport",
            )
        items = list(page.get("items") or [])
        visible = False
        for item in items:
            if dynamic_id and self._dynamic_key(item) == dynamic_id:
                visible = True
                break
            if not dynamic_id and item.get("content") == content:
                visible = True
                break
        data = {
            "content_length": len(content),
            "preview": content[:80],
            "dynamic_id": dynamic_id,
            "visible": visible,
        }
        if not visible:
            raise _ActionFailure(
                ExitCode.ASSERTION_FAILED,
                "DYNAMICS_NOT_VISIBLE",
                "created dynamic is not visible in the latest feed",
                "assertion",
                data=data,
            )
        return data, None

    @staticmethod
    def _dynamic_key(item: dict) -> str:
        return str(item.get("id") or item.get("dynamic_id") or "")

    def _open_preferences(self, _params: dict) -> tuple[dict, None]:
        session = self._require_session()
        snapshot = dict(session.get_preferences())
        self._preferences_snapshot = snapshot
        return {"preferences": snapshot}, None

    def _read_preferences(self, params: dict) -> tuple[dict, None]:
        if self._preferences_snapshot is None:
            return self._open_preferences(params)
        return {"preferences": dict(self._preferences_snapshot)}, None

    def _update_preferences(self, params: dict) -> tuple[dict, None]:
        session = self._require_session()
        values = params.get("values")
        if not isinstance(values, dict):
            raise ValueError("values must be an object")
        replace = params.get("replace", False)
        if not isinstance(replace, bool):
            raise ValueError("replace must be a boolean")
        if replace:
            payload = dict(values)
        else:
            latest = dict(session.get_preferences())
            payload = {**latest, **values}
        response = session.overwrite_preferences(payload)
        self._ensure_positive_ack(response, correlation_id=None)
        reread = dict(session.get_preferences())
        target_keys = list(values.keys())
        mismatched = [key for key in target_keys if reread.get(key) != values.get(key)]
        if mismatched:
            diff = {key: {"expected": values.get(key), "actual": reread.get(key)} for key in mismatched}
            raise _ActionFailure(
                ExitCode.ASSERTION_FAILED,
                "PREFERENCES_NOT_CONFIRMED",
                "preference update was not confirmed by re-read",
                "assertion",
                data={
                    "updated_keys": target_keys,
                    "mismatched_keys": mismatched,
                    "diff": diff,
                },
            )
        self._preferences_snapshot = reread
        return {
            "updated_keys": target_keys,
            "confirmed": True,
            "preferences": reread,
        }, None

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
            self._replay_failure("AUDIO_FORMAT_INVALID", f"audio file is not a decodable wav: {reply_uuid}", reply_uuid)
        result = self._playback.play(path)
        if result == PlaybackResult.DEVICE_UNAVAILABLE:
            self._replay_failure("DEVICE_UNAVAILABLE", "no available playback device", reply_uuid)
        if result == PlaybackResult.INTERRUPTED:
            self._replay_failure("PLAYBACK_INTERRUPTED", "playback was interrupted", reply_uuid)
        return {
            "reply_uuid": reply.uuid,
            "playback": "completed",
            "audio": self._audio_metadata(reply),
            "audio_received": reply.audio_byte_count > 0,
            "audio_byte_count": reply.audio_byte_count,
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
        eligible = reply.complete and not reply.is_ephemeral and reply.display_in_chat and not reply.audio_error
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
