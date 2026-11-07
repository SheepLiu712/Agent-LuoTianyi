import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.domain.call import CallEndReason, CallOutcome, CallState
from src.infrastructure.persistence.call_sessions import CallSessionRecord, SqlCallSessionRepository
from src.infrastructure.persistence.database.sql_database import Base, CallSession, _migrate_sqlite_schema


def _record(call_id, now):
    return CallSessionRecord(
        call_id=call_id,
        client_request_id=str(call_id),
        user_id="user",
        character_id="luotianyi",
        state=CallState.ENDED,
        requested_at=now,
        created_at=now,
        updated_at=now,
        outcome=CallOutcome.CONNECTED,
        end_reason=CallEndReason.USER_HANGUP,
        connected_at=now,
        ended_at=now,
        active_duration_ms=1,
    )


def test_old_call_sessions_schema_adds_only_nullable_digest_column(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.sqlite'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE call_sessions RENAME TO call_sessions_new")
        connection.exec_driver_sql(
            "CREATE TABLE call_sessions (call_id VARCHAR PRIMARY KEY, client_request_id VARCHAR NOT NULL, "
            "user_id VARCHAR NOT NULL, character_id VARCHAR NOT NULL, state VARCHAR NOT NULL, outcome VARCHAR, "
            "end_reason VARCHAR, requested_at DATETIME NOT NULL, connected_at DATETIME, disconnected_at DATETIME, "
            "ended_at DATETIME, active_duration_ms INTEGER NOT NULL DEFAULT 0, summary_status VARCHAR NOT NULL "
            "DEFAULT 'pending', maintenance_status VARCHAR NOT NULL DEFAULT 'pending', conversation_id VARCHAR, "
            "maintenance_turn_seq INTEGER NOT NULL DEFAULT 0, created_at DATETIME NOT NULL, "
            "updated_at DATETIME NOT NULL)"
        )
        connection.exec_driver_sql("DROP TABLE call_sessions_new")
    _migrate_sqlite_schema(engine)
    with engine.connect() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(call_sessions)").fetchall()}
    assert "settlement_input_digest" in columns


@pytest.mark.parametrize("has_records", [False, True])
def test_legacy_call_table_upgrade_preserves_records_or_allows_new_calls(tmp_path, has_records):
    from datetime import datetime, timezone
    from uuid import uuid4

    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.sqlite'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE call_sessions")
        connection.exec_driver_sql("CREATE TABLE call_sessions (call_id VARCHAR PRIMARY KEY, status VARCHAR)")
        if has_records:
            connection.exec_driver_sql("INSERT INTO call_sessions VALUES ('historic-call', 'ended')")
    if has_records:
        with pytest.raises(RuntimeError, match="explicit data migration"):
            _migrate_sqlite_schema(engine)
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT * FROM call_sessions").all() == [("historic-call", "ended")]
        return
    _migrate_sqlite_schema(engine)
    _migrate_sqlite_schema(engine)
    repository = SqlCallSessionRepository(sessionmaker(bind=engine))
    record = _record(uuid4(), datetime.now(timezone.utc))
    repository.create_if_absent(record)
    assert repository.find_by_id(record.call_id).end_reason is CallEndReason.USER_HANGUP
    with engine.connect() as connection:
        assert connection.execute(select(CallSession.call_id)).scalar_one() == str(record.call_id)
