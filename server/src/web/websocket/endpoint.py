from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.adapter.websocket import ChatEventAcceptance, EventRejection, VoiceUploadAck
from src.application.admin import get_admin_shell
from src.stage import InteractionFinalizing
from src.stage.stage_manager import InteractionOwnedByCallAdmission
from src.utils.logger import get_logger
from src.web.http import runtime_not_ready_detail

from .messages import WSEventType, WSMessage
from .service import WebSocketConnection, WebSocketService

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
        stage = await server_runtime.chat_adapter.open(connection, character_id)
        await websocket_service.send_chat_ready_event(
            connection,
            character_id=character_id,
            interaction_id=stage.interaction_id,
        )
        await _receive_events(server_runtime, connection)
    except (InteractionFinalizing, InteractionOwnedByCallAdmission) as error:
        await _reject_call_owned_chat_admission(websocket_service, connection, code=str(error))
    except WebSocketDisconnect:
        server_runtime.client_llm_executor.clear_user(connection.user_uuid, connection)
        logger.info("WebSocket client disconnected from /chat_ws")
    except Exception as exc:
        server_runtime.client_llm_executor.clear_user(connection.user_uuid, connection)
        logger.error("Error in /chat_ws: %s", exc)
    finally:
        if stage_manager is not None:
            await server_runtime.chat_adapter.close_connection(connection)


async def _reject_call_owned_chat_admission(
    websocket_service: WebSocketService, connection: WebSocketConnection, *, code: str = "INTERACTION_OWNED_BY_CALL"
) -> None:
    """Return a typed retryable admission error without fabricating chat readiness."""
    try:
        await websocket_service.send_error_event(
            connection.websocket,
            {
                "code": code,
                "message": "interaction is temporarily unavailable",
                "retryable": True,
            },
        )
        await connection.websocket.close(code=1013)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected while reporting call-owned chat admission")


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


async def _receive_events(server_runtime: "ServerRuntime", connection: WebSocketConnection) -> None:
    websocket_service = server_runtime.websocket_service
    while True:
        event = await websocket_service.try_recv_client_msg(connection)
        if event is None:
            continue
        if await _handle_transport_event(server_runtime, connection, event):
            continue
        result = await server_runtime.chat_adapter.receive(connection, event)
        if result is ChatEventAcceptance.UNSUPPORTED:
            continue
        if isinstance(result, VoiceUploadAck):
            await websocket_service.send_ack_event(
                connection, event, payload=result.payload, duplicate=result.duplicate
            )
        elif isinstance(result, dict):
            await connection.websocket.send_json(result)
        elif not await _handle_rejected_event(websocket_service, connection, event, result):
            await websocket_service.send_ack_event(connection, event)


async def _handle_transport_event(
    server_runtime: "ServerRuntime",
    connection: WebSocketConnection,
    event: WSMessage,
) -> bool:
    websocket_service = server_runtime.websocket_service
    if event.event_type == WSEventType.HB_PING.value:
        await websocket_service.handle_ping_event(connection, event)
        return True
    if event.event_type == WSEventType.LLM_RESPONSE.value:
        server_runtime.client_llm_executor.on_llm_response(event.payload)
        return True
    if event.event_type in (WSEventType.USER_TEXT.value, WSEventType.USER_IMAGE.value):
        _update_client_model_types(connection, event.payload)
    return False


def _update_client_model_types(connection: WebSocketConnection, raw_payload: object) -> None:
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    llm_mode = payload.get("llm_mode")
    if not isinstance(llm_mode, dict):
        return
    raw_types = llm_mode.get("types")
    if isinstance(raw_types, list):
        connection.client_mode = {
            "types": [
                str(model_type).strip()
                for model_type in raw_types
                if isinstance(model_type, str) and model_type.strip()
            ]
        }
    elif isinstance(raw_types, str) and raw_types.strip():
        connection.client_mode = {"types": [raw_types.strip()]}


async def _handle_rejected_event(
    websocket_service: WebSocketService,
    connection: WebSocketConnection,
    event: WSMessage,
    acceptance: ChatEventAcceptance | EventRejection,
) -> bool:
    if isinstance(acceptance, EventRejection):
        await websocket_service.send_nack_event(
            connection,
            event,
            code=acceptance.code,
            message=acceptance.message,
            retryable=acceptance.retryable,
        )
        return True
    rejections: dict[ChatEventAcceptance, tuple[str, str, bool] | None] = {
        ChatEventAcceptance.DUPLICATE: None,
        ChatEventAcceptance.BAD_MESSAGE: ("BAD_MESSAGE", "chat event payload is invalid", False),
        ChatEventAcceptance.UNSUPPORTED: ("UNSUPPORTED_EVENT", "chat event type is not supported", False),
        ChatEventAcceptance.OVERLOADED: ("OVERLOADED", "chat ingress queue is full", True),
    }
    if acceptance not in rejections:
        return False
    rejection = rejections[acceptance]
    if rejection is None:
        await websocket_service.send_duplicate_ack_event(connection, event)
        return True
    code, message, retryable = rejection
    await websocket_service.send_nack_event(
        connection,
        event,
        code=code,
        message=message,
        retryable=retryable,
    )
    return True
