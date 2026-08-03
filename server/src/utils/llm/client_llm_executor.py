"""
ClientLLMExecutor
-----------------
将单个 LLM/VLM 调用转发给在线客户端执行，客户端使用用户自己输入的
api-key 直接调用云端 OpenAI 兼容接口，服务端全程不接触用户的 key。

当用户未启用客户端执行、客户端离线、超时或客户端返回错误时，调用方
（ClientDelegatingLLMInterface）会回退到服务端自带的 key 直连。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Dict, Optional

from src.utils.logger import get_logger


LLM_REQUEST_EVENT_TYPE = "llm_request"


class ClientLLMExecutionError(Exception):
    """客户端执行 LLM 调用失败（未连接 / 超时 / 客户端返回错误）。"""


class ClientLLMUnavailable(ClientLLMExecutionError):
    """用户没有可用的在线客户端连接。"""


class ClientLLMTimeout(ClientLLMExecutionError):
    """等待客户端返回 LLM 响应超时。"""


class ClientLLMError(ClientLLMExecutionError):
    """客户端执行 LLM 调用时返回了错误。"""


class ClientLLMExecutor:
    """服务端单例：向用户的客户端转发 LLM 请求并等待响应。"""

    def __init__(self, timeout_seconds: float = 120.0):
        self.timeout_seconds = float(timeout_seconds)
        self.logger = get_logger(__name__)
        self._stream_manager: Any = None
        # request_id -> (user_id, asyncio.Future)
        self._pending: Dict[str, tuple[str, asyncio.Future]] = {}
        # 已启用客户端执行模式的用户集合
        self._enabled_users: set[str] = set()

    def bind(self, stream_manager: Any) -> None:
        """绑定 ChatStreamManager，用于按 user_id 找到在线连接。"""
        self._stream_manager = stream_manager

    def set_llm_mode(self, user_id: Optional[str], enabled: bool) -> None:
        """更新用户是否使用客户端执行 LLM 调用。"""
        if not user_id:
            return
        if enabled:
            self._enabled_users.add(user_id)
        else:
            self._enabled_users.discard(user_id)

    def is_enabled(self, user_id: Optional[str]) -> bool:
        return bool(user_id and user_id in self._enabled_users)

    def clear_user(self, user_id: Optional[str]) -> None:
        """用户断开连接时清理使能标记并失败其挂起的请求。"""
        if not user_id:
            return
        self._enabled_users.discard(user_id)
        for request_id in [rid for rid, (uid, _) in self._pending.items() if uid == user_id]:
            _, fut = self._pending.pop(request_id)
            if not fut.done():
                fut.set_exception(ClientLLMUnavailable("client disconnected"))

    def _get_live_websocket(self, user_id: str):
        """返回该用户任一活跃连接的 websocket；没有则返回 None。"""
        if self._stream_manager is None:
            return None
        stream = self._stream_manager.get_stream_by_user_uuid(user_id)
        if stream is None or stream.is_connection_lost():
            return None
        ws_connection = getattr(stream, "ws_connection", None)
        if ws_connection is None or getattr(ws_connection, "websocket", None) is None:
            return None
        return ws_connection.websocket

    async def request(
        self,
        user_id: str,
        *,
        module: str,
        prompt: str,
        params: Optional[Dict[str, Any]],
        enable_thinking: bool = False,
        use_json: bool = False,
        image_base64: Optional[str] = None,
        provider: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """向用户客户端发送 llm_request 并等待 llm_response。

        返回与 LLMAPIInterface.generate_response 相同结构的字典：
        {"content": str, "usage": dict|None, "response_time_s": float}
        """
        websocket = self._get_live_websocket(user_id)
        if websocket is None:
            raise ClientLLMUnavailable(f"no live client connection for user {user_id}")

        request_id = f"llm-{uuid.uuid4().hex[:16]}"
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[request_id] = (user_id, future)

        payload: Dict[str, Any] = {
            "request_id": request_id,
            "module": module,
            "prompt": prompt,
            "params": dict(params or {}),
            "enable_thinking": bool(enable_thinking),
            "use_json": bool(use_json),
        }
        if image_base64:
            payload["image_base64"] = image_base64
        if provider:
            payload["provider"] = provider

        event = {
            "type": LLM_REQUEST_EVENT_TYPE,
            "ts": int(time.time() * 1000),
            "payload": payload,
        }

        started = time.perf_counter()
        try:
            await websocket.send_json(event)
            result = await asyncio.wait_for(future, timeout=self.timeout_seconds)
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            raise ClientLLMTimeout(
                f"llm_request {request_id} timed out after {self.timeout_seconds}s"
            ) from None
        finally:
            self._pending.pop(request_id, None)

        if isinstance(result, dict) and result.get("error"):
            raise ClientLLMError(str(result["error"]))

        content = (result or {}).get("content")
        if content is None:
            raise ClientLLMError(f"llm_response {request_id} missing content")

        return {
            "content": str(content),
            "usage": (result or {}).get("usage"),
            "response_time_s": (time.perf_counter() - started),
        }

    def on_llm_response(self, payload: Optional[Dict[str, Any]]) -> None:
        """由 WS 收包循环调用，按 request_id 解析挂起的请求。"""
        if not isinstance(payload, dict):
            return
        request_id = payload.get("request_id")
        if not request_id:
            self.logger.warning("llm_response missing request_id")
            return
        pending = self._pending.get(request_id)
        if pending is None:
            self.logger.debug(f"llm_response for unknown request_id: {request_id}")
            return
        _, future = pending
        if future.done():
            return
        future.set_result(payload)
