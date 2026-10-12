"""向量库用户记录删除：分页完整删除，且失败必须抛出而不是返回 0 伪装成功。"""

import logging

import pytest

from src.infrastructure.persistence.database.vector_store import ChromaVectorStore


class _Collection:
    MAX_GET_CALLS = 20

    def __init__(
        self,
        ids,
        *,
        fail_on_delete=False,
        delete_is_noop=False,
        partial_delete_ratio=1.0,
        report_delete_count=True,
    ):
        self.ids = list(ids)
        self.deleted = []
        self.fail_on_delete = fail_on_delete
        self.delete_is_noop = delete_is_noop
        self.partial_delete_ratio = partial_delete_ratio
        self.report_delete_count = report_delete_count
        self.includes = []
        self.get_calls = 0
        self.page_sizes = []
        self.removed_counts = []

    def get(self, *, where, limit, include=None):
        assert where == {"user_id": "user-1"}
        # 上界保证：实现缺少“无进展”护栏时测试也必须在有限步内失败，而不是把 pytest 挂死。
        self.get_calls += 1
        if self.get_calls > self.MAX_GET_CALLS:
            raise AssertionError("pagination did not terminate")
        self.includes.append(include)
        page = self.ids[:limit]
        self.page_sizes.append(len(page))
        return {"ids": page}

    def delete(self, *, ids):
        if self.fail_on_delete:
            raise RuntimeError("chroma unavailable")
        self.deleted.extend(ids)
        if self.delete_is_noop:
            return self._delete_result(0)
        removed = set(ids)
        if self.partial_delete_ratio < 1.0:
            # 只删掉一部分：模拟后端删不干净，剩余条目会在下一页重新出现。
            remove_count = max(1, int(len(removed) * self.partial_delete_ratio))
            removed = set(sorted(removed)[:remove_count])
        self.ids = [item for item in self.ids if item not in removed]
        self.removed_counts.append(len(removed))
        return self._delete_result(len(removed))

    def _delete_result(self, removed: int):
        # 模拟有/无计数两种返回形式；此 fake 的移除计数不代表真实 Chroma 的计数语义。
        if not self.report_delete_count:
            return None
        return {"deleted": removed}


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
    assert collection.page_sizes == [1000, 1000, 500, 0]
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


@pytest.mark.parametrize("report_delete_count", [True, False])
def test_delete_user_records_verifies_a_short_final_page(report_delete_count):
    """正常短页也必须删后再查空，不能仅凭页长或返回计数提前结束。"""
    collection = _Collection([f"doc-{index}" for index in range(500)], report_delete_count=report_delete_count)

    assert _store(collection).delete_user_records("user-1") == 500
    assert collection.page_sizes == [500, 0]


@pytest.mark.parametrize("delete_result", [None, {"deleted": 500}])
def test_delete_user_records_rejects_an_unchanged_short_page(delete_result):
    """模拟删除未生效：无返回值或只报告接收数量，都须由重新查询识别未清空。"""
    collection = _Collection([f"doc-{index}" for index in range(500)])
    collection.delete = lambda *, ids: delete_result

    with pytest.raises(RuntimeError, match="made no progress"):
        _store(collection).delete_user_records("user-1")
    assert collection.page_sizes == [500, 500]


def test_delete_user_records_resumes_partial_deletes_until_empty():
    """后端只删掉一部分不是失败：剩余条目会在下一页重新出现，继续删到空，条数按实际删除累计。"""
    collection = _Collection([f"doc-{index}" for index in range(1000)], partial_delete_ratio=0.6)
    store = _store(collection)

    deleted = store.delete_user_records("user-1")

    assert deleted == 1000
    assert collection.ids == []
    assert collection.removed_counts[0] == 600
    assert collection.page_sizes[-1] == 0


def test_delete_user_records_detects_no_progress_without_a_reported_count():
    """后端不报告删除条数时，用“同一批 id 又被查了出来”兜底判为没有进展。"""
    collection = _Collection(
        [f"doc-{index}" for index in range(1000)],
        delete_is_noop=True,
        report_delete_count=False,
    )
    store = _store(collection)

    with pytest.raises(RuntimeError, match="made no progress"):
        store.delete_user_records("user-1")


def test_delete_user_records_legacy_backend_keeps_resuming_partial_deletes():
    """不报告条数的旧后端碰到部分删除时，也必须在有限步内删空而不是误判失败。"""
    collection = _Collection(
        [f"doc-{index}" for index in range(500)],
        partial_delete_ratio=0.5,
        report_delete_count=False,
    )
    store = _store(collection)

    assert store.delete_user_records("user-1") == 500
    assert collection.ids == []
    assert collection.page_sizes[-1] == 0


def test_delete_user_records_detects_alternating_stale_pages_without_a_reported_count():
    """旧后端在 A→B→A 之间交替返回陈旧页时也必须终止，而不是无限重放。"""

    class _Alternating:
        MAX_GET_CALLS = 8

        def __init__(self):
            self.calls = 0

        def get(self, *, where, limit, include=None):
            self.calls += 1
            if self.calls > self.MAX_GET_CALLS:
                raise AssertionError("pagination did not terminate")
            return {"ids": ["doc-1"] if self.calls % 2 else ["doc-2"]}

        def delete(self, *, ids):
            return None

    store = _store(_Alternating())

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
