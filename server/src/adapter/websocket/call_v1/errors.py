"""通话 Adapter 的公开连接错误契约。"""

from ..connection import AdapterConnectionError


class CallTransportError(AdapterConnectionError):
    """携带稳定协议错误码和 WebSocket 关闭码的公开异常。"""

    def __init__(self, code: str, *, close_code: int = 1002) -> None:
        super().__init__(code, close_code=close_code)
