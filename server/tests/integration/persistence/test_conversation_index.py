"""Conversation index: legacy backfill, monotonic allocation, and v1 reopen."""

import sqlite3

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.domain import ConversationItem
from src.infrastructure.persistence.database.redis_buffer import RedisBuffer
from src.infrastructure.persistence.database.services.conversation_service import ConversationService
from src.infrastructure.persistence.database.services.user_store import UserStore
from src.infrastructure.persistence.database.sql_database import (
    Base,
    User,
    _migrate_conversation_index_schema,
    init_sql_db,
)


def _service(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'index.db'}")
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


def _item(entry_id: str, timestamp: str = "2026-10-09 10:00:00") -> ConversationItem:
    return ConversationItem(uuid=entry_id, timestamp=timestamp, source="user", content=entry_id, type="text")


def test_legacy_rows_are_backfilled_in_previous_observable_order(tmp_path):
    database_path = tmp_path / "legacy.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript("""
            CREATE TABLE conversations (
                uuid VARCHAR PRIMARY KEY,
                user_id VARCHAR NOT NULL,
                character_id VARCHAR NOT NULL DEFAULT 'luotianyi',
                timestamp DATETIME,
                source VARCHAR NOT NULL,
                type VARCHAR NOT NULL,
                content TEXT NOT NULL,
                meta_data TEXT
            );
            INSERT INTO conversations VALUES
                ('b-second', 'user', 'luotianyi', '2026-10-09 10:00:00', 'user', 'text', 'b', '{}'),
                ('a-first', 'user', 'luotianyi', '2026-10-09 10:00:00', 'user', 'text', 'a', '{}'),
                ('other-role', 'user', 'another', '2026-10-09 09:00:00', 'user', 'text', 'o', '{}'),
                ('other-user', 'other', 'luotianyi', '2026-10-09 09:00:00', 'user', 'text', 'v', '{}');
            """)
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        _migrate_conversation_index_schema(engine)
        _migrate_conversation_index_schema(engine)
        with sqlite3.connect(database_path) as connection:
            rows = connection.execute(
                'SELECT uuid, "index" FROM conversations ORDER BY user_id, character_id, "index"'
            ).fetchall()
            assert rows == [
                ("other-user", 1),
                ("other-role", 1),
                ("a-first", 1),
                ("b-second", 2),
            ]
            indexes = {row[1] for row in connection.execute("PRAGMA index_list(conversations)")}
            assert "uq_conversations_user_character_index" in indexes
            # 晚到的 NULL 行接在现有序列之后，不重排已有序号。
            connection.execute("""
                INSERT INTO conversations(uuid, user_id, character_id, timestamp, source, type, content, meta_data)
                VALUES ('c-late', 'user', 'luotianyi', '2026-10-09 09:30:00', 'user', 'text', 'c', '{}')
                """)
        _migrate_conversation_index_schema(engine)
        with sqlite3.connect(database_path) as connection:
            assert connection.execute(
                "SELECT \"index\" FROM conversations WHERE uuid = 'c-late'"
            ).fetchone() == (3,)
    finally:
        engine.dispose()


def test_runtime_assigns_monotonic_index_per_user_and_character(tmp_path):
    service, engine = _service(tmp_path)
    try:
        # 同时间消息按落库顺序编号；不同时间消息按事实时间插入。
        assert service.add_conversations(
            "user",
            [
                _item("third", "2026-10-09 10:02:00"),
                _item("first", "2026-10-09 10:02:00"),
                _item("second", "2026-10-09 10:02:00"),
            ],
        ) == ["third", "first", "second"]
        assert [row.uuid for row in service.get_history_from_db("user", 0, 10)] == ["third", "first", "second"]
        service.add_conversations("user", [_item("earlier", "2026-10-09 10:00:00")])
        assert [row.uuid for row in service.get_history_from_db("user", 0, 10)] == [
            "earlier",
            "third",
            "first",
            "second",
        ]
        # 重复 UUID 保留原序号，不消耗新序号。
        service.add_conversations("user", [_item("first", "2026-10-09 10:02:00")])
        service.add_conversations("user", [_item("fourth", "2026-10-09 10:03:00")])
        assert [row.uuid for row in service.get_history_from_db("user", 0, 10)] == [
            "earlier",
            "third",
            "first",
            "second",
            "fourth",
        ]
        assert service.add_conversations("user", [_item("other-role")], character_id="another") == ["other-role"]
        assert [row.uuid for row in service.get_history_from_db("user", 0, 10, character_id="another")] == [
            "other-role"
        ]
    finally:
        engine.dispose()


def test_reopening_a_version_one_database_adds_and_backfills_the_index(tmp_path):
    database_path = tmp_path / "reopen.db"
    init_sql_db(str(tmp_path), database_path.name)
    with sqlite3.connect(database_path) as connection:
        connection.executescript("""
            DROP INDEX uq_conversations_user_character_index;
            ALTER TABLE conversations DROP COLUMN "index";
            INSERT INTO users(uuid, username, password) VALUES ('user', 'user', 'hash');
            INSERT INTO conversations(uuid, user_id, character_id, timestamp, source, type, content)
            VALUES
                ('b', 'user', 'luotianyi', '2026-10-09 10:00:00', 'user', 'text', 'b'),
                ('a', 'user', 'luotianyi', '2026-10-09 10:00:00', 'user', 'text', 'a');
            """)
    init_sql_db(str(tmp_path), database_path.name)
    with sqlite3.connect(database_path) as connection:
        assert {row[1] for row in connection.execute("PRAGMA table_info(conversations)")} >= {"index"}
        assert connection.execute("SELECT \"index\" FROM conversations WHERE uuid = 'a'").fetchone() == (1,)
        assert connection.execute("SELECT \"index\" FROM conversations WHERE uuid = 'b'").fetchone() == (2,)
        assert connection.execute("PRAGMA user_version").fetchone() == (1,)