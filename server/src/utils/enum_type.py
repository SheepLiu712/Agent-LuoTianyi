from enum import Enum

class ContextType(str, Enum):
    TEXT = "text"
    SING = "sing"
    CMD = "cmd"
    IMAGE = "image"
    CALL = "call"


class ConversationSource(str, Enum):
    USER = "user",
    AGENT = "agent",
    SYSTEM = "system",

