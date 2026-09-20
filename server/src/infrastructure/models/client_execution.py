"""客户端模型委托的中立 interface 与错误语义。"""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol

from src.utils.logger import get_logger

logger = get_logger(__name__)


class ClientLLMExecutionError(Exception):
    """客户端执行模型调用失败。"""

    def __init__(self, message: str = "", connection: Any = None):
        super().__init__(message)
        self.connection = connection


class ClientLLMUnavailable(ClientLLMExecutionError):
    """用户没有可用的在线客户端连接。"""


class ClientLLMTimeout(ClientLLMExecutionError):
    """等待客户端返回模型响应超时。"""


class ClientLLMError(ClientLLMExecutionError):
    """客户端执行模型调用时返回了错误。"""


class ClientModelExecutor(Protocol):
    """模型模块可选使用的客户端委托 seam。"""

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
        """把一次模型调用委托给用户客户端；不可用时返回 ``None``。"""

    async def notify_user(self, user_id: str, message: str, connection: Any = None) -> None:
        """向本次委托所属连接发送降级通知。"""


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
    """生成客户端执行失败后的聊天提示。"""
    text = str(exc or "")
    if _looks_like_key_error(text):
        return "你的 LLM API Key 或账户存在问题（无效/未授权/欠费等），已自动改用服务端配置继续处理。"
    reason = " ".join((text or "").split())
    if len(reason) > 120:
        reason = reason[:117] + "..."
    return f"客户端模型调用失败（{reason or '未知错误'}），已自动改用服务端配置继续处理。"


async def notify_fallback(
    executor: ClientModelExecutor,
    user_id: Optional[str],
    module: str,
    exc: Exception,
) -> None:
    """通知用户客户端委托已降级；后台任务只记录日志。"""
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
