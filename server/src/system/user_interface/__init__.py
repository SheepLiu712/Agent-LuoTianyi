"""User-interface adapters for HTTP/WebSocket and future device channels."""

from src.system.user_interface import account
from src.system.user_interface.types import *  # noqa: F403
from src.system.user_interface.websocket_service import WebSocketConnection, WebSocketService, get_websocket_service

__all__ = ["WebSocketConnection", "WebSocketService", "account", "get_websocket_service"]
