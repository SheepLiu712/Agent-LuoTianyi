"""主动重新导入 SQL-only 记忆后可检索，且去重和失败补偿仍成立。"""

import asyncio
import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import event

from src.infrastructure.persistence.database.services.memory_store import MemoryStore
from src.infrastructure.persistence.database.sql_database import AgentMemoryRecord, MemoryChunkRecord
from src.infrastructure.persistence.database.vector_store import ChromaVectorStore, DisabledVectorStore, Document

_shared_spec = importlib.util.spec_from_file_location(
    "transfer_projection_shared", Path(__file__).with_name("test_user_data_transfer.py")
)
shared = importlib.util.module_from_spec(_shared_spec)
_shared_spec.loader.exec_module(shared)


@pytest.fixture
def transfer(tmp_path):
    generator = shared.transfer.__wrapped__(tmp_path)
    state = next(generator)
    try:
        yield state
    finally:
        generator.close()
        state.sessions.kw["bind"].dispose()


def _use_vectors(state, vectors):
    state.service._vectors = vectors
    state.service._projections.vector_store = vectors


def _import(state, data):
    view = shared.preview(state, data)
    response = shared.commit(state, view)
    assert response.status_code == 200, response.text
    return view, response.json()


def _restore_without_vectors(state, tmp_path, keep_chunks=True):
    shared.seed_native(state)
    exported = state.client.get("/user/data/export?scope=memory", headers=state.headers("alice"))
    assert exported.status_code == 200, exported.text
    _use_vectors(state, DisabledVectorStore({"vector_store_path": str(tmp_path / "disabled-empty-vectors")}))
    _, result = _import(state, exported.content)
    assert result["success"] and result["imported"]["memories"] == 1 and result["warnings"]
    if not keep_chunks:
        # 普通 SQL-only 写入也允许没有分块；模拟这一合法持久状态。
        with state.sessions.begin() as db:
            ids = [row.id for row in db.query(AgentMemoryRecord).filter_by(subject_user_id="bob")]
            db.query(MemoryChunkRecord).filter(MemoryChunkRecord.memory_record_id.in_(ids)).delete()
    return exported.content


def _bob_links(state):
    with state.sessions() as db:
        records = db.query(AgentMemoryRecord).filter_by(subject_user_id="bob").all()
        chunks = db.query(MemoryChunkRecord).filter(MemoryChunkRecord.memory_record_id.in_([row.id for row in records]))
        return [row.content for row in records], [(row.chunk_text, row.embedding_id) for row in chunks]


@pytest.mark.parametrize("keep_chunks", [True, False])
def test_http_enabled_merge_links_sql_only_memory_without_duplicates(transfer, tmp_path, keep_chunks):
    data = _restore_without_vectors(transfer, tmp_path, keep_chunks)
    _use_vectors(transfer, transfer.vectors)
    _, result = _import(transfer, data)
    assert result["success"] and result["committed"] and result["warnings"] == []
    assert result["imported"]["memories"] == 0 and result["skipped"]["memories"] == 1
    contents, links = _bob_links(transfer)
    assert contents == ["用户喜欢薄荷"]
    assert len(links) == 1 and links[0][1] is not None
    assert [row["content"] for row in transfer.vectors.list_user_documents("bob")] == ["用户喜欢薄荷"]
    assert transfer.vectors.rows[links[0][1]]["content"] == links[0][0]
    before = deepcopy(transfer.vectors.rows)
    _, repeated = _import(transfer, data)
    assert repeated["success"] and repeated["skipped"]["memories"] == 1
    assert _bob_links(transfer) == (contents, links) and transfer.vectors.rows == before


def test_http_enabled_merge_restores_real_chroma_recall_and_is_idempotent(transfer, tmp_path, monkeypatch):
    data = _restore_without_vectors(transfer, tmp_path)
    vectors = ChromaVectorStore(
        {"vector_store_path": str(tmp_path / "real-vectors"), "embedding_model": {"api_key": "test-no-network"}}
    )

    async def prepare(texts):
        return [[1.0, 0.5] for _ in texts]

    monkeypatch.setattr(vectors, "prepare_embeddings", prepare)
    _use_vectors(transfer, vectors)
    try:
        vectors.upsert_documents(
            [Document("另一个账号的事实", {"user_id": "alice"}, id="other")], ["other"], embeddings=[[0.25, 1.0]]
        )
        _, result = _import(transfer, data)
        assert result["success"] and result["skipped"]["memories"] == 1
        store = MemoryStore({}, transfer.sessions, transfer.redis)
        identities = store.get_scoped_embedding_ids(
            "luotianyi", "bob", include_user=True, include_character=False, legacy_ids=set()
        )
        assert len(identities) == 1
        hits = asyncio.run(vectors.search("bob", "用户喜欢什么", k=1, ids=identities, query_embedding=[1.0, 0.5]))
        assert len(hits) == 1 and hits[0][0].get_content() == "用户喜欢薄荷"
        assert store.get_agent_memory_record_by_embedding_id(hits[0][0].id).subject_user_id == "bob"
        assert [row["id"] for row in vectors.list_user_documents("alice")] == ["other"]
        before = vectors.list_user_documents("bob")
        _, repeated = _import(transfer, data)
        assert repeated["success"] and vectors.list_user_documents("bob") == before
        assert len(_bob_links(transfer)[1]) == 1
    finally:
        vectors.close()


@pytest.mark.parametrize("failure", ["prepare", "publish", "sql_commit"])
def test_http_projection_completion_failure_preserves_sql_and_vectors(transfer, tmp_path, monkeypatch, failure):
    data = _restore_without_vectors(transfer, tmp_path)
    _use_vectors(transfer, transfer.vectors)
    transfer.vectors.rows["untouched"] = {
        "id": "untouched",
        "content": "包外旧向量",
        "metadata": {"user_id": "bob"},
        "embedding": [0.25, 1.0],
    }
    before_sql, before_vectors = _bob_links(transfer), deepcopy(transfer.vectors.rows)
    original_prepare = transfer.vectors.prepare_embeddings

    async def fail_prepare(texts):
        raise OSError("controlled prepare failure")

    def fail_commit(session):
        raise OSError("controlled SQL commit failure")

    if failure == "prepare":
        monkeypatch.setattr(transfer.vectors, "prepare_embeddings", fail_prepare)
    elif failure == "publish":
        transfer.vectors.fail_once = True
    else:
        event.listen(transfer.sessions.class_, "before_commit", fail_commit)
    try:
        view, result = _import(transfer, data)
    finally:
        if failure == "sql_commit":
            event.remove(transfer.sessions.class_, "before_commit", fail_commit)
    assert result["success"] is False and result["committed"] is False
    assert result.get("rollback_error") is None
    assert _bob_links(transfer) == before_sql and transfer.vectors.rows == before_vectors
    assert transfer.repository.receipt("bob", view["preview_id"]) is None
    monkeypatch.setattr(transfer.vectors, "prepare_embeddings", original_prepare)
    _, retried = _import(transfer, data)
    assert retried["success"] and _bob_links(transfer)[1][0][1] is not None
    assert transfer.vectors.rows["untouched"] == before_vectors["untouched"]
