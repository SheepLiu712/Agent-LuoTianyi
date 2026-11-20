"""公开向量工厂的禁用资源与真实能力契约。"""

import pytest

from src.infrastructure.persistence.database import vector_store as stores


@pytest.mark.asyncio
async def test_disabled_factory_does_not_construct_resources_or_create_directory(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("disabled vector store must not construct Chroma, embedding or its executor")

    monkeypatch.setattr(stores, "ThreadPoolExecutor", forbidden)
    monkeypatch.setattr(stores, "SiliconFlowEmbeddings", forbidden)
    monkeypatch.setattr(stores.chromadb, "PersistentClient", forbidden)
    monkeypatch.setattr(stores, "vector_store", None)
    path = tmp_path / "uncreated-vectors"

    store = stores.init_vector_store({"enabled": False, "vector_store_path": str(path)})

    assert store.enabled is False
    assert stores.get_vector_store() is store
    assert not path.exists()
    assert await store.search("u", "query") == []
    assert store.get_document_by_id(["missing"]) == []
    store.close()
    store.close()
    assert stores.clear_vector_store(store)


@pytest.mark.parametrize("value", [0, 1, None, "false", [], {}])
def test_factory_rejects_non_boolean_enabled_before_backend(tmp_path, monkeypatch, value):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid configuration reached Chroma")

    monkeypatch.setattr(stores, "ChromaVectorStore", forbidden)
    with pytest.raises(TypeError, match=r"agent_runtime.vector_store.enabled"):
        stores.VectorStoreFactory.create_vector_store("chroma", {"enabled": value})


@pytest.mark.parametrize("config", [{}, {"enabled": True}])
def test_factory_omitted_or_true_enabled_selects_original_backend(monkeypatch, config):
    created = []
    sentinel = object()

    def backend(value):
        created.append(value)
        return sentinel

    monkeypatch.setattr(stores, "ChromaVectorStore", backend)
    assert stores.VectorStoreFactory.create_vector_store("chroma", config) is sentinel
    assert created == [config]


@pytest.mark.asyncio
async def test_disabled_writes_and_embedding_are_not_fake_success(tmp_path):
    store = stores.VectorStoreFactory.create_vector_store("unused", {"enabled": False})
    document = stores.Document("事实", {"user_id": "u"})
    for operation in (
        lambda: store.add_documents([document]),
        lambda: store.upsert_documents([document], ["fake"]),
        lambda: store.update_document("fake", document),
    ):
        with pytest.raises(stores.VectorStoreDisabledError):
            operation()
    with pytest.raises(stores.VectorStoreDisabledError):
        await store.embed_query("事实")
    with pytest.raises(stores.VectorStoreDisabledError):
        await store.prepare_embeddings(["事实"])


@pytest.mark.parametrize("existing", [False, True])
def test_disabled_strict_delete_is_zero_only_for_known_empty_path(tmp_path, existing):
    path = tmp_path / "vectors"
    if existing:
        path.mkdir()
    store = stores.VectorStoreFactory.create_vector_store("chroma", {"enabled": False, "vector_store_path": str(path)})

    assert store.delete_user_records_strict("u") == 0
    assert path.exists() is existing


def test_disabled_strict_delete_preserves_old_index_and_reports_unavailable(tmp_path):
    path = tmp_path / "vectors"
    path.mkdir()
    data = path / "old-index"
    data.write_bytes(b"retained")
    store = stores.VectorStoreFactory.create_vector_store("chroma", {"enabled": False, "vector_store_path": str(path)})

    with pytest.raises(stores.VectorDeletionUnavailable):
        store.delete_user_records_strict("u")
    assert data.read_bytes() == b"retained"


def test_disabled_strict_delete_reports_unknown_path_state(tmp_path, monkeypatch):
    from pathlib import Path

    store = stores.VectorStoreFactory.create_vector_store(
        "chroma", {"enabled": False, "vector_store_path": str(tmp_path)}
    )

    def denied(*args, **kwargs):
        raise PermissionError("unreadable")

    monkeypatch.setattr(Path, "stat", denied)
    with pytest.raises(stores.VectorDeletionUnavailable):
        store.delete_user_records_strict("u")
