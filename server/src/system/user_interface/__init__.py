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

__all__ = [
    "RegisterRequest",
    "LoginRequest",
    "AutoLoginRequest",
    "HistoryRequest",
    "ImageRequest",
    "ResetAccountRequest",
    "WSEventType",
    "PreferenceGetRequest",
    "PreferenceOverwriteRequest",
    "UserInterface",
]


from .user_interface import UserInterface
