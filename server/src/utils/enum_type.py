from enum import Enum

class ContextType(str, Enum):
    TEXT = "text"
    SING = "sing"
    CMD = "cmd"
    IMAGE = "image"


class ConversationSource(str, Enum):
    USER = "user",
    AGENT = "agent",
    SYSTEM = "system",

