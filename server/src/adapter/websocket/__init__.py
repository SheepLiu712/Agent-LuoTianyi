"""WebSocket 业务适配入口。"""

from .adapter import ChatEventAcceptance, EventRejection, WebSocketAdapter

__all__ = ["ChatEventAcceptance", "EventRejection", "WebSocketAdapter"]
