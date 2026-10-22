"""
ClientLLMExecutor
-----------------
将单个 LLM 调用按客户端模型类型转发给在线客户端执行，客户端使用用户自己
输入的 api-key 直接调用云端 OpenAI 兼容接口，服务端全程不接触用户的 key。

当模块未配置委托类型、客户端未启用该类型或客户端离线时，
delegate() 返回 None，由调用方（LLMModule/VLMModule）直接使用服务端接口。
委托执行失败时不回退，直接抛错，由调用方通知用户。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Dict, Optional

from src.infrastructure.models.client_execution import (
    ClientLLMError,
    ClientLLMExecutionError,
    ClientLLMTimeout,
    ClientLLMUnavailable,
    _looks_like_key_error,
    build_fallback_notice,
    notify_fallback,
)
from src.utils.logger import get_logger

from ._protocol_translate import encode_event

__all__ = [
    "ClientLLMError",
    "ClientLLMExecutionError",
    "ClientLLMExecutor",
    "ClientLLMTimeout",
    "ClientLLMUnavailable",
    "_looks_like_key_error",
    "build_fallback_notice",
    "notify_fallback",
]


class ClientLLMExecutor:
    """服务端单例：向用户的客户端转发 LLM 请求并等待响应。"""

    def __init__(self, timeout_seconds: float = 120.0):
        self.timeout_seconds = float(timeout_seconds)
        self.logger = get_logger(__name__)
        self._lookup_connection: Any = None
        # request_id -> (user_id, asyncio.Future, 发起请求的连接)
        self._pending: Dict[str, tuple[str, asyncio.Future, Any]] = {}
        # user_id -> 最近一次处理该用户请求的连接（用于把失败通知发回正确的客户端）
        self._user_connections: Dict[str, Any] = {}

    def bind(self, lookup_connection: Any) -> None:
        """绑定在线连接查询器，用于按 user_id 找到客户端连接。"""
        self._lookup_connection = lookup_connection

    def _get_live_connection(self, user_id: Optional[str]):
        """返回该用户 Adapter 连接的内部输出端口；没有则返回 None。"""
        if not user_id or self._lookup_connection is None:
            return None
        return self._lookup_connection(user_id)

    def clear_user(self, user_id: Optional[str], ws_connection: Any = None) -> None:
        """用户断开连接时失败其挂起的请求；仅当断开的是发起请求的连接时才执行。"""
        if not user_id:
            return
        for request_id in [
            rid
            for rid, (uid, _fut, owner) in self._pending.items()
            if uid == user_id and (ws_connection is None or owner is ws_connection)
        ]:
            _, fut, _owner = self._pending.pop(request_id)
            if not fut.done():
                fut.set_exception(ClientLLMUnavailable("client disconnected"))
        if ws_connection is None or self._user_connections.get(user_id) is ws_connection:
            self._user_connections.pop(user_id, None)

    async def notify_user(self, user_id: str, message: str, connection: Any = None) -> None:
        """向发起请求的连接发送错误通知；未指定时回退到最近请求的连接；未知则跳过。"""
        ws_connection = connection if connection is not None else self._user_connections.get(user_id)
        if ws_connection is None:
            return
        try:
            await ws_connection.send(encode_event("error", {"code": "LLM_CLIENT_ERROR", "message": message}))
        except Exception as exc:
            self.logger.debug(f"Failed to notify user {user_id}: {exc}")

    async def delegate(
        self,
        user_id: Optional[str],
        *,
        module: str,
        model_type: str,
        prompt: str,
        params: Optional[Dict[str, Any]],
        model_kind: str = "llm",
        enable_thinking: bool = False,
        use_json: bool = False,
        image_base64: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """按客户端模型类型向用户客户端转发请求并等待响应。

        未配置委托类型、客户端未启用该类型或客户端离线时返回 None，调用方
        应使用服务端接口直连。返回成功时与 LLMAPIInterface.generate_response
        相同结构：{"content", "usage", "response_time_s"}。执行失败抛错，不回退。
        """
        if not model_type:
            return None
        normalized_kind = str(model_kind or "").strip().lower()
        if normalized_kind not in {"llm", "vlm"}:
            raise ValueError(f"unsupported client model kind: {model_kind}")
        ws_connection = self._get_live_connection(user_id)
        if ws_connection is None:
            return None
        mode = getattr(ws_connection, "client_mode", None) or {}
        if model_type not in (mode.get("types") or []):
            return None

        self._user_connections[user_id] = ws_connection

        request_id = f"llm-{uuid.uuid4().hex[:16]}"
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[request_id] = (user_id, future, ws_connection)

        payload: Dict[str, Any] = {
            "request_id": request_id,
            "module": module,
            "type": model_type,
            "model_kind": normalized_kind,
            "prompt": prompt,
            "params": dict(params or {}),
            "enable_thinking": bool(enable_thinking),
            "use_json": bool(use_json),
        }
        if image_base64:
            payload["image_base64"] = image_base64

        event = encode_event("llm_request", payload)

        started = time.perf_counter()
        await self._send_request(ws_connection, request_id, event, future)
        try:
            result = await asyncio.wait_for(future, timeout=self.timeout_seconds)
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            raise ClientLLMTimeout(
                f"llm_request {request_id} timed out after {self.timeout_seconds}s",
                connection=ws_connection,
            ) from None
        finally:
            self._pending.pop(request_id, None)

        if isinstance(result, dict) and result.get("error"):
            raise ClientLLMError(str(result["error"]), connection=ws_connection)

        content = (result or {}).get("content")
        if content is None:
            raise ClientLLMError(
                f"llm_response {request_id} missing content",
                connection=ws_connection,
            )

        return {
            "content": str(content),
            "usage": (result or {}).get("usage"),
            "response_time_s": (time.perf_counter() - started),
        }

    async def _send_request(self, ws_connection, request_id, event, future) -> None:
        try:
            await ws_connection.send(event)
        except BaseException as exc:
            self._pending.pop(request_id, None)
            future.cancel()
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise ClientLLMUnavailable(
                f"failed to send llm_request {request_id}: {exc}",
                connection=ws_connection,
            ) from exc

    def on_llm_response(self, payload: Optional[Dict[str, Any]], *, connection=None) -> None:
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
        _, future, _owner = pending
        if connection is not None and _owner is not connection:
            return
        if future.done():
            return
        future.set_result(payload)
