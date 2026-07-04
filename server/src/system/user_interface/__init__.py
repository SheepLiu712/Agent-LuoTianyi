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


def __getattr__(name: str):
    if name == "UserInterface":
        from .user_interface import UserInterface

        return UserInterface
    raise AttributeError(name)
