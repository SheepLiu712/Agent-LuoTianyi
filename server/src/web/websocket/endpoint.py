from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.adapter.websocket.connection import AdapterConnectionError
from src.application.admin import get_admin_shell
from src.utils.logger import get_logger
from src.web.http import runtime_not_ready_detail

from ._adapter_io import _reject_adapter_connection, _serve_adapter
from .service import WebSocketConnection

if TYPE_CHECKING:
    from src.server_runtime import ServerRuntime

logger = get_logger(__name__)
router = APIRouter()


@router.websocket("/chat_ws")
async def chat_ws(websocket: WebSocket) -> None:
    try:
        await websocket.accept()
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected before accept on /chat_ws")
        return

    server_runtime: "ServerRuntime" = get_admin_shell().runtime_supervisor.runtime
    if server_runtime is None:
        await _reject_when_runtime_is_not_ready(websocket)
        return

    logger.info("WebSocket client connected to /chat_ws")
    websocket_service = server_runtime.websocket_service
    stage_manager = getattr(server_runtime, "stage_manager", None)
    try:
        await websocket_service.send_system_ready_event(websocket)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected before system_ready on /chat_ws")
        return

    connection = WebSocketConnection(websocket=websocket, user_uuid=None, user_name=None)
    handle = None
    try:
        authenticated = await connection.auth(
            websocket_service,
            server_runtime.database_manager,
        )
        if not authenticated:
            return
        if stage_manager is None:
            raise RuntimeError("StageManager is required for production chat connections")
        character_id = server_runtime.agent_runtime.default_character_id
        handle = await server_runtime.chat_adapter.open(
            user_id=connection.user_uuid,
            connection_id=object(),
            character_id=character_id,
            capabilities=frozenset(connection.capabilities),
        )
        await _serve_adapter(websocket, server_runtime.chat_adapter, handle)
    except AdapterConnectionError as error:
        await _reject_adapter_connection(websocket, error)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected from /chat_ws")
    except Exception as exc:
        logger.error("Error in /chat_ws: %s", exc)
    finally:
        if handle is not None:
            await server_runtime.chat_adapter.disconnect(handle)


async def _reject_when_runtime_is_not_ready(websocket: WebSocket) -> None:
    try:
        await websocket.send_json(
            {
                "type": "system_not_ready",
                "payload": runtime_not_ready_detail(),
            }
        )
        await websocket.close(code=1013)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected before system_not_ready on /chat_ws")
