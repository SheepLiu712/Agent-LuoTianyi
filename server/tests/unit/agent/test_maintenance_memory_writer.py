import pytest

from src.agent.skills.adapters.memory.writer import MemoryWriter
from src.domain.agent.maintenance import MaintenanceCandidate, MaintenanceMemoryType


class LLM:
    async def generate_response(self, **kwargs):
        return '{"user_memory":["喜欢茶"],"event_memory":["今天散步"]}'


class VectorStore:
    def __init__(self):
        self.documents = {}

    def upsert_documents(self, documents, ids):
        for document, identity in zip(documents, ids):
            existing = self.documents.get(identity)
            value = (document.get_content(), document.get_metadata())
            if existing is not None and existing != value:
                raise ValueError("vector conflict")
            self.documents[identity] = value
        return ids


class MemoryStore:
    def __init__(self):
        self.records = {}
        self.links = {}

    def write_agent_memory_record_if_absent(self, record):
        existing = self.records.get(record.id)
        if existing is not None and existing.content != record.content:
            raise ValueError("record conflict")
        self.records[record.id] = record
        return existing is None

    def link_agent_memory_embeddings(self, record_id, *, chunk_texts, embedding_ids):
        value = (record_id, tuple(chunk_texts))
        for identity in embedding_ids:
            existing = self.links.get(identity)
            if existing is not None and existing != value:
                raise ValueError("link conflict")
            self.links[identity] = value


@pytest.mark.asyncio
async def test_candidate_extraction_keeps_stable_type_order():
    writer = MemoryWriter({}, LLM())
    candidates = await writer.extract_maintenance_candidates(history="旧", current_dialogue="新")
    assert candidates == (
        MaintenanceCandidate(MaintenanceMemoryType.USER_FACT, "喜欢茶"),
        MaintenanceCandidate(MaintenanceMemoryType.INTERACTION_EVENT, "今天散步"),
    )


@pytest.mark.asyncio
async def test_retry_same_candidates_does_not_increase_canonical_or_vector_count():
    writer = MemoryWriter({}, LLM())
    vector_store, memory_store = VectorStore(), MemoryStore()
    candidates = (MaintenanceCandidate(MaintenanceMemoryType.USER_FACT, "喜欢茶"),)
    kwargs = dict(
        vector_store=vector_store,
        memory_store=memory_store,
        user_id="u",
        owner_character_id="luotianyi",
        maintenance_id="batch",
        candidates=candidates,
    )
    await writer.write_maintenance_candidates(**kwargs)
    await writer.write_maintenance_candidates(**kwargs)
    assert len(memory_store.records) == len(memory_store.links) == len(vector_store.documents) == 1


@pytest.mark.asyncio
async def test_retry_changed_candidate_content_is_rejected():
    writer = MemoryWriter({}, LLM())
    vector_store, memory_store = VectorStore(), MemoryStore()
    common = dict(
        vector_store=vector_store,
        memory_store=memory_store,
        user_id="u",
        owner_character_id="luotianyi",
        maintenance_id="batch",
    )
    await writer.write_maintenance_candidates(
        **common,
        candidates=(MaintenanceCandidate(MaintenanceMemoryType.USER_FACT, "喜欢茶"),),
    )
    with pytest.raises(ValueError, match="record conflict"):
        await writer.write_maintenance_candidates(
            **common,
            candidates=(MaintenanceCandidate(MaintenanceMemoryType.USER_FACT, "喜欢咖啡"),),
        )
