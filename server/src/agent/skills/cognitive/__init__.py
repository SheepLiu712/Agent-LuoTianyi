"""Agent 私有的认知类共享技能。"""

from src.agent.skills.contracts import ComposedReply, ComposedResponse, ReplyDraft

from .image_understanding import ImageUnderstandingSkill
from .intentional_memory import ExplicitMemoryIntentSkill
from .response_composition import ResponseCompositionSkill
from .response_generation import CharacterReplyGenerator
from .song_entity_linker import SongEntityLinker
from .text_preprocessing import TextPreprocessingSkill

__all__ = [
    "CharacterReplyGenerator",
    "ComposedReply",
    "ComposedResponse",
    "ExplicitMemoryIntentSkill",
    "ImageUnderstandingSkill",
    "ReplyDraft",
    "ResponseCompositionSkill",
    "SongEntityLinker",
    "TextPreprocessingSkill",
]
