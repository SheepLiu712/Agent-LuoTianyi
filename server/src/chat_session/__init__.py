"""Chat-session orchestration layer."""

__all__ = [
    "CallStreamManager",
    "ChatSessionManager",
    "ChatStreamManager",
    "ReflexPipeline",
]

from src.chat_session.chat_session_manager import ChatSessionManager

def __getattr__(name: str):
    if name == "CallStreamManager":
        from src.chat_session.call_stream_manager import CallStreamManager

        return CallStreamManager
    if name == "ChatSessionManager":
        from src.chat_session.chat_session_manager import ChatSessionManager

        return ChatSessionManager
    if name == "ChatStreamManager":
        from src.chat_session.chat_stream_manager import ChatStreamManager

        return ChatStreamManager
    if name == "ReflexPipeline":
        from src.chat_session.reflex_pipeline import ReflexPipeline

        return ReflexPipeline
    raise AttributeError(name)
