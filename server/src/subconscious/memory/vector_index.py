from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from src.system.database.vector_store import VectorStore, get_vector_store, init_vector_store


@dataclass
class MemoryVectorIndex:
    """Vector retrieval index owned by the subconscious memory subsystem."""

    vector_store: VectorStore

    @classmethod
    def initialize(cls, config: Dict[str, Any]) -> "MemoryVectorIndex":
        init_vector_store(config)
        return cls(vector_store=get_vector_store())
