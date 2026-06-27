"""Application system services."""

__all__ = ["ConversationService"]


def __getattr__(name: str):
    if name == "ConversationService":
        from src.chat_session.conversation import ConversationService

        return ConversationService
    raise AttributeError(name)
