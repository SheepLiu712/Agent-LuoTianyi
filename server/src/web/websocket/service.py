import asyncio
import json
import time
from typing import TYPE_CHECKING, Any

from fastapi import WebSocket, WebSocketDisconnect

if TYPE_CHECKING:
    from src.infrastructure.persistence.database.database_service import DatabaseManager


_NEGATIVE_ACK_CAPABILITY = "negative_ack_v1"


class WebSocketService:
    """Shared pre-admission authentication; business protocol handling belongs to the adapters."""

    def __init__(
        self,
        *,
        max_inbound_frame_bytes: int = 128 * 1024,
    ):
        if type(max_inbound_frame_bytes) is not int or max_inbound_frame_bytes <= 0:
            raise ValueError("max_inbound_frame_bytes must be a positive integer")
        self.max_inbound_frame_bytes = max_inbound_frame_bytes

    async def _receive_auth_message(self, websocket_connection: "WebSocketConnection") -> dict[str, Any] | None:
        """
        仅在鉴权阶段读取 JSON 消息；鉴权后由 Adapter 接收原始消息。
        如果解析失败，返回None。
        """
        websocket = websocket_connection.websocket
        try:
            event = await websocket.receive_json()
        except WebSocketDisconnect:
            raise
        except Exception:
            await self._send_error_event(
                websocket=websocket,
                payload={
                    "code": "BAD_JSON",
                    "message": "message must be a JSON object",
                },
            )
            return None

        if not isinstance(event, dict):
            await self._send_error_event(
                websocket=websocket,
                payload={
                    "code": "BAD_MESSAGE",
                    "message": "message must be a JSON object",
                },
            )
            return None
        encoded_size = len(json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        limit = self.max_inbound_frame_bytes
        if encoded_size > limit:
            await self._send_error_event(
                websocket, {"code": "BAD_MESSAGE", "message": "message exceeds the inbound frame limit"}
            )
            return None

        if "type" not in event:
            await self._send_error_event(
                websocket=websocket,
                payload={
                    "code": "BAD_MESSAGE",
                    "message": "message must have a 'type' field",
                },
            )
            return None
        return event

    async def _authenticate_message(
        self,
        ws_connection: "WebSocketConnection",
        database: "DatabaseManager",
        event: dict[str, Any],
    ) -> bool:
        websocket = ws_connection.websocket
        payload = event.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        username = payload.get("username", "")
        token = payload.get("token", "")
        if not username or not token:
            await websocket.send_json(
                self._make_event(
                    "auth_error",
                    {
                        "code": "MISSING_AUTH_FIELDS",
                        "message": "username and token are required in auth payload",
                    },
                    reply_to=event.get("client_msg_id"),
                )
            )
            return False

        is_valid, user_uuid = database.credential_service.check_message_token(username, token)

        if not is_valid:
            await websocket.send_json(
                self._make_event(
                    "auth_error",
                    {
                        "code": "INVALID_TOKEN",
                        "message": "invalid or expired message token",
                    },
                    reply_to=event.get("client_msg_id"),
                )
            )
            return False

        authed_user_uuid = user_uuid
        authed_username = username
        raw_capabilities = payload.get("capabilities", [])
        negotiated_capabilities = (
            {_NEGATIVE_ACK_CAPABILITY}
            if isinstance(raw_capabilities, list) and _NEGATIVE_ACK_CAPABILITY in raw_capabilities[:32]
            else set()
        )
        ws_connection.capabilities = negotiated_capabilities
        await websocket.send_json(
            self._make_event(
                "auth_ok",
                {
                    "message": "authentication successful for user " + authed_username,
                    "capabilities": sorted(negotiated_capabilities),
                },
                reply_to=event.get("client_msg_id"),
            )
        )
        ws_connection.set_user(authed_user_uuid, authed_username)
        return True

    async def send_system_ready_event(self, websocket: WebSocket) -> None:
        """
        发送系统就绪事件，提示客户端进行认证
        """
        event = self._make_event(
            "system_ready",
            {"message": "WebSocket connected. Please send auth first.", "require_auth_before_chat": True},
        )
        await websocket.send_json(event)

    async def _send_error_event(self, websocket: WebSocket, payload: dict) -> None:
        event = self._make_event("error", payload)
        await websocket.send_json(event)

    def _make_event(self, event_type: str, payload: dict, reply_to: str | None = None) -> dict:
        event = {
            "type": event_type,
            "ts": int(time.time() * 1000),
            "payload": payload,
        }
        if reply_to:
            event["reply_to"] = reply_to
        return event


class WebSocketConnection:
    """Authentication state for one socket; no Stage binding or business delivery state."""

    AUTH_TIMEOUT_SECONDS = 15.0
    AUTH_MAX_ATTEMPTS = 5

    def __init__(self, websocket: WebSocket, user_uuid: str | None, user_name: str | None):
        self.websocket = websocket
        self.user_uuid = user_uuid
        self.user_name = user_name
        self.capabilities: set[str] = set()

    def set_user(self, user_uuid: str, user_name: str):
        self.user_uuid = user_uuid
        self.user_name = user_name

    async def auth(
        self,
        websocket_service: "WebSocketService",
        database: "DatabaseManager",
        *,
        timeout_seconds: float | None = None,
        max_attempts: int | None = None,
    ) -> bool:
        """
        进行认证流程，成功返回True，失败返回False
        """
        timeout = max(0.001, float(timeout_seconds or self.AUTH_TIMEOUT_SECONDS))
        attempt_limit = max(1, int(max_attempts or self.AUTH_MAX_ATTEMPTS))
        deadline = asyncio.get_running_loop().time() + timeout

        for _ in range(attempt_limit):
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                await self._reject_auth(websocket_service, "AUTH_TIMEOUT", "authentication timed out")
                return False
            try:
                client_event: dict[str, Any] | None = await asyncio.wait_for(
                    websocket_service._receive_auth_message(self),
                    timeout=remaining,
                )
            except asyncio.TimeoutError:
                await self._reject_auth(websocket_service, "AUTH_TIMEOUT", "authentication timed out")
                return False
            if client_event is None:
                continue
            if client_event.get("type") == "user_auth":
                ret = await websocket_service._authenticate_message(self, database, client_event)
                if ret:
                    return True

        await self._reject_auth(
            websocket_service,
            "AUTH_ATTEMPTS_EXCEEDED",
            "too many authentication attempts",
        )
        return False

    async def _reject_auth(
        self,
        websocket_service: "WebSocketService",
        code: str,
        message: str,
    ) -> None:
        try:
            await self.websocket.send_json(
                websocket_service._make_event(
                    "auth_error",
                    {"code": code, "message": message},
                )
            )
        except Exception:
            pass
        try:
            await self.websocket.close(code=1008)
        except Exception:
            pass
