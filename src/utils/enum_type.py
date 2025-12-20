from enum import Enum

class ContextType(str, Enum):
    TEXT = "text",
    CMD = "cmd",

class ConversationSource(str, Enum):
    USER = "user",
    AGENT = "agent",
    SYSTEM = "system",

