"""向量库用户记录删除：分页完整删除，且失败必须抛出而不是返回 0 伪装成功。"""

import logging

import pytest

from src.infrastructure.persistence.database.vector_store import ChromaVectorStore


class _Collection:
    MAX_GET_CALLS = 20

    def __init__(self, ids, *, fail_on_delete=False, delete_is_noop=False):
        self.ids = list(ids)
        self.deleted = []
        self.fail_on_delete = fail_on_delete
        self.delete_is_noop = delete_is_noop
        self.includes = []
        self.get_calls = 0

    def get(self, *, where, limit, include=None):
        assert where == {"user_id": "user-1"}
        # 上界保证：实现缺少“无进展”护栏时测试也必须在有限步内失败，而不是把 pytest 挂死。
        self.get_calls += 1
        if self.get_calls > self.MAX_GET_CALLS:
            raise AssertionError("pagination did not terminate")
        self.includes.append(include)
        return {"ids": self.ids[:limit]}

    def delete(self, *, ids):
        if self.fail_on_delete:
            raise RuntimeError("chroma unavailable")
        self.deleted.extend(ids)
        if self.delete_is_noop:
            return
        removed = set(ids)
        self.ids = [item for item in self.ids if item not in removed]


def _store(collection) -> ChromaVectorStore:
    store = ChromaVectorStore.__new__(ChromaVectorStore)
    store.collection = collection
    store.logger = logging.getLogger("test.vector_store")
    return store


def test_delete_user_records_removes_every_page():
    collection = _Collection([f"doc-{index}" for index in range(2500)])
    store = _store(collection)

    deleted = store.delete_user_records("user-1")

    assert deleted == 2500
    assert collection.ids == []
    # 分页大小有上限，必须多轮才能删完，证明没有静默截断。
    assert len(collection.deleted) == 2500
    # 删除路径只取 id，不把 document/metadata/embedding 拉进内存。
    assert collection.includes and all(item == [] for item in collection.includes)


def test_delete_user_records_reports_zero_for_an_empty_account():
    store = _store(_Collection([]))

    assert store.delete_user_records("user-1") == 0


def test_delete_user_records_raises_instead_of_returning_fake_success():
    store = _store(_Collection(["doc-1"], fail_on_delete=True))

    with pytest.raises(RuntimeError, match="chroma unavailable"):
        store.delete_user_records("user-1")


def test_delete_user_records_fails_fast_when_the_backend_deletes_nothing():
    """软删/最终一致后端不得让分页循环无限重放同一页。"""
    store = _store(_Collection([f"doc-{index}" for index in range(1000)], delete_is_noop=True))

    with pytest.raises(RuntimeError, match="made no progress"):
        store.delete_user_records("user-1")


def test_delete_user_records_contract_against_real_chroma():
    """用真实 chromadb 校验 get(where, limit, include)/delete(ids) 契约与多页删除（单页上限 1000）。"""
    import chromadb

    client = chromadb.EphemeralClient()
    collection = client.create_collection("audit-user-records", embedding_function=None)
    total = 2500
    collection.add(
        ids=[f"doc-{index}" for index in range(total)],
        embeddings=[[float(index % 5), 1.0] for index in range(total)],
        metadatas=[{"user_id": "user-1" if index % 3 else "user-2"} for index in range(total)],
    )
    store = _store(collection)
    expected = sum(1 for index in range(total) if index % 3)

    deleted = store.delete_user_records("user-1")

    # 必须超过单页上限，才真正覆盖分页分支。
    assert deleted == expected > 1000
    assert collection.get(where={"user_id": "user-1"}, limit=10)["ids"] == []
    assert len(collection.get(where={"user_id": "user-2"}, limit=total + 10)["ids"]) == total - deleted
