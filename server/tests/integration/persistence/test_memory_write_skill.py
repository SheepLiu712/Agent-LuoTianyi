"""真实规范存储下的记忆身份、归属、冻结与部分失败恢复。"""

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from support.skill_support import invocation

from src.agent.skills.adapters.memory import AgentMemory
from src.agent.skills.memory_write import (
    MemoryBasis,
    MemoryEvent,
    MemoryFact,
    MemoryScope,
    MemoryWriteSkill,
    MemoryWriteStatus,
)
from src.domain.memory_record import MemoryRecord, MemoryType, MemoryVisibility
from src.infrastructure.persistence.database import DatabaseManager
from src.infrastructure.persistence.database.sql_database import AgentMemoryRecord, MemoryEventBatch
from src.infrastructure.persistence.database.vector_store import Document

NOW = datetime(2026, 11, 3, 12)


class Vectors:
    async def embed_query(self, query):
        return [1.0]

    def __init__(self):
        self.documents = {}
        self.fail_at = None

    def upsert_documents(self, documents, ids):
        if self.fail_at is not None and len(self.documents) == self.fail_at:
            raise RuntimeError("索引写入失败")
        for document, key in zip(documents, ids):
            self.documents[key] = document
        return ids

    async def search(self, user_id, query, k=5, **kwargs):
        # 故意返回其他用户和角色的命中，验证规范记录仍限制可访问范围。
        return [(value, 0.99) for value in self.documents.values()]


class Models:
    def __init__(self):
        self.payload = {"user_memory": ["不吃香菜"], "event_memory": []}
        self.error = None
        self.calls = 0

    def register_llm_module(self, *args):
        return self

    async def generate_response(self, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return json.dumps(self.payload, ensure_ascii=False)


@pytest.fixture
def setup(tmp_path):
    database = DatabaseManager({"sql_db_folder": str(tmp_path), "sql_db_file": "memory.sqlite", "memory_store": {}})
    vectors, models = Vectors(), Models()
    config = {"llm_module": {"llm": {"name": "test"}}}
    skill = MemoryWriteSkill(
        config,
        llm_service=models,
        memory_store=database.memory_store,
        vector_store=vectors,
        characters=("luotianyi", "miku"),
    )

    def reader(character_id="luotianyi", legacy=None):
        return AgentMemory(
            {"memory_writer": config, "user_profile": config, "legacy_character_memory_ids": legacy or {}},
            models,
            database_manager=database,
            vector_store=vectors,
            owner_character_id=character_id,
        )

    yield SimpleNamespace(database=database, vectors=vectors, models=models, skill=skill, reader=reader)
    asyncio.run(database.shutdown())


def fact(source_id="message-1", *, scope=MemoryScope.USER, content="不吃香菜", basis=MemoryBasis.USER_REQUEST):
    return MemoryFact(
        "explicit_memory" if scope is MemoryScope.USER else "song_learned", source_id, NOW, content, scope, basis
    )


async def test_confirmed_fact_never_reenters_extraction_and_returns_persisted_id(setup):
    setup.models.error = RuntimeError("提取模型不可用")
    first = await setup.skill.commit_fact(invocation(), fact=fact())
    repeated = await setup.skill.commit_fact(invocation(), fact=fact())
    assert first.status is MemoryWriteStatus.CREATED
    assert repeated.status is MemoryWriteStatus.DUPLICATE
    assert repeated.memory_ids == first.memory_ids
    assert setup.database.memory_store.get_agent_memory_record(first.memory_ids[0]).content == "不吃香菜"
    assert setup.models.calls == 0


async def test_learning_job_is_one_character_memory_and_user_memories_stay_private(setup):
    learned = fact("job-1", scope=MemoryScope.CHARACTER, content="学会了新歌", basis=MemoryBasis.CONFIRMED_FACT)
    first = await setup.skill.commit_fact(invocation(user_id=None), fact=learned)
    await setup.skill.commit_fact(invocation(user_id=None), fact=learned)
    record = setup.database.memory_store.get_agent_memory_record(first.memory_ids[0])
    assert record.subject_user_id is None
    assert record.visibility is MemoryVisibility.CHARACTER_PRIVATE
    await setup.skill.commit_fact(invocation(user_id="甲"), fact=fact())
    result = await setup.reader().search_memory_context_for_topic("乙", ["记忆"], k=20)
    assert [hit.record.content for hit in result.hits] == ["学会了新歌"]
    assert not (await setup.reader("miku").search_memory_context_for_topic("甲", ["记忆"], k=20)).hits


async def test_no_candidate_is_distinct_from_model_failure(setup):
    event = MemoryEvent("dynamic", "post-1", NOW, "今天下雨了", MemoryScope.USER)
    setup.models.payload = {"user_memory": [], "event_memory": []}
    result = await setup.skill.remember_event(invocation(), event=event)
    assert result.status is MemoryWriteStatus.NO_CANDIDATE
    setup.models.error = RuntimeError("提取失败")
    with pytest.raises(RuntimeError, match="提取失败"):
        await setup.skill.remember_event(
            invocation(), event=MemoryEvent("dynamic", "post-2", NOW, "正文", MemoryScope.USER)
        )


async def test_partial_index_failure_reuses_frozen_candidates_and_converges(setup):
    setup.models.payload = {"user_memory": ["喜欢茶", "不吃香菜"], "event_memory": []}
    event = MemoryEvent("dynamic", "post-1", NOW, "正文", MemoryScope.USER)
    setup.vectors.fail_at = 1
    with pytest.raises(RuntimeError, match="索引写入失败"):
        await setup.skill.remember_event(invocation(), event=event)
    setup.vectors.fail_at = None
    setup.models.error = RuntimeError("重试不应重新提取")
    result = await setup.skill.remember_event(invocation(), event=replace(event, occurred_at=NOW + timedelta(days=1)))
    assert len(result.memory_ids) == len(setup.vectors.documents) == 2
    assert setup.models.calls == 1
    with setup.database.open_sql_session() as session:
        assert session.query(AgentMemoryRecord).count() == 2
    assert all(setup.database.memory_store.agent_memory_record_has_embeddings(key) for key in result.memory_ids)


async def test_legacy_character_allowlist_never_promotes_same_named_user_fact(setup):
    for key, kind, content in (
        ("old-life", MemoryType.INTERACTION_EVENT, "学会旧歌"),
        ("same-id-user", MemoryType.USER_FACT, "同名用户的私密事实"),
    ):
        record = MemoryRecord(
            id=key,
            owner_character_id="luotianyi",
            subject_user_id="luotianyi",
            memory_type=kind,
            visibility=MemoryVisibility.PRIVATE,
            source="chat",
            content=content,
        )
        setup.database.memory_store.write_agent_memory_record(record, embedding_ids=[key])
        setup.vectors.documents[key] = Document(content, {"user_id": "luotianyi"}, id=key)
    reader = setup.reader(legacy={"luotianyi": ["old-life", "same-id-user"]})
    result = await reader.search_memory_context_for_topic("其他用户", ["旧记忆"], k=20)
    assert [hit.record.id for hit in result.hits] == ["old-life"]


async def test_user_reset_removes_frozen_private_event_material(setup):
    await setup.skill.remember_event(
        invocation(), event=MemoryEvent("dynamic", "post-1", NOW, "私有材料", MemoryScope.USER)
    )
    setup.database.memory_store.delete_user_memory_records("u")
    with setup.database.open_sql_session() as session:
        assert session.query(MemoryEventBatch).count() == 0
