"""Subconscious layer.

This package keeps imports lazy so lightweight modules such as attention
planning can be loaded without also importing optional runtime integrations.
"""

__all__ = [
    "AttentionPlanner",
    "CharacterSubconscious",
    "ChatPreprocessor",
    "DateDetector",
    "MemoryUpdateService",
    "SongEntityLinker",
    "SubconsciousMemory",
    "SubconsciousState",
    "TopicAttentionPlan",
    "TopicExtractor",
    "extract_song_entities",
    "get_today_important_dates",
    "process_detected_date",
]


def __getattr__(name: str):
    if name in {"AttentionPlanner", "TopicAttentionPlan"}:
        from src.subconscious import attention

        return getattr(attention, name)
    if name == "CharacterSubconscious":
        from src.subconscious.character_mind import CharacterSubconscious

        return CharacterSubconscious
    if name == "ChatPreprocessor":
        from src.subconscious.preprocessing import ChatPreprocessor

        return ChatPreprocessor
    if name in {"DateDetector", "get_today_important_dates", "process_detected_date"}:
        from src.subconscious import date_processor

        return getattr(date_processor, name)
    if name in {"MemoryUpdateService", "SubconsciousMemory"}:
        from src.subconscious import memory

        return getattr(memory, name)
    if name in {"SongEntityLinker", "extract_song_entities"}:
        from src.subconscious.music_knowledge import jargon

        return getattr(jargon, name)
    if name == "SubconsciousState":
        from src.subconscious.state import SubconsciousState

        return SubconsciousState
    if name == "TopicExtractor":
        from src.subconscious.topic_extractor import TopicExtractor

        return TopicExtractor
    raise AttributeError(name)
