"""Authenticated physical ``call_ws`` hosting for an already registered call.

New-call ownership, ledger creation and CallStage construction intentionally do
not happen here.  Until those later bindings exist, the endpoint rejects calls
without consuming transition intent or creating business state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.adapter.websocket.call_v1 import (
    CallTransportBinding,
    CallTransportError,
    CallTransportHub,
    CallWireOutput,
    ControlProtocolError,
    decode_control_text,
)
from src.application.admin import get_admin_shell
from src.utils.logger import get_logger

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
    if runtime is None:
        await websocket.close(code=1013, reason="runtime not ready")
        return
    if not runtime.call_transport_available or runtime.call_transport_hub is None:
        await websocket.close(code=1013, reason="call transport unavailable")
        return
    connection = WebSocketConnection(websocket=websocket, user_uuid=None, user_name=None)
    binding: CallTransportBinding | None = None
    try:
        binding = await _authenticate_and_attach(websocket, runtime, connection)
        if binding is not None:
            await _receive_call_frames(websocket, runtime.call_transport_hub, binding)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected from /call_ws")
    except CallTransportError as error:
        await _close_protocol_error(websocket, error)
    except Exception as error:  # noqa: BLE001 - physical connection boundary normalizes unexpected failures
        logger.error("Error in /call_ws: %s", error)
        await websocket.close(code=1011, reason="internal call transport error")
    finally:
        if binding is not None:
            await runtime.call_transport_hub.detach(binding)


async def _authenticate_and_attach(
    websocket: WebSocket,
    runtime: "ServerRuntime",
    connection: WebSocketConnection,
) -> CallTransportBinding | None:
    await runtime.websocket_service.send_system_ready_event(websocket)
    authenticated = await connection.auth(runtime.websocket_service, runtime.database_manager)
    if not authenticated:
        return None
    first = await websocket.receive()
    if first.get("type") == "websocket.disconnect":
        return None
    raw = first.get("text")
    if not isinstance(raw, str):
        await websocket.close(code=1002, reason="call.resume text frame required")
        return None
    binding = await runtime.call_transport_hub.attach_resume(
        raw,
        user_id=connection.user_uuid or "",
        connection_id=connection,
    )
    _require_current(runtime.call_transport_hub, binding)
    await _send_bound_outputs(websocket, runtime.call_transport_hub, binding, await binding.session.receive_text(raw))
    return binding


async def _receive_call_frames(
    websocket: WebSocket,
    hub: CallTransportHub,
    binding: CallTransportBinding,
) -> None:
    while True:
        _require_current(hub, binding)
        event = await websocket.receive()
        if event.get("type") == "websocket.disconnect":
            return
        text = event.get("text")
        binary = event.get("bytes")
        if isinstance(text, str):
            outputs = await _receive_bound_text(hub, binding, text)
        elif isinstance(binary, bytes):
            outputs = await binding.session.receive_binary(binary)
        else:
            raise CallTransportError("INVALID_WEBSOCKET_FRAME")
        _require_current(hub, binding)
        await _send_bound_outputs(websocket, hub, binding, outputs)


async def _receive_bound_text(
    hub: CallTransportHub,
    binding: CallTransportBinding,
    raw: str,
) -> list[CallWireOutput]:
    try:
        message = decode_control_text(raw, sender="client", transport="call_ws")
    except ControlProtocolError as error:
        raise CallTransportError(error.code) from error
    if message["type"] == "ack":
        hub.acknowledge_bound(binding, int(message["ack_seq"]))
        return []
    return await binding.session.receive_text(raw)


def _require_current(hub: CallTransportHub, binding: CallTransportBinding) -> None:
    if not hub.is_current(binding):
        raise CallTransportError("STALE_CALL_CONNECTION", close_code=1008)


async def _send_bound_outputs(
    websocket: WebSocket,
    hub: CallTransportHub,
    binding: CallTransportBinding,
    outputs: list[CallWireOutput],
) -> None:
    for output in outputs:
        _require_current(hub, binding)
        if output.text is not None:
            await websocket.send_text(output.text)
        else:
            await websocket.send_bytes(output.binary or b"")


async def _close_protocol_error(websocket: WebSocket, error: CallTransportError) -> None:
    try:
        await websocket.close(code=error.close_code, reason=error.code[:123])
    except WebSocketDisconnect:
        pass
