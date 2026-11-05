"""Authenticated physical ``call_ws`` ingress delegated to CallWebSocketAdapter."""

from __future__ import annotations

from traceback import walk_tb
from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.adapter.websocket.call_v1 import CallTransportError
from src.application.admin import get_admin_shell
from src.utils.logger import get_logger

from ._adapter_io import _receive_message, _reject_adapter_connection, _serve_adapter
from .service import WebSocketConnection

if TYPE_CHECKING:
    from src.server_runtime import ServerRuntime

logger = get_logger(__name__)
router = APIRouter()


@router.websocket("/call_ws")
async def call_ws(websocket: WebSocket) -> None:
    try:
        await websocket.accept()
    except WebSocketDisconnect:
        return
    runtime: "ServerRuntime | None" = get_admin_shell().runtime_supervisor.runtime
    adapter = None if runtime is None else getattr(runtime, "call_adapter", None)
    if runtime is None or adapter is None or not adapter.capability_status.available:
        await websocket.close(code=1013, reason="call transport unavailable")
        return
    await _serve_call(websocket, runtime, adapter)


async def _serve_call(websocket, runtime, adapter) -> None:
    connection = WebSocketConnection(websocket=websocket, user_uuid=None, user_name=None)
    call = None
    try:
        call = await _authenticate_and_open(websocket, runtime, adapter, connection)
        if call is None:
            return
        await _serve_adapter(websocket, adapter, call)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected from /call_ws")
    except CallTransportError as error:
        logger.warning("Call WebSocket protocol failure code=%s", error.code)
        if error.__cause__ is not None:
            _log_failure_locations(error)
        await _reject_adapter_connection(websocket, error)
    except Exception as error:  # noqa: BLE001 - physical connection boundary normalizes unexpected failures
        _log_failure_locations(error)
        await websocket.close(code=1011, reason="internal call transport error")
    finally:
        if call is not None:
            await adapter.disconnect(call)


def _log_failure_locations(error: BaseException) -> None:
    """记录异常链的类型和位置，不输出可能包含凭据的异常正文或源码。"""
    seen: set[int] = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        locations = [
            (frame.f_code.co_filename, line, frame.f_code.co_name) for frame, line in walk_tb(error.__traceback__)
        ]
        logger.error("Call WebSocket failure type=%s stack=%s", type(error).__name__, locations)
        error = error.__cause__ or (None if error.__suppress_context__ else error.__context__)


async def _authenticate_and_open(websocket, runtime, adapter, connection):
    await runtime.websocket_service.send_system_ready_event(websocket)
    if not await connection.auth(runtime.websocket_service, runtime.database_manager):
        return None
    raw = await _receive_message(websocket)
    return await adapter.open(initial_message=raw, user_id=connection.user_uuid or "", connection_id=object())
