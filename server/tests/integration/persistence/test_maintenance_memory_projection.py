"""SQLite evidence for maintenance canonical and vector-chunk convergence."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.domain.memory_record import MemoryRecord, MemoryType, MemoryVisibility
from src.infrastructure.persistence.database.redis_buffer import RedisBuffer
from src.infrastructure.persistence.database.services.memory_store import MemoryStore
from src.infrastructure.persistence.database.sql_database import (
    AgentMemoryRecord,
    Base,
    MemoryChunkRecord,
    init_sql_db,
)


def _record(**changes):
    values = {
        "id": "canonical",
        "owner_character_id": "character",
        "subject_user_id": "user",
        "memory_type": MemoryType.USER_FACT,
        "visibility": MemoryVisibility.PRIVATE,
        "source": "cognitive_maintenance",
        "content": "tea",
        "summary": "summary",
        "importance": 0.7,
        "confidence": 0.8,
        "metadata": {"maintenance_id": "attempt", "candidate_index": 0},
    }
    values.update(changes)
    return MemoryRecord(**values)


def _store(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'memory.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    return MemoryStore({}, sessions, RedisBuffer()), sessions, engine


def test_legacy_memory_chunks_get_idempotent_partial_unique_index(tmp_path):
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as connection:
        connection.executescript("""
            CREATE TABLE memory_chunks (
                id VARCHAR PRIMARY KEY, memory_record_id VARCHAR NOT NULL, chunk_text TEXT NOT NULL,
                chunk_type VARCHAR, embedding_id VARCHAR, created_at DATETIME, meta_data TEXT
            );
            INSERT INTO memory_chunks VALUES ('one', 'record', 'a', 'content', 'same', NULL, NULL);
            INSERT INTO memory_chunks VALUES ('null-one', 'record', 'a', 'content', NULL, NULL, NULL);
            INSERT INTO memory_chunks VALUES ('null-two', 'record', 'b', 'content', NULL, NULL, NULL);
            """)
    init_sql_db(str(tmp_path), database.name)
    init_sql_db(str(tmp_path), database.name)
    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO memory_chunks VALUES ('two', 'record', 'b', 'content', 'same', NULL, NULL)")
        assert connection.execute("SELECT COUNT(*) FROM memory_chunks").fetchone()[0] == 3


def test_legacy_duplicate_embedding_ids_fail_without_rewriting_history(tmp_path):
    database = tmp_path / "duplicates.db"
    with sqlite3.connect(database) as connection:
        connection.executescript("""
            CREATE TABLE memory_chunks (
                id VARCHAR PRIMARY KEY, memory_record_id VARCHAR NOT NULL, chunk_text TEXT NOT NULL,
                chunk_type VARCHAR, embedding_id VARCHAR, created_at DATETIME, meta_data TEXT
            );
            INSERT INTO memory_chunks VALUES ('one', 'record', 'a', 'content', 'duplicate', NULL, NULL);
            INSERT INTO memory_chunks VALUES ('two', 'record', 'b', 'content', 'duplicate', NULL, NULL);
            """)
    with pytest.raises(RuntimeError, match="duplicate non-null embedding_id"):
        init_sql_db(str(tmp_path), database.name)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT id, embedding_id FROM memory_chunks ORDER BY id").fetchall() == [
            ("one", "duplicate"),
            ("two", "duplicate"),
        ]


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner_character_id", "other"),
        ("subject_user_id", "other"),
        ("memory_type", MemoryType.INTERACTION_EVENT),
        ("visibility", MemoryVisibility.PUBLIC),
        ("source", "other"),
        ("content", "coffee"),
        ("summary", "other"),
        ("importance", 0.6),
        ("confidence", 0.9),
        ("metadata", {"maintenance_id": "other", "candidate_index": 0}),
        ("metadata", {"maintenance_id": "attempt", "candidate_index": 1}),
    ],
)
def test_canonical_preexisting_identity_rejects_each_maintenance_field(tmp_path, field, value):
    store, _, engine = _store(tmp_path)
    try:
        assert store.write_agent_memory_record_if_absent(_record())
        with pytest.raises(ValueError, match="identity conflicts"):
            store.write_agent_memory_record_if_absent(_record(**{field: value}))
        assert store.write_agent_memory_record_if_absent(_record()) is False
    finally:
        engine.dispose()


def test_two_sessions_converge_canonical_and_embedding_chunk(tmp_path):
    store, sessions, engine = _store(tmp_path)
    try:
        record = _record()

        def write():
            local = MemoryStore({}, sessions, RedisBuffer())
            local.write_agent_memory_record_if_absent(record)
            local.link_agent_memory_embeddings(record.id, chunk_texts=[record.content], embedding_ids=["vector"])

        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(lambda _: write(), range(2)))
        with sessions() as session:
            assert session.query(AgentMemoryRecord).count() == 1
            assert session.query(MemoryChunkRecord).filter_by(embedding_id="vector").count() == 1
    finally:
        engine.dispose()


def test_partial_canonical_vector_chunk_projection_recovers(tmp_path):
    store, sessions, engine = _store(tmp_path)
    try:
        record = _record()
        assert store.write_agent_memory_record_if_absent(record)
        store.link_agent_memory_embeddings(record.id, chunk_texts=[record.content], embedding_ids=["vector"])
        store.link_agent_memory_embeddings(record.id, chunk_texts=[record.content], embedding_ids=["vector"])
        with sessions() as session:
            assert session.query(AgentMemoryRecord).count() == 1
            assert session.query(MemoryChunkRecord).count() == 1
    finally:
        engine.dispose()
