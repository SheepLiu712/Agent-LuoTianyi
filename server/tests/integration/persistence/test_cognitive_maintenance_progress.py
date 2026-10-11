"""Persistent cognitive-maintenance progress migration and CAS behavior."""

import sqlite3

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.agent.context import ConversationCompaction, ConversationSummary
from src.domain import ConversationItem
from src.infrastructure.persistence.cognitive_maintenance import CognitiveMaintenanceBatchDraft
from src.infrastructure.persistence.database.redis_buffer import RedisBuffer
from src.infrastructure.persistence.database.services.conversation_service import ConversationService
from src.infrastructure.persistence.database.services.user_store import UserStore
from src.infrastructure.persistence.database.sql_database import Base, User, init_sql_db


def _service(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'progress.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as session:
        session.add(User(uuid="user", username="user", password="unused"))
        session.commit()
    cache = RedisBuffer()
    service = ConversationService(
        sql_session_factory=sessions,
        redis_buffer=cache,
        user_store=UserStore({}, sessions, cache),
    )
    return service, engine


def _item(entry_id: str, timestamp: str) -> ConversationItem:
    return ConversationItem(
        uuid=entry_id,
        timestamp=timestamp,
        source="user",
        content=entry_id,
        type="text",
    )


def test_sqlite_migration_preserves_old_context_state_and_leaves_progress_null(tmp_path):
    database_path = tmp_path / "legacy.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript("""
            CREATE TABLE users (uuid VARCHAR PRIMARY KEY, username VARCHAR, password VARCHAR);
            CREATE TABLE conversation_contexts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id VARCHAR NOT NULL,
                character_id VARCHAR NOT NULL,
                context_summary TEXT,
                context_memory_count INTEGER,
                updated_at DATETIME
            );
            INSERT INTO conversation_contexts (user_id, character_id, context_summary, context_memory_count)
            VALUES ('user', 'luotianyi', 'existing summary', 7);
            """)

    init_sql_db(str(tmp_path), database_path.name)
    init_sql_db(str(tmp_path), database_path.name)

    with sqlite3.connect(database_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(conversation_contexts)")}
        row = connection.execute("""
            SELECT context_summary, context_memory_count, maintenance_entry_id
            FROM conversation_contexts WHERE user_id = 'user' AND character_id = 'luotianyi'
            """).fetchone()
    assert "maintenance_entry_id" in columns
    assert row == ("existing summary", 7, None)


def test_progress_compare_and_swap_scopes_identity_and_cannot_move_backward(tmp_path):
    service, engine = _service(tmp_path)
    try:
        assert service.add_conversations(
            "user",
            [_item("first", "2026-10-09 10:00:00"), _item("second", "2026-10-09 10:01:00")],
        ) == ["first", "second"]

        assert service.get_cognitive_maintenance_progress("user", character_id="luotianyi") is None
        assert (
            service.advance_cognitive_maintenance_progress(
                "user", character_id="luotianyi", expected_entry_id=None, new_entry_id="second"
            )
            is True
        )
        assert service.get_cognitive_maintenance_progress("user", character_id="luotianyi") == "second"

        # A concurrent contender with the old NULL expectation loses the CAS.
        assert (
            service.advance_cognitive_maintenance_progress(
                "user", character_id="luotianyi", expected_entry_id=None, new_entry_id="first"
            )
            is False
        )
        # Even a caller holding the current value cannot use it to regress to an older entry.
        assert (
            service.advance_cognitive_maintenance_progress(
                "user", character_id="luotianyi", expected_entry_id="second", new_entry_id="first"
            )
            is False
        )
        # A record owned by another character cannot be used as the target.
        assert service.add_conversations("user", [_item("miku-entry", "2026-10-09 10:02:00")], character_id="miku") == [
            "miku-entry"
        ]
        assert (
            service.advance_cognitive_maintenance_progress(
                "user", character_id="luotianyi", expected_entry_id="second", new_entry_id="miku-entry"
            )
            is False
        )
        assert service.get_cognitive_maintenance_progress("user", character_id="luotianyi") == "second"
    finally:
        engine.dispose()


def test_reset_deletes_context_and_its_maintenance_progress(tmp_path):
    service, engine = _service(tmp_path)
    try:
        service.add_conversations("user", [_item("entry", "2026-10-09 10:00:00")])
        assert (
            service.advance_cognitive_maintenance_progress(
                "user", character_id="luotianyi", expected_entry_id=None, new_entry_id="entry"
            )
            is True
        )

        assert service.reset_user_conversations("user") == 1
        assert service.get_cognitive_maintenance_progress("user", character_id="luotianyi") is None
    finally:
        engine.dispose()


def _draft(*, target="second", candidates=None, summary=None):
    return CognitiveMaintenanceBatchDraft(
        target_entry_id=target,
        covered_entry_ids=("first",),
        maintained_entry_ids=("first", target),
        candidates=[] if candidates is None else candidates,
        proposed_profile="更新画像",
        input_digest="digest",
        compaction_previous_summary="" if summary is not None else None,
        compaction_covered_entry_ids=("first",) if summary is not None else (),
        compaction_summary=summary,
        compaction_expected_count=2 if summary is not None else None,
    )


def test_batch_is_frozen_once_per_predecessor_including_empty_candidates(tmp_path):
    service, engine = _service(tmp_path)
    try:
        service.add_conversations(
            "user", [_item("first", "2026-10-09 10:00:00"), _item("second", "2026-10-09 10:01:00")]
        )
        winner = service.create_or_load_cognitive_maintenance_batch(
            "user", character_id="luotianyi", previous_progress=None, draft=_draft(candidates=[])
        )
        loser = service.create_or_load_cognitive_maintenance_batch(
            "user", character_id="luotianyi", previous_progress=None, draft=_draft(candidates=[{"changed": True}])
        )

        assert winner.maintenance_id == loser.maintenance_id
        assert loser.candidates == []
        assert (
            service.load_cognitive_maintenance_batch("user", character_id="luotianyi", previous_progress=None) == winner
        )
    finally:
        engine.dispose()


def test_atomic_commit_rejects_conflicting_compaction_without_advancing_progress(tmp_path):
    service, engine = _service(tmp_path)
    try:
        service.add_conversations(
            "user", [_item("first", "2026-10-09 10:00:00"), _item("second", "2026-10-09 10:01:00")]
        )
        batch = service.create_or_load_cognitive_maintenance_batch(
            "user", character_id="luotianyi", previous_progress=None, draft=_draft(summary="new summary")
        )
        invalid = ConversationCompaction(ConversationSummary("wrong"), ("first",), ConversationSummary("new summary"))

        assert (
            service.commit_cognitive_maintenance(
                "user",
                character_id="luotianyi",
                compaction=invalid,
                expected_progress=None,
                new_progress="second",
                maintenance_id=batch.maintenance_id,
            )
            is False
        )
        state = service.get_conversation_context_state("user")
        assert state["summary"] == ""
        assert state["context_count"] == 2
        assert service.get_cognitive_maintenance_progress("user", character_id="luotianyi") is None

        valid = ConversationCompaction(ConversationSummary(), ("first",), ConversationSummary("new summary"))
        assert (
            service.commit_cognitive_maintenance(
                "user",
                character_id="luotianyi",
                compaction=valid,
                expected_progress=None,
                new_progress="second",
                maintenance_id=batch.maintenance_id,
            )
            is True
        )
        state = service.get_conversation_context_state("user")
        assert state["summary"] == "new summary"
        assert state["context_count"] == 1
        assert service.get_cognitive_maintenance_progress("user", character_id="luotianyi") == "second"
    finally:
        engine.dispose()


def test_frozen_batch_rejects_a_different_compaction_payload(tmp_path):
    service, engine = _service(tmp_path)
    try:
        service.add_conversations(
            "user", [_item("first", "2026-10-09 10:00:00"), _item("second", "2026-10-09 10:01:00")]
        )
        batch = service.create_or_load_cognitive_maintenance_batch(
            "user", character_id="luotianyi", previous_progress=None, draft=_draft(summary="frozen summary")
        )
        changed = ConversationCompaction(ConversationSummary(), ("first",), ConversationSummary("changed summary"))

        assert (
            service.commit_cognitive_maintenance(
                "user",
                character_id="luotianyi",
                compaction=changed,
                expected_progress=None,
                new_progress="second",
                maintenance_id=batch.maintenance_id,
            )
            is False
        )
        assert service.get_cognitive_maintenance_progress("user", character_id="luotianyi") is None
    finally:
        engine.dispose()


def test_identical_timestamps_use_entry_id_for_window_and_progress_order(tmp_path):
    service, engine = _service(tmp_path)
    try:
        service.add_conversations(
            "user",
            [_item("z-last", "2026-10-09 10:00:00"), _item("a-first", "2026-10-09 10:00:00")],
        )
        assert [item.uuid for item in service.get_history_from_db("user", 0, 10)] == ["a-first", "z-last"]
        assert (
            service.advance_cognitive_maintenance_progress(
                "user", character_id="luotianyi", expected_entry_id=None, new_entry_id="a-first"
            )
            is True
        )
        assert (
            service.advance_cognitive_maintenance_progress(
                "user", character_id="luotianyi", expected_entry_id="a-first", new_entry_id="z-last"
            )
            is True
        )
    finally:
        engine.dispose()
