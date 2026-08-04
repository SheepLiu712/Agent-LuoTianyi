from collections import OrderedDict
from enum import Enum
from typing import TYPE_CHECKING, Dict
import time
from fastapi import WebSocket, WebSocketDisconnect
import asyncio
from src.system.user_interface.types import WSEventType, WSMessage
from src.domain.stimulus import Stimulus
from src.legacy.chat_input_adapter import (
    is_chat_related_ws_message,
    stimulus_to_chat_input_event,
    validate_ws_chat_message,
    ws_message_to_stimulus,
)
from src.domain.chat import ChatInputEvent
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.chat_session.chat_pipeline.chat_stream import ChatStream
    from src.system.database.database_service import DatabaseManager


NEGATIVE_ACK_CAPABILITY = "negative_ack_v1"


class ChatEventAcceptance(str, Enum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    BAD_MESSAGE = "bad_message"
    UNSUPPORTED = "unsupported"
    OVERLOADED = "overloaded"


class WebSocketService:
    def __init__(self):
        self.logger = get_logger(__name__)
        self._recent_client_messages: OrderedDict[str, float] = OrderedDict()
        self._recent_client_msg_ttl_seconds = 600.0
        self._recent_client_msg_limit = 4096

    async def try_recv_client_msg(self, websocket_connection: "WebSocketConnection") -> WSMessage | None:
        '''
        尝试接收一条WebSocket消息并解析为JSON对象。
        如果解析失败，返回None。
        '''
        websocket = websocket_connection.websocket
        try:
            event = await websocket.receive_json()
        except WebSocketDisconnect:
            raise
        except Exception:
            await self.send_error_event(
                websocket=websocket,
                payload={
                    "code": "BAD_JSON",
                    "message": "message must be a JSON object",
                    }
                )
            return None

        if not isinstance(event, dict):
            await self.send_error_event(
                websocket=websocket,
                payload={
                    "code": "BAD_MESSAGE",
                    "message": "message must be a JSON object",
                    },
                )
            return None
        
        if "type" not in event:
            await self.send_error_event(
                    websocket=websocket,
                    payload={
                        "code": "BAD_MESSAGE",
                        "message": "message must have a 'type' field",
                    },
                )
            return None
        return WSMessage(
            event_type=event.get("type"),
            payload=event.get("payload", {}),
            client_msg_id=event.get("client_msg_id"),
            ts=event.get("ts"),
        )
    
    async def handle_auth_event(
        self,
        ws_connection: "WebSocketConnection",
        database: "DatabaseManager",
        event: WSMessage,
    ) -> bool:
        websocket = ws_connection.websocket
        payload = event.payload if isinstance(event.payload, dict) else {}
        username = payload.get("username", "")
        token = payload.get("token", "")
        if not username or not token:
            await websocket.send_json(
                self._make_event(
                    WSEventType.AUTH_ERROR,
                    {
                        "code": "MISSING_AUTH_FIELDS",
                        "message": "username and token are required in auth payload",
                    },
                    reply_to=event.client_msg_id,
                )
            )
            return False

        is_valid, user_uuid = database.check_message_token(username, token)

        if not is_valid:
            await websocket.send_json(
                self._make_event(
                    WSEventType.AUTH_ERROR,
                    {
                        "code": "INVALID_TOKEN",
                        "message": "invalid or expired message token",
                    },
                    reply_to=event.client_msg_id,
                )
            )
            return False

        authed_user_uuid = user_uuid
        authed_username = username
        raw_capabilities = payload.get("capabilities", [])
        negotiated_capabilities = (
            {NEGATIVE_ACK_CAPABILITY}
            if isinstance(raw_capabilities, list)
            and NEGATIVE_ACK_CAPABILITY in raw_capabilities[:32]
            else set()
        )
        ws_connection.capabilities = negotiated_capabilities
        await websocket.send_json(
            self._make_event(
                WSEventType.AUTH_OK,
                {
                    "message": "authentication successful for user " + authed_username,
                    "capabilities": sorted(negotiated_capabilities),
                },
                reply_to=event.client_msg_id,
            )
        )
        ws_connection.set_user(authed_user_uuid, authed_username)
        return True
    
    async def handle_ping_event(self, ws_connection: "WebSocketConnection", event: WSMessage) -> None:
        websocket = ws_connection.websocket
        payload = event.payload if isinstance(event.payload, dict) else {}
        event_ping_id = payload.get("ping_id")
        if event_ping_id is None:
            await self.send_error_event(
                websocket=websocket,
                payload={
                    "code": "MISSING_PING_ID",
                    "message": "ping event must have a ping_id in payload",
                },)
            return
        
        if ws_connection.last_ping_id is None or ws_connection.last_ping_id < event_ping_id:
            ws_connection.last_ping_id = event_ping_id
            ws_connection.last_ping_time = int(time.time() * 1000)
            await websocket.send_json(
                self._make_event(
                    WSEventType.HB_PONG,
                    {"ping_id": event_ping_id,"server_ts": ws_connection.last_ping_time},
                    reply_to=event.client_msg_id,
                )
            )
            

    async def send_system_ready_event(self, websocket: WebSocket) -> None:
        '''
        发送系统就绪事件，提示客户端进行认证
        '''
        event =  self._make_event(WSEventType.SYSTEM_READY, {
            "message": "WebSocket connected. Please send auth first.",
            "require_auth_before_chat": True
        })
        await websocket.send_json(event)

    async def send_error_event(self, websocket: WebSocket, payload: Dict) -> None:
        event = self._make_event(
            WSEventType.SERVER_ERROR,
            payload
        )
        await websocket.send_json(event)

    async def send_agent_state_event(self, websocket: WebSocket, state: str) -> None:
        event = self._make_event(
            WSEventType.AGENT_STATE_CHANGED,
            {"state": state},
        )
        await websocket.send_json(event)

    async def send_ack_event(self, websocket_connection: "WebSocketConnection", event: WSMessage) -> None:
        if event.client_msg_id is None:
            self.logger.warning("Received event without client_msg_id, cannot send ACK")
            return
        ack_event = self._make_event(
            WSEventType.SERVER_ACK,
            {
                "ok": True,
                "received_event_type": event.event_type,
            },
            reply_to=event.client_msg_id,
        )
        await websocket_connection.websocket.send_json(ack_event)

    async def send_nack_event(
        self,
        websocket_connection: "WebSocketConnection",
        event: WSMessage,
        *,
        code: str,
        message: str,
        retryable: bool,
    ) -> None:
        """Report that a client event was not accepted for processing."""
        supports_negative_ack = (
            NEGATIVE_ACK_CAPABILITY in websocket_connection.capabilities
        )
        payload = {
            "received_event_type": event.event_type,
            "code": code,
            "message": message,
            "retryable": retryable,
        }
        if supports_negative_ack:
            payload["ok"] = False
        nack_event = self._make_event(
            WSEventType.SERVER_ACK if supports_negative_ack else WSEventType.SERVER_ERROR,
            payload,
            reply_to=event.client_msg_id,
        )
        await websocket_connection.websocket.send_json(nack_event)

    async def send_duplicate_ack_event(self, websocket_connection: "WebSocketConnection", event: WSMessage) -> None:
        """对重复客户端消息返回 ACK，但不让上游再次处理同一条业务消息。"""
        if event.client_msg_id is None:
            self.logger.warning("Received duplicate event without client_msg_id, cannot send ACK")
            return
        ack_event = self._make_event(
            WSEventType.SERVER_ACK,
            {
                "ok": True,
                "received_event_type": event.event_type,
                "duplicate": True,
            },
            reply_to=event.client_msg_id,
        )
        await websocket_connection.websocket.send_json(ack_event)

    def is_duplicate_client_message(self, websocket_connection: "WebSocketConnection", event: WSMessage) -> bool:
        """Check recent accepted messages without marking a new event as accepted."""
        key = self._client_message_key(websocket_connection, event)
        if key is None:
            return False

        now = time.monotonic()
        self._prune_recent_client_messages(now)
        return key in self._recent_client_messages

    def mark_client_message_accepted(
        self,
        websocket_connection: "WebSocketConnection",
        event: WSMessage,
    ) -> bool:
        """Record idempotency only after the ingress queue accepted the event."""
        key = self._client_message_key(websocket_connection, event)
        if key is None:
            return False
        now = time.monotonic()
        self._prune_recent_client_messages(now)
        self._recent_client_messages[key] = now
        self._recent_client_messages.move_to_end(key)
        while len(self._recent_client_messages) > self._recent_client_msg_limit:
            self._recent_client_messages.popitem(last=False)
        return True

    def has_valid_client_message_id(self, event: WSMessage) -> bool:
        return (
            isinstance(event.client_msg_id, str)
            and 0 < len(event.client_msg_id) <= 128
        )

    def _client_message_key(
        self,
        websocket_connection: "WebSocketConnection",
        event: WSMessage,
    ) -> str | None:
        if not self.has_valid_client_message_id(event):
            return None
        owner = websocket_connection.user_uuid or websocket_connection.user_name or "anonymous"
        return f"{owner}:{event.client_msg_id}"

    def _prune_recent_client_messages(self, now: float) -> None:
        expired_before = now - self._recent_client_msg_ttl_seconds
        while self._recent_client_messages:
            _, accepted_at = next(iter(self._recent_client_messages.items()))
            if accepted_at >= expired_before:
                break
            self._recent_client_messages.popitem(last=False)

    def is_chat_related_event(self, event: WSMessage) -> bool:
        return is_chat_related_ws_message(event)

    def try_accept_chat_event(
        self,
        websocket_connection: "WebSocketConnection",
        event: WSMessage,
        chat_stream: "ChatStream",
    ) -> ChatEventAcceptance:
        """Convert and enqueue atomically with respect to event-loop tasks."""
        if not self.has_valid_client_message_id(event):
            return ChatEventAcceptance.BAD_MESSAGE
        try:
            validate_ws_chat_message(event)
            chat_event = self.convert_to_chat_input_event(
                event,
                sender_user_id=websocket_connection.user_uuid,
                default_character_id=getattr(chat_stream, "character_id", None) or "luotianyi",
            )
            self._validate_chat_event_targets(chat_stream, chat_event)
        except (KeyError, TypeError, ValueError):
            return ChatEventAcceptance.BAD_MESSAGE
        if chat_event is None:
            return ChatEventAcceptance.UNSUPPORTED
        if self.is_duplicate_client_message(websocket_connection, event):
            return ChatEventAcceptance.DUPLICATE
        if not chat_stream.try_feed_event(chat_event):
            return ChatEventAcceptance.OVERLOADED
        self.mark_client_message_accepted(websocket_connection, event)
        return ChatEventAcceptance.ACCEPTED

    @staticmethod
    def _validate_chat_event_targets(
        chat_stream: "ChatStream",
        chat_event: ChatInputEvent | None,
    ) -> None:
        if chat_event is None:
            return
        payload = chat_event.payload or {}
        raw_targets = payload.get("target_character_ids")
        targets = (raw_targets,) if isinstance(raw_targets, str) else tuple(raw_targets or ())
        system_runtime = getattr(chat_stream, "system_runtime", None)
        agent_runtime = getattr(system_runtime, "agent_runtime", None)
        registry = getattr(agent_runtime, "character_registry", None)
        if registry is not None:
            registry.resolve_targets(targets)

    def convert_to_stimulus(
        self,
        event: WSMessage,
        sender_user_id: str | None = None,
        default_character_id: str = "luotianyi",
    ) -> Stimulus | None:
        return ws_message_to_stimulus(
            event,
            sender_user_id=sender_user_id,
            default_character_id=default_character_id,
        )

    def convert_to_chat_input_event(
        self,
        event: WSMessage,
        sender_user_id: str | None = None,
        default_character_id: str = "luotianyi",
    ) -> ChatInputEvent | None:
        stimulus = self.convert_to_stimulus(
            event,
            sender_user_id=sender_user_id,
            default_character_id=default_character_id,
        )
        if stimulus is None:
            return None
        return stimulus_to_chat_input_event(stimulus)

    def _make_event(self, event_type: WSEventType, payload: Dict, reply_to: str = None) -> Dict:
        event = {
            "type": event_type.value,
            "ts": int(time.time() * 1000),
            "payload": payload,
        }
        if reply_to:
            event["reply_to"] = reply_to
        return event



class WebSocketConnection:
    AUTH_TIMEOUT_SECONDS = 15.0
    AUTH_MAX_ATTEMPTS = 5

    def __init__(self, websocket: WebSocket, user_uuid: str | None, user_name: str | None):
        self.websocket = websocket
        self.user_uuid = user_uuid
        self.user_name = user_name
        self.last_ping_id: int | None = None
        self.last_ping_time: int | None = None
        self.client_llm_enabled: bool = False
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
        '''
        进行认证流程，成功返回True，失败返回False
        '''
        timeout = max(0.001, float(timeout_seconds or self.AUTH_TIMEOUT_SECONDS))
        attempt_limit = max(1, int(max_attempts or self.AUTH_MAX_ATTEMPTS))
        deadline = asyncio.get_running_loop().time() + timeout

        for _ in range(attempt_limit):
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                await self._reject_auth(websocket_service, "AUTH_TIMEOUT", "authentication timed out")
                return False
            try:
                client_event: WSMessage | None = await asyncio.wait_for(
                    websocket_service.try_recv_client_msg(self),
                    timeout=remaining,
                )
            except asyncio.TimeoutError:
                await self._reject_auth(websocket_service, "AUTH_TIMEOUT", "authentication timed out")
                return False
            if client_event is None:
                continue
            if client_event.event_type == WSEventType.USER_AUTH.value:
                ret = await websocket_service.handle_auth_event(self, database, client_event)
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
                    WSEventType.AUTH_ERROR,
                    {"code": code, "message": message},
                )
            )
        except Exception:
            pass
        try:
            await self.websocket.close(code=1008)
        except Exception:
            pass
