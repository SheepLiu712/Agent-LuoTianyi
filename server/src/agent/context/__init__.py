"""角色交互上下文及其公开数据类型。"""

from .context_factory import ContextFactory
from .conversation_context import ConversationContext
from .interaction_context import InteractionContext
from .models import (
    AudioContent, CompactionPolicy, CompactionResult, ContextIdentity,
    ConversationEntry, ConversationSnapshot, ConversationSummarizer,
    ConversationSummary, ImageContent, JargonExplanation, RecallEntry,
    SongContent, TextContent, UserContextSnapshot, UserPreferences, UserProfile,
)
from .recalled_memory_context import RecalledMemoryContext
from .user_context import UserContext

__all__ = [
    "ContextFactory", "InteractionContext", "UserContext", "ConversationContext",
    "RecalledMemoryContext", "ContextIdentity", "UserProfile", "UserPreferences",
    "UserContextSnapshot", "ConversationEntry", "ConversationSummary",
    "ConversationSnapshot", "ConversationSummarizer", "CompactionPolicy",
    "CompactionResult", "TextContent", "ImageContent", "AudioContent", "SongContent",
    "RecallEntry", "JargonExplanation",
]
