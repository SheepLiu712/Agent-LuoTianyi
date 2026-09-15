"""明确记忆写入的正本权威、投影补偿与角色隔离契约。"""

import pytest

from src.subconscious.memory.memory_write import MemoryWriter
from src.system.database.vector_store import Document


class _VectorStore:
    def __init__(self):
        self.documents = []
        self.deleted = []
        self.next_id = 1

    def add_documents(self, documents):
        ids = []
        for document in documents:
            doc_id = f"vec-{self.next_id}"
            self.next_id += 1
            self.documents.append(Document(document.get_content(), dict(document.get_metadata()), id=doc_id))
            ids.append(doc_id)
        return ids

    async def search(self, user_id, query, k=5, **kwargs):
        where = kwargs.get("where") or {"user_id": user_id}
        hits = []
        for document in self.documents:
            metadata = document.get_metadata()
            if not all(metadata.get(key) == value for key, value in where.items()):
                continue
            score = 0.95 if query in document.get_content() else 0.1
            hits.append((document, score))
        return hits[:k]

    def delete_documents(self, doc_ids):
        self.deleted.extend(doc_ids)
        wanted = set(doc_ids)
        self.documents = [document for document in self.documents if document.id not in wanted]
        return True


class _MemoryStore:
    def __init__(self, *, fail_link=False):
        self.fail_link = fail_link
        self.updates = []
        self.records = []
        self.links = {}

    def write_memory_update(self, user_id, memory_update, commit=True):
        self.updates.append((user_id, memory_update, commit))

    def write_agent_memory_record(self, memory_record, *, chunk_texts=None, embedding_ids=None, commit=True):
        self.records.append((memory_record, list(embedding_ids or []), commit))
        return memory_record.id

    def link_agent_memory_embeddings(self, memory_record_id, *, chunk_texts, embedding_ids, commit=True):
        if self.fail_link:
            raise RuntimeError("canonical link failed")
        for embedding_id in embedding_ids:
            self.links[embedding_id] = memory_record_id

    def get_agent_memory_record_by_embedding_id(self, embedding_id):
        for record, _, _ in self.records:
            if self.links.get(embedding_id) == record.id:
                return record
        return None

    def get_agent_memory_records_by_embedding_ids(self, embedding_ids):
        return {
            embedding_id: self.get_agent_memory_record_by_embedding_id(embedding_id)
            for embedding_id in embedding_ids
            if self.get_agent_memory_record_by_embedding_id(embedding_id) is not None
        }

    def delete_agent_memory_record(self, memory_record_id, *, commit=True):
        self.records = [record for record in self.records if record[0].id != memory_record_id]


@pytest.mark.asyncio
async def test_commit_user_memory_cleans_vector_and_fails_when_projection_link_fails():
    writer = MemoryWriter({"user_memory_dedup_threshold": 0.72}, object())
    vector_store = _VectorStore()
    memory_store = _MemoryStore(fail_link=True)

    with pytest.raises(RuntimeError, match="canonical link failed"):
        await writer.commit_user_memory(vector_store, memory_store, "u", "我喜欢茶", "luotianyi")

    assert vector_store.documents == []
    assert vector_store.deleted == ["vec-1"]


@pytest.mark.asyncio
async def test_orphan_vector_redelivery_is_not_reported_as_committed():
    writer = MemoryWriter({"user_memory_dedup_threshold": 0.72}, object())
    vector_store = _VectorStore()
    vector_store.add_documents([Document("我喜欢茶", {
        "source": "memory_writer",
        "timestamp": "2026-09-15",
        "event_date": "2026-09-15",
        "memory_type": "user_memory",
        "user_id": "u",
        "owner_character_id": "luotianyi",
    })])
    memory_store = _MemoryStore()

    record_id, committed = await writer.commit_user_memory(vector_store, memory_store, "u", "我喜欢茶", "luotianyi")

    assert committed is True
    assert record_id
    assert len(memory_store.records) == 1
    assert len(vector_store.documents) == 2


@pytest.mark.asyncio
async def test_duplicate_redelivery_returns_same_canonical_record_without_new_record():
    writer = MemoryWriter({"user_memory_dedup_threshold": 0.72}, object())
    vector_store = _VectorStore()
    memory_store = _MemoryStore()

    first_id, first_committed = await writer.commit_user_memory(vector_store, memory_store, "u", "我喜欢茶", "luotianyi")
    second_id, second_committed = await writer.commit_user_memory(vector_store, memory_store, "u", "我喜欢茶", "luotianyi")

    assert first_committed is True
    assert second_committed is False
    assert second_id == first_id
    assert len(memory_store.records) == 1
    assert len(vector_store.documents) == 1


@pytest.mark.asyncio
async def test_user_memory_dedup_is_character_isolated_for_explicit_and_batch_paths():
    writer = MemoryWriter({"user_memory_dedup_threshold": 0.72}, object())
    vector_store = _VectorStore()
    miku_store = _MemoryStore()
    luo_store = _MemoryStore()

    assert (await writer.commit_user_memory(vector_store, miku_store, "u", "我喜欢茶", "miku"))[1] is True
    assert (await writer.commit_user_memory(vector_store, luo_store, "u", "我喜欢茶", "luotianyi"))[1] is True
    seen = await writer._batch_check_user_memory_dups(vector_store, "u", ["我喜欢茶"], "rin")

    assert seen == set()
    assert len(vector_store.documents) == 2


@pytest.mark.asyncio
async def test_legacy_write_user_memory_commit_false_keeps_boolean_success():
    writer = MemoryWriter({"user_memory_dedup_threshold": 0.72}, object())
    vector_store = _VectorStore()
    memory_store = _MemoryStore()

    written = await writer.write_user_memory(vector_store, memory_store, "u", "我喜欢茶", "luotianyi", commit=False)

    assert written is True
    assert memory_store.records[0][2] is False
    assert memory_store.updates[0][2] is False
