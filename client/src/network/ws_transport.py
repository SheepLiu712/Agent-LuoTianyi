import asyncio
import json
import ssl
import threading
from typing import Callable

import websockets

from .event_types import build_event, normalize_agent_message, normalize_error_message, parse_server_message, WSEventType, WSMessage, AgentMessage
from ..utils.logger import get_logger

class WsTransport:
    def __init__(
        self,
        base_url: str,
        username_getter: Callable[[], str | None],
        token_getter: Callable[[], str | None],
        verify_ssl: bool = True,
        heartbeat_interval: float = 10.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.username_getter = username_getter
        self.token_getter = token_getter
        self.verify_ssl = verify_ssl
        self.heartbeat_interval = heartbeat_interval

        self._lock = threading.Lock()
        self._submit_lock = threading.Lock()
        self._ack_waiter: dict | None = None
        self._agent_message_listener: Callable[[AgentMessage], None] | None = None # 收到的消息发送到哪里
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

        self.logger = get_logger(self.__class__.__name__)

        
        self._ws = None
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._connected_event = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._ready_event.clear()
        self._connected_event.clear()
        self._thread = threading.Thread(target=self._thread_entry, daemon=True)
        self._thread.start()
        self.logger.debug("WebSocket thread started")

    def stop(self) -> None:
        self._stop_event.set()
        self._ready_event.clear()
        self._connected_event.clear()
        self._notify_ack_failure("WebSocket disconnected")
        self.logger.debug("WebSocket disconnected")
        if self._loop and self._ws:
            try:
                asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)
            except Exception:
                pass

    def set_agent_message_listener(self, listener: Callable[[AgentMessage], None] | None) -> None:
        with self._lock:
            self._agent_message_listener = listener

    def submit_user_text(self, text: str, ack_timeout: float = 10.0) -> dict:
        return self._submit_user_event(WSEventType.USER_TEXT, payload={"message": text}, ack_timeout=ack_timeout)

    def submit_user_image(self, image_base64: str, mime_type: str, image_client_path: str | None = None, ack_timeout: float = 10.0) -> dict:
        payload = {
            "image_base64": image_base64,
            "mime_type": mime_type,
        }
        if image_client_path:
            payload["image_client_path"] = image_client_path
        return self._submit_user_event(WSEventType.USER_IMAGE, payload=payload, ack_timeout=ack_timeout)
    
    def submit_typing_event(self, ack_timeout: float = 10.0) -> dict:
        return self._submit_user_event(WSEventType.USER_TYPING, payload={"is_typing": True}, ack_timeout=ack_timeout)

    def _submit_user_event(self, event_type: WSEventType, payload: dict, ack_timeout: float) -> dict:
        event = build_event(event_type, payload=payload)
        request_id = event.client_msg_id

        self.start()
        if not self._ready_event.wait(timeout=8): # 验证是否登录，从而完整地建立WS连接，避免登录后立即发消息导致的鉴权失败问题
            return {
                "ok": False,
                "request_id": request_id,
                "error": "WebSocket auth timeout",
                "drop": True,
            }

        with self._submit_lock:
            waiter = {
                "request_id": request_id,
                "event": threading.Event(),
                "result": None,
            }
            with self._lock:
                self._ack_waiter = waiter

            if not self._send_event(event):
                with self._lock:
                    if self._ack_waiter is waiter:
                        self._ack_waiter = None
                return {
                    "ok": False,
                    "request_id": request_id,
                    "error": "Send failed",
                }

            if not waiter["event"].wait(timeout=max(0.1, ack_timeout)):
                with self._lock:
                    if self._ack_waiter is waiter:
                        self._ack_waiter = None
                return {
                    "ok": False,
                    "request_id": request_id,
                    "error": "Wait server ack timeout",
                }

            result = waiter["result"] or {
                "ok": False,
                "request_id": request_id,
                "error": "Unknown ack state",
            }
            with self._lock:
                if self._ack_waiter is waiter:
                    self._ack_waiter = None
            return result

    def _send_event(self, event: WSMessage) -> bool:
        if not self._ready_event.is_set() or not self._loop:
            return False
        

        async def _send() -> None:
            if not self._ws:
                return
            event_dict = event.__dict__()
            await self._ws.send(json.dumps(event_dict, ensure_ascii=False))

        try:
            fut = asyncio.run_coroutine_threadsafe(_send(), self._loop)
            fut.result(timeout=1)
            return True
        except Exception as exc:
            self._notify_ack_failure(f"Send failed: {exc}")
            return False

    def _thread_entry(self) -> None:
        asyncio.run(self._run())

    async def _run(self) -> None:
        reconnect_delay = 2
        while not self._stop_event.is_set():
            self._loop = asyncio.get_running_loop()
            ws_url = self._build_ws_url(self.base_url)
            ssl_ctx = self._build_ssl_context(self.base_url)
            try:
                async with websockets.connect(ws_url, max_size=8 * 1024 * 1024, ssl=ssl_ctx) as ws:
                    self._ws = ws
                    self._connected_event.set()
                    self._ready_event.clear()

                    await self._authenticate(ws)
                    recv_task = asyncio.create_task(self._recv_loop(ws))
                    hb_task = asyncio.create_task(self._heartbeat_loop(ws))
                    reconnect_delay = 2
                    done, pending = await asyncio.wait(
                        [recv_task, hb_task],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    self.logger.debug("WebSocket connection task completed, cancelling pending tasks...")
                    for task in pending:
                        task.cancel()
                    for task in done:
                        exc = task.exception()
                        if exc:
                            self.logger.error(f"WebSocket inner task exited with error: {exc}")
            except Exception as e:
                self.logger.error(f"WebSocket connection error: {e}")
                self._notify_ack_failure("WebSocket disconnected")
                self.logger.debug("WebSocket connection closed, retrying...")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 30) # 指数退避，最大30秒
            finally:
                self._ws = None
                self._connected_event.clear()
                self._ready_event.clear()

    async def _authenticate(self, ws) -> None:
        # 服务端首次会发 system_ready；如未发也继续鉴权流程
        self.logger.debug("Waiting for WebSocket auth response...")
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            msg = parse_server_message(raw)
            if msg and msg.event_type == WSEventType.AUTH_OK:
                self._ready_event.set()
                return
        except Exception as e:
            self.logger.error(f"Error occurred while waiting for auth response: {e}")
            pass

        username = self.username_getter()
        token = self.token_getter()
        if not username or not token:
            self.logger.error("WebSocket auth failed: missing username or token")
            return

        auth_event = build_event(WSEventType.USER_AUTH, payload={"username": username, "token": token})
        await ws.send(json.dumps(auth_event.__dict__(), ensure_ascii=False))

        # 等待 auth_ok
        for _ in range(10):
            raw = await ws.recv()
            msg = parse_server_message(raw)
            if not msg:
                continue
            if msg.event_type == WSEventType.AUTH_OK:
                self.logger.debug("WebSocket auth successful")
                self._ready_event.set()
                return
            if msg.event_type in (WSEventType.AUTH_ERROR, WSEventType.SERVER_ERROR):
                self.logger.error(f"WebSocket auth failed: {msg.payload.get('message')}")
                return

    async def _recv_loop(self, ws) -> None:
        while not self._stop_event.is_set():
            raw = await ws.recv()
            msg = parse_server_message(raw)
            if not msg:
                continue
            event_type = msg.event_type

            if event_type == WSEventType.SERVER_ACK:
                self._complete_ack_waiter(ok=True, error=None, reply_to=msg.reply_to)
                continue

            if event_type == WSEventType.AGENT_STATE_CHANGED:
                continue

            if event_type == WSEventType.AGENT_MESSAGE:
                agent_msg = normalize_agent_message(msg)
                self._emit_agent_message(agent_msg)
                continue

            if event_type == WSEventType.HB_PONG:
                ping_id = msg.payload.get("ping_id")

            if event_type in (WSEventType.SERVER_ERROR, WSEventType.AUTH_ERROR):
                error_msg = normalize_error_message(msg)
                consumed = self._complete_ack_waiter(
                    ok=False,
                    error=f"[{error_msg.code}] {error_msg.message}",
                    reply_to=error_msg.reply_to,
                )
                if not consumed:
                    self._emit_agent_message(
                        AgentMessage(
                            text=f"[{error_msg.code}] {error_msg.message}",
                            audio="",
                            expression=None,
                            is_final_package=True,
                            uuid=None,
                            reply_to=error_msg.reply_to,
                        )
                    )
        self.logger.debug("WebSocket receive loop exited")

    async def _heartbeat_loop(self, ws) -> None:
        ping_id = 0
        while not self._stop_event.is_set():
            if self._ready_event.is_set():
                ping_id += 1
                hb_event = build_event(WSEventType.HB_PING, payload={"ping_id": ping_id})
                await ws.send(json.dumps(hb_event.__dict__(), ensure_ascii=False))
            await asyncio.sleep(self.heartbeat_interval)
        self.logger.debug("WebSocket heartbeat loop exited")

    def _complete_ack_waiter(self, ok: bool, error: str | None, reply_to: str | None) -> bool:
        with self._lock:
            waiter = self._ack_waiter
            if not waiter:
                return False

            expected = waiter.get("request_id")
            if reply_to and expected and reply_to != expected:
                return False

            waiter["result"] = {
                "ok": ok,
                "request_id": expected,
                "error": error,
            }
            waiter["event"].set()
            return True

    def _notify_ack_failure(self, error_text: str) -> None:
        with self._lock:
            waiter = self._ack_waiter
            if not waiter:
                return
            waiter["result"] = {
                "ok": False,
                "request_id": waiter.get("request_id"),
                "error": error_text,
            }
            waiter["event"].set()

    def _emit_agent_message(self, agent_msg: AgentMessage) -> None:
        if not self._agent_message_listener:
            return
        try:
            self._agent_message_listener(agent_msg)
        except Exception:
            pass

    @staticmethod
    def _build_ws_url(base_url: str) -> str:
        if base_url.startswith("https://"):
            return "wss://" + base_url[len("https://") :].rstrip("/") + "/chat_ws"
        if base_url.startswith("http://"):
            return "ws://" + base_url[len("http://") :].rstrip("/") + "/chat_ws"
        raise ValueError("base_url must start with http:// or https://")

    def _build_ssl_context(self, base_url: str):
        if not base_url.startswith("https://"):
            return None
        if self.verify_ssl:
            ctx = ssl.create_default_context()
        else:
            ctx = ssl._create_unverified_context()

        # Improve compatibility with some tunneling endpoints in this project runtime.
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        return ctx
