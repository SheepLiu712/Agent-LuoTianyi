"""仅供共享技能装配器使用的具名资源。"""

from dataclasses import dataclass
from typing import Mapping

from src.domain.character import CharacterProfile
from src.infrastructure.media import MediaResolver
from src.infrastructure.models.service import LLMService
from src.infrastructure.persistence.database import DatabaseManager
from src.infrastructure.persistence.database.vector_store import VectorStore


@dataclass(frozen=True)
class SkillResources:
    llm_service: LLMService
    database: DatabaseManager
    vector_store: VectorStore
    media_resolver: MediaResolver
    characters: Mapping[str, CharacterProfile]
