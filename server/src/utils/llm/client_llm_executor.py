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

from src.utils.logger import get_logger


LLM_REQUEST_EVENT_TYPE = "llm_request"

logger = get_logger(__name__)


class ClientLLMExecutionError(Exception):
    """客户端执行 LLM 调用失败（未连接 / 超时 / 客户端返回错误）。"""

    def __init__(self, message: str = "", connection: Any = None):
        super().__init__(message)
        # 发起该请求的连接，用于把失败通知发回正确的客户端
        self.connection = connection


class ClientLLMUnavailable(ClientLLMExecutionError):
    """用户没有可用的在线客户端连接。"""


class ClientLLMTimeout(ClientLLMExecutionError):
    """等待客户端返回 LLM 响应超时。"""


class ClientLLMError(ClientLLMExecutionError):
    """客户端执行 LLM 调用时返回了错误。"""


_KEY_ERROR_MARKERS = (
    "401",
    "403",
    "invalid api key",
    "api key",
    "authentication",
    "unauthorized",
    "access denied",
    "bad key",
    "permission denied",
    "arrearage",
    "overdue payment",
    "account in good standing",
    "no api key configured",
)


def _looks_like_key_error(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _KEY_ERROR_MARKERS)


def build_fallback_notice(exc: Exception) -> str:
    """生成客户端执行失败后的聊天信息提示（含回退说明）。"""
    text = str(exc or "")
    if _looks_like_key_error(text):
        return "你的 LLM API Key 或账户存在问题（无效/未授权/欠费等），已自动改用服务端配置继续处理。"
    reason = " ".join((text or "").split())
    if len(reason) > 120:
        reason = reason[:117] + "..."
    return f"客户端模型调用失败（{reason or '未知错误'}），已自动改用服务端配置继续处理。"


async def notify_fallback(executor: "ClientLLMExecutor", user_id: Optional[str], module: str, exc: Exception) -> None:
    """向用户发送客户端委托失败的信息提示；后台任务（无 user_id）只记录日志。"""
    if not user_id:
        logger.warning(
            "Client delegation failed for module %s (no user to notify): %s",
            module,
            exc,
        )
        return
    await executor.notify_user(
        user_id,
        build_fallback_notice(exc),
        connection=getattr(exc, "connection", None),
    )


class ClientLLMExecutor:
    """服务端单例：向用户的客户端转发 LLM 请求并等待响应。"""

    def __init__(self, timeout_seconds: float = 120.0):
        self.timeout_seconds = float(timeout_seconds)
        self.logger = get_logger(__name__)
        self._stream_manager: Any = None
        # request_id -> (user_id, asyncio.Future, 发起请求的连接)
        self._pending: Dict[str, tuple[str, asyncio.Future, Any]] = {}
        # user_id -> 最近一次处理该用户请求的连接（用于把失败通知发回正确的客户端）
        self._user_connections: Dict[str, Any] = {}

    def bind(self, stream_manager: Any) -> None:
        """绑定 ChatStreamManager，用于按 user_id 找到在线连接。"""
        self._stream_manager = stream_manager

    def is_enabled(self, user_id: Optional[str], model_type: Optional[str]) -> bool:
        """判断该用户当前活跃连接是否声明了指定客户端委托类型。"""
        if not model_type:
            return False
        ws_connection = self._get_live_connection(user_id)
        mode = getattr(ws_connection, "client_mode", None) or {}
        return model_type in (mode.get("types") or [])

    def _get_live_connection(self, user_id: Optional[str]):
        """返回该用户活跃连接的 WebSocketConnection；没有则返回 None。"""
        if not user_id or self._stream_manager is None:
            return None
        stream = self._stream_manager.get_stream_by_user_uuid(user_id)
        if stream is None or stream.is_connection_lost():
            return None
        ws_connection = getattr(stream, "ws_connection", None)
        if ws_connection is None or getattr(ws_connection, "websocket", None) is None:
            return None
        return ws_connection

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
            event = {
                "type": "error",
                "ts": int(time.time() * 1000),
                "payload": {"code": "LLM_CLIENT_ERROR", "message": message},
            }
            await ws_connection.websocket.send_json(event)
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
        ws_connection = self._get_live_connection(user_id)
        if ws_connection is None:
            return None
        mode = getattr(ws_connection, "client_mode", None) or {}
        if model_type not in (mode.get("types") or []):
            return None

        self._user_connections[user_id] = ws_connection
        websocket = ws_connection.websocket

        request_id = f"llm-{uuid.uuid4().hex[:16]}"
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[request_id] = (user_id, future, ws_connection)

        payload: Dict[str, Any] = {
            "request_id": request_id,
            "module": module,
            "type": model_type,
            "prompt": prompt,
            "params": dict(params or {}),
            "enable_thinking": bool(enable_thinking),
            "use_json": bool(use_json),
        }
        if image_base64:
            payload["image_base64"] = image_base64

        event = {
            "type": LLM_REQUEST_EVENT_TYPE,
            "ts": int(time.time() * 1000),
            "payload": payload,
        }

        started = time.perf_counter()
        try:
            await websocket.send_json(event)
        except Exception as exc:
            self._pending.pop(request_id, None)
            raise ClientLLMUnavailable(
                f"failed to send llm_request {request_id}: {exc}",
                connection=ws_connection,
            ) from exc
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
        _, future, _owner = pending
        if future.done():
            return
        future.set_result(payload)
