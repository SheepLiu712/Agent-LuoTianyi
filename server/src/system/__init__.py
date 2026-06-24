"""Application system services."""

__all__ = ["ConversationManager", "ConversationService"]


def __getattr__(name: str):
    if name == "ConversationManager":
        from src.chat_session.conversation import ConversationManager

        return ConversationManager
    if name == "ConversationService":
        from src.chat_session.conversation import ConversationService

        return ConversationService
    raise AttributeError(name)
