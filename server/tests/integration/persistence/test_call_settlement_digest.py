from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.domain.call import CallEndReason, CallOutcome, CallState
from src.infrastructure.persistence.call_sessions import CallSessionRecord, SqlCallSessionRepository
from src.infrastructure.persistence.database.sql_database import Base, _migrate_sqlite_schema


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


def test_sql_settlement_digest_claim_is_idempotent_and_conflicts(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'digest.sqlite'}")
    Base.metadata.create_all(engine)
    repository = SqlCallSessionRepository(sessionmaker(bind=engine))
    call_id = uuid4()
    repository.create_if_absent(_record(call_id, datetime.now(timezone.utc)))

    assert repository.claim_settlement_input(call_id, digest="a" * 64)
    assert repository.claim_settlement_input(call_id, digest="a" * 64)
    with pytest.raises(ValueError, match="SETTLEMENT_INPUT_CONFLICT"):
        repository.claim_settlement_input(call_id, digest="b" * 64)


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
