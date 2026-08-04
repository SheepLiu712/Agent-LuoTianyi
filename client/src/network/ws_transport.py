import asyncio
import json
import ssl
import threading
import time
from typing import Callable

import websockets

from .event_types import build_event, normalize_agent_message, normalize_error_message, parse_server_message, WSEventType, WSMessage, AgentMessage, AgentStateMessage
from ..utils.logger import get_logger
from ..utils.tls import create_default_ssl_context
from ..utils.llm_client import (
    build_chat_completions_payload,
    call_llm_api_async,
)


WS_CLIENT_CAPABILITIES = ("negative_ack_v1",)


def normalize_server_ack(payload: dict) -> dict:
    """Normalize positive and negative ACK payloads, including legacy ACKs."""
    if payload.get("ok") is not False:
        return {"ok": True, "error": None}

    code = payload.get("code") if isinstance(payload.get("code"), str) else "REJECTED"
    retryable = payload.get("retryable") is True
    message = payload.get("message") if isinstance(payload.get("message"), str) else code
    return {
        "ok": False,
        "error": f"[{code}] {message}",
        "code": code,
        "retryable": retryable,
        "drop": not retryable,
    }


class WsTransport:
    READY_TIMEOUT_SECONDS = 8.0

    def __init__(
        self,
        base_url: str,
        username_getter: Callable[[], str | None],
        token_getter: Callable[[], str | None],
        verify_ssl: bool = True,
        heartbeat_interval: float = 10.0,
        api_key_getter: Callable[[], str | None] | None = None,
        provider_getter: Callable[[], str | None] | None = None,
        model_getter: Callable[[], str | None] | None = None,
        vlm_provider_getter: Callable[[], str | None] | None = None,
        vlm_model_getter: Callable[[], str | None] | None = None,
        vlm_api_key_getter: Callable[[], str | None] | None = None,
        base_url_getter: Callable[[], str | None] | None = None,
        vlm_base_url_getter: Callable[[], str | None] | None = None,
        params_getter: Callable[[], dict | None] | None = None,
        vlm_params_getter: Callable[[], dict | None] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.username_getter = username_getter
        self.token_getter = token_getter
        self.verify_ssl = verify_ssl
        self.heartbeat_interval = heartbeat_interval
        self.api_key_getter = api_key_getter
        self.provider_getter = provider_getter
        self.model_getter = model_getter
        self.vlm_provider_getter = vlm_provider_getter
        self.vlm_model_getter = vlm_model_getter
        self.vlm_api_key_getter = vlm_api_key_getter
        self.base_url_getter = base_url_getter
        self.vlm_base_url_getter = vlm_base_url_getter
        self.params_getter = params_getter
        self.vlm_params_getter = vlm_params_getter

        self._lock = threading.Lock()
        self._submit_lock = threading.Lock()
        self._ack_waiter: dict | None = None
        self._agent_message_listener: Callable[[AgentMessage], None] | None = None # 收到的消息发送到哪里
        self._agent_state_listener: Callable[[bool], None] | None = None # agent状态变化的监听器
        self._system_message_listener: Callable[[str], None] | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

        self.logger = get_logger(self.__class__.__name__)

        
        self._ws = None
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._connected_event = threading.Event()
        self._auth_rejected_credentials: tuple[str | None, str | None] | None = None

    def set_base_url(self, base_url: str, verify_ssl: bool) -> None:
        """更新服务器地址，断开当前连接以便自动重连到新地址。"""
        self.base_url = base_url.rstrip("/")
        self.verify_ssl = verify_ssl
        # 断开当前 WS，_run() 循环会自动用新 base_url 重连
        self.stop()

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
        self._notify_ack_failure(
            "WebSocket stopped",
            drop=True,
            code="TRANSPORT_STOPPED",
            retryable=False,
        )
        self.logger.debug("WebSocket disconnected")
        if self._loop and self._ws:
            try:
                asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)
            except Exception:
                pass

    def set_agent_message_listener(
        self,
        agent_message_listener: Callable[[AgentMessage], None] | None,
        agent_state_listener: Callable[[bool], None] | None,
        system_message_listener: Callable[[str], None] | None = None,
    ) -> None:
        with self._lock:
            self._agent_message_listener = agent_message_listener
            self._agent_state_listener = agent_state_listener
            self._system_message_listener = system_message_listener

    def submit_user_text(
        self,
        text: str,
        is_proactive: bool = False,
        ack_timeout: float = 10.0,
        client_msg_id: str | None = None,
    ) -> dict:
        payload = {"message": text}
        if is_proactive:
            payload["is_proactive"] = True
        if self.api_key_getter and self.api_key_getter():
            payload["llm_mode"] = "client"
        return self._submit_user_event(
            WSEventType.USER_TEXT,
            payload=payload,
            ack_timeout=ack_timeout,
            client_msg_id=client_msg_id,
        )

    def submit_user_image(
        self,
        image_base64: str,
        mime_type: str,
        image_client_path: str | None = None,
        ack_timeout: float = 10.0,
        client_msg_id: str | None = None,
    ) -> dict:
        payload = {
            "image_base64": image_base64,
            "mime_type": mime_type,
        }
        if image_client_path:
            payload["image_client_path"] = image_client_path
        if self.api_key_getter and self.api_key_getter():
            payload["llm_mode"] = "client"
        return self._submit_user_event(
            WSEventType.USER_IMAGE,
            payload=payload,
            ack_timeout=ack_timeout,
            client_msg_id=client_msg_id,
        )
    
    def submit_typing_event(self, text_length: int, ack_timeout: float = 10.0, client_msg_id: str | None = None) -> dict:
        return self._submit_user_event(
            WSEventType.USER_TYPING,
            payload={"text_length": text_length},
            ack_timeout=ack_timeout,
            client_msg_id=client_msg_id,
        )

    def submit_user_touch(
        self,
        touch_area: str | list,
        click_frequency: dict = None,
        touch_meta: dict = None,
        ack_timeout: float = 10.0,
        client_msg_id: str | None = None,
    ) -> dict:
        if isinstance(touch_area, str):
            payload = {"touch_area": touch_area}
        else:
            payload = {"touchArea": touch_area}
        if click_frequency:
            payload["click_frequency"] = click_frequency
        if touch_meta:
            payload.update(touch_meta)
        return self._submit_user_event(
            WSEventType.USER_TOUCH,
            payload=payload,
            ack_timeout=ack_timeout,
            client_msg_id=client_msg_id,
        )

    def submit_image_selecting(self, ack_timeout: float = 5.0) -> dict:
        """发送图片选择中的事件，服务端会延长等待时间。"""
        return self._submit_user_event(WSEventType.USER_IMAGE_SELECTING, payload={}, ack_timeout=ack_timeout)

    def submit_image_selecting_cancel(self, ack_timeout: float = 5.0) -> dict:
        """发送图片选择取消的事件，服务端重置等待时间。"""
        return self._submit_user_event(WSEventType.USER_IMAGE_SELECTING_CANCEL, payload={}, ack_timeout=ack_timeout)
    def _submit_user_event(
        self,
        event_type: WSEventType,
        payload: dict,
        ack_timeout: float,
        client_msg_id: str | None = None,
    ) -> dict:
        event = build_event(event_type, payload=payload, client_msg_id=client_msg_id)
        request_id = event.client_msg_id

        self.start()
        deadline = time.monotonic() + self.READY_TIMEOUT_SECONDS
        while not self._ready_event.is_set():
            if self._is_auth_rejected():
                return {
                    "ok": False,
                    "request_id": request_id,
                    "error": "WebSocket authentication rejected",
                    "code": "AUTH_REJECTED",
                    "retryable": False,
                    "drop": True,
                }
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            self._ready_event.wait(timeout=min(0.1, remaining))

        if not self._ready_event.is_set():
            return {
                "ok": False,
                "request_id": request_id,
                "error": "WebSocket auth timeout",
                "code": "NOT_READY",
                "retryable": True,
                "drop": False,
            }

        with self._submit_lock:
            waiter = {
                "request_id": request_id,
                "event": threading.Event(),
                "result": None,
            }
            with self._lock:
                self._ack_waiter = waiter
            self.logger.debug(f"Submitting event {event_type} with request_id {request_id}")
            if not self._send_event(event):
                with self._lock:
                    if self._ack_waiter is waiter:
                        self._ack_waiter = None
                return {
                    "ok": False,
                    "request_id": request_id,
                    "error": "Send failed",
                    "drop": False,
                }

            if not waiter["event"].wait(timeout=max(0.1, ack_timeout)):
                with self._lock:
                    if self._ack_waiter is waiter:
                        self._ack_waiter = None
                self.logger.error(f"ACK timeout for request_id {request_id} after {ack_timeout}s")
                return {
                    "ok": False,
                    "request_id": request_id,
                    "error": "Wait server ack timeout",
                    "drop": False,
                }

            result = waiter["result"] or {
                "ok": False,
                "request_id": request_id,
                "error": "Unknown ack state",
                "drop": True,
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
                    if self._is_auth_rejected():
                        await ws.close()
                        return
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
                self._notify_ack_failure(
                    "WebSocket disconnected",
                    drop=False,
                    code="DISCONNECTED",
                    retryable=True,
                )
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
                self._auth_rejected_credentials = None
                self._ready_event.set()
                return
            if msg and msg.event_type == WSEventType.AUTH_ERROR:
                self._mark_auth_rejected()
                error_msg = normalize_error_message(msg)
                self._emit_system_message(f"[{error_msg.code}] {error_msg.message}")
                return
        except Exception as e:
            self.logger.error(f"Error occurred while waiting for auth response: {e}")
            pass

        username = self.username_getter()
        token = self.token_getter()
        if not username or not token:
            self.logger.error("WebSocket auth failed: missing username or token")
            self._mark_auth_rejected()
            return

        auth_event = build_event(
            WSEventType.USER_AUTH,
            payload={
                "username": username,
                "token": token,
                "capabilities": list(WS_CLIENT_CAPABILITIES),
            },
        )
        await ws.send(json.dumps(auth_event.__dict__(), ensure_ascii=False))

        # 等待 auth_ok
        for _ in range(10):
            raw = await ws.recv()
            msg = parse_server_message(raw)
            if not msg:
                continue
            if msg.event_type == WSEventType.AUTH_OK:
                self.logger.debug("WebSocket auth successful")
                self._auth_rejected_credentials = None
                self._ready_event.set()
                return
            if msg.event_type == WSEventType.AUTH_ERROR:
                self._mark_auth_rejected()
                self.logger.error(f"WebSocket auth failed: {msg.payload.get('message')}")
                error_msg = normalize_error_message(msg)
                self._emit_system_message(f"[{error_msg.code}] {error_msg.message}")
                return
            if msg.event_type == WSEventType.SERVER_ERROR:
                self.logger.error(f"WebSocket auth failed: {msg.payload.get('message')}")
                error_msg = normalize_error_message(msg)
                self._emit_system_message(f"[{error_msg.code}] {error_msg.message}")
                return

    async def _recv_loop(self, ws) -> None:
        while not self._stop_event.is_set():
            raw = await ws.recv()
            msg = parse_server_message(raw)
            if not msg:
                continue
            event_type = msg.event_type

            if event_type == WSEventType.SERVER_ACK:
                self.logger.debug(f"Received ack for request_id {msg.reply_to}")
                ack = normalize_server_ack(msg.payload)
                self._complete_ack_waiter(
                    ok=ack["ok"],
                    error=ack["error"],
                    reply_to=msg.reply_to,
                    drop=ack.get("drop"),
                    code=ack.get("code"),
                    retryable=ack.get("retryable"),
                )
                continue

            if event_type == WSEventType.AGENT_MESSAGE:
                agent_msg = normalize_agent_message(msg)
                self._emit_agent_message(agent_msg)
                continue

            if event_type == WSEventType.HB_PONG:
                ping_id = msg.payload.get("ping_id")
                continue

            if event_type == WSEventType.LLM_REQUEST:
                asyncio.create_task(self._handle_llm_request(ws, msg.payload))
                continue

            if event_type == WSEventType.AGENT_STATE_CHANGED:
                state = msg.payload.get("state", "waiting")
                self._emit_agent_state(state)
                continue


            if event_type in (WSEventType.SERVER_ERROR, WSEventType.AUTH_ERROR):
                error_msg = normalize_error_message(msg)
                is_auth_rejection = event_type == WSEventType.AUTH_ERROR
                if is_auth_rejection:
                    self._mark_auth_rejected()
                    self._ready_event.clear()
                consumed = self._complete_ack_waiter(
                    ok=False,
                    error=f"[{error_msg.code}] {error_msg.message}",
                    reply_to=error_msg.reply_to,
                    drop=True if is_auth_rejection else None,
                    code="AUTH_REJECTED" if is_auth_rejection else None,
                    retryable=False if is_auth_rejection else None,
                )
                if not consumed:
                    self._emit_system_message(f"[{error_msg.code}] {error_msg.message}")
        self.logger.debug("WebSocket receive loop exited")

    async def _handle_llm_request(self, ws, payload: dict) -> None:
        """处理服务端下发的 llm_request：用用户自己的 api-key 调用大模型。"""
        request_id = payload.get("request_id")
        if not request_id:
            return

        is_image = bool(payload.get("image_base64"))
        api_key = (
            self.vlm_api_key_getter() if is_image and self.vlm_api_key_getter else None
        )
        if not api_key:
            api_key = self.api_key_getter() if self.api_key_getter else None
        if not api_key:
            self.logger.warning("llm_request received but no api key configured on client")
            await self._send_llm_response(request_id, error="no api key configured on client")
            return

        if is_image:
            base_url = self.vlm_base_url_getter() if self.vlm_base_url_getter else None
        else:
            base_url = self.base_url_getter() if self.base_url_getter else None
        if not base_url:
            await self._send_llm_response(
                request_id,
                error="LLM 配置不完整，请在 LLM 模型设置中重新保存",
            )
            return
        url = f"{base_url.rstrip('/')}/chat/completions"
        if is_image:
            model = self.vlm_model_getter() if self.vlm_model_getter else None
        else:
            model = self.model_getter() if self.model_getter else None
        if not model:
            await self._send_llm_response(request_id, error="missing provider info")
            return

        server_params = payload.get("params") or {}
        if is_image:
            cached_params = self.vlm_params_getter() if self.vlm_params_getter else None
        else:
            cached_params = self.params_getter() if self.params_getter else None
        merged_params = {**(server_params or {}), **(cached_params or {})}
        body = build_chat_completions_payload(
            prompt=payload.get("prompt", ""),
            model=model,
            params=merged_params,
            enable_thinking=bool(payload.get("enable_thinking")),
            use_json=bool(payload.get("use_json")),
            image_base64=payload.get("image_base64"),
        )
        try:
            result = await call_llm_api_async(url=url, api_key=api_key, payload=body)
            await self._send_llm_response(
                request_id,
                content=result["content"],
                usage=result["usage"],
            )
        except Exception as exc:
            self.logger.error(f"Client LLM execution failed: {exc}")
            await self._send_llm_response(request_id, error=str(exc))

    async def _send_llm_response(
        self,
        request_id: str,
        *,
        content: str | None = None,
        usage: dict | None = None,
        error: str | None = None,
    ) -> None:
        payload = {"request_id": request_id}
        if error is not None:
            payload["error"] = error
        else:
            payload["content"] = content or ""
            payload["usage"] = usage
        event = build_event(WSEventType.LLM_RESPONSE, payload=payload)
        if self._ws is not None:
            try:
                await self._ws.send(json.dumps(event.__dict__(), ensure_ascii=False))
            except Exception as exc:
                self.logger.warning(f"Failed to send llm_response: {exc}")

    async def _heartbeat_loop(self, ws) -> None:
        ping_id = 0
        while not self._stop_event.is_set():
            if self._ready_event.is_set():
                ping_id += 1
                hb_event = build_event(WSEventType.HB_PING, payload={"ping_id": ping_id})
                await ws.send(json.dumps(hb_event.__dict__(), ensure_ascii=False))
            await asyncio.sleep(self.heartbeat_interval)
        self.logger.debug("WebSocket heartbeat loop exited")

    def _complete_ack_waiter(
        self,
        ok: bool,
        error: str | None,
        reply_to: str | None,
        *,
        drop: bool | None = None,
        code: str | None = None,
        retryable: bool | None = None,
    ) -> bool:
        with self._lock:
            waiter = self._ack_waiter
            if not waiter:
                self.logger.debug(f"ACK arrived but no waiter found. reply_to={reply_to}, error={error}")
                return False

            expected = waiter.get("request_id")
            if reply_to and expected and reply_to != expected:
                self.logger.warning(f"ACK request_id mismatch: reply_to={reply_to}, expected={expected}")
                return False

            waiter["result"] = {
                "ok": ok,
                "request_id": expected,
                "error": error,
            }
            if drop is not None:
                waiter["result"]["drop"] = drop
            if code is not None:
                waiter["result"]["code"] = code
            if retryable is not None:
                waiter["result"]["retryable"] = retryable
            waiter["event"].set()
            self.logger.debug(f"ACK waiter completed for request_id {expected}")
            return True

    def _notify_ack_failure(
        self,
        error_text: str,
        *,
        drop: bool = False,
        code: str = "DISCONNECTED",
        retryable: bool = True,
    ) -> None:
        with self._lock:
            waiter = self._ack_waiter
            if not waiter:
                return
            waiter["result"] = {
                "ok": False,
                "request_id": waiter.get("request_id"),
                "error": error_text,
                "drop": drop,
                "code": code,
                "retryable": retryable,
            }
            waiter["event"].set()

    def _mark_auth_rejected(self) -> None:
        self._auth_rejected_credentials = (
            self.username_getter(),
            self.token_getter(),
        )

    def _is_auth_rejected(self) -> bool:
        rejected = self._auth_rejected_credentials
        if rejected is None:
            return False
        current = (self.username_getter(), self.token_getter())
        if current != rejected:
            self._auth_rejected_credentials = None
            return False
        return True

    def _emit_agent_message(self, agent_msg: AgentMessage) -> None:
        if not self._agent_message_listener:
            return
        try:
            self._agent_message_listener(agent_msg)
        except Exception:
            pass

    def _emit_agent_state(self, state_msg: str) -> None:
        self.logger.debug(f"Agent state changed: {state_msg}")
        if not self._agent_state_listener:
            return
        try:
            self._agent_state_listener(state_msg)
        except Exception:
            pass

    def _emit_system_message(self, text: str) -> None:
        if not self._system_message_listener:
            return
        try:
            self._system_message_listener(text)
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
        ctx = create_default_ssl_context()
        # Improve compatibility with some tunneling endpoints in this project runtime.
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        return ctx
