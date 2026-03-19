from typing import Dict, Tuple
import time
from fastapi import WebSocket, WebSocketDisconnect
import asyncio
from sqlalchemy.orm import Session
from ..database.sql_database import get_sql_session
from .types import WSEventType, WSMessage
from ..agent.chat_events import ChatInputEvent, ChatInputEventType
from .account import check_message_token


class WebSocketService:
    def __init__(self):
        pass

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
            client_msg_id=event.get("client_msg_id")
        )
    
    async def handle_auth_event(self, ws_connection: "WebSocketConnection", db: Session, event: WSMessage) -> bool:
        websocket = ws_connection.websocket
        username = event.payload.get("username", "")
        token = event.payload.get("token", "")
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

        is_valid, user_uuid = check_message_token(db, username, token)

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
        await websocket.send_json(
            self._make_event(
                WSEventType.AUTH_OK,
                {"message": "authentication successful for user " + authed_username},
                reply_to=event.client_msg_id,
            )
        )
        ws_connection.set_user(authed_user_uuid, authed_username)
        return True
    
    async def handle_ping_event(self, ws_connection: "WebSocketConnection", event: WSMessage) -> None:
        websocket = ws_connection.websocket
        event_ping_id = event.payload.get("ping_id")
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

    def is_chat_related_event(self, event: WSMessage) -> bool:
        return event.event_type in {
            WSEventType.USER_MESSAGE.value,
            WSEventType.USER_TEXT.value,
            WSEventType.USER_IMAGE.value,
            WSEventType.USER_TYPING.value,
            "message",
            "chat_message",
            "chat",
        }

    def convert_to_chat_input_event(self, event: WSMessage) -> ChatInputEvent | None:
        if not self.is_chat_related_event(event):
            return None

        if event.event_type == WSEventType.USER_TYPING.value:
            return ChatInputEvent(
                event_type=ChatInputEventType.USER_TYPING,
                payload=event.payload if isinstance(event.payload, dict) else {},
                client_msg_id=event.client_msg_id,
                ts=event.ts,
            )

        payload = event.payload if isinstance(event.payload, dict) else {}
        if event.event_type == WSEventType.USER_IMAGE.value:
            return ChatInputEvent(
                event_type=ChatInputEventType.USER_IMAGE,
                image_hint="[用户发送了一张图片]",
                payload=payload,
                client_msg_id=event.client_msg_id,
                ts=event.ts,
            )

        text = ""
        for key in ("message", "text", "content"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                text = value.strip()
                break

        return ChatInputEvent(
            event_type=ChatInputEventType.USER_TEXT,
            text=text,
            payload=payload,
            client_msg_id=event.client_msg_id,
            ts=event.ts,
        )

    def _make_event(self, event_type: WSEventType, payload: Dict, reply_to: str = None) -> Dict:
        event = {
            "type": event_type.value,
            "ts": int(time.time() * 1000),
            "payload": payload,
        }
        if reply_to:
            event["reply_to"] = reply_to
        return event

    

_websocket_service = None
def get_websocket_service() -> WebSocketService:
    global _websocket_service
    if _websocket_service is None:
        _websocket_service = WebSocketService()
    return _websocket_service


class WebSocketConnection:
    def __init__(self, websocket: WebSocket, user_uuid: str | None, user_name: str | None):
        self.websocket = websocket
        self.user_uuid = user_uuid
        self.user_name = user_name
        self.last_ping_id: int | None = None
        self.last_ping_time: int | None = None

    def set_user(self, user_uuid: str, user_name: str):
        self.user_uuid = user_uuid
        self.user_name = user_name
        
    async def auth(self, websocket_service: "WebSocketService") -> bool:
        '''
        进行认证流程，成功返回True，失败返回False
        '''
        while True:
            client_event: WSMessage | None = await websocket_service.try_recv_client_msg(self)
            if client_event is None:
                await asyncio.sleep(0.1)  # 避免空循环占用过多CPU
                continue
            if client_event.event_type == WSEventType.USER_AUTH.value:
                db = get_sql_session()
                try:
                    ret = await websocket_service.handle_auth_event(self, db, client_event)
                finally:
                    db.close()
                if ret:  # 验证成功
                    
                    break  # 认证成功后跳出循环，进入正常的消息处理流程
        return True