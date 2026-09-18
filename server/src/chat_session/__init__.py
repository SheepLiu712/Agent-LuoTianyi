"""Chat-session orchestration layer."""

__all__ = [
    "CallStreamManager",
]

def __getattr__(name: str):
    if name == "CallStreamManager":
        from src.chat_session.call_stream_manager import CallStreamManager

        return CallStreamManager
    raise AttributeError(name)
