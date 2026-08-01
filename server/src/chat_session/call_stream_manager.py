from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Dict

from src.chat_session.call_models import CallExitCode, CallState
from src.chat_session.call_stream import CallStream
from src.utils.logger import get_logger


class CallRejectedError(RuntimeError):
    def __init__(self, code: str, message: str, exit_code: int = -5) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code


def is_call_event_bound(
    stream: CallStream | None,
    ws_connection,
    payload: dict[str, Any] | None,
) -> bool:
    if stream is None or stream.ws_connection is not ws_connection:
        return False
    if payload is not None and not isinstance(payload, dict):
        return False
    payload_call_id = str((payload or {}).get("call_id") or "")
    return not payload_call_id or payload_call_id == stream.call_id


class CallStreamManager:
    """按用户管理 CallStream，并负责 5 秒重连保留和 5 路并发限制。"""

    def __init__(self, config: Dict[str, Any] | None = None, **kwargs) -> None:
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", False))
        self.dependencies = kwargs
        self.logger = get_logger("CallStreamManager")
        self._streams_by_call_id: dict[str, CallStream] = {}
        self._call_id_by_user_id: dict[str, str] = {}
        self._start_tasks: dict[str, asyncio.Task] = {}
        self._start_requests: dict[tuple[str, str], str] = {}
        self._lock = asyncio.Lock()
        self._stop_lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task | None = None
        self._stopping = False
        self._stopped = False

    def wire_dependencies(self, **kwargs) -> None:
        self.dependencies.update(kwargs)
        self.ensure_dependencies()

    def ensure_dependencies(self) -> None:
        if self.config is None:
            raise RuntimeError("CallStreamManager dependency is missing: config")
        if not self.enabled:
            return
        required = (
            "conversation_service",
            "global_speaking_worker",
            "realtime_dialogue_service",
            "agent_runtime",
            "call_store",
        )
        missing = [name for name in required if self.dependencies.get(name) is None]
        if missing:
            raise RuntimeError(f"CallStreamManager dependencies are missing: {', '.join(missing)}")

    async def start_call(
        self,
        *,
        ws_connection,
        character_id: str = "luotianyi",
        client_request_id: str | None = None,
    ) -> CallStream:
        if not self.enabled:
            raise CallRejectedError(
                "CALL_DISABLED",
                "电话功能尚未启用",
                int(CallExitCode.INTERNAL_ERROR),
            )
        self.ensure_dependencies()
        user_id = ws_connection.user_uuid
        if not user_id:
            raise CallRejectedError("AUTH_REQUIRED", "call requires authentication", -4)
        async with self._lock:
            self._reject_if_stopping()
            if client_request_id:
                previous_call_id = self._start_requests.get((user_id, client_request_id))
                previous_stream = self._streams_by_call_id.get(previous_call_id) if previous_call_id else None
                if (
                    previous_stream
                    and previous_stream.state != CallState.ENDED
                    and previous_stream.ws_connection is ws_connection
                ):
                    return previous_stream
            existing_id = self._call_id_by_user_id.get(user_id)
            if existing_id:
                existing = self._streams_by_call_id.get(existing_id)
                if existing and existing.state != CallState.ENDED:
                    raise CallRejectedError("CALL_IN_PROGRESS", "用户正在通话", -5)
                self._call_id_by_user_id.pop(user_id, None)
            active_count = sum(
                stream.state in {CallState.REQUESTING, CallState.ACTIVE, CallState.RECONNECTING}
                for stream in self._streams_by_call_id.values()
            )
            if active_count >= int(self.config.get("max_concurrent_calls", 5)):
                raise CallRejectedError("CALL_CONCURRENCY_LIMIT", "当前电话并发已满", int(CallExitCode.CONCURRENCY_REJECTED))
            call_id = str(uuid.uuid4())
            stream = CallStream(
                call_id=call_id,
                user_id=user_id,
                user_name=ws_connection.user_name or "",
                character_id=character_id,
                ws_connection=ws_connection,
                config=self.config,
                realtime_dialogue_service=self.dependencies["realtime_dialogue_service"],
                conversation_service=self.dependencies["conversation_service"],
                global_speaking_worker=self.dependencies["global_speaking_worker"],
                agent_runtime=self.dependencies["agent_runtime"],
                call_store=self.dependencies["call_store"],
                llm_service=self.dependencies.get("llm_service"),
                observability=self.dependencies.get("observability"),
            )
            self._streams_by_call_id[call_id] = stream
            self._call_id_by_user_id[user_id] = call_id
            if client_request_id:
                self._start_requests[(user_id, client_request_id)] = call_id
            self._start_tasks[call_id] = asyncio.create_task(self._start_stream(stream))
            return stream

    async def _start_stream(self, stream: CallStream) -> None:
        try:
            await stream.start()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.logger.exception("CallStream start failed: call_id=%s", stream.call_id)
            try:
                await stream.end(CallExitCode.INTERNAL_ERROR, str(exc))
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger.exception(
                    "CallStream cleanup after start failure failed: call_id=%s",
                    stream.call_id,
                )

    async def resume_call(self, *, ws_connection, call_id: str) -> CallStream:
        if not self.enabled:
            raise CallRejectedError(
                "CALL_DISABLED",
                "电话功能尚未启用",
                int(CallExitCode.INTERNAL_ERROR),
            )
        async with self._lock:
            self._reject_if_stopping()
            stream = self._streams_by_call_id.get(call_id)
            if stream is None or stream.user_id != ws_connection.user_uuid:
                raise CallRejectedError("CALL_NOT_FOUND", "找不到可恢复的电话", -4)
            if await stream.reconnect(ws_connection):
                return stream
        raise CallRejectedError("CALL_NOT_RESUMABLE", "电话已过期，无法恢复", int(CallExitCode.RECONNECT_TIMEOUT))

    def _reject_if_stopping(self) -> None:
        if self._stopping or self._stopped:
            raise CallRejectedError(
                "CALL_SERVICE_STOPPING",
                "电话服务正在停止",
                int(CallExitCode.INTERNAL_ERROR),
            )

    def get_by_call_id(self, call_id: str) -> CallStream | None:
        return self._streams_by_call_id.get(call_id)

    def get_by_user_id(self, user_id: str) -> CallStream | None:
        call_id = self._call_id_by_user_id.get(user_id)
        return self._streams_by_call_id.get(call_id) if call_id else None

    def has_blocking_call(self, user_id: str | None) -> bool:
        if not user_id:
            return False
        stream = self.get_by_user_id(user_id)
        return bool(stream and stream.is_blocking_chat)

    async def on_ws_lost(self, ws_connection) -> None:
        stream = self.get_by_user_id(ws_connection.user_uuid)
        if stream is None or stream.ws_connection is not ws_connection:
            return
        await stream.lost_connection()

    async def release(self, call_id: str) -> None:
        async with self._lock:
            stream = self._streams_by_call_id.get(call_id)
            task = self._start_tasks.get(call_id)

        if stream is None and task is None:
            return

        timeout = max(
            0.01,
            float(
                self.config.get(
                    "release_timeout_seconds",
                    self.config.get("shutdown_timeout_seconds", 30),
                )
            ),
        )
        end_event = getattr(stream, "_end_event", None)
        if (
            stream is not None
            and stream.state == CallState.ENDED
            and end_event is not None
            and not end_event.is_set()
        ):
            try:
                await asyncio.wait_for(end_event.wait(), timeout=timeout)
            except asyncio.TimeoutError as error:
                raise RuntimeError(
                    "Call stream release failed: end finalization still running"
                ) from error

        ensure_postprocess = getattr(stream, "ensure_postprocess_started", None)
        if ensure_postprocess is not None:
            ensure_postprocess()
        owned_tasks = {
            candidate
            for candidate in (
                task,
                getattr(stream, "_postprocess_task", None),
                *tuple(getattr(stream, "_memory_tasks", ())),
            )
            if candidate is not None and candidate is not asyncio.current_task()
        }
        if (
            task is not None
            and not task.done()
            and task is not asyncio.current_task()
            and getattr(stream, "state", None) != CallState.ENDED
        ):
            task.cancel()
        errors = await self._wait_owned_tasks(
            owned_tasks,
            timeout=timeout,
        )
        if errors:
            raise RuntimeError("Call stream release failed: " + "; ".join(errors))

        async with self._lock:
            stream = self._streams_by_call_id.pop(call_id, None)
            if stream:
                if self._call_id_by_user_id.get(stream.user_id) == call_id:
                    self._call_id_by_user_id.pop(stream.user_id, None)
                for key, value in list(self._start_requests.items()):
                    if value == call_id:
                        self._start_requests.pop(key, None)
            self._start_tasks.pop(call_id, None)

    def start_background_services(self) -> None:
        if not self.enabled:
            return
        self.ensure_dependencies()
        if self._stopping or self._stopped:
            raise RuntimeError("CallStreamManager cannot restart after shutdown")
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(0.5)
            try:
                await self.cleanup_expired_streams()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger.exception("CallStream cleanup iteration failed")

    async def cleanup_expired_streams(self) -> None:
        now = time.monotonic()
        candidates = [
            stream
            for stream in list(self._streams_by_call_id.values())
            if stream.state == CallState.RECONNECTING
            and stream._reconnect_deadline is not None
            and stream._reconnect_deadline <= now
        ]
        for stream in candidates:
            try:
                expired = await stream.end_if_reconnect_expired(now)
            except Exception:
                self.logger.warning(
                    "CallStream reconnect settlement retry deferred: call_id=%s",
                    stream.call_id,
                    exc_info=True,
                )
                continue
            if not expired:
                continue
            try:
                await self.release(stream.call_id)
            except RuntimeError:
                self.logger.warning(
                    "CallStream release deferred: call_id=%s",
                    stream.call_id,
                    exc_info=True,
                )
        ending = [
            stream
            for stream in list(self._streams_by_call_id.values())
            if stream.state == CallState.ENDING
        ]
        for stream in ending:
            try:
                await stream.end(
                    stream.exit_code or int(CallExitCode.INTERNAL_ERROR),
                    "settlement_retry",
                )
            except Exception:
                self.logger.warning(
                    "CallStream settlement retry deferred: call_id=%s",
                    stream.call_id,
                    exc_info=True,
                )
        ended = [stream for stream in list(self._streams_by_call_id.values()) if stream.state == CallState.ENDED]
        for stream in ended:
            try:
                await self.release(stream.call_id)
            except RuntimeError:
                self.logger.warning(
                    "CallStream release deferred: call_id=%s",
                    stream.call_id,
                    exc_info=True,
                )

    async def stop_background_services(self) -> None:
        async with self._stop_lock:
            async with self._lock:
                if self._stopped:
                    return
                self._stopping = True
            errors: list[str] = []

            cleanup_task = self._cleanup_task
            if cleanup_task is not None:
                if not cleanup_task.done():
                    cleanup_task.cancel()
                try:
                    await cleanup_task
                except asyncio.CancelledError:
                    self._cleanup_task = None
                except Exception as error:
                    errors.append(f"cleanup: {type(error).__name__}: {error}")
                    self._cleanup_task = None
                else:
                    self._cleanup_task = None

            streams = list(self._streams_by_call_id.values())
            for stream in streams:
                try:
                    await stream.end(CallExitCode.INTERNAL_ERROR, "server_shutdown")
                except Exception as error:
                    errors.append(
                        f"call {stream.call_id}: {type(error).__name__}: {error}"
                    )

            timeout = max(
                0.01,
                float(self.config.get("shutdown_timeout_seconds", 30)),
            )
            owned_tasks = {
                task
                for task in self._start_tasks.values()
                if task is not None
            }
            for stream in streams:
                ensure_postprocess = getattr(stream, "ensure_postprocess_started", None)
                if ensure_postprocess is not None:
                    ensure_postprocess()
                postprocess_task = getattr(stream, "_postprocess_task", None)
                if postprocess_task is not None:
                    owned_tasks.add(postprocess_task)
                owned_tasks.update(getattr(stream, "_memory_tasks", ()))
            errors.extend(await self._wait_owned_tasks(owned_tasks, timeout=timeout))

            if errors:
                raise RuntimeError("Call stream shutdown failed: " + "; ".join(errors))

            self._streams_by_call_id.clear()
            self._call_id_by_user_id.clear()
            self._start_requests.clear()
            self._start_tasks.clear()
            self._stopped = True

    @staticmethod
    async def _wait_owned_tasks(
        tasks: set[asyncio.Task],
        *,
        timeout: float,
    ) -> list[str]:
        if not tasks:
            return []
        done, pending = await asyncio.wait(tasks, timeout=timeout)
        errors: list[str] = []
        for task in done:
            try:
                task.result()
            except asyncio.CancelledError:
                pass
            except Exception as error:
                errors.append(f"owned task: {type(error).__name__}: {error}")
        if pending:
            errors.append(f"{len(pending)} call task(s) still running")
        return errors
