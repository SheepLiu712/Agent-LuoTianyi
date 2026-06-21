import os
import sys
import asyncio

current_dir = os.getcwd()
if current_dir not in sys.path:
    sys.path.append(current_dir)

import pytest
from sqlalchemy import inspect

from src.system.database.database_service import (
    get_agent_memory_record,
    get_agent_memory_record_by_embedding_id,
    write_agent_memory_record,
)
from src.system.database.memory_storage import MemoryStorage
from src.system.database.sql_database import (
    AgentMemoryRecord,
    Base,
    MemoryChunkRecord,
    User,
    get_sql_session,
    init_sql_db,
)
from src.domain.memory_record import MemoryRecord, MemoryType, MemoryVisibility
from src.subconscious.memory.memory_write import MemoryWriter


class FakeVectorStore:
    def __init__(self):
        self.documents = []

    async def search(self, user_id, content, k=5):
        return []

    def add_documents(self, docs):
        self.documents.extend(docs)
        return [f"vec-{len(self.documents) - len(docs) + i}" for i, _ in enumerate(docs)]


@pytest.fixture()
def temp_db(tmp_path):
    init_sql_db(db_folder=str(tmp_path), db_file="memory_refactor.db")
    session = get_sql_session()
    Base.metadata.drop_all(bind=session.get_bind())
    Base.metadata.create_all(bind=session.get_bind())
    yield
    session.close()


def test_init_sql_db_creates_canonical_memory_tables(temp_db):
    session = get_sql_session()
    try:
        bind = session.get_bind()
        inspector = inspect(bind)
        assert inspector.has_table(AgentMemoryRecord.__tablename__)
        assert inspector.has_table(MemoryChunkRecord.__tablename__)
    finally:
        session.close()


def test_write_agent_memory_record_persists_record_and_chunk(temp_db):
    session = get_sql_session()
    try:
        record = MemoryRecord(
            owner_character_id="luotianyi",
            subject_user_id="user-1",
            memory_type=MemoryType.USER_FACT,
            visibility=MemoryVisibility.PRIVATE,
            source="chat",
            content="用户喜欢蓝色。",
            metadata={"legacy_vector_ids": ["vec-1"]},
        )

        record_id = write_agent_memory_record(
            session,
            record,
            embedding_ids=["vec-1"],
            commit=True,
        )

        assert record_id == record.id
        saved = get_agent_memory_record(session, record_id)
        assert saved is not None
        assert saved.content == "用户喜欢蓝色。"
        assert saved.memory_type == MemoryType.USER_FACT
        by_embedding = get_agent_memory_record_by_embedding_id(session, "vec-1")
        assert by_embedding is not None
        assert by_embedding.id == record_id

        chunk = session.query(MemoryChunkRecord).filter_by(memory_record_id=record_id).one()
        assert chunk.chunk_text == "用户喜欢蓝色。"
        assert chunk.embedding_id == "vec-1"
    finally:
        session.close()


def test_memory_writer_syncs_user_memory_to_canonical_record(temp_db):
    asyncio.run(_run_memory_writer_syncs_user_memory_to_canonical_record())


async def _run_memory_writer_syncs_user_memory_to_canonical_record():
    session = get_sql_session()
    try:
        user = User(username="memory_user", password="pwd")
        session.add(user)
        session.commit()

        writer = MemoryWriter.__new__(MemoryWriter)
        writer.config = {"user_memory_dedup_threshold": 0.72}

        vector_store = FakeVectorStore()
        redis = MemoryStorage()

        ok = await writer.write_user_memory(
            db=session,
            redis=redis,
            vector_store=vector_store,
            user_id=user.uuid,
            content="用户喜欢蓝色。",
            commit=True,
        )

        assert ok is True
        rows = session.query(AgentMemoryRecord).filter_by(subject_user_id=user.uuid).all()
        assert len(rows) == 1
        assert rows[0].owner_character_id == "luotianyi"
        assert rows[0].memory_type == MemoryType.USER_FACT.value
        assert rows[0].visibility == MemoryVisibility.PRIVATE.value
        assert rows[0].content == "用户喜欢蓝色。"

        chunk = session.query(MemoryChunkRecord).filter_by(memory_record_id=rows[0].id).one()
        assert chunk.embedding_id == "vec-0"
    finally:
        session.close()


def test_memory_writer_can_scope_canonical_memory_to_character(temp_db):
    asyncio.run(_run_memory_writer_can_scope_canonical_memory_to_character())


async def _run_memory_writer_can_scope_canonical_memory_to_character():
    session = get_sql_session()
    try:
        user = User(username="memory_user_2", password="pwd")
        session.add(user)
        session.commit()

        writer = MemoryWriter.__new__(MemoryWriter)
        writer.config = {"user_memory_dedup_threshold": 0.72}

        ok = await writer.write_user_memory(
            db=session,
            redis=MemoryStorage(),
            vector_store=FakeVectorStore(),
            user_id=user.uuid,
            content="character scoped memory",
            owner_character_id="yanhe",
            commit=True,
        )

        assert ok is True
        row = session.query(AgentMemoryRecord).filter_by(subject_user_id=user.uuid).one()
        assert row.owner_character_id == "yanhe"
    finally:
        session.close()
