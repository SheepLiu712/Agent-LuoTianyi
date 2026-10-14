"""Authenticated physical ``call_ws`` ingress delegated to CallWebSocketAdapter."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.adapter.websocket.call_v1 import CallTransportError
from src.application.admin import get_admin_shell
from src.utils.logger import get_logger

from .service import WebSocketConnection

if TYPE_CHECKING:
    from src.adapter.websocket.call_v1 import CallConnection, CallWebSocketAdapter
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
    tasks: tuple[asyncio.Task, ...] = ()
    try:
        call = await _authenticate_and_open(websocket, runtime, adapter, connection)
        if call is None:
            return
        send_task = asyncio.create_task(_send_pump(websocket, adapter, call), name="call-ws-send")
        receive_task = asyncio.create_task(_receive_pump(websocket, adapter, call), name="call-ws-receive")
        tasks = (send_task, receive_task)
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected from /call_ws")
    except CallTransportError as error:
        logger.warning("Call WebSocket protocol failure code=%s", error.code)
        if hasattr(error, "request_id"):
            await websocket.send_text(_call_start_error(error))
        await _close_protocol_error(websocket, error)
    except Exception as error:  # noqa: BLE001 - physical connection boundary normalizes unexpected failures
        logger.error("Call WebSocket failed type=%s", type(error).__name__)
        await websocket.close(code=1011, reason="internal call transport error")
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if call is not None:
            await adapter.disconnect(call)


async def _authenticate_and_open(websocket, runtime, adapter, connection):
    await runtime.websocket_service.send_system_ready_event(websocket)
    if not await connection.auth(runtime.websocket_service, runtime.database_manager):
        return None
    first = await websocket.receive()
    if first.get("type") == "websocket.disconnect":
        return None
    raw = first.get("text")
    if not isinstance(raw, str):
        raise CallTransportError("CALL_START_REQUIRED", close_code=1002)
    return await adapter.open(raw=raw, user_id=connection.user_uuid or "", connection_id=connection)


async def _send_pump(websocket: WebSocket, adapter: "CallWebSocketAdapter", call: "CallConnection") -> None:
    while True:
        output = await adapter.next_output(call)
        if output.text is not None:
            await websocket.send_text(output.text)
        else:
            await websocket.send_bytes(output.binary or b"")


async def _receive_pump(websocket: WebSocket, adapter: "CallWebSocketAdapter", call: "CallConnection") -> None:
    while True:
        event = await websocket.receive()
        if event.get("type") == "websocket.disconnect":
            return
        text, binary = event.get("text"), event.get("bytes")
        if isinstance(text, str):
            await adapter.receive_text(call, text)
        elif isinstance(binary, bytes):
            await adapter.receive_binary(call, binary)
        else:
            raise CallTransportError("INVALID_WEBSOCKET_FRAME")


async def _close_protocol_error(websocket: WebSocket, error: CallTransportError) -> None:
    try:
        await websocket.close(code=error.close_code, reason=error.code[:123])
    except WebSocketDisconnect:
        pass


def _call_start_error(error: CallTransportError) -> str:
    from src.adapter.websocket.call_v1 import encode_control_message

    return encode_control_message(
        {
            "protocol": "call.v1",
            "type": "error",
            "code": error.code,
            "message": "call start was not accepted",
            "retryable": error.retryable,
            "request_type": "call.start",
            "request_seq": error.request_seq,
            "client_request_id": error.request_id,
            **({} if error.call_id is None else {"call_id": error.call_id}),
        },
        sender="server",
        transport="call_ws",
    )
