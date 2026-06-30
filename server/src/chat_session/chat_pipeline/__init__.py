"""Chat stream pipeline components."""

from src.domain.chat import ChatInputEvent, ChatInputEventType, ExtractedTopic

__all__ = [
    "ChatInputEvent",
    "ChatInputEventType",
    "ExtractedTopic",
    "TopicPlanner",
    "TopicReplier",
]


def __getattr__(name: str):
    if name == "TopicPlanner":
        from src.chat_session.chat_pipeline.topic_planner import TopicPlanner

        return TopicPlanner
    if name == "TopicReplier":
        from src.chat_session.chat_pipeline.topic_replier import TopicReplier

        return TopicReplier
    raise AttributeError(name)
