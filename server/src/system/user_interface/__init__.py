"""User-interface adapters for HTTP/WebSocket and future device channels."""

from .types import (
    RegisterRequest,
    LoginRequest,
    AutoLoginRequest,
    HistoryRequest,
    ImageRequest,
    ResetAccountRequest,
    WSEventType,
    PreferenceGetRequest,
    PreferenceOverwriteRequest,
)
from .user_interface import UserInterface

__all__ = ["WebSocketConnection", "WebSocketService", "account", "get_websocket_service"]
