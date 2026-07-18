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


class CallStreamManager:
    """按用户管理 CallStream，并负责 5 秒重连保留和 5 路并发限制。"""

    def __init__(self, config: Dict[str, Any] | None = None, **kwargs) -> None:
        self.config = config or {}
        self.dependencies = kwargs
        self.logger = get_logger("CallStreamManager")
        self._streams_by_call_id: dict[str, CallStream] = {}
        self._call_id_by_user_id: dict[str, str] = {}
        self._start_tasks: dict[str, asyncio.Task] = {}
        self._start_requests: dict[tuple[str, str], str] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task | None = None

    def wire_dependencies(self, **kwargs) -> None:
        self.dependencies.update(kwargs)
        self.ensure_dependencies()

    def ensure_dependencies(self) -> None:
        if self.config is None:
            raise RuntimeError("CallStreamManager dependency is missing: config")
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
        self.ensure_dependencies()
        user_id = ws_connection.user_uuid
        if not user_id:
            raise CallRejectedError("AUTH_REQUIRED", "call requires authentication", -4)
        async with self._lock:
            if client_request_id:
                previous_call_id = self._start_requests.get((user_id, client_request_id))
                previous_stream = self._streams_by_call_id.get(previous_call_id) if previous_call_id else None
                if previous_stream and previous_stream.state != CallState.ENDED:
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
            await stream.end(CallExitCode.INTERNAL_ERROR, str(exc))

    async def resume_call(self, *, ws_connection, call_id: str) -> CallStream:
        stream = self._streams_by_call_id.get(call_id)
        if stream is None or stream.user_id != ws_connection.user_uuid:
            raise CallRejectedError("CALL_NOT_FOUND", "找不到可恢复的电话", -4)
        if await stream.reconnect(ws_connection):
            return stream
        raise CallRejectedError("CALL_NOT_RESUMABLE", "电话已过期，无法恢复", int(CallExitCode.RECONNECT_TIMEOUT))

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
            stream = self._streams_by_call_id.pop(call_id, None)
            if stream:
                if self._call_id_by_user_id.get(stream.user_id) == call_id:
                    self._call_id_by_user_id.pop(stream.user_id, None)
                for key, value in list(self._start_requests.items()):
                    if value == call_id:
                        self._start_requests.pop(key, None)
            task = self._start_tasks.pop(call_id, None)
            if task and not task.done() and task is not asyncio.current_task():
                task.cancel()

    def start_background_services(self) -> None:
        self.ensure_dependencies()
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(0.5)
            await self.cleanup_expired_streams()

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
            await stream.end(CallExitCode.RECONNECT_TIMEOUT, "reconnect_timeout")
            await self.release(stream.call_id)
        ended = [stream for stream in list(self._streams_by_call_id.values()) if stream.state == CallState.ENDED]
        for stream in ended:
            await self.release(stream.call_id)

    async def stop_background_services(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
        streams = list(self._streams_by_call_id.values())
        for stream in streams:
            if stream.state != CallState.ENDED:
                await stream.end(CallExitCode.INTERNAL_ERROR, "server_shutdown")
        self._streams_by_call_id.clear()
        self._call_id_by_user_id.clear()
        self._start_requests.clear()
        self._start_tasks.clear()
