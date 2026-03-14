from typing import Dict, Tuple
import time
from fastapi import WebSocket, WebSocketDisconnect
import asyncio
from sqlalchemy.orm import Session
from ..database.sql_database import get_sql_session
from .types import EventType, ClientMessage
from .account import check_message_token


class WebSocketService:
    def __init__(self):
        pass

    async def try_recv_client_msg(self, websocket_connection: "WebSocketConnection") -> ClientMessage | None:
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
        return ClientMessage(
            event_type=event.get("type"),
            payload=event.get("payload", {}),
            client_msg_id=event.get("client_msg_id")
        )
    
    async def handle_auth_event(self, ws_connection: "WebSocketConnection", db: Session, event: ClientMessage) -> bool:
        websocket = ws_connection.websocket
        username = event.payload.get("username", "")
        token = event.payload.get("token", "")
        if not username or not token:
            await websocket.send_json(
                self._make_event(
                    EventType.AUTH_ERROR,
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
                    EventType.AUTH_ERROR,
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
                EventType.AUTH_OK,
                {"message": "authentication successful for user " + authed_username},
                reply_to=event.client_msg_id,
            )
        )
        ws_connection.set_user(authed_user_uuid, authed_username)
        return True

    async def send_system_ready_event(self, websocket: WebSocket) -> None:
        '''
        发送系统就绪事件，提示客户端进行认证
        '''
        event =  self._make_event(EventType.SYSTEM_READY, {
            "message": "WebSocket connected. Please send auth first.",
            "require_auth_before_chat": True
        })
        await websocket.send_json(event)

    async def send_error_event(self, websocket: WebSocket, payload: Dict) -> None:
        event = self._make_event(
            EventType.SERVER_ERROR,
            payload
        )
        await websocket.send_json(event)

    def _make_event(self, event_type: EventType, payload: Dict, reply_to: str = None) -> Dict:
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
        self.is_ws_alive = True

    def set_user(self, user_uuid: str, user_name: str):
        self.user_uuid = user_uuid
        self.user_name = user_name
        
    async def auth(self, websocket_service: "WebSocketService") -> bool:
        '''
        进行认证流程，成功返回True，失败返回False
        '''
        while True:
            client_event: ClientMessage | None = await websocket_service.try_recv_client_msg(self)
            if client_event is None:
                await asyncio.sleep(0.1)  # 避免空循环占用过多CPU
                continue
            if client_event.event_type == "auth":
                db = get_sql_session()
                try:
                    ret = await websocket_service.handle_auth_event(self, db, client_event)
                finally:
                    db.close()
                if ret:  # 验证成功
                    
                    break  # 认证成功后跳出循环，进入正常的消息处理流程
        return True